import type { LayerKey } from "../types/forecast";

export interface AppState {
  lat: number;
  lon: number;
  date: string; // YYYY-MM-DD
  hour: number | null; // 0-48 offset from forecast start, or null when using a daypart
  daypart: string | null; // morning|afternoon|evening|night, used for days 3-7
  activity: string;
  layer: LayerKey;
}

export const DEFAULT_STATE: AppState = {
  lat: 59.3293,
  lon: 18.0686,
  date: "",
  hour: null,
  daypart: "afternoon",
  activity: "general",
  layer: "risk",
};

const VALID_LAYERS: LayerKey[] = ["risk", "population_potential", "biting_activity", "confidence"];

export function parseUrlState(search: string): Partial<AppState> {
  const params = new URLSearchParams(search);
  const result: Partial<AppState> = {};

  const lat = parseFloat(params.get("lat") ?? "");
  const lon = parseFloat(params.get("lon") ?? "");
  if (Number.isFinite(lat) && lat >= -90 && lat <= 90) result.lat = lat;
  if (Number.isFinite(lon) && lon >= -180 && lon <= 180) result.lon = lon;

  const date = params.get("date");
  if (date && /^\d{4}-\d{2}-\d{2}$/.test(date)) result.date = date;

  const hourParam = params.get("hour");
  if (hourParam !== null) {
    const hour = parseInt(hourParam, 10);
    if (Number.isFinite(hour) && hour >= 0 && hour <= 48) result.hour = hour;
  }

  const daypart = params.get("daypart");
  if (daypart && ["morning", "afternoon", "evening", "night"].includes(daypart)) {
    result.daypart = daypart;
  }

  const activity = params.get("activity");
  if (activity) result.activity = activity;

  const layer = params.get("layer") as LayerKey | null;
  if (layer && VALID_LAYERS.includes(layer)) result.layer = layer;

  return result;
}

export function serializeUrlState(state: AppState): string {
  const params = new URLSearchParams();
  params.set("lat", state.lat.toFixed(4));
  params.set("lon", state.lon.toFixed(4));
  if (state.date) params.set("date", state.date);
  if (state.hour !== null) {
    params.set("hour", String(state.hour));
  } else if (state.daypart) {
    params.set("daypart", state.daypart);
  }
  params.set("activity", state.activity);
  params.set("layer", state.layer);
  return `?${params.toString()}`;
}
