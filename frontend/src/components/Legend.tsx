import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import { RISK_CATEGORIES } from "../lib/riskModel";
import type { LayerKey } from "../types/forecast";

const CONFIDENCE_STOPS: { key: "low" | "medium" | "high"; color: string }[] = [
  { key: "low", color: "#d9432e" },
  { key: "medium", color: "#f2c94c" },
  { key: "high", color: "#2e8b4f" },
];

// Every layer key needs its own title -- previously only "confidence" had
// one, and everything else (including population_potential and
// biting_activity) silently fell back to "Myggrisk (0-100)", so the
// legend kept saying "mosquito risk" even while showing e.g. Bettaktivitet.
const LEGEND_TITLE_KEYS: Record<LayerKey, I18nKey> = {
  risk: "legend.riskTitle",
  population_potential: "legend.populationTitle",
  biting_activity: "legend.activityTitle",
  confidence: "legend.confidenceTitle",
};

export function Legend({ layer }: { layer: LayerKey }) {
  const { t } = useI18n();

  const stops =
    layer === "confidence"
      ? CONFIDENCE_STOPS.map((s) => ({ label: t(`confidence.${s.key}` as I18nKey), color: s.color }))
      : RISK_CATEGORIES.map((c) => ({ label: t(`risk.category.${c.key}` as I18nKey), color: c.color }));

  const title = t(LEGEND_TITLE_KEYS[layer]);

  return (
    <details className="legend">
      <summary aria-label={title}>
        <span className="legend-arrow" aria-hidden="true" />
        <strong>{title}</strong>
      </summary>
      <div className="legend-scale">
        {stops.map((stop) => (
          <div className="legend-swatch" key={stop.label}>
            <div className="chip" style={{ background: stop.color }} aria-hidden="true" />
            <span>{stop.label}</span>
          </div>
        ))}
      </div>
    </details>
  );
}
