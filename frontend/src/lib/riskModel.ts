// Mirrors the combination step in forecast/src/model.py so the frontend can
// re-derive risk for a different activity profile from already-downloaded
// data, without re-fetching or re-running the full model. The underlying
// population_potential / biting_activity / base_exposure_fraction values
// still come from the generated forecast assets (server-computed); only the
// activity multiplier + final combination is reproduced client-side.
//
// Keep this in sync with compute_exposure()/compute_score() in model.py.

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function exposureForActivity(baseExposureFraction: number, activityMultiplier: number): number {
  const adjusted = clamp(baseExposureFraction * activityMultiplier, 0, 1.5);
  return clamp(adjusted, 0, 1.5) * 100;
}

export function finalRiskForActivity(
  populationPotential: number,
  bitingActivity: number,
  baseExposureFraction: number,
  activityMultiplier: number
): number {
  const exposure0to100 = clamp(exposureForActivity(baseExposureFraction, activityMultiplier), 0, 100);
  const combinedFraction =
    (populationPotential / 100) * (bitingActivity / 100) * clamp(exposure0to100 / 100, 0, 1);
  return clamp(combinedFraction * 100 * 2.6, 0, 100);
}

// Risk is a 0-100 score (mirrors forecast/src/config.py::RISK_CATEGORIES).
// `key` is an internal, locale-independent identifier -- components resolve
// the *displayed* label via `t(`risk.category.${key}`)` (see i18n/sv.ts),
// never `label` directly, which exists only as an English fallback/debug id.
export type RiskCategoryKey = "very_low" | "low" | "moderate" | "high" | "very_high";

export const RISK_CATEGORIES: { min: number; max: number; key: RiskCategoryKey; label: string; color: string }[] = [
  { min: 0, max: 19, key: "very_low", label: "Very low", color: "#2e8b4f" },
  { min: 20, max: 39, key: "low", label: "Low", color: "#9ecb3c" },
  { min: 40, max: 59, key: "moderate", label: "Moderate", color: "#f2c94c" },
  { min: 60, max: 79, key: "high", label: "High", color: "#f2994a" },
  { min: 80, max: 100, key: "very_high", label: "Very high", color: "#d9432e" },
];

export function riskCategory(score: number) {
  return (
    RISK_CATEGORIES.find((c) => score >= c.min && score <= c.max) ?? RISK_CATEGORIES[RISK_CATEGORIES.length - 1]
  );
}

// Smooth (non-banded) 0-100 -> color interpolation used by the map and any
// continuous-scale UI, matching the required green -> yellow-green ->
// yellow -> orange -> red progression. Legend swatches use the discrete
// RISK_CATEGORIES colors above; the map uses this continuous ramp.
export const RISK_COLOR_STOPS: { value: number; color: string }[] = [
  { value: 0, color: "#2e8b4f" },
  { value: 20, color: "#9ecb3c" },
  { value: 40, color: "#f2c94c" },
  { value: 60, color: "#f2994a" },
  { value: 80, color: "#d9432e" },
  { value: 100, color: "#a5262c" },
];

export type ConfidenceCategoryKey = "low" | "medium" | "high";

export function confidenceCategory(confidence: number): ConfidenceCategoryKey {
  if (confidence < 40) return "low";
  if (confidence < 70) return "medium";
  return "high";
}

export function formatScore(score: number): string {
  return Math.round(score).toString();
}
