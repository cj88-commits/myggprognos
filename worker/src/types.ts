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
}
