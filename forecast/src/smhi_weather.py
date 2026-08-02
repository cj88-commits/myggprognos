"""SMHI Open Data based WeatherProvider (evaluated in parallel with
OpenMeteoProvider -- see weather.py -- not yet the default).

Structurally different from Open-Meteo's per-point-batch REST design: SMHI's
MultiPoint endpoint returns one value **per grid point in its entire
~1M-point domain** for a single (time, parameter) pair, in one request. So
instead of looping over batches of our own grid cells, this loops over the
(time, parameter) pairs we need and does one whole-domain fetch each,
picking out our cells' values via a precomputed nearest-neighbor index (see
scripts/prepare_smhi_grid_index.py). Total request count is therefore
independent of how many cells we have -- the structural fix for the
per-cell-batch rate limiting Open-Meteo hit at full-Sweden scale.

Two real, permanent limitations versus Open-Meteo, both confirmed live
against the API (see README):
  - No soil moisture parameter exists on either SMHI product. Left as None
    throughout, same as HourlyWeather already supports for missing fields.
  - The MESAN analysis API only exposes a rolling ~24h window (`times.json`
    never lists more than a day of history) -- there is no bulk historical
    backfill call. A `past_days` request is honored only up to whatever
    history SMHI actually has available; anything beyond that is simply not
    returned (callers merging into history_cache.py's rolling cache will
    self-heal over subsequent runs, same as a cold Open-Meteo cache would,
    just slower since each run only contributes ~1 day rather than 21).

SMHI's own forecast time steps coarsen with lead time (1h out to 48h, 2h to
72h, 6h to 132h, 12h beyond) rather than staying hourly like Open-Meteo's
output. feature_engineering.py's rolling-window precompute assumes a
uniformly hourly series (each array index = 1 hour) -- so the raw per-time
fetches here are forward-filled onto a synthetic uniform hourly grid before
being returned, keeping the WeatherProvider contract identical to
OpenMeteoProvider's.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import httpx

from config import (
    SMHI_ANALYSIS_BASE_URL,
    SMHI_BACKOFF_BASE_S,
    SMHI_FORECAST_BASE_URL,
    SMHI_GRID_INDEX_PATH,
    SMHI_MAX_RETRIES,
    SMHI_REQUEST_TIMEOUT_S,
)
from grid import GridCell
from weather import HourlyWeather, WeatherValidationError, _plausible

logger = logging.getLogger("mosquito_forecast.smhi_weather")

# Maps our internal field name -> SMHI's flat parameter name. Confirmed live
# against both products' JSON responses (not just docs, which drifted out of
# date within this same product generation -- see README).
FORECAST_PARAMETERS = {
    "temperature_2m": "air_temperature",
    "relative_humidity_2m": "relative_humidity",
    "precipitation": "precipitation_amount_mean",
    "wind_speed_10m": "wind_speed",
    "wind_gusts_10m": "wind_speed_of_gust",
    "cloud_cover": "cloud_area_fraction",
}
ANALYSIS_PARAMETERS = {
    "temperature_2m": "air_temperature",
    "relative_humidity_2m": "relative_humidity",
    "precipitation": "precipitation_amount_last_1_hours",
    "wind_speed_10m": "wind_speed",
    "wind_gusts_10m": "wind_speed_of_gust",
    "cloud_cover": "cloud_area_fraction",
}
PLAUSIBLE_RANGES = {
    "temperature_2m": (-60.0, 55.0),
    "relative_humidity_2m": (0.0, 100.0),
    "precipitation": (0.0, 500.0),
    "wind_speed_10m": (0.0, 150.0),
    "wind_gusts_10m": (0.0, 200.0),
    "cloud_cover": (0.0, 100.0),
}


def load_grid_index(path: Path = SMHI_GRID_INDEX_PATH) -> dict[str, int]:
    if not path.exists():
        raise FileNotFoundError(
            f"SMHI grid index not found at {path} -- run "
            "scripts/prepare_smhi_grid_index.py first"
        )
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _request_with_retry(client: httpx.Client, url: str, max_retries: int, backoff_base_s: float) -> dict:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.get(url, headers={"Accept-Encoding": "gzip"})
            response.raise_for_status()
            return response.json()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            # A 404 means this exact (time, parameter) combination doesn't
            # exist -- e.g. a forecast time that fell off the model's
            # actual output schedule. That's not transient: retrying won't
            # produce a different answer, so don't waste the backoff delay
            # (this matters a lot here -- unlike Open-Meteo's ~370 batches,
            # a full SMHI fetch is hundreds of individual time/parameter
            # requests, and some genuinely-missing combos are expected).
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
                raise WeatherValidationError(f"SMHI resource not found: {exc}") from exc
            if attempt < max_retries:
                sleep_s = backoff_base_s * (2**attempt)
                logger.warning(
                    "SMHI request failed (attempt %d/%d): %s. Retrying in %.1fs",
                    attempt + 1, max_retries + 1, exc, sleep_s,
                )
                time.sleep(sleep_s)
    raise WeatherValidationError(f"SMHI request failed after retries: {last_exc}")


def _fetch_times(client: httpx.Client, base_url: str, max_retries: int, backoff_base_s: float) -> list[str]:
    payload = _request_with_retry(client, f"{base_url}/times.json", max_retries, backoff_base_s)
    return payload.get("time", [])


def _fetch_multipoint_values(
    client: httpx.Client, base_url: str, time_str: str, parameter: str, max_retries: int, backoff_base_s: float
) -> list[float | None] | None:
    """One whole-domain value array for one (time, parameter) pair, or None
    if this exact time/parameter combination isn't available (e.g. a
    forecast time that fell off the model's actual output schedule).

    `time_str` is the ISO-with-separators form returned by /times.json
    (e.g. "2026-08-02T07:00:00Z") -- the MultiPoint URL's path segment
    needs SMHI's compact form instead (e.g. "20260802T070000Z"); using the
    former there 404s on every single request (every character after the
    date is a valid path character individually, so it fails silently
    rather than erroring obviously -- this was missed in initial testing)."""
    compact_time = _to_smhi_time_str(datetime.fromisoformat(time_str))
    url = f"{base_url}/geotype/multipoint/time/{compact_time}/parameter/{parameter}/data.json?with-geo=false"
    try:
        payload = _request_with_retry(client, url, max_retries, backoff_base_s)
    except WeatherValidationError:
        logger.warning("SMHI multipoint fetch failed for %s @ %s; skipping this time/parameter", parameter, time_str)
        return None
    series = payload.get("timeSeries", [])
    if not series:
        return None
    return series[0].get("data", {}).get(parameter)


def _to_smhi_time_str(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _build_hourly_grid(start: datetime, hours: int) -> list[datetime]:
    return [start + timedelta(hours=h) for h in range(hours)]


def _forward_fill_onto_hourly(
    raw_times: list[datetime], raw_values: dict[str, list[float | None]], hourly_times: list[datetime]
) -> dict[str, list[float | None]]:
    """SMHI's own time steps aren't uniformly hourly at longer lead times
    (or, for analysis, may skip an hour SMHI didn't publish). Resample onto
    a strictly hourly grid via forward-fill (nearest prior real reading)
    so the result satisfies feature_engineering.py's uniform-hourly
    assumption, the same contract OpenMeteoProvider already provides
    natively."""
    result: dict[str, list[float | None]] = {field: [] for field in raw_values}
    idx = 0
    n_raw = len(raw_times)
    for t in hourly_times:
        while idx + 1 < n_raw and raw_times[idx + 1] <= t:
            idx += 1
        # Only fill if the nearest known reading is actually at or before
        # this hour (no fabricating values before the series starts) and
        # not absurdly stale (>13h old -- covers the coarsest documented
        # 12h forecast step with a small margin).
        if raw_times and raw_times[idx] <= t and (t - raw_times[idx]) <= timedelta(hours=13):
            for field in raw_values:
                result[field].append(raw_values[field][idx])
        else:
            for field in raw_values:
                result[field].append(None)
    return result


class SMHIProvider:
    """WeatherProvider backed by SMHI Open Data (SNOW forecast + MESAN
    analysis). See module docstring for the request-shape difference versus
    OpenMeteoProvider and the two known permanent limitations."""

    def __init__(
        self,
        forecast_base_url: str = SMHI_FORECAST_BASE_URL,
        analysis_base_url: str = SMHI_ANALYSIS_BASE_URL,
        grid_index: dict[str, int] | None = None,
        grid_index_path: Path = SMHI_GRID_INDEX_PATH,
        timeout_s: float = SMHI_REQUEST_TIMEOUT_S,
        max_retries: int = SMHI_MAX_RETRIES,
        backoff_base_s: float = SMHI_BACKOFF_BASE_S,
        client: httpx.Client | None = None,
        now: datetime | None = None,
    ):
        self.forecast_base_url = forecast_base_url
        self.analysis_base_url = analysis_base_url
        self.grid_index = grid_index if grid_index is not None else load_grid_index(grid_index_path)
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self._client = client
        # Optional fixed reference point, same purpose as
        # SyntheticWeatherProvider.today: real runs want actual wall-clock
        # time, but tests need it pinned for reproducibility.
        self._now = now

    def _fetch_domain(
        self, client: httpx.Client, base_url: str, times: list[str], parameters: dict[str, str]
    ) -> dict[str, dict[str, list[float | None]]]:
        """Returns {internal_field: {time_str: whole-domain value array}}."""
        out: dict[str, dict[str, list[float | None]]] = {field: {} for field in parameters}
        total = len(times) * len(parameters)
        done = 0
        for field, smhi_param in parameters.items():
            for t in times:
                done += 1
                if done == 1 or done % 20 == 0 or done == total:
                    logger.info("SMHI fetch progress: %d/%d (%s)", done, total, base_url.rsplit("/", 4)[-4])
                values = _fetch_multipoint_values(client, base_url, t, smhi_param, self.max_retries, self.backoff_base_s)
                if values is not None:
                    out[field][t] = values
        return out

    def fetch_combined(
        self, points: Iterable[GridCell], past_days: int, forecast_days: int
    ) -> dict[str, HourlyWeather]:
        points = list(points)
        indices = [self.grid_index.get(p.cell_id) for p in points]
        missing = [p.cell_id for p, i in zip(points, indices) if i is None]
        if missing:
            logger.warning(
                "%d/%d cells have no SMHI grid index (run prepare_smhi_grid_index.py?); "
                "they will be skipped: %s%s",
                len(missing), len(points), missing[:5], "..." if len(missing) > 5 else "",
            )

        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout_s)
        try:
            analysis_times = _fetch_times(client, self.analysis_base_url, self.max_retries, self.backoff_base_s)
            forecast_times = _fetch_times(client, self.forecast_base_url, self.max_retries, self.backoff_base_s)

            now = self._now or datetime.now(timezone.utc)
            forecast_cutoff = now + timedelta(days=forecast_days)
            forecast_times = [t for t in forecast_times if datetime.fromisoformat(t) <= forecast_cutoff]

            analysis_data = self._fetch_domain(client, self.analysis_base_url, analysis_times, ANALYSIS_PARAMETERS)
            forecast_data = self._fetch_domain(client, self.forecast_base_url, forecast_times, FORECAST_PARAMETERS)
        finally:
            if owns_client:
                client.close()

        # Raw (irregularly spaced) merged series, per field: analysis times
        # (real observed past) followed by forecast times (future), in
        # order -- overlap is not expected (analysis is always <= now,
        # forecast is always > now) so no de-dup/merge logic is needed here.
        raw_times_str = analysis_times + forecast_times
        raw_times = [datetime.fromisoformat(t) for t in raw_times_str]

        fields = list(FORECAST_PARAMETERS.keys())

        # Build the target uniform hourly grid spanning the full requested
        # window, same shape OpenMeteoProvider would produce.
        window_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(days=past_days)
        hourly_times = _build_hourly_grid(window_start, (past_days + forecast_days) * 24)

        results: dict[str, HourlyWeather] = {}
        for cell, idx in zip(points, indices):
            if idx is None:
                continue
            raw_values: dict[str, list[float | None]] = {}
            for field in fields:
                series = []
                for t in raw_times_str:
                    domain_values = analysis_data.get(field, {}).get(t) or forecast_data.get(field, {}).get(t)
                    if domain_values is None:
                        series.append(None)
                    else:
                        lo, hi = PLAUSIBLE_RANGES[field]
                        series.append(_plausible(domain_values[idx], lo, hi))
                raw_values[field] = series

            hourly_values = _forward_fill_onto_hourly(raw_times, raw_values, hourly_times)
            results[cell.cell_id] = HourlyWeather(
                cell_id=cell.cell_id,
                latitude=cell.latitude,
                longitude=cell.longitude,
                times=[t.strftime("%Y-%m-%dT%H:%M") for t in hourly_times],
                temperature_2m=hourly_values["temperature_2m"],
                relative_humidity_2m=hourly_values["relative_humidity_2m"],
                precipitation=hourly_values["precipitation"],
                wind_speed_10m=hourly_values["wind_speed_10m"],
                wind_gusts_10m=hourly_values["wind_gusts_10m"],
                cloud_cover=hourly_values["cloud_cover"],
                soil_moisture=[None] * len(hourly_times),
                used_fallback=False,
            )
        return results
