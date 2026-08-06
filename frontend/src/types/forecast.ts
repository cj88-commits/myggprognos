export interface Manifest {
  generated_at: string;
  model_version: string;
  // Exact source commit this run's code came from (docs/wind-calm-
  // investigation.md item 11); "unknown" if it couldn't be resolved.
  // Optional -- older manifests predate this field.
  build_sha?: string;
  forecast_start: string;
  forecast_end: string;
  hourly_until: string;
  cell_count: number;
  data_quality: "normal" | "degraded" | string;
  daily_files: string[];
  hourly_files: string[];
  activities: Record<string, number>;
  warnings: string[];
  series_files: string[];
  series_shard_count: number;
  // The exact modifier-combination constants forecast/src/model.py used for
  // this run (see model.yaml `combination:`) -- read by riskModel.ts
  // instead of holding an independent hardcoded copy, so backend and
  // frontend can never silently drift apart on how risk is combined.
  combination?: CombinationParams;
  // Category-band boundaries per product (see model.yaml `thresholds:`) --
  // read instead of holding an independently-drifting hardcoded copy.
  thresholds?: { abundance?: number[] };
}

export interface CombinationParams {
  activity_floor: number;
  activity_weight: number;
  exposure_floor: number;
  exposure_weight: number;
  scale: number;
}

export interface CellRecord {
  cell_id: string;
  latitude: number;
  longitude: number;
  region: string;
  forest_fraction?: number;
  wetland_fraction?: number;
  urban_fraction?: number;
  distance_to_water_km?: number;
  elevation_m?: number;
  coastal_exposure?: number;
}

export interface ScoreFields {
  cell_id: string;
  risk: number;
  population_potential: number;
  biting_activity: number;
  exposure: number;
  base_exposure_fraction: number;
  confidence: number;
  // Newer, clearer-named aliases published alongside the original fields
  // above (kept for backward compatibility -- see docs/model-audit-after.md
  // "backward compatibility"). Optional because older cached/offline
  // manifests won't have them.
  mosquito_abundance?: number;
  activity_modifier?: number;
  exposure_modifier?: number;
  // Forecast context (docs/wind-calm-investigation.md item 10) -- used to
  // attach exactly what the model knew to a user report at submission
  // time. Optional because older cached/offline manifests won't have them.
  forecast_wind_ms?: number;
  effective_wind_ms?: number;
  temperature_c?: number;
  humidity_pct?: number;
}

export interface ExplanationFactor {
  key: string;
  label: string;
  contribution: number;
}

export interface Explanation {
  positive_factors: ExplanationFactor[];
  negative_factors: ExplanationFactor[];
  summary: string;
}

export type Daypart = "morning" | "afternoon" | "evening" | "night";

export interface DailyRecord extends ScoreFields {
  date: string;
  peak_period: Daypart;
  dayparts: Record<Daypart, ScoreFields>;
  explanation: Explanation;
  // Flat, spec-literal factor strings, e.g. "Hög temperatur (+18)" -- see
  // forecast/src/explanation.py::format_factor_strings. Additive to (not a
  // replacement for) the structured `explanation` object above.
  explanation_text: string[];
  // "HH:00" in Europe/Stockholm, the representative local time for
  // peak_period (see pipeline.py DAYPART_REPRESENTATIVE_HOUR) -- an
  // approximate peak, honestly reflecting the model's daypart-level (not
  // hourly) resolution for the 7-day horizon. Optional for older manifests.
  daily_peak_local_time?: string;
}

export type HourlyRecord = ScoreFields;

export interface PlaceRecord {
  name: string;
  municipality: string;
  latitude: number;
  longitude: number;
}

// Three named public products (see docs/model-audit-after.md and the
// "forecast products" iteration): "daily_peak_risk" (Myggrisk idag, the
// default -- today's highest expected nuisance regardless of the moment
// you happen to load the page) and "current_risk" (Myggrisk just nu, the
// old page-load-hour-driven behaviour, now explicit and opt-in) are both
// risk-like 0-100 scores on the same scale/categories, differing only in
// which time window they summarise. "population_potential" (Myggläge) is
// a distinct product: how favourable conditions are for mosquitoes to be
// present at all, independent of the current hour's weather. The
// remaining two ("biting_activity", "confidence") are secondary/advanced
// layers, not part of the three named products.
export type LayerKey = "daily_peak_risk" | "current_risk" | "population_potential" | "biting_activity" | "confidence";

// Locale-independent keys only -- components resolve the *displayed* label
// via `t(`layer.${key}`)` / `t(`activity.${key}`)` (see frontend/src/i18n).
export const LAYER_KEYS: LayerKey[] = [
  "daily_peak_risk",
  "current_risk",
  "population_potential",
  "biting_activity",
  "confidence",
];

// Users do not care about the model -- they care whether they're likely to
// get bitten (see the "simplify around the user's mental model" iteration).
// Exactly two products are exposed as a primary, always-visible choice:
// "Myggrisk" (daily_peak_risk -- "am I likely to get bitten here") and
// "Myggläge" (population_potential -- "how favourable is this area in
// general", for trip/campsite planning). "current_risk" (the old separate
// "just nu" product), "biting_activity" and "confidence" are no longer
// independently selectable in the UI at all -- LocationPanel always renders
// the daily_peak_risk-style hero for any non-population_potential layer
// value (including a legacy bookmarked link carrying one of the old three),
// and biting_activity/confidence remain visible only as read-only figures
// inside "Tekniska detaljer". LAYER_KEYS above is kept as the full backend-
// compatible type/list; this is deliberately a separate, smaller constant
// for what the primary switch itself offers.
export const SIMPLE_PRODUCT_KEYS: LayerKey[] = ["daily_peak_risk", "population_potential"];

export const ACTIVITY_KEYS: string[] = [
  "general",
  "running",
  "hiking",
  "camping",
  "fishing",
  "gardening",
  "outdoor_dining",
];
