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
import type { DailyRecord } from "../types/forecast";
import { finalRiskForActivity, riskCategory } from "../lib/riskModel";
import type { LocationSeries } from "../hooks/useForecastData";

function dayLabel(dateIso: string): string {
  const d = new Date(dateIso + "T00:00:00Z");
  return d.toLocaleDateString(undefined, { weekday: "short", timeZone: "UTC" });
}

function hourLabelShort(hourLabel: string): string {
  const d = new Date(hourLabel + ":00:00Z");
  return d.toLocaleTimeString(undefined, { hour: "numeric", timeZone: "UTC" });
}

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { value: number }[]; label?: string }) {
  if (!active || !payload || payload.length === 0) return null;
  const value = payload[0].value;
  const category = riskCategory(value);
  return (
    <div className="chart-tooltip">
      <div>{label}</div>
      <div>
        Risk {value.toFixed(1)} &middot; {category.label}
      </div>
    </div>
  );
}

export function SevenDayChart({ daily, activityMultiplier }: { daily: DailyRecord[]; activityMultiplier: number }) {
  const data = daily.map((d) => ({
    label: dayLabel(d.date),
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
          <YAxis domain={[0, 10]} tick={{ fontSize: 11 }} width={28} />
          <Tooltip content={<ChartTooltip />} />
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
  const data = hourly.map((h) => ({
    label: hourLabelShort(h.hourLabel),
    risk: finalRiskForActivity(h.population_potential, h.biting_activity, h.base_exposure_fraction, activityMultiplier),
  }));

  return (
    <div style={{ width: "100%", height: 160 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 6, right: 8, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={5} />
          <YAxis domain={[0, 10]} tick={{ fontSize: 11 }} width={28} />
          <Tooltip content={<ChartTooltip />} />
          <Line type="monotone" dataKey="risk" stroke="#2b6fd6" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
