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
  return clamp(adjusted, 0, 1.5) * 10;
}

export function finalRiskForActivity(
  populationPotential: number,
  bitingActivity: number,
  baseExposureFraction: number,
  activityMultiplier: number
): number {
  const exposure0to10 = clamp(exposureForActivity(baseExposureFraction, activityMultiplier), 0, 10);
  const combinedFraction =
    (populationPotential / 10) * (bitingActivity / 10) * clamp(exposure0to10 / 10, 0, 1);
  return clamp(combinedFraction * 10 * 2.6, 0, 10);
}

export type RiskCategoryKey = "very_low" | "low" | "moderate" | "high" | "very_high";

export const RISK_CATEGORIES: { min: number; max: number; key: RiskCategoryKey; label: string; color: string }[] = [
  { min: 0.0, max: 1.9, key: "very_low", label: "Very low", color: "#2f6f4f" },
  { min: 2.0, max: 3.9, key: "low", label: "Low", color: "#6a9e3f" },
  { min: 4.0, max: 5.9, key: "moderate", label: "Moderate", color: "#d9a441" },
  { min: 6.0, max: 7.9, key: "high", label: "High", color: "#d9682f" },
  { min: 8.0, max: 10.0, key: "very_high", label: "Very high", color: "#a5262c" },
];

export function riskCategory(score: number) {
  return (
    RISK_CATEGORIES.find((c) => score >= c.min && score <= c.max) ?? RISK_CATEGORIES[RISK_CATEGORIES.length - 1]
  );
}

export type ConfidenceLabel = "Low" | "Medium" | "High";

export function confidenceLabel(confidence: number): ConfidenceLabel {
  if (confidence < 0.4) return "Low";
  if (confidence < 0.7) return "Medium";
  return "High";
}

export function formatScore(score: number): string {
  return score.toFixed(1);
}
