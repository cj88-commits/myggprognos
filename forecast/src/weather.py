"""Weather data providers.

Defines a small `WeatherProvider` protocol so Open-Meteo can be swapped for
another provider later without touching the rest of the pipeline. The
Open-Meteo implementation batches many grid points per HTTP request, retries
with exponential backoff, times out, validates responses, and caches results
on disk so repeated runs (and local development) don't hammer the API.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Protocol

import httpx

from config import (
    OPEN_METEO_BASE_URL,
    WEATHER_BACKOFF_BASE_S,
    WEATHER_BATCH_SIZE,
    WEATHER_CACHE_DIR,
    WEATHER_CACHE_TTL_S,
    WEATHER_MAX_RETRIES,
    WEATHER_RATE_LIMIT_BACKOFF_S,
    WEATHER_REQUEST_PACING_S,
    WEATHER_REQUEST_TIMEOUT_S,
)
from grid import GridCell

logger = logging.getLogger("mosquito_forecast.weather")

HOURLY_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_gusts_10m",
    "cloud_cover",
    "soil_moisture_0_to_1cm",
    # Snowmelt ecology (geographic-model redesign, Phase 7): real
    # accumulated snow depth (meters), so far-north/high-latitude snowmelt-
    # driven emergence can be derived from actual per-cell snow history
    # instead of a calendar-only, geographically-uniform curve -- see
    # docs/geographic-model-audit-before.md #4.6. Open-Meteo's forecast API
    # supports this hourly variable; SMHI's does not (see smhi_weather.py --
    # snow_depth is left as None there, same documented-fallback pattern
    # already used for soil_moisture).
    "snow_depth",
]


@dataclass(frozen=True)
class HourlyWeather:
    """Hourly weather series for a single point. Each field is a parallel
    list aligned with `times`. Missing optional fields (e.g. soil moisture,
    which Open-Meteo does not provide for all locations) are left as None
    entries rather than silently dropped, so downstream code can apply a
    documented fallback and mark confidence accordingly."""

    cell_id: str
    latitude: float
    longitude: float
    times: list[str]
    temperature_2m: list[float | None]
    relative_humidity_2m: list[float | None]
    precipitation: list[float | None]
    wind_speed_10m: list[float | None]
    wind_gusts_10m: list[float | None]
    cloud_cover: list[float | None]
    soil_moisture: list[float | None]
    used_fallback: bool = False
    # Snow depth in meters, or None throughout for providers that don't
    # supply it at all (SMHI, synthetic) -- distinct from per-hour None
    # entries within an otherwise-present series (a provider that supports
    # snow_depth but is missing it for one specific hour).
    snow_depth_m: list[float | None] = field(default_factory=list)


class WeatherProvider(Protocol):
    def fetch_combined(
        self, points: Iterable[GridCell], past_days: int, forecast_days: int
    ) -> dict[str, HourlyWeather]:
        """Fetch one continuous hourly series per point spanning `past_days`
        days before today through `forecast_days` days ahead (inclusive),
        keyed by cell_id. The recent-past portion feeds lagged rainfall /
        accumulated-warmth features; the forward portion is the actual
        forecast. A single call per batch rather than two (one to an
        archive endpoint for history, one to the forecast endpoint) --
        Open-Meteo's forecast endpoint natively supports returning both via
        its `past_days` parameter, which halves total request volume."""
        ...


class WeatherValidationError(ValueError):
    pass


def _cache_key(url: str, params: dict) -> str:
    payload = json.dumps({"url": url, "params": params}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DiskCache:
    def __init__(self, directory: Path = WEATHER_CACHE_DIR, ttl_s: int = WEATHER_CACHE_TTL_S):
        self.directory = directory
        self.ttl_s = ttl_s
        self.directory.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> dict | None:
        path = self.directory / f"{key}.json"
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > self.ttl_s:
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, key: str, value: dict) -> None:
        path = self.directory / f"{key}.json"
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(value, fh)
        except OSError:
            logger.warning("Failed to write weather cache entry %s", key)


def _validate_response(payload: dict | list) -> None:
    """Open-Meteo returns a single JSON object for one coordinate, or a
    JSON array of objects when multiple coordinates are requested in one
    call (our batched case) -- both are valid response shapes."""
    if isinstance(payload, list):
        for item in payload:
            _validate_response(item)
        return
    if not isinstance(payload, dict):
        raise WeatherValidationError("Response is not a JSON object or array")
    if "error" in payload and payload.get("error"):
        raise WeatherValidationError(f"Open-Meteo error: {payload.get('reason', 'unknown')}")


def _plausible(value: float | None, lo: float, hi: float) -> float | None:
    if value is None:
        return None
    if value != value:  # NaN check without importing math for this
        return None
    if value < lo or value > hi:
        return None
    return value


class OpenMeteoProvider:
    """Open-Meteo based WeatherProvider implementation.

    Batches multiple points into a single request using Open-Meteo's
    multi-coordinate support (comma-separated latitude/longitude lists),
    retries transient failures with exponential backoff, and caches
    responses on disk for `WEATHER_CACHE_TTL_S` seconds.
    """

    def __init__(
        self,
        base_url: str = OPEN_METEO_BASE_URL,
        batch_size: int = WEATHER_BATCH_SIZE,
        timeout_s: float = WEATHER_REQUEST_TIMEOUT_S,
        max_retries: int = WEATHER_MAX_RETRIES,
        backoff_base_s: float = WEATHER_BACKOFF_BASE_S,
        pacing_s: float = WEATHER_REQUEST_PACING_S,
        rate_limit_backoff_s: float = WEATHER_RATE_LIMIT_BACKOFF_S,
        cache: DiskCache | None = None,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url
        self.batch_size = batch_size
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.pacing_s = pacing_s
        self.rate_limit_backoff_s = rate_limit_backoff_s
        self.cache = cache or DiskCache()
        self._client = client

    def _request_with_retry(self, client: httpx.Client, url: str, params: dict) -> dict:
        cache_key = _cache_key(url, params)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        # Proactive pacing (once per call, not per retry -- retries already
        # have their own backoff below): spaces consecutive *different*
        # batch requests out so we don't trip the rate limit in the first
        # place. See WEATHER_REQUEST_PACING_S in config.py.
        if self.pacing_s > 0:
            time.sleep(self.pacing_s)

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                _validate_response(payload)
                self.cache.set(cache_key, payload)
                return payload
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError, WeatherValidationError) as exc:
                last_exc = exc
                is_rate_limited = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429
                if attempt < self.max_retries:
                    if is_rate_limited:
                        # A 429 means "over quota right now" -- a short
                        # 1s/2s/4s ramp just re-hits the same window.
                        sleep_s = self.rate_limit_backoff_s * (attempt + 1)
                    else:
                        sleep_s = self.backoff_base_s * (2**attempt)
                    logger.warning(
                        "Weather request failed (attempt %d/%d)%s: %s. Retrying in %.1fs",
                        attempt + 1,
                        self.max_retries + 1,
                        " [rate limited]" if is_rate_limited else "",
                        exc,
                        sleep_s,
                    )
                    time.sleep(sleep_s)

        raise WeatherValidationError(f"Weather request failed after retries: {last_exc}")

    def _batched(self, points: list[GridCell]) -> Iterable[list[GridCell]]:
        for i in range(0, len(points), self.batch_size):
            yield points[i : i + self.batch_size]

    def _parse_batch(self, batch: list[GridCell], payload_list: list[dict], used_fallback: bool = False) -> dict[str, HourlyWeather]:
        results: dict[str, HourlyWeather] = {}
        for cell, payload in zip(batch, payload_list):
            hourly = payload.get("hourly", {})
            times = hourly.get("time", [])
            n = len(times)

            def series(key: str, lo: float, hi: float) -> list[float | None]:
                raw = hourly.get(key, [None] * n)
                return [_plausible(v, lo, hi) for v in raw]

            results[cell.cell_id] = HourlyWeather(
                cell_id=cell.cell_id,
                latitude=cell.latitude,
                longitude=cell.longitude,
                times=times,
                temperature_2m=series("temperature_2m", -60, 55),
                relative_humidity_2m=series("relative_humidity_2m", 0, 100),
                precipitation=series("precipitation", 0, 500),
                wind_speed_10m=series("wind_speed_10m", 0, 150),
                wind_gusts_10m=series("wind_gusts_10m", 0, 200),
                cloud_cover=series("cloud_cover", 0, 100),
                soil_moisture=series("soil_moisture_0_to_1cm", 0, 1),
                used_fallback=used_fallback,
                snow_depth_m=series("snow_depth", 0, 20),
            )
        return results

    def fetch_combined(
        self, points: Iterable[GridCell], past_days: int, forecast_days: int
    ) -> dict[str, HourlyWeather]:
        """One request per batch instead of two: Open-Meteo's forecast
        endpoint natively returns `past_days` days of recent history
        immediately followed by `forecast_days` of forward forecast, as a
        single continuous, sorted, non-overlapping hourly series -- no
        separate archive-API call or client-side merge/de-dup needed."""
        points = list(points)
        results: dict[str, HourlyWeather] = {}
        total_batches = (len(points) + self.batch_size - 1) // self.batch_size

        # One shared client (one persistent, keep-alive connection) for
        # every batch in this call, instead of opening + closing a brand
        # new TCP+TLS connection per batch. At full-Sweden scale (~370
        # batches) a fresh handshake every single request turned out to be
        # a major source of the "handshake operation timed out" failures
        # seen in production (a live run had 136/373 batches need at least
        # one retry) -- repeatedly hammering fresh connections instead of
        # reusing a warm one is both slower and less reliable.
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout_s)
        try:
            for batch_num, batch in enumerate(self._batched(points), start=1):
                # Periodic progress at INFO (not per-batch, which would be
                # noisy at ~370 batches) -- long unattended runs (full
                # grid, ~20+ min even in the best case) were previously
                # silent until the very end, making it impossible to tell
                # "still working" from "stuck" without downloading logs
                # after the fact.
                if batch_num == 1 or batch_num % 10 == 0 or batch_num == total_batches:
                    logger.info("Weather fetch progress: batch %d/%d", batch_num, total_batches)
                params = {
                    "latitude": ",".join(str(p.latitude) for p in batch),
                    "longitude": ",".join(str(p.longitude) for p in batch),
                    "hourly": ",".join(HOURLY_VARIABLES),
                    "past_days": past_days,
                    "forecast_days": forecast_days,
                    "timezone": "UTC",
                    # Open-Meteo's default wind unit is km/h, not m/s -- every
                    # wind threshold in this codebase (model.yaml
                    # wind_half_suppression_ms, calm_threshold_ms, etc.) is
                    # named and calibrated in m/s. Found while building the
                    # historical-validation harness (2026-calibration sprint):
                    # this parameter was missing here, meaning any live run
                    # actually falling back to Open-Meteo (SMHI is the default
                    # production provider and unaffected -- it returns m/s
                    # natively) would silently read wind speeds ~3.6x too
                    # high, over-suppressing biting activity. Fixed here
                    # rather than left latent for whenever the fallback is
                    # next used.
                    "wind_speed_unit": "ms",
                }
                try:
                    payload = self._request_with_retry(client, self.base_url, params)
                except WeatherValidationError:
                    logger.error("Weather fetch failed for batch of %d points; skipping batch", len(batch))
                    continue
                payload_list = payload if isinstance(payload, list) else [payload]
                if len(payload_list) != len(batch):
                    logger.error(
                        "Open-Meteo returned %d results for %d requested points; skipping mismatched batch",
                        len(payload_list),
                        len(batch),
                    )
                    continue
                results.update(self._parse_batch(batch, payload_list))
        finally:
            if owns_client:
                client.close()

        return results


# Open-Meteo's Historical Weather API (ERA5-Land-based reanalysis, free,
# keyless, no paid tier -- https://open-meteo.com/en/docs/historical-weather-api)
# -- distinct from the forecast endpoint's `past_days` (bounded relative to
# "now", not usable for an arbitrary date in 2024) and from SMHI's MESAN
# analysis (only exposes a rolling ~24h window, see smhi_weather.py module
# docstring). Built for the calibration/validation sprint (see
# docs/calibration-validation-final.md and scripts/historical_model_validation.py)
# -- neither production provider can answer "what did the model say for a
# specific week in June 2024", and validating category thresholds against
# only the current week's weather (as the geographic-model redesign
# originally did) was exactly the gap this harness exists to close.
ARCHIVE_BASE_URL = os.environ.get("OPEN_METEO_ARCHIVE_BASE_URL", "https://archive-api.open-meteo.com/v1/archive")


class OpenMeteoArchiveProvider(OpenMeteoProvider):
    """Historical-date variant of OpenMeteoProvider -- reuses its retry/
    batching/parsing machinery unchanged (`_request_with_retry`,
    `_parse_batch`, `_batched`), only replacing the endpoint and the
    request's time-range parameters (`start_date`/`end_date` instead of
    `past_days`/`forecast_days`). Returns the identical `HourlyWeather`
    shape, so it's a drop-in `WeatherProvider` for `run_pipeline`/
    `compute_features` -- the calibration sprint runs the SAME model code
    used in production, not a separate simplified calibration model."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("base_url", ARCHIVE_BASE_URL)
        super().__init__(*args, **kwargs)

    def fetch_combined(self, points: Iterable[GridCell], past_days: int, forecast_days: int) -> dict[str, HourlyWeather]:
        raise NotImplementedError(
            "OpenMeteoArchiveProvider uses fetch_range(points, start_date, end_date) -- "
            "past_days/forecast_days are relative to 'now', meaningless for a fixed historical date."
        )

    def fetch_range(
        self, points: Iterable[GridCell], start_date: date, end_date: date
    ) -> dict[str, HourlyWeather]:
        """Same batching/retry/parsing behavior as
        OpenMeteoProvider.fetch_combined, but for an explicit
        [start_date, end_date] calendar-date window (inclusive) instead of
        a past_days/forecast_days window relative to now."""
        points = list(points)
        results: dict[str, HourlyWeather] = {}
        total_batches = (len(points) + self.batch_size - 1) // self.batch_size

        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout_s)
        try:
            for batch_num, batch in enumerate(self._batched(points), start=1):
                if batch_num == 1 or batch_num % 10 == 0 or batch_num == total_batches:
                    logger.info("Historical weather fetch progress: batch %d/%d", batch_num, total_batches)
                params = {
                    "latitude": ",".join(str(p.latitude) for p in batch),
                    "longitude": ",".join(str(p.longitude) for p in batch),
                    "hourly": ",".join(HOURLY_VARIABLES),
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "timezone": "UTC",
                    "wind_speed_unit": "ms",
                }
                try:
                    payload = self._request_with_retry(client, self.base_url, params)
                except WeatherValidationError:
                    logger.error("Historical weather fetch failed for batch of %d points; skipping batch", len(batch))
                    continue
                payload_list = payload if isinstance(payload, list) else [payload]
                if len(payload_list) != len(batch):
                    logger.error(
                        "Open-Meteo archive returned %d results for %d requested points; skipping mismatched batch",
                        len(payload_list),
                        len(batch),
                    )
                    continue
                results.update(self._parse_batch(batch, payload_list, used_fallback=True))
        finally:
            if owns_client:
                client.close()

        return results


class SyntheticWeatherProvider:
    """Deterministic synthetic WeatherProvider for sample mode, offline
    development, and tests. Produces plausible seasonal hourly series
    without any network access."""

    def __init__(self, today: datetime | None = None):
        # Optional fixed reference point for "today" -- real sample-mode
        # runs want actual wall-clock time, but tests asserting scores are
        # stable/reproducible (see test_fixtures.py) need it pinned so the
        # seasonal-mean calculation below doesn't shift with whatever date
        # the test happens to run on.
        self._today = today

    def _series_for(self, cell: GridCell, start: datetime, hours: int) -> HourlyWeather:
        import math as _math

        times = []
        temps: list[float | None] = []
        humidity: list[float | None] = []
        precip: list[float | None] = []
        wind: list[float | None] = []
        gusts: list[float | None] = []
        cloud: list[float | None] = []
        soil: list[float | None] = []
        snow: list[float | None] = []

        day_of_year = start.timetuple().tm_yday
        seasonal_mean = 12 + 10 * _math.sin(2 * _math.pi * (day_of_year - 80) / 365)

        seed = int(hashlib.sha256(cell.cell_id.encode()).hexdigest()[:6], 16)

        # Synthetic snow depth (Phase 7 sample-mode support): NOT a real
        # snow model -- a simple, deterministic, latitude-aware proxy so
        # sample-mode/CI runs exercise the snowmelt-emergence code path with
        # plausible non-degenerate values. Real production data comes from
        # Open-Meteo's actual snow_depth parameter (see OpenMeteoProvider);
        # regression tests that need precise snow timing construct
        # HourlyWeather fixtures directly rather than relying on this.
        # Melt date shifts later (and peak depth increases) with latitude, a
        # documented, physically-motivated proxy (see docs/mosquito-ecology-
        # evidence.md), not a hidden "Norrland bonus" -- it only shifts
        # WHEN snow is present, actual emergence still requires real
        # accumulated warmth + habitat afterward.
        melt_day = 55 + max(0.0, cell.latitude - 55.0) * 3.0
        winter_peak_depth_m = 0.05 + max(0.0, cell.latitude - 55.0) * 0.02

        for h in range(hours):
            t = start + timedelta(hours=h)
            times.append(t.strftime("%Y-%m-%dT%H:%M"))
            hour_of_day = t.hour
            diurnal = 4 * _math.sin(2 * _math.pi * (hour_of_day - 6) / 24)
            noise = _math.sin((seed + h) * 0.37) * 1.5
            temps.append(round(seasonal_mean + diurnal + noise, 1))
            humidity.append(round(60 + 20 * _math.sin((seed + h) * 0.21) + (10 if hour_of_day >= 18 or hour_of_day <= 5 else 0), 1))
            precip.append(round(max(0.0, 0.6 * _math.sin((seed + h) * 0.53) - 0.3), 2))
            wind.append(round(max(0.0, 3 + 2 * _math.sin((seed + h) * 0.11)), 1))
            gusts.append(round(max(0.0, 5 + 3 * _math.sin((seed + h) * 0.11)), 1))
            cloud.append(round(max(0.0, min(100.0, 50 + 30 * _math.sin((seed + h) * 0.17))), 1))
            soil.append(round(max(0.0, min(1.0, 0.25 + 0.1 * _math.sin((seed + h) * 0.05))), 3))
            day_frac = t.timetuple().tm_yday
            days_before_melt = melt_day - day_frac
            if days_before_melt > 30:
                depth = winter_peak_depth_m
            elif days_before_melt > 0:
                depth = winter_peak_depth_m * (days_before_melt / 30.0)
            else:
                depth = 0.0
            snow.append(round(max(0.0, depth), 3))

        return HourlyWeather(
            cell_id=cell.cell_id,
            latitude=cell.latitude,
            longitude=cell.longitude,
            times=times,
            temperature_2m=temps,
            relative_humidity_2m=humidity,
            precipitation=precip,
            wind_speed_10m=wind,
            wind_gusts_10m=gusts,
            cloud_cover=cloud,
            soil_moisture=soil,
            used_fallback=True,
            snow_depth_m=snow,
        )

    def fetch_combined(
        self, points: Iterable[GridCell], past_days: int, forecast_days: int
    ) -> dict[str, HourlyWeather]:
        today = self._today or datetime.now(timezone.utc)
        today_midnight = today.replace(hour=0, minute=0, second=0, microsecond=0)
        start = today_midnight - timedelta(days=past_days)
        hours = (past_days + forecast_days) * 24
        return {cell.cell_id: self._series_for(cell, start, hours) for cell in points}
