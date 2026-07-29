export interface Manifest {
  generated_at: string;
  model_version: string;
  forecast_start: string;
  forecast_end: string;
  hourly_until: string;
  cell_count: number;
  data_quality: "normal" | "degraded" | string;
  daily_files: string[];
  hourly_files: string[];
  activities: Record<string, number>;
  warnings: string[];
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
}

export type HourlyRecord = ScoreFields;

export interface PlaceRecord {
  name: string;
  municipality: string;
  latitude: number;
  longitude: number;
}

export type LayerKey = "risk" | "population_potential" | "biting_activity" | "confidence";

export const LAYER_LABELS: Record<LayerKey, string> = {
  risk: "Overall risk",
  population_potential: "Population potential",
  biting_activity: "Biting activity",
  confidence: "Confidence",
};

export const ACTIVITY_LABELS: Record<string, string> = {
  general: "General",
  running: "Running",
  hiking: "Hiking",
  camping: "Camping",
  fishing: "Fishing",
  gardening: "Gardening",
  outdoor_dining: "Outdoor dining",
};
