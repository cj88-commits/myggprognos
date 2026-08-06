import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import type { CombinationParams } from "../types/forecast";
import type { LocationSeries } from "../hooks/useForecastData";
import { finalRiskForActivity, riskCategory } from "../lib/riskModel";
import { formatStockholmHourShort, hourBucketToDate, STOCKHOLM_TZ } from "../lib/time";

// Waking-hours sample (item 8: "decision support, not analytics") -- a
// compact dawn-to-night strip rather than a full 24-point chart, matching
// the shape of the spec's own example ("08 🟢 10 🟢 ... 22 🔴"). The
// SevenDayChart/HourlyChart (recharts) remain available lower down, inside
// the "Tekniska detaljer" disclosure, for anyone who wants the full curve.
const TARGET_HOURS = [6, 8, 10, 12, 14, 16, 18, 20, 22];

function stockholmDateKey(hourLabel: string): string {
  return hourBucketToDate(hourLabel).toLocaleDateString("sv-SE", { timeZone: STOCKHOLM_TZ });
}

export interface HourTimelineProps {
  hourly: LocationSeries["hourly"];
  date: string; // Stockholm-local date (YYYY-MM-DD) to show, e.g. selected day
  activityMultiplier: number;
  combination?: CombinationParams;
}

export function HourTimeline({ hourly, date, activityMultiplier, combination }: HourTimelineProps) {
  const { t, locale } = useI18n();

  const points = TARGET_HOURS.map((targetHour) => {
    const entry = hourly.find(
      (h) =>
        stockholmDateKey(h.hourLabel) === date &&
        parseInt(formatStockholmHourShort(h.hourLabel, locale), 10) === targetHour
    );
    if (!entry) return null;
    const risk = finalRiskForActivity(
      entry.population_potential,
      entry.biting_activity,
      entry.base_exposure_fraction,
      activityMultiplier,
      combination
    );
    return { hour: targetHour, risk, category: riskCategory(risk) };
  }).filter((p): p is { hour: number; risk: number; category: ReturnType<typeof riskCategory> } => p !== null);

  if (points.length === 0) return null;

  // Label the worst hour directly on the strip (item 5) -- "instantly
  // understand when mosquitoes are worst" without reading every dot.
  // Skipped when every sampled hour is tied (nothing distinctly "worst").
  const peakRisk = Math.max(...points.map((p) => p.risk));
  const peakIsDistinct = points.some((p) => p.risk < peakRisk);
  const peakHour = peakIsDistinct ? points.find((p) => p.risk === peakRisk)?.hour : undefined;

  return (
    <div>
      <div className="section-title">{t("panel.timelineTitle")}</div>
      <div className="hour-timeline" role="list" aria-label={t("panel.timelineTitle")}>
        {points.map((p) => (
          <div className="hour-timeline-point" role="listitem" key={p.hour}>
            {p.hour === peakHour && <span className="hour-timeline-peak-label">{t("panel.timelinePeak")}</span>}
            <span className="hour-timeline-dot" style={{ background: p.category.color }} aria-hidden="true" />
            <span className="hour-timeline-hour" aria-hidden="true">
              {p.hour}
            </span>
            <span className="sr-only">
              {t("panel.timelineAriaLabel", {
                hour: String(p.hour),
                category: t(`risk.category.${p.category.key}` as I18nKey),
              })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
