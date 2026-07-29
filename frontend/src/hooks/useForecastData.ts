import { useEffect, useState } from "react";
import { getCells, getDaily, getHourly, getManifest, getPlaces } from "../lib/api";
import { mapWithConcurrency } from "../lib/concurrency";
import type { CellRecord, DailyRecord, HourlyRecord, Manifest, PlaceRecord } from "../types/forecast";

const SERIES_FETCH_CONCURRENCY = 6;

interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, loading: true, error: null });

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn()
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null });
      })
      .catch((err: Error) => {
        if (!cancelled) setState({ data: null, loading: false, error: err.message });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}

export function useManifest(refreshKey = 0): AsyncState<Manifest> {
  return useAsync(() => getManifest(refreshKey > 0), [refreshKey]);
}

export function useCells(refreshKey = 0): AsyncState<CellRecord[]> {
  return useAsync(() => getCells(), [refreshKey]);
}

export function usePlaces(refreshKey = 0): AsyncState<PlaceRecord[]> {
  return useAsync(() => getPlaces(), [refreshKey]);
}

export function useDailyForDate(date: string | null, refreshKey = 0): AsyncState<DailyRecord[]> {
  return useAsync(() => (date ? getDaily(date) : Promise.resolve([])), [date, refreshKey]);
}

export function useHourlyForHour(hourLabel: string | null, refreshKey = 0): AsyncState<HourlyRecord[]> {
  return useAsync(() => (hourLabel ? getHourly(hourLabel) : Promise.resolve([])), [hourLabel, refreshKey]);
}

export interface LocationSeries {
  daily: DailyRecord[];
  hourly: (HourlyRecord & { hourLabel: string; hourOffset: number })[];
}

export function useLocationSeries(
  cellId: string | null,
  manifest: Manifest | null,
  refreshKey = 0
): AsyncState<LocationSeries> {
  return useAsync(async () => {
    if (!cellId || !manifest) return { daily: [], hourly: [] };

    const dailyResults = await mapWithConcurrency(manifest.daily_files, SERIES_FETCH_CONCURRENCY, (path) =>
      loadDailyByPath(path)
    );
    const daily = dailyResults
      .map((records) => records.find((r) => r.cell_id === cellId))
      .filter((r): r is DailyRecord => Boolean(r));

    const hourlyResults = await mapWithConcurrency(
      manifest.hourly_files,
      SERIES_FETCH_CONCURRENCY,
      async (path, index) => {
        const hourLabel = path.replace("hourly/", "").replace(".json.gz", "");
        const records = await loadHourlyByPath(path);
        const record = records.find((r) => r.cell_id === cellId);
        return record ? { ...record, hourLabel, hourOffset: index } : null;
      }
    );
    const hourly = hourlyResults.filter((r): r is HourlyRecord & { hourLabel: string; hourOffset: number } => Boolean(r));

    return { daily, hourly };
  }, [cellId, manifest, refreshKey]);
}

async function loadDailyByPath(path: string): Promise<DailyRecord[]> {
  const dateStr = path.replace("daily/", "").replace(".json.gz", "");
  return getDaily(dateStr);
}

async function loadHourlyByPath(path: string): Promise<HourlyRecord[]> {
  const hourLabel = path.replace("hourly/", "").replace(".json.gz", "");
  return getHourly(hourLabel);
}
