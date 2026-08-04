import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { ControlBar } from "./components/ControlBar";
import { Legend } from "./components/Legend";
import { StatusBanner } from "./components/StatusBanner";
import { LocationPanel } from "./components/LocationPanel";
import { BottomSheet, type SheetState } from "./components/BottomSheet";
import { useCells, useDailyForDate, useHourlyForHour, useLocationSeries, useManifest, usePlaces } from "./hooks/useForecastData";
import { useI18n } from "./i18n";
import { nearestCell, nearestPlace } from "./lib/api";
import { clearFetchCache } from "./lib/fetchJsonGz";
import { finalRiskForActivity } from "./lib/riskModel";
import { STOCKHOLM_TZ } from "./lib/time";
import { DEFAULT_STATE, parseUrlState, serializeUrlState, type AppState } from "./lib/urlState";
import type { DailyRecord, LayerKey, ScoreFields } from "./types/forecast";

// maplibre-gl is a sizeable dependency (see vite.config.ts manualChunks) --
// deferring its import until after the app shell/loading state has
// rendered keeps it out of the critical first-paint path (requirement:
// <2s first load, no blank screen).
const MapView = lazy(() => import("./components/MapView").then((m) => ({ default: m.MapView })));

function MapSkeleton({ label }: { label: string }) {
  return (
    <div className="map-skeleton" role="status" aria-live="polite">
      <div className="map-skeleton-pulse" />
      <span>{label}</span>
    </div>
  );
}

function addDaysIso(dateIso: string, days: number): string {
  const d = new Date(dateIso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

const ANIMATION_INTERVAL_MS = 900;

// The full production grid is ~18,185 cells; the bundled fallback sample is
// 5. Anything well below full scale means the site is showing limited
// example data, not real Sweden-wide coverage -- worth a distinct, explicit
// message rather than lumping it into the generic "degraded quality"
// warning, so a sparse/placeholder dataset is never mistaken for complete
// coverage (see also MapView's neutral basemap, which avoids the map
// itself looking like a risk choropleth when it isn't one).
const FULL_COVERAGE_MIN_CELLS = 1000;

export default function App() {
  const { t, locale } = useI18n();
  const [refreshKey, setRefreshKey] = useState(0);
  const { data: manifest, loading: manifestLoading, error: manifestError } = useManifest(refreshKey);
  const { data: cells } = useCells(refreshKey);
  const { data: places } = usePlaces(refreshKey);

  const initialUrlState = useMemo(() => parseUrlState(window.location.search), []);

  const [selectedLat, setSelectedLat] = useState(initialUrlState.lat ?? DEFAULT_STATE.lat);
  const [selectedLon, setSelectedLon] = useState(initialUrlState.lon ?? DEFAULT_STATE.lon);
  const [placeName, setPlaceName] = useState<string>("");
  const [date, setDate] = useState<string>(initialUrlState.date ?? "");
  const [hourOfDay, setHourOfDay] = useState<number>(initialUrlState.hour ?? new Date().getUTCHours());
  const [daypart, setDaypart] = useState<string>(initialUrlState.daypart ?? DEFAULT_STATE.daypart!);
  const [activity, setActivity] = useState<string>(initialUrlState.activity ?? DEFAULT_STATE.activity);
  const [layer, setLayer] = useState<LayerKey>(initialUrlState.layer ?? DEFAULT_STATE.layer);
  const [animating, setAnimating] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [userLocation, setUserLocation] = useState<{ lat: number; lon: number } | null>(null);
  // Mobile bottom sheet (item 1) -- irrelevant on desktop, which keeps the
  // static side panel regardless of this value (see BottomSheet.tsx / the
  // 860px breakpoint in global.css). Starts half-open so a first-time
  // visitor sees the answer immediately without having to discover the
  // sheet exists.
  const [sheetState, setSheetState] = useState<SheetState>("half");

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

  // "Myggrisk idag" and "Myggläge" both always describe the WHOLE
  // day/peak, never whichever hour happens to be selected -- this is the
  // fix for the reported default behaviour (map used to default to
  // page-load-hour, which could show a misleadingly suppressed midday
  // score). Only "Myggrisk just nu" (and the secondary biting_activity/
  // confidence layers) are still driven by the hour/daypart selector.
  const usesPeakData = layer === "daily_peak_risk" || layer === "population_potential";

  const valuesByCellId = useMemo(() => {
    const source: ScoreFields[] | null = usesPeakData ? dailyRecords : isHourlyDay ? hourlyRecords : dailyRecords;
    if (!source) return null;
    const map: Record<string, number> = {};
    for (const record of source) {
      if (layer === "daily_peak_risk" || layer === "current_risk") {
        map[record.cell_id] = finalRiskForActivity(
          record.population_potential,
          record.biting_activity,
          record.base_exposure_fraction,
          activityMultiplier,
          manifest?.combination
        );
      } else if (layer === "confidence") {
        map[record.cell_id] = record.confidence;
      } else {
        map[record.cell_id] = record[layer];
      }
    }
    return map;
  }, [usesPeakData, isHourlyDay, hourlyRecords, dailyRecords, layer, activityMultiplier, manifest?.combination]);

  const selectedCell = cells ? nearestCell(cells, selectedLat, selectedLon) : null;
  const { data: series, loading: seriesLoading, error: seriesError } = useLocationSeries(
    selectedCell?.cell_id ?? null,
    manifest,
    refreshKey
  );

  const activeDailyRecord: DailyRecord | null =
    dailyRecords?.find((r) => r.cell_id === selectedCell?.cell_id) ?? null;

  const activeRecord: ScoreFields | null = useMemo(() => {
    // The daily record's own top-level fields already ARE the peak
    // daypart's values (see pipeline.py) -- reusing it directly here means
    // "Myggrisk idag"/"Myggläge" never depend on the hour/daypart selector.
    if (usesPeakData) {
      return activeDailyRecord;
    }
    if (isHourlyDay) {
      return hourlyRecords?.find((r) => r.cell_id === selectedCell?.cell_id) ?? null;
    }
    return activeDailyRecord?.dayparts?.[daypart as keyof DailyRecord["dayparts"]] ?? null;
  }, [usesPeakData, isHourlyDay, hourlyRecords, selectedCell, activeDailyRecord, daypart]);

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
    // A freshly chosen location is exactly what the sheet exists to show --
    // if the user had collapsed it (e.g. to look at the map), bring it back
    // to at least half-open rather than leaving the new result hidden.
    setSheetState((s) => (s === "closed" ? "half" : s));
    if (label) {
      setPlaceName(label);
      return;
    }
    // Map clicks (no search label) get a friendlier fallback than raw
    // coordinates: the nearest named place, qualified with "Nara" beyond
    // ~3km so it never reads as more precise than it is (item 8).
    const nearby = places ? nearestPlace(places, lat, lon) : null;
    if (nearby) {
      setPlaceName(nearby.distanceKm <= 3 ? nearby.place.name : t("map.nearPlace", { place: nearby.place.name }));
    } else {
      setPlaceName(`${lat.toFixed(4)}, ${lon.toFixed(4)}`);
    }
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

  const dataQualityWarning = useMemo(() => {
    if (!manifest) return null;
    if (manifest.cell_count < FULL_COVERAGE_MIN_CELLS) {
      return t("status.sampleData", { count: manifest.cell_count });
    }
    if (manifest.data_quality !== "normal") {
      return t("status.degraded");
    }
    return null;
  }, [manifest, t]);

  const staleWarning = useMemo(() => {
    if (!manifest) return null;
    const generatedAt = new Date(manifest.generated_at).getTime();
    const ageHours = (Date.now() - generatedAt) / 3600000;
    if (ageHours > 12) {
      return t("status.stale", { hours: Math.round(ageHours) });
    }
    return null;
  }, [manifest, t]);

  function handleRetry() {
    clearFetchCache();
    setRefreshKey((k) => k + 1);
  }

  const loadingBanner = manifestLoading ? t("panel.loading") : null;
  const errorBanner = manifestError
    ? t("status.loadFailed", { error: manifestError })
    : dailyError || hourlyError || null;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-title">{t("app.title")}</div>
        {manifest && (
          <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)" }}>
            {t("app.updated", {
              date: new Date(manifest.generated_at).toLocaleTimeString(locale === "sv" ? "sv-SE" : undefined, {
                hour: "2-digit",
                minute: "2-digit",
                timeZone: STOCKHOLM_TZ,
              }),
            })}
          </div>
        )}
      </header>

      <div className="map-area">
        <Suspense fallback={<MapSkeleton label={t("loading.map")} />}>
          <MapView
            cells={cells ?? []}
            valuesByCellId={valuesByCellId}
            layer={layer}
            selectedLat={selectedLat}
            selectedLon={selectedLon}
            selectedCellId={selectedCell?.cell_id ?? null}
            abundanceThresholds={manifest?.thresholds?.abundance}
            onSelectLocation={(lat, lon) => handleSelectLocation(lat, lon)}
            userLocation={userLocation}
            onBackgroundTap={() => setSheetState("closed")}
          />
        </Suspense>

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
            handleSelectLocation(lat, lon, t("search.myLocation"));
          }}
          animating={animating}
          onToggleAnimation={() => setAnimating((a) => !a)}
        />

        <Legend layer={layer} abundanceThresholds={manifest?.thresholds?.abundance} />

        {(loadingBanner || errorBanner || dataQualityWarning || staleWarning) && (
          <StatusBanner
            message={errorBanner ?? loadingBanner ?? dataQualityWarning ?? staleWarning ?? ""}
            // Sample/limited-coverage data gets the same visually-prominent
            // "error" treatment as a real error -- this is a trust-critical
            // notice (don't let sparse example data read as full coverage),
            // not a minor informational aside.
            tone={errorBanner || (manifest && manifest.cell_count < FULL_COVERAGE_MIN_CELLS) ? "error" : "info"}
            onRetry={errorBanner ? handleRetry : undefined}
          />
        )}
      </div>

      <BottomSheet state={sheetState} onStateChange={setSheetState}>
        <LocationPanel
          placeName={placeName || t("panel.defaultLocationLabel")}
          latitude={selectedLat}
          longitude={selectedLon}
          cellId={selectedCell?.cell_id ?? null}
          manifest={manifest}
          activity={activity}
          layer={layer}
          activeRecord={activeRecord}
          activeDailyRecord={activeDailyRecord}
          isHourlyDay={isHourlyDay}
          hourLabel={isHourlyDay ? hourLabel : null}
          dayIndex={dayIndex}
          daypart={daypart}
          date={date}
          series={series}
          loading={dailyLoading || hourlyLoading || seriesLoading}
          error={dailyError || hourlyError || seriesError}
          onShare={handleShare}
          shareCopied={shareCopied}
        />
      </BottomSheet>
    </div>
  );
}
