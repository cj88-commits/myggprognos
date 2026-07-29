import type { ReportInput } from "./types";

// Mirrors the Swedish bounding box used by the forecast grid
// (forecast/src/config.py SWEDEN_BBOX), with a small margin.
const SWEDEN_BBOX = { minLat: 54.5, maxLat: 69.6, minLon: 10.0, maxLon: 24.7 };

export const TERRAIN_OPTIONS = ["Urban", "Open countryside", "Forest", "Wetland", "Waterside"];
export const ACTIVITY_OPTIONS = ["Stationary", "Walking", "Running", "Camping", "Fishing", "Gardening"];

const CELL_ID_PATTERN = /^[A-Z0-9_]{3,32}$/;
const EMAIL_PATTERN = /[^\s@]+@[^\s@]+\.[^\s@]+/;
const PHONE_PATTERN = /\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b/;
const MAX_COMMENT_LENGTH = 280;

export interface ValidationResult {
  ok: boolean;
  errors: string[];
  value?: ReportInput;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

// We don't bundle the full ~thousands-of-cells grid into the Worker (it
// would bloat the deployed script for little benefit), so cell_id is
// validated by format + the submitted coordinates are validated against
// Sweden's bounding box, rather than exact grid membership. This still
// prevents arbitrary/malformed cell_id values and out-of-country
// coordinates from being trusted and stored -- see README "Security
// limitations" for the full-validation upgrade path.
export function validateReportInput(body: unknown): ValidationResult {
  const errors: string[] = [];
  if (typeof body !== "object" || body === null) {
    return { ok: false, errors: ["Request body must be a JSON object"] };
  }
  const b = body as Record<string, unknown>;

  if (typeof b.cell_id !== "string" || !CELL_ID_PATTERN.test(b.cell_id)) {
    errors.push("cell_id must be a short alphanumeric identifier");
  }

  if (!isFiniteNumber(b.latitude_rounded) || b.latitude_rounded < SWEDEN_BBOX.minLat || b.latitude_rounded > SWEDEN_BBOX.maxLat) {
    errors.push("latitude_rounded is missing or out of range for Sweden");
  }
  if (!isFiniteNumber(b.longitude_rounded) || b.longitude_rounded < SWEDEN_BBOX.minLon || b.longitude_rounded > SWEDEN_BBOX.maxLon) {
    errors.push("longitude_rounded is missing or out of range for Sweden");
  }

  if (!Number.isInteger(b.severity) || (b.severity as number) < 0 || (b.severity as number) > 4) {
    errors.push("severity must be an integer between 0 and 4");
  }

  if (b.terrain !== undefined && (typeof b.terrain !== "string" || !TERRAIN_OPTIONS.includes(b.terrain))) {
    errors.push("terrain must be one of the predefined options");
  }
  if (b.activity !== undefined && (typeof b.activity !== "string" || !ACTIVITY_OPTIONS.includes(b.activity))) {
    errors.push("activity must be one of the predefined options");
  }
  if (b.repellent_used !== undefined && typeof b.repellent_used !== "boolean") {
    errors.push("repellent_used must be a boolean");
  }

  if (b.comment !== undefined) {
    if (typeof b.comment !== "string" || b.comment.length > MAX_COMMENT_LENGTH) {
      errors.push(`comment must be a string of at most ${MAX_COMMENT_LENGTH} characters`);
    } else if (EMAIL_PATTERN.test(b.comment) || PHONE_PATTERN.test(b.comment)) {
      errors.push("comment appears to contain personal contact information and was rejected");
    }
  }

  if (b.forecast_score !== undefined && (!isFiniteNumber(b.forecast_score) || b.forecast_score < 0 || b.forecast_score > 10)) {
    errors.push("forecast_score must be a number between 0 and 10");
  }
  if (b.model_version !== undefined && (typeof b.model_version !== "string" || b.model_version.length > 32)) {
    errors.push("model_version must be a short string");
  }

  if (errors.length > 0) {
    return { ok: false, errors };
  }

  return {
    ok: true,
    errors: [],
    value: {
      cell_id: b.cell_id as string,
      latitude_rounded: b.latitude_rounded as number,
      longitude_rounded: b.longitude_rounded as number,
      severity: b.severity as number,
      terrain: b.terrain as string | undefined,
      activity: b.activity as string | undefined,
      repellent_used: b.repellent_used as boolean | undefined,
      comment: b.comment as string | undefined,
      forecast_score: b.forecast_score as number | undefined,
      model_version: b.model_version as string | undefined,
    },
  };
}

export function validateBbox(bbox: string | null): { minLat: number; minLon: number; maxLat: number; maxLon: number } | null {
  if (!bbox) return null;
  const parts = bbox.split(",").map(Number);
  if (parts.length !== 4 || parts.some((p) => !Number.isFinite(p))) return null;
  const [minLon, minLat, maxLon, maxLat] = parts;
  if (minLat > maxLat || minLon > maxLon) return null;
  return { minLat, minLon, maxLat, maxLon };
}
