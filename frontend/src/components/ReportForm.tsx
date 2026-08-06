import { useState } from "react";
import { useI18n } from "../i18n";
import type { I18nKey } from "../i18n/types";
import { ACTIVITY_OPTIONS, SEVERITY_LABELS, TERRAIN_OPTIONS, submitReport } from "../lib/reportsApi";

export interface ReportFormProps {
  cellId: string;
  latitude: number;
  longitude: number;
  forecastScore: number;
  modelVersion: string;
  // Forecast context (docs/wind-calm-investigation.md item 10) -- whatever
  // the currently-displayed forecast record has available; all optional
  // since older/offline data won't have them.
  forecastWindMs?: number;
  effectiveWindMs?: number;
  temperatureC?: number;
  humidityPct?: number;
  populationPotential?: number;
  bitingActivity?: number;
  targetTimestamp?: string;
  onClose: () => void;
  onSubmitted: () => void;
}

const EMAIL_PATTERN = /[^\s@]+@[^\s@]+\.[^\s@]+/;
const PHONE_PATTERN = /\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b/;

// Wire values (sent to the Worker API, validated server-side against the
// exact same English strings -- see worker/src/validation.ts) stay in
// English; only the *displayed* label is translated, via these key maps.
const SEVERITY_KEYS = ["none", "few", "noticeable", "many", "unbearable"] as const;
const TERRAIN_KEY_BY_VALUE: Record<string, string> = {
  Urban: "urban",
  "Open countryside": "countryside",
  Forest: "forest",
  Wetland: "wetland",
  Waterside: "waterside",
};
const ACTIVITY_KEY_BY_VALUE: Record<string, string> = {
  Stationary: "stationary",
  Walking: "walking",
  Running: "running",
  Camping: "camping",
  Fishing: "fishing",
  Gardening: "gardening",
};

function roundCoordinate(value: number): number {
  // ~1.1km precision at Swedish latitudes -- coarse enough to protect
  // individual privacy while remaining useful for cell-level aggregation.
  return Math.round(value * 100) / 100;
}

export function ReportForm({
  cellId,
  latitude,
  longitude,
  forecastScore,
  modelVersion,
  forecastWindMs,
  effectiveWindMs,
  temperatureC,
  humidityPct,
  populationPotential,
  bitingActivity,
  targetTimestamp,
  onClose,
  onSubmitted,
}: ReportFormProps) {
  const { t } = useI18n();
  const [severity, setSeverity] = useState<number | null>(null);
  const [terrain, setTerrain] = useState<string | null>(null);
  const [activity, setActivity] = useState<string | null>(null);
  const [repellent, setRepellent] = useState<boolean | null>(null);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const commentHasPossiblePersonalData = EMAIL_PATTERN.test(comment) || PHONE_PATTERN.test(comment);

  async function handleSubmit() {
    if (severity === null) {
      setError(t("report.errorSeverityRequired"));
      return;
    }
    if (commentHasPossiblePersonalData) {
      setError(t("report.errorPersonalData"));
      return;
    }
    setSubmitting(true);
    setError(null);
    const result = await submitReport({
      cell_id: cellId,
      latitude_rounded: roundCoordinate(latitude),
      longitude_rounded: roundCoordinate(longitude),
      severity,
      terrain: terrain ?? undefined,
      activity: activity ?? undefined,
      repellent_used: repellent ?? undefined,
      comment: comment.trim() ? comment.trim().slice(0, 280) : undefined,
      forecast_score: forecastScore,
      model_version: modelVersion,
      forecast_wind_ms: forecastWindMs,
      effective_wind_ms: effectiveWindMs,
      temperature_c: temperatureC,
      humidity_pct: humidityPct,
      population_potential: populationPotential,
      biting_activity: bitingActivity,
      target_timestamp: targetTimestamp,
    });
    setSubmitting(false);
    if (result.ok) {
      onSubmitted();
    } else {
      setError(result.error);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="report-title">
        <h2 id="report-title" style={{ marginTop: 0 }}>
          {t("report.title")}
        </h2>

        <div className="field-group">
          <span className="field-label">{t("report.severity")}</span>
          <div className="option-grid">
            {SEVERITY_LABELS.map((label, index) => (
              <button
                key={label}
                type="button"
                className="option-chip"
                aria-pressed={severity === index}
                onClick={() => setSeverity(index)}
              >
                {t(`report.severity.${SEVERITY_KEYS[index]}` as I18nKey)}
              </button>
            ))}
          </div>
        </div>

        <div className="field-group">
          <span className="field-label">{t("report.terrain")}</span>
          <div className="option-grid">
            {TERRAIN_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                className="option-chip"
                aria-pressed={terrain === option}
                onClick={() => setTerrain(terrain === option ? null : option)}
              >
                {t(`report.terrain.${TERRAIN_KEY_BY_VALUE[option]}` as I18nKey)}
              </button>
            ))}
          </div>
        </div>

        <div className="field-group">
          <span className="field-label">{t("report.activity")}</span>
          <div className="option-grid">
            {ACTIVITY_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                className="option-chip"
                aria-pressed={activity === option}
                onClick={() => setActivity(activity === option ? null : option)}
              >
                {t(`report.activity.${ACTIVITY_KEY_BY_VALUE[option]}` as I18nKey)}
              </button>
            ))}
          </div>
        </div>

        <div className="field-group">
          <span className="field-label">{t("report.repellent")}</span>
          <div className="option-grid">
            {[
              { label: t("report.yes"), value: true },
              { label: t("report.no"), value: false },
            ].map(({ label, value }) => (
              <button
                key={label}
                type="button"
                className="option-chip"
                aria-pressed={repellent === value}
                onClick={() => setRepellent(repellent === value ? null : value)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="field-group">
          <label htmlFor="report-comment" className="field-label">
            {t("report.comment")}
          </label>
          <textarea
            id="report-comment"
            className="comment-field"
            maxLength={280}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder={t("report.commentPlaceholder")}
          />
        </div>

        <p style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>{t("report.privacyNote")}</p>

        {error && (
          <p role="alert" style={{ color: "var(--color-danger)", fontSize: "0.85rem" }}>
            {error}
          </p>
        )}

        <div className="button-row">
          <button type="button" className="button primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? t("report.submitting") : t("report.submit")}
          </button>
          <button type="button" className="button" onClick={onClose} disabled={submitting}>
            {t("report.cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}
