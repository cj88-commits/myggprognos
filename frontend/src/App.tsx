import { useEffect, useMemo, useRef, useState } from "react";
import { MapView } from "./components/MapView";
import { ControlBar } from "./components/ControlBar";
import { Legend } from "./components/Legend";
import { StatusBanner } from "./components/StatusBanner";
import { LocationPanel } from "./components/LocationPanel";
import { useCells, useDailyForDate, useHourlyForHour, useLocationSeries, useManifest, usePlaces } from "./hooks/useForecastData";
import { nearestCell } from "./lib/api";
import { clearFetchCache } from "./lib/fetchJsonGz";
import { finalRiskForActivity } from "./lib/riskModel";
import { DEFAULT_STATE, parseUrlState, serializeUrlState, type AppState } from "./lib/urlState";
import type { DailyRecord, LayerKey, ScoreFields } from "./types/forecast";

function addDaysIso(dateIso: string, days: number): string {
  const d = new Date(dateIso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

const ANIMATION_INTERVAL_MS = 900;

export default function App() {
  const [refreshKey, setRefreshKey] = useState(0);
  const { data: manifest, loading: manifestLoading, error: manifestError } = useManifest(refreshKey);
  const { data: cells } = useCells(refreshKey);
  const { data: places } = usePlaces(refreshKey);

  const initialUrlState = useMemo(() => parseUrlState(window.location.search), []);

  const [selectedLat, setSelectedLat] = useState(initialUrlState.lat ?? DEFAULT_STATE.lat);
  const [selectedLon, setSelectedLon] = useState(initialUrlState.lon ?? DEFAULT_STATE.lon);
  const [placeName, setPlaceName] = useState<string>("Selected location");
  const [date, setDate] = useState<string>(initialUrlState.date ?? "");
  const [hourOfDay, setHourOfDay] = useState<number>(initialUrlState.hour ?? new Date().getUTCHours());
  const [daypart, setDaypart] = useState<string>(initialUrlState.daypart ?? DEFAULT_STATE.daypart!);
  const [activity, setActivity] = useState<string>(initialUrlState.activity ?? DEFAULT_STATE.activity);
  const [layer, setLayer] = useState<LayerKey>(initialUrlState.layer ?? DEFAULT_STATE.layer);
  const [animating, setAnimating] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [userLocation, setUserLocation] = useState<{ lat: number; lon: number } | null>(null);

  const dayOptions = useMemo(() => {
    const start = manifest?.forecast_start ?? new Date().toISOString().slice(0, 10);
    return Array.from({ length: 7 }, (_, i) => addDaysIso(start, i));
  }, [manifest?.forecast_start]);

  useEffect(() => {
    if (!date && dayOptions.length > 0) setDate(dayOptions[0]);
  }, [date, dayOptions]);

  const dayIndex = Math.max(0, dayOptions.indexOf(date));
  const isHourlyDay = dayIndex <= 1;
  const hourOffset = Math.min(48, dayIndex * 24 + hourOfDay);
  const hourLabel = manifest?.hourly_files[hourOffset]?.replace("hourly/", "").replace(".json.gz", "") ?? null;

  const { data: dailyRecords, loading: dailyLoading, error: dailyError } = useDailyForDate(date || null, refreshKey);
  const { data: hourlyRecords, loading: hourlyLoading, error: hourlyError } = useHourlyForHour(
    isHourlyDay ? hourLabel : null,
    refreshKey
  );

  // Animation: advance hour-of-day while playing (hourly days only).
  const animationTimer = useRef<number | null>(null);
  useEffect(() => {
    if (!animating || !isHourlyDay) return;
    animationTimer.current = window.setInterval(() => {
      setHourOfDay((h) => (h + 1) % 24);
    }, ANIMATION_INTERVAL_MS);
    return () => {
      if (animationTimer.current) window.clearInterval(animationTimer.current);
    };
  }, [animating, isHourlyDay]);

  const activityMultiplier = manifest?.activities?.[activity] ?? 1.0;

  const valuesByCellId = useMemo(() => {
    const source: ScoreFields[] | null = isHourlyDay ? hourlyRecords : dailyRecords;
    if (!source) return null;
    const map: Record<string, number> = {};
    for (const record of source) {
      if (layer === "risk") {
        map[record.cell_id] = finalRiskForActivity(
          record.population_potential,
          record.biting_activity,
          record.base_exposure_fraction,
          activityMultiplier
        );
      } else if (layer === "confidence") {
        map[record.cell_id] = record.confidence;
      } else {
        map[record.cell_id] = record[layer];
      }
    }
    return map;
  }, [isHourlyDay, hourlyRecords, dailyRecords, layer, activityMultiplier]);

  const selectedCell = cells ? nearestCell(cells, selectedLat, selectedLon) : null;
  const { data: series, loading: seriesLoading, error: seriesError } = useLocationSeries(
    selectedCell?.cell_id ?? null,
    manifest,
    refreshKey
  );

  const activeDailyRecord: DailyRecord | null =
    dailyRecords?.find((r) => r.cell_id === selectedCell?.cell_id) ?? null;

  const activeRecord: ScoreFields | null = useMemo(() => {
    if (isHourlyDay) {
      return hourlyRecords?.find((r) => r.cell_id === selectedCell?.cell_id) ?? null;
    }
    return activeDailyRecord?.dayparts?.[daypart as keyof DailyRecord["dayparts"]] ?? null;
  }, [isHourlyDay, hourlyRecords, selectedCell, activeDailyRecord, daypart]);

  const activeLabel = isHourlyDay
    ? `${dayIndex === 0 ? "Today" : "Tomorrow"}, ${String(hourOfDay).padStart(2, "0")}:00 UTC`
    : `${date} (${daypart})`;

  // Keep URL query string in sync with app state (replace, not push, to
  // avoid flooding browser history on every slider tick).
  useEffect(() => {
    const state: AppState = {
      lat: selectedLat,
      lon: selectedLon,
      date,
      hour: isHourlyDay ? hourOfDay : null,
      daypart,
      activity,
      layer,
    };
    const search = serializeUrlState(state);
    window.history.replaceState(null, "", search);
  }, [selectedLat, selectedLon, date, hourOfDay, daypart, activity, layer, isHourlyDay]);

  function handleSelectLocation(lat: number, lon: number, label?: string) {
    setSelectedLat(lat);
    setSelectedLon(lon);
    setPlaceName(label ?? `${lat.toFixed(4)}, ${lon.toFixed(4)}`);
  }

  function handleShare() {
    const url = `${window.location.origin}${window.location.pathname}${serializeUrlState({
      lat: selectedLat,
      lon: selectedLon,
      date,
      hour: isHourlyDay ? hourOfDay : null,
      daypart,
      activity,
      layer,
    })}`;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(url).then(() => {
        setShareCopied(true);
        setTimeout(() => setShareCopied(false), 2000);
      });
    }
  }

  const dataQualityWarning =
    manifest && manifest.data_quality !== "normal"
      ? "Showing degraded-quality forecast data (see manifest warnings)."
      : null;

  const staleWarning = useMemo(() => {
    if (!manifest) return null;
    const generatedAt = new Date(manifest.generated_at).getTime();
    const ageHours = (Date.now() - generatedAt) / 3600000;
    if (ageHours > 12) {
      return `Forecast data is ${Math.round(ageHours)}h old and may be stale.`;
    }
    return null;
  }, [manifest]);

  function handleRetry() {
    clearFetchCache();
    setRefreshKey((k) => k + 1);
  }

  const loadingBanner = manifestLoading ? "Loading forecast…" : null;
  const errorBanner = manifestError ? `Could not load forecast: ${manifestError}` : dailyError || hourlyError || null;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-title">
          Mosquito Risk <span className="subtitle">Sweden &middot; experimental forecast, not a mosquito count</span>
        </div>
        {manifest && (
          <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)" }}>
            Updated {new Date(manifest.generated_at).toLocaleString()}
          </div>
        )}
      </header>

      <div className="map-area">
        <MapView
          cells={cells ?? []}
          valuesByCellId={valuesByCellId}
          layer={layer}
          selectedLat={selectedLat}
          selectedLon={selectedLon}
          onSelectLocation={(lat, lon) => handleSelectLocation(lat, lon)}
          userLocation={userLocation}
        />

        <ControlBar
          manifest={manifest}
          places={places ?? []}
          date={date}
          onDateChange={setDate}
          isHourlyDay={isHourlyDay}
          hour={hourOfDay}
          onHourChange={setHourOfDay}
          daypart={daypart}
          onDaypartChange={setDaypart}
          activity={activity}
          onActivityChange={setActivity}
          layer={layer}
          onLayerChange={setLayer}
          onSelectLocation={(lat, lon) => {
            setUserLocation({ lat, lon });
            handleSelectLocation(lat, lon, "My location");
          }}
          animating={animating}
          onToggleAnimation={() => setAnimating((a) => !a)}
        />

        <Legend layer={layer} />

        {(loadingBanner || errorBanner || dataQualityWarning || staleWarning) && (
          <StatusBanner
            message={errorBanner ?? loadingBanner ?? dataQualityWarning ?? staleWarning ?? ""}
            tone={errorBanner ? "error" : "info"}
            onRetry={errorBanner ? handleRetry : undefined}
          />
        )}
      </div>

      <div className="panel-area">
        <LocationPanel
          placeName={placeName}
          latitude={selectedLat}
          longitude={selectedLon}
          cellId={selectedCell?.cell_id ?? null}
          manifest={manifest}
          activity={activity}
          activeRecord={activeRecord}
          activeDailyRecord={activeDailyRecord}
          activeLabel={activeLabel}
          series={series}
          loading={dailyLoading || hourlyLoading || seriesLoading}
          error={dailyError || hourlyError || seriesError}
          onShare={handleShare}
          shareCopied={shareCopied}
        />
      </div>
    </div>
  );
}
