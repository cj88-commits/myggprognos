import { lazy, Suspense, useEffect, useState } from "react";
import type { DailyRecord, LayerKey, Manifest, ScoreFields } from "../types/forecast";
import {
  abundanceCategory,
  dataQualityCategory,
  DATA_QUALITY_CATEGORIES,
  exposureForActivity,
  finalRiskForActivity,
  formatScore,
  riskCategory,
} from "../lib/riskModel";
import { computeAdjustedRisk } from "../lib/reportAdjustment";
import { getReportSummary, isReportingConfigured, type ReportSummary } from "../lib/reportsApi";
import type { LocationSeries } from "../hooks/useForecastData";
import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import { currentDateIso, formatStockholmDateLabel, hourBucketToDate } from "../lib/time";
import { ReportForm } from "./ReportForm";
import { HourTimeline } from "./HourTimeline";
import { ForecastCards } from "./ForecastCards";

// recharts is a sizeable dependency (see vite.config.ts manualChunks) --
// deferring its import until a chart is actually about to render (rather
// than eagerly at LocationPanel module load) keeps it out of the initial
// bundle/network path entirely for users who never open a location.
const SevenDayChart = lazy(() => import("./RiskCharts").then((m) => ({ default: m.SevenDayChart })));
const HourlyChart = lazy(() => import("./RiskCharts").then((m) => ({ default: m.HourlyChart })));

function ChartSkeleton() {
  return <div className="skeleton skeleton-chart" aria-hidden="true" />;
}

export interface LocationPanelProps {
  placeName: string;
  latitude: number;
  longitude: number;
  cellId: string | null;
  manifest: Manifest | null;
  activity: string;
  layer: LayerKey;
  activeRecord: ScoreFields | null;
  activeDailyRecord: DailyRecord | null;
  isHourlyDay: boolean;
  hourLabel: string | null;
  dayIndex: number;
  daypart: string;
  date: string;
  series: LocationSeries | null;
  loading: boolean;
  error: string | null;
  onShare: () => void;
  shareCopied: boolean;
}

function SubscoreCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="subscore-card">
      <div className="label">{label}</div>
      <div className="value">{formatScore(value)}</div>
    </div>
  );
}

function DataQualityMeter({ activeIndex }: { activeIndex: number }) {
  return (
    <div className="quality-meter" aria-hidden="true">
      {DATA_QUALITY_CATEGORIES.map((c, i) => (
        <span key={c.key} className={`quality-seg${i <= activeIndex ? " filled" : ""}`} style={{ background: i <= activeIndex ? c.color : undefined }} />
      ))}
    </div>
  );
}

function PanelSkeleton() {
  return (
    <div className="panel-content" aria-hidden="true">
      <div className="skeleton skeleton-line skeleton-title" />
      <div className="skeleton skeleton-line skeleton-subtitle" />
      <div className="skeleton skeleton-hero" />
      <div className="subscore-grid">
        <div className="skeleton skeleton-card" />
        <div className="skeleton skeleton-card" />
        <div className="skeleton skeleton-card" />
      </div>
      <div className="skeleton skeleton-block" />
    </div>
  );
}

export function LocationPanel({
  placeName,
  latitude,
  longitude,
  cellId,
  manifest,
  activity,
  layer,
  activeRecord,
  activeDailyRecord,
  isHourlyDay,
  hourLabel,
  date,
  series,
  loading,
  error,
  onShare,
  shareCopied,
}: LocationPanelProps) {
  const { t, locale } = useI18n();
  const [reportOpen, setReportOpen] = useState(false);
  const [reportSummary, setReportSummary] = useState<ReportSummary | null>(null);
  const [justSubmitted, setJustSubmitted] = useState(false);

  useEffect(() => {
    setReportSummary(null);
    if (!cellId || !isReportingConfigured()) return;
    let cancelled = false;
    getReportSummary(cellId).then((result) => {
      if (!cancelled && result.ok) setReportSummary(result.data);
    });
    return () => {
      cancelled = true;
    };
  }, [cellId, justSubmitted]);

  if (loading && !activeRecord) {
    return <PanelSkeleton />;
  }

  if (error) {
    return (
      <div className="panel-content">
        <p role="alert">{t("panel.loadError", { error })}</p>
      </div>
    );
  }

  if (!activeRecord) {
    return (
      <div className="panel-empty">
        <p>{t("panel.empty")}</p>
      </div>
    );
  }

  const activityMultiplier = manifest?.activities?.[activity] ?? 1.0;
  const adjustedFinalRisk = finalRiskForActivity(
    activeRecord.population_potential,
    activeRecord.biting_activity,
    activeRecord.base_exposure_fraction,
    activityMultiplier,
    manifest?.combination
  );

  // Exactly two products are exposed in the UI now: Myggrisk ("am I likely
  // to get bitten") and Myggläge ("how favourable is this area in
  // general") -- see types/forecast.ts::SIMPLE_PRODUCT_KEYS. Anything else
  // (a legacy bookmarked link carrying the old current_risk/biting_activity/
  // confidence layer values) falls back to the risk treatment rather than
  // breaking, since that's the more universally-meaningful default.
  const isAbundanceLayer = layer === "population_potential";
  const isRiskProduct = !isAbundanceLayer;

  const displayValue = isAbundanceLayer ? activeRecord.population_potential : adjustedFinalRisk;
  const dqCategory = dataQualityCategory(activeRecord.confidence);
  const dqLabel = t(`dataQuality.${dqCategory}` as I18nKey);
  const dqIndex = DATA_QUALITY_CATEGORIES.findIndex((c) => c.key === dqCategory);
  // Myggläge uses its own category bounds (see riskModel.ts::abundanceCategory)
  // -- reusing risk's 0/20/40/60/80 bounds left "very_high" permanently
  // empty for this product (docs/model-audit-after.md).
  const riskLikeCategory = isAbundanceLayer
    ? abundanceCategory(displayValue, manifest?.thresholds?.abundance)
    : riskCategory(displayValue);
  const riskLikeLabel = t(`risk.category.${riskLikeCategory.key}` as I18nKey);

  const reportAdjustment = computeAdjustedRisk(adjustedFinalRisk, reportSummary);

  // Day-level context only -- "Idag" / "Imorgon" / "Lördag 8 aug" -- never
  // an hour, since both remaining products always describe the whole day,
  // not a selected moment (see App.tsx).
  const timeContext = date === currentDateIso() ? t("controlBar.today") : formatStockholmDateLabel(date, locale);

  // "Högst risk idag: kl 20" -- honestly daypart-resolution (not a precise
  // minute), from the daily record's own daily_peak_local_time (already
  // Stockholm-local, see pipeline.py). Risk-product only: Myggläge
  // shouldn't imply it has an hourly peak the way a weather-driven nuisance
  // score does.
  const peakAroundNote =
    isRiskProduct && activeDailyRecord?.daily_peak_local_time
      ? t("panel.peakAroundTime", { time: activeDailyRecord.daily_peak_local_time.slice(0, 2) })
      : null;

  return (
    <div className="panel-content">
      <div>
        <div style={{ fontWeight: 700 }}>{placeName}</div>
        <div style={{ fontSize: "0.78rem", color: "var(--color-text-muted)" }}>
          {latitude.toFixed(4)}, {longitude.toFixed(4)} &middot; {timeContext}
        </div>
      </div>

      {/* Hero: the answer to "will mosquitoes bother me?" first, in plain
          language and large type -- the recommendation sentence is the
          hero, not the number (see the "simplify around the user's mental
          model" iteration). Technical figures live in "Tekniska detaljer"
          further down, never up here. */}
      <div className="hero-block">
        <div className="hero-headline" style={{ color: riskLikeCategory.color }}>
          {isAbundanceLayer
            ? t(`panel.abundanceHeadline.${riskLikeCategory.key}` as I18nKey)
            : t("panel.heroHeadlineRisk", { category: riskLikeLabel })}
        </div>

        <p className="hero-guidance">
          {t(`panel.${isAbundanceLayer ? "abundanceAdvice" : "advice"}.${riskLikeCategory.key}` as I18nKey)}
        </p>

        {isRiskProduct && peakAroundNote && <p className="hero-subnote">{peakAroundNote}</p>}
        {isAbundanceLayer && <p className="hero-subnote">{t("panel.abundanceExplain")}</p>}
      </div>

      {/* "When is it worst?" -- a compact dawn-to-night dot strip for the
          selected day, only meaningful while hourly data exists (today/
          tomorrow); days 2-6 only have daily-resolution data. */}
      {isRiskProduct && isHourlyDay && series && series.hourly.length > 0 && (
        <HourTimeline
          hourly={series.hourly}
          date={date}
          activityMultiplier={activityMultiplier}
          combination={manifest?.combination}
        />
      )}

      {/* "Tomorrow" / weekend planning -- plain today/tomorrow/day-after
          cards instead of making everyone read a line chart to plan ahead. */}
      {isRiskProduct && series && series.daily.length > 0 && (
        <ForecastCards daily={series.daily} activityMultiplier={activityMultiplier} combination={manifest?.combination} />
      )}

      {/* Everything below is progressive disclosure: collapsed by default,
          for the minority of visitors who want the methodology or the raw
          numbers rather than just the headline/recommendation above. */}

      {/* Myggläge deliberately has NO factor list here: the generated
          explanation mixes population, activity and exposure factors
          (including wind/rain suppression), which would misleadingly read
          as if current weather affects abundance -- see
          panel.abundanceExplain in the hero block instead. */}
      {((activeDailyRecord && isRiskProduct) || (series && (series.daily.length > 0 || series.hourly.length > 0))) && (
        <details className="disclosure">
          <summary>{t("panel.howItWorksTitle")}</summary>
          <div className="disclosure-content">
            {activeDailyRecord && isRiskProduct && (
              <div>
                <div className="section-title">{t("panel.whyTitleToday")}</div>
                <p style={{ margin: 0, fontSize: "0.9rem" }}>{activeDailyRecord.explanation.summary}</p>
                <ul className="factor-list">
                  {activeDailyRecord.explanation.positive_factors.map((f) => (
                    <li className="positive" key={f.key}>
                      <span className="sign">+</span> {f.label}
                    </li>
                  ))}
                  {activeDailyRecord.explanation.negative_factors.map((f) => (
                    <li className="negative" key={f.key}>
                      <span className="sign">-</span> {f.label}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {series && series.daily.length > 0 && (
              <div>
                <div className="section-title">{t("panel.next7days")}</div>
                <Suspense fallback={<ChartSkeleton />}>
                  <SevenDayChart daily={series.daily} activityMultiplier={activityMultiplier} combination={manifest?.combination} />
                </Suspense>
              </div>
            )}

            {series && series.hourly.length > 0 && (
              <div>
                <div className="section-title">{t("panel.next48h")}</div>
                <Suspense fallback={<ChartSkeleton />}>
                  <HourlyChart hourly={series.hourly} activityMultiplier={activityMultiplier} combination={manifest?.combination} />
                </Suspense>
              </div>
            )}
          </div>
        </details>
      )}

      <details className="disclosure">
        <summary>{t("panel.detailsTitle")}</summary>
        <div className="disclosure-content technical-section">
          <p className="model-disclaimer">{t("panel.modelDisclaimer")}</p>

          <p className="index-line">{t("panel.indexLabel", { value: formatScore(displayValue) })}</p>

          {isRiskProduct && (
            <p style={{ fontSize: "0.78rem", color: "var(--color-text-muted)" }}>
              {t("panel.activityAdjusted", { activity: t(`activity.${activity}` as I18nKey) })}
            </p>
          )}

          {reportAdjustment.applied && (
            <p style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
              {t("panel.modelEstimate", {
                model: formatScore(reportAdjustment.modelRisk),
                count: reportSummary?.report_count ?? 0,
                adjusted: formatScore(reportAdjustment.adjustedRisk),
                weight: Math.round(reportAdjustment.weight * 100),
              })}
            </p>
          )}

          <div className="subscore-grid">
            <SubscoreCard label={t("panel.population")} value={activeRecord.population_potential} />
            <SubscoreCard label={t("panel.activity")} value={activeRecord.biting_activity} />
            <SubscoreCard
              label={t("panel.exposure")}
              value={exposureForActivity(activeRecord.base_exposure_fraction, activityMultiplier)}
            />
          </div>

          <div>
            <div className="section-title">{t("panel.dataQualityTitle")}</div>
            <div className="quality-row">
              <DataQualityMeter activeIndex={dqIndex} />
              <span className="quality-label">{dqLabel}</span>
            </div>
            <p className="quality-explain">{t("panel.dataQualityExplain")}</p>
          </div>
        </div>
      </details>

      <div className="button-row">
        <button type="button" className="button primary" onClick={() => setReportOpen(true)}>
          {t("panel.reportButton")}
        </button>
        <button type="button" className="button" onClick={onShare}>
          {shareCopied ? t("panel.shareCopied") : t("panel.shareButton")}
        </button>
      </div>

      {!isReportingConfigured() && (
        <p style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>{t("panel.offlineDemo")}</p>
      )}

      {reportOpen && cellId && (
        <ReportForm
          cellId={cellId}
          latitude={latitude}
          longitude={longitude}
          forecastScore={adjustedFinalRisk}
          modelVersion={manifest?.model_version ?? "unknown"}
          forecastWindMs={activeRecord.forecast_wind_ms}
          effectiveWindMs={activeRecord.effective_wind_ms}
          temperatureC={activeRecord.temperature_c}
          humidityPct={activeRecord.humidity_pct}
          populationPotential={activeRecord.population_potential}
          bitingActivity={activeRecord.biting_activity}
          targetTimestamp={
            isHourlyDay && hourLabel ? hourBucketToDate(hourLabel).toISOString() : date ? `${date}T00:00:00Z` : undefined
          }
          onClose={() => setReportOpen(false)}
          onSubmitted={() => {
            setReportOpen(false);
            setJustSubmitted((v) => !v);
          }}
        />
      )}
    </div>
  );
}
