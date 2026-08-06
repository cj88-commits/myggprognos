import { lazy, Suspense, useEffect, useState } from "react";
import type { Daypart, DailyRecord, LayerKey, Manifest, ScoreFields } from "../types/forecast";
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
import { currentDateIso, currentHourBucketLabel, formatStockholmDateLabel, formatStockholmHourShort, hourBucketToDate } from "../lib/time";
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

// Mirrors forecast/src/config.py::DAYPARTS -- UTC hour boundaries used by
// the pipeline to bucket hourly scores into a daypart. Kept in sync here
// only for *display* purposes (deciding whether the currently-selected
// hour falls inside the day's peak daypart), never to recompute a score.
const DAYPART_ORDER: Daypart[] = ["morning", "afternoon", "evening", "night"];

function hourToDaypart(utcHour: number): Daypart {
  if (utcHour >= 6 && utcHour < 11) return "morning";
  if (utcHour >= 11 && utcHour < 17) return "afternoon";
  if (utcHour >= 17 && utcHour < 22) return "evening";
  return "night";
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
  dayIndex,
  daypart,
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

  // The hero score/badge/color must track whichever metric the map is
  // actually colored by (`layer`) -- previously this always showed overall
  // risk even when the map (and its legend) had been switched to e.g.
  // "Myggaktivitet", so toggling the layer changed the map but silently
  // left the panel's number, badge, and explanation talking about a
  // different metric entirely.
  //
  // "daily_peak_risk" and "current_risk" are both risk-like 0-100 scores
  // (same guidance text, same category bands) that differ only in WHICH
  // moment they summarise; "population_potential" (Myggläge) is a
  // genuinely different claim (how favourable conditions are, independent
  // of the current hour) and must never borrow risk-specific wording like
  // wind/activity suppression -- see the "forecast products" iteration.
  const isRiskProduct = layer === "daily_peak_risk" || layer === "current_risk";
  const isAbundanceLayer = layer === "population_potential";
  const isDataQualityLayer = layer === "confidence";
  const displayValue = isRiskProduct
    ? adjustedFinalRisk
    : isDataQualityLayer
      ? activeRecord.confidence
      : activeRecord[layer];
  // population_potential/biting_activity are bounded 0-100 "how favourable/
  // active is it" scores just like risk, so the same five-band scale/colors
  // apply; data quality (backed by the raw confidence score) has its own
  // four-band scale -- see riskModel.ts::dataQualityCategory. Never shown
  // as a percentage: it describes how much evidence backs the number, not
  // a probability the forecast is "correct".
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
  const categoryLabel = isDataQualityLayer ? dqLabel : riskLikeLabel;
  const heroColor = isDataQualityLayer ? DATA_QUALITY_CATEGORIES[dqIndex]?.color ?? "var(--color-text)" : riskLikeCategory.color;
  const layerLabel = t(`layer.${layer}` as I18nKey);

  const reportAdjustment = computeAdjustedRisk(adjustedFinalRisk, reportSummary);

  // --- Time context: "Idag kl 14" / "Imorgon kl 09" / "Torsdag 7 aug ·
  // Kväll" -- always Europe/Stockholm, never UTC (see lib/time.ts). ---
  const selectedUtcHour = hourLabel ? hourBucketToDate(hourLabel).getUTCHours() : null;
  const isNow = isHourlyDay && dayIndex === 0 && hourLabel === currentHourBucketLabel();
  const timeContext = isHourlyDay
    ? t(dayIndex === 0 ? "panel.timeToday" : "panel.timeTomorrow", {
        hour: hourLabel ? formatStockholmHourShort(hourLabel, locale) : "",
      })
    : t("panel.timeDaypart", {
        day: date === currentDateIso() ? t("controlBar.today") : formatStockholmDateLabel(date, locale),
        daypart: t(`daypart.${daypart}` as I18nKey),
      });

  // --- Item 3: the generated explanation always describes the day's PEAK
  // daypart (see forecast/src/pipeline.py), not necessarily whichever
  // hour/daypart the user has selected. Rather than silently attaching a
  // peak-time explanation to a different score, we detect the mismatch and
  // relabel the section honestly instead. This mismatch can only happen for
  // "current_risk" (a specific hour) -- "daily_peak_risk" always IS the
  // peak record by construction (see App.tsx usesPeakData), so there's
  // nothing to mismatch.
  const selectedDaypart: Daypart | null = isHourlyDay
    ? selectedUtcHour !== null
      ? hourToDaypart(selectedUtcHour)
      : null
    : (daypart as Daypart);
  const peakPeriod = activeDailyRecord?.peak_period ?? null;
  const explanationMatchesSelection =
    layer === "daily_peak_risk" || (peakPeriod !== null && selectedDaypart === peakPeriod);

  let whenChangesNote: string | null = null;
  if (layer === "current_risk" && peakPeriod && !explanationMatchesSelection && selectedDaypart) {
    const peakIdx = DAYPART_ORDER.indexOf(peakPeriod);
    const selectedIdx = DAYPART_ORDER.indexOf(selectedDaypart);
    whenChangesNote =
      peakIdx > selectedIdx
        ? t("panel.risingAfter", { period: t(`daypartOn.${peakPeriod}` as I18nKey) })
        : t("panel.peakPeriod", { period: t(`daypartOn.${peakPeriod}` as I18nKey) });
  } else if (layer === "current_risk" && peakPeriod) {
    whenChangesNote = t("panel.peakPeriod", { period: t(`daypartOn.${peakPeriod}` as I18nKey) });
  }

  // "Myggrisk idag" hero subnote: "Topp väntas omkring kl 20." -- honestly
  // daypart-resolution (not a precise minute), from the daily record's own
  // daily_peak_local_time (already Stockholm-local, see pipeline.py).
  const peakAroundNote =
    layer === "daily_peak_risk" && activeDailyRecord?.daily_peak_local_time
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

      {/* Hero: plain-language headline first, technical figures further down
          (item 2 -- answer "what does this mean for me" before model internals). */}
      <div className="hero-block">
        <div className="hero-headline" style={{ color: heroColor }}>
          {layer === "current_risk"
            ? isNow
              ? t("panel.heroHeadlineNow", { category: riskLikeLabel })
              : t("panel.heroHeadline", { category: riskLikeLabel })
            : layer === "daily_peak_risk"
              ? t("panel.heroHeadlineDailyPeak", { category: riskLikeLabel })
              : isAbundanceLayer
                ? t(`panel.abundanceHeadline.${riskLikeCategory.key}` as I18nKey)
                : t("panel.metricHeadline", { metric: layerLabel, category: categoryLabel })}
        </div>

        {isRiskProduct && (
          <>
            <p className="hero-guidance">{t(`panel.guidance.${riskLikeCategory.key}` as I18nKey)}</p>
            {layer === "daily_peak_risk" && peakAroundNote && <p className="hero-subnote">{peakAroundNote}</p>}
            {layer === "current_risk" && whenChangesNote && <p className="hero-subnote">{whenChangesNote}</p>}
          </>
        )}

        {isAbundanceLayer && <p className="hero-subnote">{t("panel.abundanceExplain")}</p>}

        {!isRiskProduct && !isAbundanceLayer && (
          <p className="hero-subnote">{t("panel.viewingLayer", { layer: layerLabel })}</p>
        )}
      </div>

      {/* "Vad bör jag göra?" -- one conservative, actionable line straight
          after the plain-language guidance above, before any chart or
          number. Deliberately risk-product only: Myggläge/aktivitet/
          prognosunderlag aren't nuisance predictions, so there's no
          "should I do X" advice to give for them (same gating as the
          guidance text itself). */}
      {isRiskProduct && (
        <div>
          <div className="section-title">{t("panel.adviceTitle")}</div>
          <p style={{ margin: 0, fontSize: "0.95rem" }}>{t(`panel.advice.${riskLikeCategory.key}` as I18nKey)}</p>
        </div>
      )}

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

      {/* Everything below is progressive disclosure (item 3): collapsed by
          default, for the minority of visitors who want the methodology or
          the raw numbers rather than just the headline/advice above. */}

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
                <div className="section-title">
                  {layer === "daily_peak_risk"
                    ? t("panel.whyTitleToday")
                    : explanationMatchesSelection
                      ? t("panel.whyTitle")
                      : t("panel.whyPeakTitle")}
                </div>
                {layer === "current_risk" && !explanationMatchesSelection && peakPeriod && (
                  <p className="explanation-scope-note">
                    {t("panel.explanationForPeak", { period: t(`daypartOn.${peakPeriod}` as I18nKey) })}
                  </p>
                )}
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

          {(isRiskProduct || isAbundanceLayer) && (
            <p className="index-line">{t("panel.indexLabel", { value: formatScore(displayValue) })}</p>
          )}

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
