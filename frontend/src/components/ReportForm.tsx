import { useState } from "react";
import { ACTIVITY_OPTIONS, SEVERITY_LABELS, TERRAIN_OPTIONS, submitReport } from "../lib/reportsApi";

export interface ReportFormProps {
  cellId: string;
  latitude: number;
  longitude: number;
  forecastScore: number;
  modelVersion: string;
  onClose: () => void;
  onSubmitted: () => void;
}

const EMAIL_PATTERN = /[^\s@]+@[^\s@]+\.[^\s@]+/;
const PHONE_PATTERN = /\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b/;

function roundCoordinate(value: number): number {
  // ~1.1km precision at Swedish latitudes -- coarse enough to protect
  // individual privacy while remaining useful for cell-level aggregation.
  return Math.round(value * 100) / 100;
}

export function ReportForm({ cellId, latitude, longitude, forecastScore, modelVersion, onClose, onSubmitted }: ReportFormProps) {
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
      setError("Please choose how bad mosquitoes are here right now.");
      return;
    }
    if (commentHasPossiblePersonalData) {
      setError("Please remove anything that looks like an email address or phone number from the comment.");
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
          How bad are mosquitoes here right now?
        </h2>

        <div className="field-group">
          <span className="field-label">Severity</span>
          <div className="option-grid">
            {SEVERITY_LABELS.map((label, index) => (
              <button
                key={label}
                type="button"
                className="option-chip"
                aria-pressed={severity === index}
                onClick={() => setSeverity(index)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="field-group">
          <span className="field-label">Terrain (optional)</span>
          <div className="option-grid">
            {TERRAIN_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                className="option-chip"
                aria-pressed={terrain === option}
                onClick={() => setTerrain(terrain === option ? null : option)}
              >
                {option}
              </button>
            ))}
          </div>
        </div>

        <div className="field-group">
          <span className="field-label">Activity (optional)</span>
          <div className="option-grid">
            {ACTIVITY_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                className="option-chip"
                aria-pressed={activity === option}
                onClick={() => setActivity(activity === option ? null : option)}
              >
                {option}
              </button>
            ))}
          </div>
        </div>

        <div className="field-group">
          <span className="field-label">Repellent used? (optional)</span>
          <div className="option-grid">
            {["Yes", "No"].map((label) => {
              const value = label === "Yes";
              return (
                <button
                  key={label}
                  type="button"
                  className="option-chip"
                  aria-pressed={repellent === value}
                  onClick={() => setRepellent(repellent === value ? null : value)}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="field-group">
          <label htmlFor="report-comment" className="field-label">
            Comment (optional, max 280 characters)
          </label>
          <textarea
            id="report-comment"
            className="comment-field"
            maxLength={280}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="No names, emails or phone numbers, please."
          />
        </div>

        <p style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
          We store only an approximate (rounded) location and forecast cell, never your name, email or exact GPS
          position.
        </p>

        {error && (
          <p role="alert" style={{ color: "var(--color-danger)", fontSize: "0.85rem" }}>
            {error}
          </p>
        )}

        <div className="button-row">
          <button type="button" className="button primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? "Submitting…" : "Submit report"}
          </button>
          <button type="button" className="button" onClick={onClose} disabled={submitting}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
