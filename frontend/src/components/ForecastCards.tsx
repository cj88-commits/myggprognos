import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import type { CombinationParams, DailyRecord } from "../types/forecast";
import { categoryIntensity, categoryRank, finalRiskForActivity, riskCategory } from "../lib/riskModel";
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
      // Subtle shading within the category (item 11: "41 and 59 are both
      // moderate but shouldn't look identical") -- never changes which
      // category a day falls in, just how saturated its badge looks within
      // that band.
      const intensity = categoryIntensity(risk, category);
      const label =
        relative === 0
          ? t("panel.cardToday")
          : relative === 1
            ? t("panel.cardTomorrow")
            : formatStockholmDateLabel(d.date, locale);
      const peakTime = d.daily_peak_local_time
        ? t("panel.cardPeak", { time: d.daily_peak_local_time.slice(0, 2) })
        : t("panel.cardPeakUnknown");
      return { key: d.date, label, category, peakTime, risk, intensity };
    });

  if (cards.length === 0) return null;

  // Highlight the best/worst day so users can compare at a glance (item 6)
  // -- gated on the *displayed category* differing, not the raw score.
  // Two days can both read "Måttlig" while differing by a fraction of a
  // point internally; badging one "HÖGST RISK" and the other "LÄGST RISK"
  // in that case reads as an arbitrary/misleading ranking of two days a
  // user can plainly see are shown identically. categoryRank (already
  // used elsewhere to compare Myggrisk/Myggläge tiers) reuses the exact
  // category each card already displays, so this is presentation-only --
  // no new scoring, nothing invented.
  let bestIdx = -1;
  let worstIdx = -1;
  if (cards.length > 1) {
    const ranks = cards.map((c) => categoryRank(c.category.key));
    const minRank = Math.min(...ranks);
    const maxRank = Math.max(...ranks);
    if (minRank !== maxRank) {
      // A tie *within* the best or worst tier (e.g. two days both the
      // lowest-ranked category) is exactly the "arbitrarily pick the
      // first one" case to avoid -- suppress that specific badge rather
      // than crown one of several equally-ranked days.
      const bestCandidates = ranks.flatMap((r, i) => (r === minRank ? [i] : []));
      const worstCandidates = ranks.flatMap((r, i) => (r === maxRank ? [i] : []));
      if (bestCandidates.length === 1) bestIdx = bestCandidates[0];
      if (worstCandidates.length === 1) worstIdx = worstCandidates[0];
    }
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
            <span
              className="forecast-card-badge"
              style={{ background: c.category.color, opacity: 0.6 + 0.4 * c.intensity }}
              aria-hidden="true"
            />
            <div className="forecast-card-category">{t(`risk.category.${c.category.key}` as I18nKey)}</div>
            <div className="forecast-card-peak">{c.peakTime}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
