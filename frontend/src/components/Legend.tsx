import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import { abundanceCategory, DATA_QUALITY_CATEGORIES, DEFAULT_ABUNDANCE_THRESHOLDS, RISK_CATEGORIES } from "../lib/riskModel";
import type { LayerKey } from "../types/forecast";

// Every layer key needs its own title -- previously only "confidence" had
// one, and everything else (including population_potential and
// biting_activity) silently fell back to "Myggrisk (0-100)", so the
// legend kept saying "mosquito risk" even while showing e.g. Myggaktivitet.
// The legend must change meaning according to the selected product (daily
// peak vs. right-now vs. abundance are different claims on the same 0-100
// scale) -- see the "forecast products" iteration.
const LEGEND_TITLE_KEYS: Record<LayerKey, I18nKey> = {
  daily_peak_risk: "legend.dailyPeakTitle",
  current_risk: "legend.currentRiskTitle",
  population_potential: "legend.populationTitle",
  biting_activity: "legend.activityTitle",
  confidence: "legend.confidenceTitle",
};

export function Legend({ layer, abundanceThresholds }: { layer: LayerKey; abundanceThresholds?: number[] }) {
  const { t } = useI18n();

  // "Prognosunderlag" (data quality) uses its own four qualitative bands --
  // deliberately not a continuous 0-100 scale, since the point is "how much
  // to trust this", not a precise measurement (see riskModel.ts). Myggläge
  // uses its own 0-100 bounds (docs/model-audit-after.md) so its legend
  // swatches, unlike the shared risk ones, aren't at RISK_CATEGORIES' fixed
  // 0/20/40/60/80 -- built from the same edges abundanceCategory() uses via
  // its midpoint, so the legend's five colors always match what a real
  // score in that band would actually render as.
  const edges = abundanceThresholds ?? DEFAULT_ABUNDANCE_THRESHOLDS;
  const abundanceMidpoints = [edges[0] / 2, (edges[0] + edges[1]) / 2, (edges[1] + edges[2]) / 2, (edges[2] + edges[3]) / 2, edges[3] + 5];
  const stops =
    layer === "confidence"
      ? DATA_QUALITY_CATEGORIES.map((c) => ({ label: t(`dataQuality.${c.key}` as I18nKey), color: c.color }))
      : layer === "population_potential"
        ? abundanceMidpoints.map((v) => {
            const c = abundanceCategory(v, edges);
            return { label: t(`risk.category.${c.key}` as I18nKey), color: c.color };
          })
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
