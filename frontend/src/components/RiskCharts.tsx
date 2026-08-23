import {
  Area,
  AreaChart,
  CartesianGrid,
  Label,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import type { CombinationParams, DailyRecord } from "../types/forecast";
import { abundanceBands, abundanceCategory, finalRiskForActivity, RISK_CATEGORIES, riskCategory } from "../lib/riskModel";
import type { LocationSeries } from "../hooks/useForecastData";
import { currentDateIso, currentHourBucketLabel, formatStockholmHourShort, formatStockholmWeekday } from "../lib/time";

// Light, translucent fills for the risk-category bands drawn behind the
// line/area (item 7: "coloured risk bands") -- distinct from (and much
// lower-opacity than) RISK_CATEGORIES' own solid swatch colors used
// elsewhere (legend, badges), since here they're a background reference,
// not the data itself.
const BAND_OPACITY = 0.12;

function RiskBands({ bands }: { bands: { min: number; max: number; key: string; color: string }[] }) {
  return (
    <>
      {bands.map((c) => (
        <ReferenceArea key={c.key} y1={c.min} y2={c.max} fill={c.color} fillOpacity={BAND_OPACITY} strokeWidth={0} />
      ))}
    </>
  );
}

function ChartTooltip({
  active,
  payload,
  t,
  categoryFor,
}: {
  active?: boolean;
  payload?: { payload: { displayLabel: string }; value: number }[];
  label?: string;
  t: (key: I18nKey, vars?: Record<string, string | number>) => string;
  categoryFor: (value: number) => { key: string };
}) {
  if (!active || !payload || payload.length === 0) return null;
  const value = payload[0].value;
  const category = categoryFor(value);
  return (
    <div className="chart-tooltip">
      <div>{payload[0].payload.displayLabel}</div>
      <div>{t("chart.tooltip", { value: Math.round(value), category: t(`risk.category.${category.key}` as I18nKey) })}</div>
    </div>
  );
}

// Highest/lowest point in the series, annotated directly on the chart
// (item 7: "labels for highs/lows") rather than left for the user to eyeball.
function findExtremes<T extends { risk: number }>(data: T[]): { high: T | null; low: T | null } {
  if (data.length === 0) return { high: null, low: null };
  let high = data[0];
  let low = data[0];
  for (const d of data) {
    if (d.risk > high.risk) high = d;
    if (d.risk < low.risk) low = d;
  }
  return { high, low };
}

// Both products are nominally 0-100 scores, but real values rarely clear
// ~35 (Myggrisk's category bounds are 0/4/8/14/22 -- see
// riskModel.ts::RISK_CATEGORIES, confirmed against the live dataset in
// data/generated/diagnostics/national-diagnostics.json: p90 ~14, max ~34).
// A fixed 0-100 y-axis squashed every line into the bottom third of the
// chart, reading as "too low" even at "very high".
//
// The axis top is derived from the top category band's floor (doubled, for
// headroom into "very high"), NOT from this chart's own data -- deliberately,
// so the ceiling is the same for every cell/date on a given manifest instead
// of jumping around per location (a cell at 14 got a ~25 ceiling, a
// different cell at 30 would have gotten ~50, making "high" look
// inconsistently tall/short depending purely on which place you clicked, and
// making a borderline-high value look unimpressive on its own thin axis).
// `dataMax` only widens the ceiling further, as a safety net against actual
// values ever exceeding it (never as the primary driver).
function computeYMax(data: { risk: number }[], bands: { max: number }[]): number {
  const dataMax = Math.max(0, ...data.map((d) => d.risk));
  const topBandFloor = bands.length > 1 ? bands[bands.length - 2].max : 0;
  const target = Math.max(topBandFloor * 2, dataMax * 1.1);
  return Math.max(10, Math.ceil(target / 5) * 5);
}

export function SevenDayChart({
  daily,
  activityMultiplier,
  combination,
  isAbundanceLayer,
  abundanceThresholds,
}: {
  daily: DailyRecord[];
  activityMultiplier: number;
  combination?: CombinationParams;
  isAbundanceLayer?: boolean;
  abundanceThresholds?: number[];
}) {
  const { t, locale } = useI18n();
  const today = currentDateIso();
  // Myggläge (isAbundanceLayer) plots population_potential directly, matching
  // what the hero index/map show for that product -- the combined
  // finalRiskForActivity score used for Myggrisk lives on a much lower scale
  // (its own 0/4/8/14/22 category bounds vs. abundance's 0/28/38/48/58), so
  // using it here made the chart read as consistently, misleadingly lower
  // than the area's actual displayed value.
  const data = daily.map((d, idx) => ({
    idx,
    displayLabel: formatStockholmWeekday(d.date, locale),
    isToday: d.date === today,
    risk: isAbundanceLayer
      ? d.population_potential
      : finalRiskForActivity(d.population_potential, d.biting_activity, d.base_exposure_fraction, activityMultiplier, combination),
  }));
  const { high, low } = findExtremes(data);
  const todayPoint = data.find((d) => d.isToday);
  const bands = isAbundanceLayer ? abundanceBands(abundanceThresholds) : RISK_CATEGORIES;
  const categoryFor = isAbundanceLayer ? (v: number) => abundanceCategory(v, abundanceThresholds) : riskCategory;
  const yMax = computeYMax(data, bands);

  return (
    <div style={{ width: "100%", height: 190 }}>
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 6, right: 12, left: -6, bottom: 0 }}>
          <defs>
            <linearGradient id="riskFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#4fae6b" stopOpacity={0.5} />
              <stop offset="95%" stopColor="#4fae6b" stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <RiskBands bands={bands} />
          <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
          <XAxis dataKey="idx" tickFormatter={(idx: number) => data[idx]?.displayLabel ?? ""} tick={{ fontSize: 11 }} />
          <YAxis domain={[0, yMax]} tick={{ fontSize: 11 }} width={34} allowDecimals={false} />
          <Tooltip content={<ChartTooltip t={t} categoryFor={categoryFor} />} />
          {todayPoint && (
            <ReferenceLine x={todayPoint.idx} stroke="var(--color-text-muted)" strokeDasharray="3 3">
              <Label value={t("chart.now")} position="insideTopRight" style={{ fontSize: 10, fill: "var(--color-text-muted)" }} />
            </ReferenceLine>
          )}
          <Area type="monotone" dataKey="risk" stroke="#4fae6b" fill="url(#riskFill)" strokeWidth={2} />
          {high && (
            <ReferenceDot x={high.idx} y={high.risk} r={4} fill="#d9432e" stroke="none">
              <Label value={t("chart.high")} position="top" style={{ fontSize: 10, fill: "#d9432e" }} />
            </ReferenceDot>
          )}
          {low && low !== high && (
            <ReferenceDot x={low.idx} y={low.risk} r={4} fill="#2e8b4f" stroke="none">
              <Label value={t("chart.low")} position="bottom" style={{ fontSize: 10, fill: "#2e8b4f" }} />
            </ReferenceDot>
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function HourlyChart({
  hourly,
  activityMultiplier,
  combination,
  isAbundanceLayer,
  abundanceThresholds,
}: {
  hourly: LocationSeries["hourly"];
  activityMultiplier: number;
  combination?: CombinationParams;
  isAbundanceLayer?: boolean;
  abundanceThresholds?: number[];
}) {
  const { t, locale } = useI18n();
  const nowLabel = currentHourBucketLabel();
  // See SevenDayChart above for why isAbundanceLayer switches to plotting
  // population_potential directly instead of the combined risk score.
  const data = hourly.map((h, idx) => ({
    idx,
    displayLabel: formatStockholmHourShort(h.hourLabel, locale),
    isNow: h.hourLabel === nowLabel,
    risk: isAbundanceLayer
      ? h.population_potential
      : finalRiskForActivity(h.population_potential, h.biting_activity, h.base_exposure_fraction, activityMultiplier, combination),
  }));
  const { high, low } = findExtremes(data);
  const nowPoint = data.find((d) => d.isNow);
  const bands = isAbundanceLayer ? abundanceBands(abundanceThresholds) : RISK_CATEGORIES;
  const categoryFor = isAbundanceLayer ? (v: number) => abundanceCategory(v, abundanceThresholds) : riskCategory;
  const yMax = computeYMax(data, bands);

  return (
    <div style={{ width: "100%", height: 190 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 6, right: 12, left: -6, bottom: 0 }}>
          <RiskBands bands={bands} />
          <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
          <XAxis
            dataKey="idx"
            tickFormatter={(idx: number) => data[idx]?.displayLabel ?? ""}
            tick={{ fontSize: 10 }}
            interval={5}
          />
          <YAxis domain={[0, yMax]} tick={{ fontSize: 11 }} width={34} allowDecimals={false} />
          <Tooltip content={<ChartTooltip t={t} categoryFor={categoryFor} />} />
          {nowPoint && (
            <ReferenceLine x={nowPoint.idx} stroke="var(--color-text-muted)" strokeDasharray="3 3">
              <Label value={t("chart.now")} position="insideTopRight" style={{ fontSize: 10, fill: "var(--color-text-muted)" }} />
            </ReferenceLine>
          )}
          <Line type="monotone" dataKey="risk" stroke="#2b6fd6" strokeWidth={2} dot={false} />
          {high && (
            <ReferenceDot x={high.idx} y={high.risk} r={4} fill="#d9432e" stroke="none">
              <Label value={t("chart.high")} position="top" style={{ fontSize: 10, fill: "#d9432e" }} />
            </ReferenceDot>
          )}
          {low && low !== high && (
            <ReferenceDot x={low.idx} y={low.risk} r={4} fill="#2e8b4f" stroke="none">
              <Label value={t("chart.low")} position="bottom" style={{ fontSize: 10, fill: "#2e8b4f" }} />
            </ReferenceDot>
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
