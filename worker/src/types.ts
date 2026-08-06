export interface Env {
  DB: D1Database;
  ALLOWED_ORIGINS: string;
  REPORT_HASH_SALT: string;
}

export interface ReportInput {
  cell_id: string;
  latitude_rounded: number;
  longitude_rounded: number;
  severity: number;
  terrain?: string;
  activity?: string;
  repellent_used?: boolean;
  comment?: string;
  forecast_score?: number;
  model_version?: string;
  // Forecast context at submission time (docs/wind-calm-investigation.md
  // item 10) -- lets a future analysis join reports back to exactly what
  // the model knew, without needing generated forecast archives that may
  // no longer be retained. All optional: older clients never send them.
  forecast_wind_ms?: number;
  effective_wind_ms?: number;
  temperature_c?: number;
  humidity_pct?: number;
  population_potential?: number;
  biting_activity?: number;
  target_timestamp?: string;
}

export interface ReportRow {
  id: string;
  created_at: string;
  cell_id: string;
  latitude_rounded: number;
  longitude_rounded: number;
  severity: number;
  terrain: string | null;
  activity: string | null;
  repellent_used: number | null;
  comment: string | null;
  forecast_score: number | null;
  model_version: string | null;
  forecast_wind_ms: number | null;
  effective_wind_ms: number | null;
  temperature_c: number | null;
  humidity_pct: number | null;
  population_potential: number | null;
  biting_activity: number | null;
  target_timestamp: string | null;
}
