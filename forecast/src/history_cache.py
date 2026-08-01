"""Persistent rolling-window cache of OBSERVED (past) weather per cell.

Forecast data (today through +N days) must always be refetched fresh --
it changes as Open-Meteo's models update. But a given PAST hour's observed
weather never changes once it's in the past. Refetching a full 21-day
history from scratch on every routine run was the dominant driver of both
pipeline runtime and Open-Meteo rate-limiting (each run repeated ~95% of
the same data it had already fetched 6 hours earlier).

This module persists the rolling 21-day history across runs
(data/generated/weather_history_cache.json.gz, committed like
data/generated/latest -- NOT inside data/generated/latest itself, so it
never gets bundled into the public frontend build). Each run:

  1. Loads the cache (empty dict if missing -- e.g. the very first run).
  2. Fetches only the gap since the cache was last updated (a small
     `past_days`) if the cache is fresh, or the FULL history window if the
     cache is missing/stale enough to be untrustworthy -- the same code
     path naturally handles both the initial backfill and routine
     updates, and self-heals if the cache is ever lost or falls behind.
  3. Merges the freshly fetched data into the cache, dropping anything
     older than the rolling window.
  4. Saves the updated (history-only, forecast excluded) cache back for
     next time.
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather import HourlyWeather

CACHE_SERIES_FIELDS = [
    "temperature_2m", "relative_humidity_2m", "precipitation",
    "wind_speed_10m", "wind_gusts_10m", "cloud_cover", "soil_moisture",
]

# If the cache is fresher than this, a small incremental fetch (covering
# the gap plus a safety margin) is enough. Anything staler -- including a
# missing cache -- triggers a full history re-fetch instead of risking a
# silent gap in the 21-day window the model actually depends on.
CACHE_FRESH_THRESHOLD_HOURS = 48
INCREMENTAL_PAST_DAYS = 2


def cache_age_hours(path: Path) -> float | None:
    if not path.exists():
        return None
    return (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600.0


def past_days_to_fetch(cache_path: Path, full_history_days: int) -> int:
    """How many days of history this run needs to fetch fresh. A warm,
    recently-updated cache only needs a small gap-filling fetch; a
    missing or stale cache falls back to the full window."""
    age = cache_age_hours(cache_path)
    if age is not None and age <= CACHE_FRESH_THRESHOLD_HOURS:
        return INCREMENTAL_PAST_DAYS
    return full_history_days


def load_history_cache(path: Path) -> dict[str, HourlyWeather]:
    if not path.exists():
        return {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError, gzip.BadGzipFile):
        return {}

    result: dict[str, HourlyWeather] = {}
    for cell_id, entry in raw.items():
        try:
            result[cell_id] = HourlyWeather(
                cell_id=cell_id,
                latitude=entry["latitude"],
                longitude=entry["longitude"],
                times=entry["times"],
                temperature_2m=entry["temperature_2m"],
                relative_humidity_2m=entry["relative_humidity_2m"],
                precipitation=entry["precipitation"],
                wind_speed_10m=entry["wind_speed_10m"],
                wind_gusts_10m=entry["wind_gusts_10m"],
                cloud_cover=entry["cloud_cover"],
                soil_moisture=entry["soil_moisture"],
                used_fallback=entry.get("used_fallback", False),
            )
        except KeyError:
            continue  # malformed entry -- skip it, that cell just re-backfills
    return result


def save_history_cache(path: Path, history_by_cell: dict[str, HourlyWeather]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = {}
    for cell_id, weather in history_by_cell.items():
        raw[cell_id] = {
            "latitude": weather.latitude,
            "longitude": weather.longitude,
            "times": weather.times,
            "temperature_2m": weather.temperature_2m,
            "relative_humidity_2m": weather.relative_humidity_2m,
            "precipitation": weather.precipitation,
            "wind_speed_10m": weather.wind_speed_10m,
            "wind_gusts_10m": weather.wind_gusts_10m,
            "cloud_cover": weather.cloud_cover,
            "soil_moisture": weather.soil_moisture,
            "used_fallback": weather.used_fallback,
        }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp_path, "wt", encoding="utf-8") as fh:
        json.dump(raw, fh)
    tmp_path.replace(path)


def _parse_time(t: str) -> datetime:
    return datetime.fromisoformat(t).replace(tzinfo=timezone.utc)


def merge_cached_and_fresh(
    cached: HourlyWeather | None, fresh: HourlyWeather, now: datetime
) -> HourlyWeather:
    """Combine previously-cached history with a freshly fetched
    (gap-filling history + forecast) series into one continuous,
    de-duplicated, sorted series -- preferring fresh values on any
    overlapping timestamp (more authoritative, since it's the newer
    fetch of the same real-world hour)."""
    if cached is None or not cached.times:
        return fresh

    fresh_index = {t: i for i, t in enumerate(fresh.times)}
    cached_index = {t: i for i, t in enumerate(cached.times)}
    all_times = sorted(set(cached.times) | set(fresh.times))

    merged: dict[str, list] = {f: [] for f in CACHE_SERIES_FIELDS}
    for t in all_times:
        f_idx = fresh_index.get(t)
        c_idx = cached_index.get(t)
        source, idx = (fresh, f_idx) if f_idx is not None else (cached, c_idx)
        for field in CACHE_SERIES_FIELDS:
            merged[field].append(getattr(source, field)[idx])

    return HourlyWeather(
        cell_id=fresh.cell_id,
        latitude=fresh.latitude,
        longitude=fresh.longitude,
        times=all_times,
        temperature_2m=merged["temperature_2m"],
        relative_humidity_2m=merged["relative_humidity_2m"],
        precipitation=merged["precipitation"],
        wind_speed_10m=merged["wind_speed_10m"],
        wind_gusts_10m=merged["wind_gusts_10m"],
        cloud_cover=merged["cloud_cover"],
        soil_moisture=merged["soil_moisture"],
        used_fallback=fresh.used_fallback or cached.used_fallback,
    )


def split_history_for_cache(weather: HourlyWeather, now: datetime, keep_days: int) -> HourlyWeather:
    """Extract just the past (<=now), rolling-window portion of a merged
    series to persist -- the forecast (future) portion is deliberately
    excluded, since it must always be refetched fresh next run, and
    anything older than `keep_days` is dropped so the cache doesn't grow
    unbounded."""
    cutoff = now - timedelta(days=keep_days)
    kept_indices = [
        i for i, t in enumerate(weather.times)
        if cutoff <= _parse_time(t) <= now
    ]
    return HourlyWeather(
        cell_id=weather.cell_id,
        latitude=weather.latitude,
        longitude=weather.longitude,
        times=[weather.times[i] for i in kept_indices],
        temperature_2m=[weather.temperature_2m[i] for i in kept_indices],
        relative_humidity_2m=[weather.relative_humidity_2m[i] for i in kept_indices],
        precipitation=[weather.precipitation[i] for i in kept_indices],
        wind_speed_10m=[weather.wind_speed_10m[i] for i in kept_indices],
        wind_gusts_10m=[weather.wind_gusts_10m[i] for i in kept_indices],
        cloud_cover=[weather.cloud_cover[i] for i in kept_indices],
        soil_moisture=[weather.soil_moisture[i] for i in kept_indices],
        used_fallback=weather.used_fallback,
    )
