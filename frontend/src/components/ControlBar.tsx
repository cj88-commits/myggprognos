import { useState } from "react";
import {
  ACTIVITY_KEYS,
  LAYER_KEYS,
  PRIMARY_PRODUCT_KEYS,
  type LayerKey,
  type Manifest,
  type PlaceRecord,
} from "../types/forecast";
import { SearchBox } from "./SearchBox";
import { useGeolocation } from "../hooks/useGeolocation";
import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import { formatStockholmDateLabel, formatStockholmHourShort } from "../lib/time";

function addDaysIso(dateIso: string, days: number): string {
  const d = new Date(dateIso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export interface ControlBarProps {
  manifest: Manifest | null;
  places: PlaceRecord[];
  date: string;
  onDateChange: (date: string) => void;
  isHourlyDay: boolean;
  hour: number | null;
  onHourChange: (hour: number) => void;
  daypart: string;
  onDaypartChange: (daypart: string) => void;
  activity: string;
  onActivityChange: (activity: string) => void;
  layer: LayerKey;
  onLayerChange: (layer: LayerKey) => void;
  onSelectLocation: (lat: number, lon: number) => void;
  animating: boolean;
  onToggleAnimation: () => void;
}

const DAYPARTS = ["morning", "afternoon", "evening", "night"];

export function ControlBar({
  manifest,
  places,
  date,
  onDateChange,
  isHourlyDay,
  hour,
  onHourChange,
  daypart,
  onDaypartChange,
  activity,
  onActivityChange,
  layer,
  onLayerChange,
  onSelectLocation,
  animating,
  onToggleAnimation,
}: ControlBarProps) {
  const { t, locale } = useI18n();
  const forecastStart = manifest?.forecast_start ?? new Date().toISOString().slice(0, 10);
  const dayOptions = Array.from({ length: 7 }, (_, i) => addDaysIso(forecastStart, i));

  const { locate, loading: locating, error: geoError } = useGeolocation(onSelectLocation);

  // Desktop keeps every control inline (unchanged) behind "Fler
  // installningar" for just activity/map-view, same as before. Mobile
  // collapses everything except search behind a single settings sheet --
  // the map itself was too cluttered with buttons to pan/zoom reliably
  // (confirmed by the user on a real phone). Same open/close state drives
  // both; only which controls live inline vs. inside the sheet differs by
  // breakpoint (see .control-bar-inline / .control-bar-sheet-only in
  // global.css).
  const [advancedOpen, setAdvancedOpen] = useState(false);

  function formatDateLabel(dateIso: string): string {
    return formatStockholmDateLabel(dateIso, locale);
  }

  // Hour buckets are stored/keyed in UTC (see manifest.hourly_files), but
  // this is the one and only place that ever turns one into a clock time
  // shown to a user -- always Europe/Stockholm (item 4: never show UTC).
  const stockholmHour =
    isHourlyDay && hour !== null ? formatStockholmHourShort(`${date}T${String(hour).padStart(2, "0")}`, locale) : "";
  // Compact summary shown on the settings toggle (desktop only -- see
  // .filters-toggle-summary, hidden on mobile where the button is icon-only)
  // so current activity/map-view state is visible without opening the panel.
  const advancedSummary = `${t(`activity.${activity}` as I18nKey)} · ${t(`layer.${layer}` as I18nKey)}`;

  // Locate button + product switch + day + hour/daypart: rendered once
  // inline for desktop (idSuffix "") and once again inside the mobile
  // settings sheet (idSuffix "-mobile") -- CSS shows exactly one copy per
  // breakpoint (see .control-bar-inline / .control-bar-sheet-only), never
  // both. A shared function instead of writing this twice by hand; id
  // suffixes keep the two copies' <label htmlFor>/<select id> pairs valid
  // (DOM ids must be unique even though only one copy is ever visible).
  function renderCoreControls(idSuffix: string) {
    const dateId = `date-select${idSuffix}`;
    const hourId = `hour-select${idSuffix}`;
    const daypartId = `daypart-select${idSuffix}`;
    return (
      <>
        <button
          type="button"
          className="icon-button"
          onClick={locate}
          aria-label={t("controlBar.useMyLocation")}
          title={geoError ?? t("controlBar.useMyLocation")}
        >
          {locating ? "…" : "📍"}
        </button>

        <div className="control-group product-switch" role="group" aria-label={t("controlBar.layer")}>
          {PRIMARY_PRODUCT_KEYS.map((key) => (
            <button
              key={key}
              type="button"
              className="option-chip"
              aria-pressed={layer === key}
              onClick={() => onLayerChange(key)}
            >
              {t(`layer.${key}` as I18nKey)}
            </button>
          ))}
        </div>

        <div className="control-group">
          <label htmlFor={dateId}>{t("controlBar.day")}</label>
          <select id={dateId} value={date} onChange={(e) => onDateChange(e.target.value)}>
            {dayOptions.map((d, i) => (
              <option key={d} value={d}>
                {i === 0 ? t("controlBar.today") : formatDateLabel(d)}
              </option>
            ))}
          </select>
        </div>

        {isHourlyDay ? (
          <div className="control-group">
            <label htmlFor={hourId}>{t("controlBar.hour")}</label>
            <input
              id={hourId}
              type="range"
              min={0}
              max={23}
              step={1}
              value={hour ?? 0}
              onChange={(e) => onHourChange(parseInt(e.target.value, 10))}
              aria-valuetext={stockholmHour}
            />
            <span aria-hidden="true">{stockholmHour}</span>
            <button
              type="button"
              className="icon-button"
              aria-pressed={animating}
              onClick={onToggleAnimation}
              title={t("controlBar.playPause")}
            >
              {animating ? "⏸" : "▶"}
            </button>
          </div>
        ) : (
          <div className="control-group">
            <label htmlFor={daypartId}>{t("controlBar.timeOfDay")}</label>
            <select id={daypartId} value={daypart} onChange={(e) => onDaypartChange(e.target.value)}>
              {DAYPARTS.map((part) => (
                <option key={part} value={part}>
                  {t(`daypart.${part}` as I18nKey)}
                </option>
              ))}
            </select>
          </div>
        )}
      </>
    );
  }

  return (
    <div className="control-bar">
      <div className="control-group control-group-search">
        <SearchBox places={places} onSelect={(lat, lon) => onSelectLocation(lat, lon)} />
      </div>

      {/* Desktop: identical to the pre-redesign inline layout (display:contents
          makes these direct flex items of .control-bar). Mobile hides this
          whole block -- the same controls reappear inside the sheet below. */}
      <div className="control-bar-inline">{renderCoreControls("")}</div>

      <button
        type="button"
        className="filters-toggle"
        onClick={() => setAdvancedOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={advancedOpen}
        aria-label={t("controlBar.filters")}
      >
        <span className="filters-toggle-icon" aria-hidden="true">
          ⚙
        </span>
        <span className="filters-toggle-label">{t("controlBar.filters")}</span>
        <span className="filters-toggle-summary">{advancedSummary}</span>
      </button>

      {advancedOpen && (
        <div className="filters-backdrop" onClick={() => setAdvancedOpen(false)} aria-hidden="true" />
      )}

      <div className={`filters-panel${advancedOpen ? " open" : ""}`} role="dialog" aria-modal={advancedOpen}>
        <div className="filters-panel-header">
          <span className="filters-panel-title">{t("controlBar.filters")}</span>
          <button
            type="button"
            className="icon-button filters-close"
            onClick={() => setAdvancedOpen(false)}
            aria-label={t("controlBar.closeFilters")}
          >
            ✕
          </button>
        </div>

        {/* Mobile only: on desktop these are already shown inline above via
            .control-bar-inline, so this second copy stays display:none there
            (see global.css) and only appears inside the mobile breakpoint. */}
        <div className="control-bar-sheet-only">{renderCoreControls("-mobile")}</div>

        <div className="control-group">
          <label htmlFor="activity-select">{t("controlBar.activity")}</label>
          <select id="activity-select" value={activity} onChange={(e) => onActivityChange(e.target.value)}>
            {ACTIVITY_KEYS.map((key) => (
              <option key={key} value={key}>
                {t(`activity.${key}` as I18nKey)}
              </option>
            ))}
          </select>
        </div>

        <div className="control-group">
          <label htmlFor="layer-select">{t("controlBar.layer")}</label>
          <select id="layer-select" value={layer} onChange={(e) => onLayerChange(e.target.value as LayerKey)}>
            {LAYER_KEYS.map((key) => (
              <option key={key} value={key}>
                {t(`layer.${key}` as I18nKey)}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}
