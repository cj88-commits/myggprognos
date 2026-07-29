import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import type { DailyRecord } from "../types/forecast";
import { finalRiskForActivity, riskCategory } from "../lib/riskModel";
import type { LocationSeries } from "../hooks/useForecastData";

function dayLabel(dateIso: string, locale: string): string {
  const d = new Date(dateIso + "T00:00:00Z");
  return d.toLocaleDateString(locale === "sv" ? "sv-SE" : undefined, { weekday: "short", timeZone: "UTC" });
}

function hourLabelShort(hourLabel: string, locale: string): string {
  const d = new Date(hourLabel + ":00:00Z");
  return d.toLocaleTimeString(locale === "sv" ? "sv-SE" : undefined, { hour: "numeric", timeZone: "UTC" });
}

function ChartTooltip({
  active,
  payload,
  label,
  t,
}: {
  active?: boolean;
  payload?: { value: number }[];
  label?: string;
  t: (key: I18nKey, vars?: Record<string, string | number>) => string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const value = payload[0].value;
  const category = riskCategory(value);
  return (
    <div className="chart-tooltip">
      <div>{label}</div>
      <div>{t("chart.tooltip", { value: Math.round(value), category: t(`risk.category.${category.key}` as I18nKey) })}</div>
    </div>
  );
}

export function SevenDayChart({ daily, activityMultiplier }: { daily: DailyRecord[]; activityMultiplier: number }) {
  const { t, locale } = useI18n();
  const data = daily.map((d) => ({
    label: dayLabel(d.date, locale),
    risk: finalRiskForActivity(d.population_potential, d.biting_activity, d.base_exposure_fraction, activityMultiplier),
  }));

  return (
    <div style={{ width: "100%", height: 160 }}>
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 6, right: 8, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="riskFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#4fae6b" stopOpacity={0.5} />
              <stop offset="95%" stopColor="#4fae6b" stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} />
          <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} width={28} />
          <Tooltip content={<ChartTooltip t={t} />} />
          <Area type="monotone" dataKey="risk" stroke="#4fae6b" fill="url(#riskFill)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function HourlyChart({
  hourly,
  activityMultiplier,
}: {
  hourly: LocationSeries["hourly"];
  activityMultiplier: number;
}) {
  const { t, locale } = useI18n();
  const data = hourly.map((h) => ({
    label: hourLabelShort(h.hourLabel, locale),
    risk: finalRiskForActivity(h.population_potential, h.biting_activity, h.base_exposure_fraction, activityMultiplier),
  }));

  return (
    <div style={{ width: "100%", height: 160 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 6, right: 8, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={5} />
          <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} width={28} />
          <Tooltip content={<ChartTooltip t={t} />} />
          <Line type="monotone" dataKey="risk" stroke="#2b6fd6" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
