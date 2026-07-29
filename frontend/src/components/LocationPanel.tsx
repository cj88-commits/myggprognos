import { useEffect, useState } from "react";
import type { DailyRecord, Manifest, ScoreFields } from "../types/forecast";
import { confidenceLabel, finalRiskForActivity, formatScore, riskCategory } from "../lib/riskModel";
import { computeAdjustedRisk } from "../lib/reportAdjustment";
import { getReportSummary, isReportingConfigured, type ReportSummary } from "../lib/reportsApi";
import type { LocationSeries } from "../hooks/useForecastData";
import { SevenDayChart, HourlyChart } from "./RiskCharts";
import { ReportForm } from "./ReportForm";

export interface LocationPanelProps {
  placeName: string;
  latitude: number;
  longitude: number;
  cellId: string | null;
  manifest: Manifest | null;
  activity: string;
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

export function LocationPanel({
  placeName,
  latitude,
  longitude,
  cellId,
  manifest,
  activity,
  activeRecord,
  activeDailyRecord,
  activeLabel,
  series,
  loading,
  error,
  onShare,
  shareCopied,
}: LocationPanelProps) {
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
    return (
      <div className="panel-content">
        <p>Loading forecast…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="panel-content">
        <p role="alert">Could not load forecast data: {error}</p>
      </div>
    );
  }

  if (!activeRecord) {
    return (
      <div className="panel-empty">
        <p>Select a location on the map, search for a place, or use your current location to see mosquito risk.</p>
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
  const category = riskCategory(adjustedFinalRisk);
  const confLabel = confidenceLabel(activeRecord.confidence);

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
        <div className="score-value" style={{ color: category.color }}>
          {formatScore(adjustedFinalRisk)}
        </div>
        <div>
          <span className="risk-badge" style={{ color: category.color }}>
            <span className="dot" aria-hidden="true" />
            {category.label} risk
          </span>
          <div style={{ fontSize: "0.78rem", color: "var(--color-text-muted)", marginTop: "0.3rem" }}>
            Activity-adjusted for <strong>{activity.replace("_", " ")}</strong>
          </div>
        </div>
      </div>

      {reportAdjustment.applied && (
        <p style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
          Model estimate: {formatScore(reportAdjustment.modelRisk)}. Adjusted using {reportSummary?.report_count}{" "}
          recent nearby reports: <strong>{formatScore(reportAdjustment.adjustedRisk)}</strong> (report weight{" "}
          {Math.round(reportAdjustment.weight * 100)}%).
        </p>
      )}

      <div className="subscore-grid">
        <SubscoreCard label="Population" value={activeRecord.population_potential} />
        <SubscoreCard label="Activity" value={activeRecord.biting_activity} />
        <SubscoreCard label="Exposure" value={activeRecord.exposure} />
      </div>

      <div>
        <div className="section-title">Confidence</div>
        <div className="confidence-row">
          <div className="confidence-bar">
            <div style={{ width: `${Math.round(activeRecord.confidence * 100)}%` }} />
          </div>
          <span>
            {confLabel} ({Math.round(activeRecord.confidence * 100)}%)
          </span>
        </div>
      </div>

      {activeDailyRecord && (
        <div>
          <div className="section-title">Why this forecast</div>
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
            Peak activity expected in the <strong>{activeDailyRecord.peak_period}</strong>.
          </p>
        </div>
      )}

      {series && series.daily.length > 0 && (
        <div>
          <div className="section-title">Next 7 days</div>
          <SevenDayChart daily={series.daily} activityMultiplier={activityMultiplier} />
        </div>
      )}

      {series && series.hourly.length > 0 && (
        <div>
          <div className="section-title">Next 48 hours</div>
          <HourlyChart hourly={series.hourly} activityMultiplier={activityMultiplier} />
        </div>
      )}

      <div className="button-row">
        <button type="button" className="button primary" onClick={() => setReportOpen(true)}>
          Report mosquitoes here
        </button>
        <button type="button" className="button" onClick={onShare}>
          {shareCopied ? "Link copied!" : "Share this view"}
        </button>
      </div>

      {!isReportingConfigured() && (
        <p style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
          Reporting is running in offline demo mode; submissions won&apos;t be saved until the Worker API is
          configured (see README).
        </p>
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
