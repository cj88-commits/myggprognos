import { useState } from "react";
import { ACTIVITY_KEYS, SIMPLE_PRODUCT_KEYS, type LayerKey, type PlaceRecord } from "../types/forecast";
import { SearchBox } from "./SearchBox";
import { useGeolocation } from "../hooks/useGeolocation";
import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";

export interface ControlBarProps {
  places: PlaceRecord[];
  activity: string;
  onActivityChange: (activity: string) => void;
  layer: LayerKey;
  onLayerChange: (layer: LayerKey) => void;
  // Search result selection (with the place's real name/label) and the
  // "use my location" geolocation button are deliberately two separate
  // callbacks -- they used to share one prop, which meant every search
  // result silently got relabelled "Din plats" (the geolocation label) and
  // dropped a "my location" pin at the searched place. See App.tsx.
  onSearchSelect: (lat: number, lon: number, label: string) => void;
  onLocate: (lat: number, lon: number) => void;
}

export function ControlBar({
  places,
  activity,
  onActivityChange,
  layer,
  onLayerChange,
  onSearchSelect,
  onLocate,
}: ControlBarProps) {
  const { t } = useI18n();

  const { locate, loading: locating, error: geoError } = useGeolocation(onLocate);

  // Users do not care about the model -- only search and geolocation are
  // always-visible controls now (item 1 of the public-launch UX pass: the
  // opening state prioritises the primary consumer question, "how's the
  // mosquito situation where I am", not a choice between two underlying
  // metrics). Which day to view lives in the answer panel itself (see
  // DaySelector in LocationPanel); which product (Myggrisk/Myggläge) and
  // activity profile live behind this one settings icon.
  const [advancedOpen, setAdvancedOpen] = useState(false);

  return (
    <div className="control-bar">
      {/* Search + geolocate are strictly map controls -- they select WHERE
          on the map, not what to show about it -- so they're grouped for
          layout/alignment purposes. The whole .control-bar (this group
          plus the settings gear) is hidden as one unit while the answer
          sheet is fully expanded -- see the .bottom-sheet--full rule in
          global.css. */}
      <div className="map-only-controls">
        <div className="control-group control-group-search">
          <SearchBox places={places} onSelect={onSearchSelect} />
        </div>

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

        {/* Myggrisk vs Myggläge (item 1): demoted from an always-visible
            primary control into this settings panel -- a first-time
            visitor should never have to understand the distinction before
            using the site, but it stays one tap away for anyone who wants
            it. */}
        <div className="control-group product-switch-group">
          <label>{t("controlBar.productSwitchLabel")}</label>
          <div className="product-switch" role="group" aria-label={t("controlBar.layer")}>
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
          <p className="filters-hint">{t("controlBar.productSwitchHint")}</p>
        </div>

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
