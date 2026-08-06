import { useState } from "react";
import { ACTIVITY_KEYS, SIMPLE_PRODUCT_KEYS, type LayerKey, type Manifest, type PlaceRecord } from "../types/forecast";
import { SearchBox } from "./SearchBox";
import { useGeolocation } from "../hooks/useGeolocation";
import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import { formatStockholmDateLabel } from "../lib/time";

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
  activity: string;
  onActivityChange: (activity: string) => void;
  layer: LayerKey;
  onLayerChange: (layer: LayerKey) => void;
  onSelectLocation: (lat: number, lon: number) => void;
}

export function ControlBar({
  manifest,
  places,
  date,
  onDateChange,
  activity,
  onActivityChange,
  layer,
  onLayerChange,
  onSelectLocation,
}: ControlBarProps) {
  const { t, locale } = useI18n();
  const forecastStart = manifest?.forecast_start ?? new Date().toISOString().slice(0, 10);
  const dayOptions = Array.from({ length: 7 }, (_, i) => addDaysIso(forecastStart, i));

  const { locate, loading: locating, error: geoError } = useGeolocation(onSelectLocation);

  // Users do not care about the model -- only search, "which product" and
  // "which day" are always-visible controls now. Everything else
  // (activity personalisation) lives behind this one settings icon. Same
  // open/close state drives both the desktop dropdown and the mobile
  // bottom sheet (see .filters-panel / .filters-toggle in global.css) --
  // only the positioning differs by media query, not the mechanism.
  const [advancedOpen, setAdvancedOpen] = useState(false);

  function formatDateLabel(dateIso: string): string {
    return formatStockholmDateLabel(dateIso, locale);
  }

  // Locate button + day picker: rendered once inline for desktop (idSuffix
  // "") and once again inside the mobile settings sheet (idSuffix
  // "-mobile") -- CSS shows exactly one copy per breakpoint (see
  // .control-bar-inline / .control-bar-sheet-only), never both. Id
  // suffixes keep the two copies' <label htmlFor>/<select id> pairs valid.
  function renderCoreControls(idSuffix: string) {
    const dateId = `date-select${idSuffix}`;
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
      </>
    );
  }

  return (
    <div className="control-bar">
      <div className="control-group control-group-search">
        <SearchBox places={places} onSelect={(lat, lon) => onSelectLocation(lat, lon)} />
      </div>

      {/* The only always-visible "which product" choice: Myggrisk (am I
          likely to get bitten) vs Myggläge (how favourable is this area in
          general). Segmented buttons, not a dropdown, so the selected mode
          is always visually obvious -- see the "simplify around the user's
          mental model" iteration. */}
      <div className="control-group product-switch" role="group" aria-label={t("controlBar.layer")}>
        {SIMPLE_PRODUCT_KEYS.map((key) => (
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
        <span className="filters-toggle-summary">{t(`activity.${activity}` as I18nKey)}</span>
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
      </div>
    </div>
  );
}
