import { fetchJsonGz } from "./fetchJsonGz";
import type { CellRecord, DailyRecord, HourlyRecord, Manifest, PlaceRecord } from "../types/forecast";

// Base URL forecast data is fetched from. Defaults to the relative,
// bundled-into-the-build path (see .github/workflows/deploy-pages.yml and
// netlify.toml) so any deploy target that hasn't set VITE_FORECAST_DATA_BASE
// yet keeps working exactly as before -- relative (not root-absolute) so it
// resolves correctly whether the app is served from a domain root or a
// GitHub Pages project subpath.
//
// Set VITE_FORECAST_DATA_BASE (frontend/.env, or the environment a build is
// run in) to an absolute URL to instead fetch live from the Cloudflare R2
// forecast-data bucket, decoupling forecast updates from frontend deploys
// entirely -- see README "Forecast data hosting". Trailing slash stripped
// so both "https://data.example.com" and "https://data.example.com/" work.
const DATA_BASE = ((import.meta.env.VITE_FORECAST_DATA_BASE as string | undefined) || "data/latest").replace(
  /\/$/,
  ""
);

let manifestPromise: Promise<Manifest> | null = null;

const MANIFEST_MAX_RETRIES = 2;
const MANIFEST_RETRY_DELAY_MS = 400;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchManifestOnce(): Promise<Manifest> {
  const response = await fetch(`${DATA_BASE}/manifest.json`, { cache: "no-cache" });
  if (!response.ok) {
    throw new Error(`Failed to load forecast manifest (status ${response.status})`);
  }
  return (await response.json()) as Manifest;
}

export async function getManifest(forceReload = false): Promise<Manifest> {
  if (forceReload) manifestPromise = null;
  if (!manifestPromise) {
    manifestPromise = (async () => {
      let lastError: unknown;
      for (let attempt = 0; attempt <= MANIFEST_MAX_RETRIES; attempt++) {
        try {
          return await fetchManifestOnce();
        } catch (err) {
          lastError = err;
          if (attempt < MANIFEST_MAX_RETRIES) await delay(MANIFEST_RETRY_DELAY_MS * (attempt + 1));
        }
      }
      throw lastError;
    })().catch((err) => {
      // Don't let a persistent failure permanently poison the module-level
      // cache -- a later call (e.g. a manual retry) should try again.
      manifestPromise = null;
      throw err;
    });
  }
  return manifestPromise;
}

export async function getCells(): Promise<CellRecord[]> {
  return fetchJsonGz<CellRecord[]>(`${DATA_BASE}/cells.json.gz`);
}

export async function getDaily(dateStr: string): Promise<DailyRecord[]> {
  return fetchJsonGz<DailyRecord[]>(`${DATA_BASE}/daily/${dateStr}.json.gz`);
}

export async function getHourly(hourLabel: string): Promise<HourlyRecord[]> {
  return fetchJsonGz<HourlyRecord[]>(`${DATA_BASE}/hourly/${hourLabel}.json.gz`);
}

export async function getPlaces(): Promise<PlaceRecord[]> {
  try {
    return await fetchJsonGz<PlaceRecord[]>(`${DATA_BASE}/locations/index.json.gz`);
  } catch {
    return [];
  }
}

export interface SeriesShardEntry {
  daily: DailyRecord[];
  hourly: HourlyRecord[];
}

export async function getSeriesShard(shard: number): Promise<Record<string, SeriesShardEntry>> {
  return fetchJsonGz<Record<string, SeriesShardEntry>>(`${DATA_BASE}/series/${shard}.json.gz`);
}

export function nearestCell(cells: CellRecord[], lat: number, lon: number): CellRecord | null {
  if (cells.length === 0) return null;
  let best = cells[0];
  let bestDist = Infinity;
  for (const cell of cells) {
    const dLat = cell.latitude - lat;
    const dLon = (cell.longitude - lon) * Math.cos((lat * Math.PI) / 180);
    const dist = dLat * dLat + dLon * dLon;
    if (dist < bestDist) {
      bestDist = dist;
      best = cell;
    }
  }
  return best;
}

const EARTH_RADIUS_KM = 6371;

function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(a));
}

export interface NearestPlaceResult {
  place: PlaceRecord;
  distanceKm: number;
}

// Used as a friendlier fallback label than raw coordinates when a user taps
// the map without going through search (item 8: users should always
// understand what area/place they've selected). Only ~300 named places
// cover all of Sweden, so a straight linear scan per click is cheap and a
// spatial index would be overkill.
export function nearestPlace(places: PlaceRecord[], lat: number, lon: number): NearestPlaceResult | null {
  if (places.length === 0) return null;
  let best = places[0];
  let bestDist = haversineKm(lat, lon, best.latitude, best.longitude);
  for (const place of places) {
    const dist = haversineKm(lat, lon, place.latitude, place.longitude);
    if (dist < bestDist) {
      bestDist = dist;
      best = place;
    }
  }
  return { place: best, distanceKm: bestDist };
}
