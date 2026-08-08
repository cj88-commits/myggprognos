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
  // "Myggrisk idag" (today's peak, not whichever hour happens to be
  // selected) is now the default map product -- see App.tsx `usesPeakData`.
  layer: "daily_peak_risk",
};

// Exactly two products are reachable via the URL now (item 2 of the UX
// clarity pass: only Myggrisk/Myggläge are public views -- Myggaktivitet,
// Prognosunderlag and the old separate "just nu" product are technical-
// details-only figures, never their own selectable layer/legend/map ramp).
const VALID_LAYERS: LayerKey[] = ["daily_peak_risk", "population_potential"];

// A bookmarked/shared URL from before this or an earlier iteration may still
// carry one of the now-retired layer keys ("risk" pre-dates even
// current_risk/daily_peak_risk; current_risk/biting_activity/confidence were
// briefly their own selectable layers) -- redirect all of them to the
// closest current public equivalent (daily_peak_risk) rather than silently
// dropping the whole `layer` param, which previously left biting_activity/
// confidence reachable via URL with a mismatched map color ramp even though
// no UI control could produce that state.
const LEGACY_LAYER_ALIASES: Record<string, LayerKey> = {
  risk: "daily_peak_risk",
  current_risk: "daily_peak_risk",
  biting_activity: "daily_peak_risk",
  confidence: "daily_peak_risk",
};

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

  const rawLayer = params.get("layer");
  const layer = (rawLayer && LEGACY_LAYER_ALIASES[rawLayer]) || (rawLayer as LayerKey | null);
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
