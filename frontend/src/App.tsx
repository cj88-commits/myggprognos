import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { ControlBar } from "./components/ControlBar";
import { Legend } from "./components/Legend";
import { StatusBanner } from "./components/StatusBanner";
import { LocationPanel } from "./components/LocationPanel";
import { BottomSheet, type SheetState } from "./components/BottomSheet";
import { useCells, useDailyForDate, useLocationSeries, useManifest, usePlaces } from "./hooks/useForecastData";
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

  const activityMultiplier = manifest?.activities?.[activity] ?? 1.0;

  // Both remaining products -- Myggrisk (daily_peak_risk) and Myggläge
  // (population_potential) -- always describe the WHOLE day/peak, never
  // whichever hour happens to be selected (see the "simplify around the
  // user's mental model" iteration: there is no longer an "just nu"/hour-
  // driven product to switch to). A legacy bookmarked link carrying one of
  // the old current_risk/biting_activity/confidence layer values falls
  // back to the risk calculation below rather than breaking.
  const valuesByCellId = useMemo(() => {
    if (!dailyRecords) return null;
    const map: Record<string, number> = {};
    for (const record of dailyRecords) {
      map[record.cell_id] =
        layer === "population_potential"
          ? record.population_potential
          : finalRiskForActivity(
              record.population_potential,
              record.biting_activity,
              record.base_exposure_fraction,
              activityMultiplier,
              manifest?.combination
            );
    }
    return map;
  }, [dailyRecords, layer, activityMultiplier, manifest?.combination]);

  const selectedCell = cells ? nearestCell(cells, selectedLat, selectedLon) : null;
  const { data: series, loading: seriesLoading, error: seriesError } = useLocationSeries(
    selectedCell?.cell_id ?? null,
    manifest,
    refreshKey
  );

  const activeDailyRecord: DailyRecord | null =
    dailyRecords?.find((r) => r.cell_id === selectedCell?.cell_id) ?? null;

  // The daily record's own top-level fields already ARE the peak daypart's
  // values (see pipeline.py) -- using it directly means Myggrisk/Myggläge
  // never depend on an hour/daypart selector that no longer exists in the UI.
  const activeRecord: ScoreFields | null = activeDailyRecord;

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
    : dailyError || null;

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
          activity={activity}
          onActivityChange={setActivity}
          layer={layer}
          onLayerChange={setLayer}
          onSelectLocation={(lat, lon) => {
            setUserLocation({ lat, lon });
            handleSelectLocation(lat, lon, t("search.myLocation"));
          }}
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
          loading={dailyLoading || seriesLoading}
          error={dailyError || seriesError}
          onShare={handleShare}
          shareCopied={shareCopied}
        />
      </BottomSheet>
    </div>
  );
}
