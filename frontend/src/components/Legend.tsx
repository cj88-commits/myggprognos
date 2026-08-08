import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import { abundanceCategory, DEFAULT_ABUNDANCE_THRESHOLDS, RISK_CATEGORIES } from "../lib/riskModel";
import type { LayerKey } from "../types/forecast";

// Exactly two public products reach this component now (item 2 -- Myggrisk
// and Myggläge only; biting_activity/confidence are technical-details-only
// figures, never an independently legended layer). A legacy URL carrying one
// of the old layer values is redirected before it ever reaches here (see
// urlState.ts's LEGACY_LAYER_ALIASES), so this only ever needs to
// distinguish the two.
function isAbundance(layer: LayerKey): boolean {
  return layer === "population_potential";
}

// Practical, per-category meaning (item 3 + item 4) -- deliberately two
// separate sentence sets: Myggrisk answers "will I get bitten", Myggläge
// answers "are there generally many mosquitoes here". Reusing one set for
// both would blur exactly the distinction the legend exists to make clear.
function explainKey(layer: LayerKey, categoryKey: string): I18nKey {
  return (isAbundance(layer) ? `legend.abundance.explain.${categoryKey}` : `legend.risk.explain.${categoryKey}`) as I18nKey;
}

export function Legend({ layer, abundanceThresholds }: { layer: LayerKey; abundanceThresholds?: number[] }) {
  const { t } = useI18n();
  const abundance = isAbundance(layer);

  // Myggläge uses its own 0-100 bounds (docs/calibration-validation-final.md
  // "Myggläge thresholds") so its legend swatches, unlike the shared risk
  // ones, aren't at RISK_CATEGORIES' fixed bounds -- built from the same
  // edges abundanceCategory() uses via each band's midpoint, so the
  // legend's five colors always match what a real score in that band would
  // actually render as.
  const edges = abundanceThresholds ?? DEFAULT_ABUNDANCE_THRESHOLDS;
  const abundanceMidpoints = [edges[0] / 2, (edges[0] + edges[1]) / 2, (edges[1] + edges[2]) / 2, (edges[2] + edges[3]) / 2, edges[3] + 5];

  const rows = abundance
    ? abundanceMidpoints.map((v) => {
        const c = abundanceCategory(v, edges);
        return { key: c.key, label: t(`risk.category.${c.key}` as I18nKey), color: c.color, explain: t(explainKey(layer, c.key)) };
      })
    : RISK_CATEGORIES.map((c) => ({
        key: c.key,
        label: t(`risk.category.${c.key}` as I18nKey),
        color: c.color,
        explain: t(explainKey(layer, c.key)),
      }));

  const modeLabel = t(abundance ? "legend.modeAbundance" : "legend.modeRisk");

  return (
    <details className="legend">
      <summary aria-label={t("legend.whatColorsMean")}>
        <span className="legend-arrow" aria-hidden="true" />
        <strong>{t("legend.whatColorsMean")}</strong>
      </summary>
      <div className="legend-panel">
        <div className="legend-mode">{modeLabel}</div>
        <div className="legend-scale">
          {rows.map((row) => (
            <div className="legend-row" key={row.key}>
              <span className="chip" style={{ background: row.color }} aria-hidden="true" />
              <div className="legend-row-text">
                <span className="legend-row-label">{row.label}</span>
                <span className="legend-row-explain">{row.explain}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}
