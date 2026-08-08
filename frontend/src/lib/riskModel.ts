// Mirrors the combination step in forecast/src/model.py::compute_score so
// the frontend can re-derive risk for a different activity profile from
// already-downloaded data, without re-fetching or re-running the full
// model. The underlying population_potential / biting_activity /
// base_exposure_fraction values still come from the generated forecast
// assets (server-computed); only the activity multiplier + final
// combination is reproduced client-side.
//
// The five combination constants below are NOT hardcoded here -- they're
// read from manifest.combination (see forecast/src/output.py), which
// publishes exactly what compute_score() used for that run. This is
// deliberate: an earlier version of this file *did* hardcode its own copy
// of the formula/constants, which is exactly the backend/frontend drift
// risk documented in docs/model-audit-before.md #8. Callers must pass the
// manifest's `combination` object through; DEFAULT_COMBINATION_PARAMS
// exists only as a last-resort fallback for a manifest that predates this
// field.
import type { CombinationParams } from "../types/forecast";

export const DEFAULT_COMBINATION_PARAMS: CombinationParams = {
  activity_floor: 0.3,
  activity_weight: 0.7,
  exposure_floor: 0.75,
  exposure_weight: 0.5,
  scale: 105,
};

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
  activityMultiplier: number,
  combination: CombinationParams = DEFAULT_COMBINATION_PARAMS
): number {
  const populationFraction = clamp(populationPotential / 100, 0, 1);
  const activityFraction = clamp(bitingActivity / 100, 0, 1);
  const exposureFraction = clamp(baseExposureFraction, 0, 1);

  const activityModifier = combination.activity_floor + combination.activity_weight * activityFraction;
  const exposureModifier =
    (combination.exposure_floor + combination.exposure_weight * exposureFraction) * activityMultiplier;

  const riskFraction = populationFraction * activityModifier * exposureModifier;
  return clamp(riskFraction * combination.scale, 0, 100);
}

// Risk is a 0-100 score (mirrors forecast/src/config.py::RISK_CATEGORIES).
// `key` is an internal, locale-independent identifier -- components resolve
// the *displayed* label via `t(`risk.category.${key}`)` (see i18n/sv.ts),
// never `label` directly, which exists only as an English fallback/debug id.
//
// Bounds recalibrated alongside the v0.3.0 geographic-model redesign (see
// docs/calibration-validation-final.md "Myggrisk thresholds") -- final_risk's
// typical scale roughly halved under the new architecture, and this frontend
// mirror had drifted from config.py's new 0/4/8/14/22 bounds until this fix
// (the live site was briefly showing risk categories against the old
// 0/20/40/60/80 bounds after the backend was recalibrated).
export type RiskCategoryKey = "very_low" | "low" | "moderate" | "high" | "very_high";

export const RISK_CATEGORIES: { min: number; max: number; key: RiskCategoryKey; label: string; color: string }[] = [
  { min: 0, max: 3, key: "very_low", label: "Very low", color: "#2e8b4f" },
  { min: 4, max: 7, key: "low", label: "Low", color: "#9ecb3c" },
  { min: 8, max: 13, key: "moderate", label: "Moderate", color: "#f2c94c" },
  { min: 14, max: 21, key: "high", label: "High", color: "#f2994a" },
  { min: 22, max: 100, key: "very_high", label: "Very high", color: "#d9432e" },
];

export function riskCategory(score: number) {
  // Pick the highest-min band the score clears, rather than requiring
  // `min <= x <= max` -- with adjacent integer bounds (e.g. ...19 / 20...)
  // any fractional score landing in the gap (e.g. 19.13) would otherwise
  // match no band and fall back to the *last* (very_high) entry, regardless
  // of the actual score. Mirrors forecast/src/model.py::risk_category.
  let result = RISK_CATEGORIES[0];
  for (const c of RISK_CATEGORIES) {
    if (score >= c.min) result = c;
  }
  return result;
}

// Smooth (non-banded) 0-100 -> color interpolation used by the map and any
// continuous-scale UI, matching the required green -> yellow-green ->
// yellow -> orange -> red progression. Legend swatches use the discrete
// RISK_CATEGORIES colors above; the map uses this continuous ramp. Stops sit
// exactly at the RISK_CATEGORIES boundaries so two cells in the same band
// (e.g. 9 and 13, both "moderate") still render visibly different shades
// (MapLibre linearly interpolates between stops on the GPU) while a cell
// right at a boundary shows the category's own defining color.
export const RISK_COLOR_STOPS: { value: number; color: string }[] = [
  { value: 0, color: "#2e8b4f" },
  { value: 4, color: "#9ecb3c" },
  { value: 8, color: "#f2c94c" },
  { value: 14, color: "#f2994a" },
  { value: 22, color: "#d9432e" },
  { value: 100, color: "#a5262c" },
];

// Myggläge (population_potential/"abundance") is a genuinely different
// distribution from risk -- a weighted SUM of bounded terms, not the same
// multiplicative combination, and empirically tops out far short of 100
// (checked against the real full-Sweden dataset: max ~74). Reusing
// RISK_CATEGORIES' 0/20/40/60/80 bounds left "very_high" permanently
// empty -- see docs/model-audit-after.md and model.yaml `thresholds:`.
// The 4 edges are read from manifest.thresholds.abundance (backend-
// published, same drift-avoidance pattern as DEFAULT_COMBINATION_PARAMS
// above); this default is only a last-resort fallback for a manifest that
// predates the field.
export const DEFAULT_ABUNDANCE_THRESHOLDS = [28, 38, 48, 58];

const CATEGORY_COLORS: Record<RiskCategoryKey, string> = {
  very_low: "#2e8b4f",
  low: "#9ecb3c",
  moderate: "#f2c94c",
  high: "#f2994a",
  very_high: "#d94322",
};

export function abundanceCategory(
  score: number,
  edges: number[] = DEFAULT_ABUNDANCE_THRESHOLDS
): { key: RiskCategoryKey; color: string } {
  const keys: RiskCategoryKey[] = ["very_low", "low", "moderate", "high", "very_high"];
  const mins = [0, ...edges];
  let resultIndex = 0;
  for (let i = 0; i < mins.length; i++) {
    if (score >= mins[i]) resultIndex = i;
  }
  const key = keys[resultIndex];
  return { key, color: CATEGORY_COLORS[key] };
}

// Continuous 0-100 -> color ramp for the map, matching abundanceCategory's
// bands (same green -> red progression as RISK_COLOR_STOPS, different
// value breakpoints) so the map's shading and the legend/panel's category
// words agree with each other.
export function abundanceColorStops(
  edges: number[] = DEFAULT_ABUNDANCE_THRESHOLDS
): { value: number; color: string }[] {
  return [
    { value: 0, color: "#2e8b4f" },
    { value: edges[0], color: "#9ecb3c" },
    { value: edges[1], color: "#f2c94c" },
    { value: edges[2], color: "#f2994a" },
    { value: edges[3], color: "#d9432e" },
    { value: 100, color: "#a5262c" },
  ];
}

// "Data quality" / "forecast basis" -- the user-facing reframing of the raw
// 0-100 confidence score (still computed server-side from forecast horizon,
// weather completeness, static-data quality and model-component agreement;
// see forecast/src/confidence.py). Deliberately NOT shown as a percentage:
// that invites reading it as "probability the forecast is correct", which
// it isn't -- it's a statement about how much *evidence* backs the number,
// not about the number's odds of being right. Four qualitative bands
// (rather than the raw score) keep it firmly in "how much to trust this"
// territory instead of false precision.
export type DataQualityCategoryKey = "very_good" | "good" | "limited" | "low";

export const DATA_QUALITY_CATEGORIES: { min: number; key: DataQualityCategoryKey; color: string }[] = [
  { min: 0, key: "low", color: "#d9432e" },
  { min: 40, key: "limited", color: "#e8964a" },
  { min: 65, key: "good", color: "#9ecb3c" },
  { min: 85, key: "very_good", color: "#2e8b4f" },
];

export function dataQualityCategory(confidence: number): DataQualityCategoryKey {
  let result = DATA_QUALITY_CATEGORIES[0];
  for (const c of DATA_QUALITY_CATEGORIES) {
    if (confidence >= c.min) result = c;
  }
  return result.key;
}

export function formatScore(score: number): string {
  return Math.round(score).toString();
}

// Ordinal rank of the five shared category keys, low to high -- used to
// compare a Myggrisk category against a Myggläge category (they're on
// different underlying 0-100 scales, so only the category *tier* is
// comparable, never the raw scores against each other).
const CATEGORY_ORDER: RiskCategoryKey[] = ["very_low", "low", "moderate", "high", "very_high"];

export function categoryRank(key: RiskCategoryKey): number {
  return CATEGORY_ORDER.indexOf(key);
}

// Where a score sits within its own category band, 0 (band floor) to 1
// (band ceiling) -- lets UI badges/dots shade a touch lighter or darker
// within a category (item 11: "41 and 59 are both moderate but shouldn't
// look identical") without altering the category or its defining color.
// Purely presentational: never changes which category a score belongs to.
export function categoryIntensity(score: number, band: { min: number; max: number }): number {
  if (band.max <= band.min) return 1;
  return clamp((score - band.min) / (band.max - band.min), 0, 1);
}
