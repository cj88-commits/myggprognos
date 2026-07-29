import { useEffect, useState } from "react";
import { getCells, getDaily, getHourly, getManifest, getPlaces, getSeriesShard } from "../lib/api";
import { shardForCellId } from "../lib/sharding";
import type { CellRecord, DailyRecord, HourlyRecord, Manifest, PlaceRecord } from "../types/forecast";

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

// Fetches a single small sharded series file (series/<shard>.json.gz,
// ~100-300KB for ~140 cells) instead of all 7 daily + 49 hourly full-grid
// files (56 requests, 50-150MB at full-Sweden scale) just to chart one
// cell -- see forecast/src/output.py::write_series_shards and
// frontend/src/lib/sharding.ts.
export function useLocationSeries(
  cellId: string | null,
  manifest: Manifest | null,
  refreshKey = 0
): AsyncState<LocationSeries> {
  return useAsync(async () => {
    if (!cellId || !manifest || !manifest.series_shard_count) return { daily: [], hourly: [] };

    const shard = shardForCellId(cellId, manifest.series_shard_count);
    const shardData = await getSeriesShard(shard);
    const entry = shardData[cellId];
    if (!entry) return { daily: [], hourly: [] };

    const hourly = entry.hourly.map((record, index) => ({
      ...record,
      hourLabel: manifest.hourly_files[index]?.replace("hourly/", "").replace(".json.gz", "") ?? "",
      hourOffset: index,
    }));

    return { daily: entry.daily, hourly };
  }, [cellId, manifest, refreshKey]);
}
