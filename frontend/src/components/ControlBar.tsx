import { useState } from "react";
import { ACTIVITY_KEYS, LAYER_KEYS, type LayerKey, type Manifest, type PlaceRecord } from "../types/forecast";
import { SearchBox } from "./SearchBox";
import { useGeolocation } from "../hooks/useGeolocation";
import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";

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

  // Only meaningful on mobile (see .filters-panel / .filters-toggle in
  // global.css) -- on desktop the panel is always visible inline
  // (`display: contents`) and this state is simply never read.
  const [filtersOpen, setFiltersOpen] = useState(false);

  function formatDateLabel(dateIso: string): string {
    const d = new Date(dateIso + "T00:00:00Z");
    return d.toLocaleDateString(locale === "sv" ? "sv-SE" : undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });
  }

  const dayLabel = dayOptions.indexOf(date) === 0 ? t("controlBar.today") : formatDateLabel(date);
  const timeLabel = isHourlyDay ? `${String(hour ?? 0).padStart(2, "0")}:00` : t(`daypart.${daypart}` as I18nKey);
  // Compact summary shown on the mobile-only toggle button so the current
  // filter state is visible without opening the sheet -- e.g. "Idag · 18:00".
  const filtersSummary = `${dayLabel} · ${timeLabel}`;

  return (
    <div className="control-bar">
      <div className="control-group control-group-search">
        <SearchBox places={places} onSelect={(lat, lon) => onSelectLocation(lat, lon)} />
      </div>

      <div className="control-group">
        <button
          type="button"
          className="icon-button"
          onClick={locate}
          aria-label={t("controlBar.useMyLocation")}
          title={geoError ?? t("controlBar.useMyLocation")}
        >
          {locating ? "…" : "📍"}
        </button>
      </div>

      <button
        type="button"
        className="filters-toggle"
        onClick={() => setFiltersOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={filtersOpen}
      >
        <span className="filters-toggle-label">{t("controlBar.filters")}</span>
        <span className="filters-toggle-summary">{filtersSummary}</span>
      </button>

      {filtersOpen && (
        <div className="filters-backdrop" onClick={() => setFiltersOpen(false)} aria-hidden="true" />
      )}

      <div className={`filters-panel${filtersOpen ? " open" : ""}`} role="dialog" aria-modal={filtersOpen}>
        <div className="filters-panel-header">
          <span className="filters-panel-title">{t("controlBar.filters")}</span>
          <button
            type="button"
            className="icon-button filters-close"
            onClick={() => setFiltersOpen(false)}
            aria-label={t("controlBar.closeFilters")}
          >
            ✕
          </button>
        </div>

        <div className="control-group">
          <label htmlFor="date-select">{t("controlBar.day")}</label>
          <select id="date-select" value={date} onChange={(e) => onDateChange(e.target.value)}>
            {dayOptions.map((d, i) => (
              <option key={d} value={d}>
                {i === 0 ? t("controlBar.today") : formatDateLabel(d)}
              </option>
            ))}
          </select>
        </div>

        {isHourlyDay ? (
          <div className="control-group">
            <label htmlFor="hour-select">{t("controlBar.hour")}</label>
            <input
              id="hour-select"
              type="range"
              min={0}
              max={23}
              step={1}
              value={hour ?? 0}
              onChange={(e) => onHourChange(parseInt(e.target.value, 10))}
              aria-valuetext={`${hour ?? 0}:00 UTC`}
            />
            <span aria-hidden="true">{String(hour ?? 0).padStart(2, "0")}:00</span>
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
            <label htmlFor="daypart-select">{t("controlBar.timeOfDay")}</label>
            <select id="daypart-select" value={daypart} onChange={(e) => onDaypartChange(e.target.value)}>
              {DAYPARTS.map((part) => (
                <option key={part} value={part}>
                  {t(`daypart.${part}` as I18nKey)}
                </option>
              ))}
            </select>
          </div>
        )}

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
