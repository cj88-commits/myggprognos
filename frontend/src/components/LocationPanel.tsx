import { lazy, Suspense, useEffect, useState } from "react";
import type { DailyRecord, LayerKey, Manifest, ScoreFields } from "../types/forecast";
import { confidenceCategory, exposureForActivity, finalRiskForActivity, formatScore, riskCategory } from "../lib/riskModel";
import { computeAdjustedRisk } from "../lib/reportAdjustment";
import { getReportSummary, isReportingConfigured, type ReportSummary } from "../lib/reportsApi";
import type { LocationSeries } from "../hooks/useForecastData";
import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import { ReportForm } from "./ReportForm";

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
  activeLabel: string;
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
  activeLabel,
  series,
  loading,
  error,
  onShare,
  shareCopied,
}: LocationPanelProps) {
  const { t } = useI18n();
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
    activityMultiplier
  );

  // The hero score/badge/color must track whichever metric the map is
  // actually colored by (`layer`) -- previously this always showed overall
  // risk even when the map (and its legend) had been switched to e.g.
  // "Bettaktivitet" (biting activity), so toggling the layer changed the
  // map but silently left the panel's number, badge, and explanation
  // talking about a different metric entirely.
  const isRiskLayer = layer === "risk";
  const displayValue = isRiskLayer
    ? adjustedFinalRisk
    : layer === "confidence"
      ? activeRecord.confidence
      : activeRecord[layer];
  // population_potential/biting_activity are bounded 0-100 "how favourable/
  // active is it" scores just like risk, so the same five-band scale/colors
  // apply; confidence has its own three-band scale.
  const confCategory = confidenceCategory(activeRecord.confidence);
  const confLabel = t(`confidence.${confCategory}` as I18nKey);
  const riskLikeCategory = riskCategory(displayValue);
  const riskLikeLabel = t(`risk.category.${riskLikeCategory.key}` as I18nKey);
  const categoryLabel = layer === "confidence" ? confLabel : riskLikeLabel;
  const heroColor = layer === "confidence" ? "var(--color-text)" : riskLikeCategory.color;
  const layerLabel = t(`layer.${layer}` as I18nKey);

  const reportAdjustment = computeAdjustedRisk(adjustedFinalRisk, reportSummary);

  return (
    <div className="panel-content">
      <div>
        <div style={{ fontWeight: 700 }}>{placeName}</div>
        <div style={{ fontSize: "0.78rem", color: "var(--color-text-muted)" }}>
          {latitude.toFixed(4)}, {longitude.toFixed(4)} &middot; {activeLabel}
        </div>
      </div>

      <div className="score-hero">
        <div className="score-value" style={{ color: heroColor }}>
          {formatScore(displayValue)}
        </div>
        <div>
          <span className="risk-badge" style={{ color: heroColor }}>
            <span className="dot" aria-hidden="true" />
            {isRiskLayer
              ? t("panel.riskLabel", { category: categoryLabel })
              : t("panel.metricLabel", { metric: layerLabel, category: categoryLabel })}
          </span>
          {isRiskLayer && (
            <div style={{ fontSize: "0.78rem", color: "var(--color-text-muted)", marginTop: "0.3rem" }}>
              {t("panel.activityAdjusted", { activity: t(`activity.${activity}` as I18nKey) })}
            </div>
          )}
        </div>
      </div>

      {!isRiskLayer && (
        <p style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
          {t("panel.viewingLayer", { layer: layerLabel })}
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
        <div className="section-title">{t("panel.confidenceTitle")}</div>
        <div className="confidence-row">
          <div className="confidence-bar">
            <div style={{ width: `${Math.round(activeRecord.confidence)}%` }} />
          </div>
          <span>
            {confLabel} ({Math.round(activeRecord.confidence)}%)
          </span>
        </div>
      </div>

      {activeDailyRecord && isRiskLayer && (
        <div>
          <div className="section-title">{t("panel.whyTitle")}</div>
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
          <p style={{ fontSize: "0.78rem", color: "var(--color-text-muted)", marginTop: "0.4rem" }}>
            {t("panel.peakPeriod", { period: t(`daypart.${activeDailyRecord.peak_period}` as I18nKey) })}
          </p>
        </div>
      )}

      {series && series.daily.length > 0 && (
        <div>
          <div className="section-title">{t("panel.next7days")}</div>
          <Suspense fallback={<ChartSkeleton />}>
            <SevenDayChart daily={series.daily} activityMultiplier={activityMultiplier} />
          </Suspense>
        </div>
      )}

      {series && series.hourly.length > 0 && (
        <div>
          <div className="section-title">{t("panel.next48h")}</div>
          <Suspense fallback={<ChartSkeleton />}>
            <HourlyChart hourly={series.hourly} activityMultiplier={activityMultiplier} />
          </Suspense>
        </div>
      )}

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
