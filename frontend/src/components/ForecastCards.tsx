import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import type { CombinationParams, DailyRecord } from "../types/forecast";
import { finalRiskForActivity, riskCategory } from "../lib/riskModel";
import { currentDateIso, formatStockholmDateLabel } from "../lib/time";

export interface ForecastCardsProps {
  daily: DailyRecord[];
  activityMultiplier: number;
  combination?: CombinationParams;
}

// Today/tomorrow/day-after as three plain cards (item 10) -- lets someone
// plan a weekend without reading a line chart. The 7-day chart further down
// (inside "Tekniska detaljer") still covers the full week for anyone who
// wants it.
export function ForecastCards({ daily, activityMultiplier, combination }: ForecastCardsProps) {
  const { t, locale } = useI18n();
  const today = currentDateIso();
  const todayIndex = daily.findIndex((d) => d.date === today);

  const cards = daily
    .map((d, idx) => ({ d, relative: todayIndex === -1 ? idx : idx - todayIndex }))
    .filter((x) => x.relative >= 0 && x.relative <= 2)
    .map(({ d, relative }) => {
      const risk = finalRiskForActivity(
        d.population_potential,
        d.biting_activity,
        d.base_exposure_fraction,
        activityMultiplier,
        combination
      );
      const category = riskCategory(risk);
      const label =
        relative === 0
          ? t("panel.cardToday")
          : relative === 1
            ? t("panel.cardTomorrow")
            : formatStockholmDateLabel(d.date, locale);
      const peakTime = d.daily_peak_local_time
        ? t("panel.cardPeak", { time: d.daily_peak_local_time.slice(0, 2) })
        : t("panel.cardPeakUnknown");
      return { key: d.date, label, category, peakTime, risk };
    });

  if (cards.length === 0) return null;

  // Highlight the best/worst day so users can compare at a glance (item 6)
  // -- only meaningful with more than one card, and only when the days
  // actually differ (no point calling one day both "best" and "worst" out
  // of an otherwise-identical set).
  const risksDiffer = cards.some((c) => c.risk !== cards[0].risk);
  let bestIdx = -1;
  let worstIdx = -1;
  if (cards.length > 1 && risksDiffer) {
    bestIdx = cards.reduce((best, c, i) => (c.risk < cards[best].risk ? i : best), 0);
    worstIdx = cards.reduce((worst, c, i) => (c.risk > cards[worst].risk ? i : worst), 0);
  }

  return (
    <div>
      <div className="section-title">{t("panel.cardsTitle")}</div>
      <div className="forecast-cards" role="list" aria-label={t("panel.cardsTitle")}>
        {cards.map((c, i) => (
          <div
            className={`forecast-card${i === bestIdx ? " forecast-card--best" : ""}${i === worstIdx ? " forecast-card--worst" : ""}`}
            role="listitem"
            key={c.key}
          >
            {i === bestIdx && <span className="forecast-card-tag forecast-card-tag--best">{t("panel.cardBest")}</span>}
            {i === worstIdx && <span className="forecast-card-tag forecast-card-tag--worst">{t("panel.cardWorst")}</span>}
            <div className="forecast-card-label">{c.label}</div>
            <span className="forecast-card-badge" style={{ background: c.category.color }} aria-hidden="true" />
            <div className="forecast-card-category">{t(`risk.category.${c.category.key}` as I18nKey)}</div>
            <div className="forecast-card-peak">{c.peakTime}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
