import { fetchJsonGz } from "./fetchJsonGz";
import type { CellRecord, DailyRecord, HourlyRecord, Manifest, PlaceRecord } from "../types/forecast";

// Generated forecast assets are published alongside the built frontend
// under this relative path (see .github/workflows/deploy-pages.yml and
// scripts/run_forecast.py). Relative (not root-absolute) so it resolves
// correctly whether the app is served from a domain root or a GitHub
// Pages project subpath.
const DATA_BASE = "data/latest";

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
