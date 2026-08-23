import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import type { CombinationParams, DailyRecord } from "../types/forecast";
import { abundanceCategory, finalRiskForActivity, riskCategory } from "../lib/riskModel";
import { formatStockholmWeekday } from "../lib/time";

export interface DaySelectorProps {
  dayOptions: string[];
  date: string;
  onDateChange: (date: string) => void;
  // Per-day records for the *selected* location, already fetched for the
  // 7-day chart/cards (see App.tsx `series.daily`) -- reused here rather
  // than fetching anything new, so the risk badge under each day costs
  // nothing extra over the plain day buttons.
  dailyByDate: Map<string, DailyRecord> | null;
  isAbundanceLayer: boolean;
  activityMultiplier: number;
  combination?: CombinationParams;
  abundanceThresholds?: number[];
}

function capitalize(s: string): string {
  return s.length > 0 ? s[0].toUpperCase() + s.slice(1) : s;
}

// Replaces the old single date <select> (item 2 of the public-launch UX
// pass): a horizontal, always-visible 7-day strip so the available
// forecast days are scannable at a glance instead of hidden inside a
// dropdown. Purely a UI change -- `onDateChange` drives the exact same
// `date` state the old select did, so map sync / URL state / everything
// downstream is untouched.
export function DaySelector({
  dayOptions,
  date,
  onDateChange,
  dailyByDate,
  isAbundanceLayer,
  activityMultiplier,
  combination,
  abundanceThresholds,
}: DaySelectorProps) {
  const { t, locale } = useI18n();

  return (
    <div className="day-selector">
      <div className="day-selector-scroll" role="group" aria-label={t("daySelector.ariaLabel")}>
        {dayOptions.map((d, i) => {
          const record = dailyByDate?.get(d) ?? null;
          let categoryKey: string | null = null;
          let categoryColor: string | null = null;
          if (record) {
            if (isAbundanceLayer) {
              const cat = abundanceCategory(record.population_potential, abundanceThresholds);
              categoryKey = cat.key;
              categoryColor = cat.color;
            } else {
              const risk = finalRiskForActivity(
                record.population_potential,
                record.biting_activity,
                record.base_exposure_fraction,
                activityMultiplier,
                combination
              );
              const cat = riskCategory(risk);
              categoryKey = cat.key;
              categoryColor = cat.color;
            }
          }
          const label = i === 0 ? t("controlBar.today") : capitalize(formatStockholmWeekday(d, locale));
          const selected = d === date;
          return (
            <button
              key={d}
              type="button"
              className="day-chip"
              aria-pressed={selected}
              onClick={() => onDateChange(d)}
            >
              <span className="day-chip-label">{label}</span>
              {categoryKey && (
                <span className="day-chip-category" style={{ color: categoryColor ?? undefined }}>
                  {t(`risk.category.${categoryKey}` as I18nKey)}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
