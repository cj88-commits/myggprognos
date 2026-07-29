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
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Protocol

import httpx

from config import (
    OPEN_METEO_ARCHIVE_URL,
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


class WeatherProvider(Protocol):
    def fetch_forecast(
        self, points: Iterable[GridCell], start_date: date, end_date: date
    ) -> dict[str, HourlyWeather]:
        """Fetch hourly forecast weather for the given points and date
        range, keyed by cell_id."""
        ...

    def fetch_recent_history(
        self, points: Iterable[GridCell], days_back: int
    ) -> dict[str, HourlyWeather]:
        """Fetch recent historical/observed weather, used for lagged
        rainfall and accumulated-warmth features."""
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
        archive_url: str = OPEN_METEO_ARCHIVE_URL,
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
        self.archive_url = archive_url
        self.batch_size = batch_size
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.pacing_s = pacing_s
        self.rate_limit_backoff_s = rate_limit_backoff_s
        self.cache = cache or DiskCache()
        self._client = client

    def _get_client(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=self.timeout_s)

    def _request_with_retry(self, url: str, params: dict) -> dict:
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
        client = self._get_client()
        owns_client = self._client is None
        try:
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
        finally:
            if owns_client:
                client.close()

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
            )
        return results

    def fetch_forecast(
        self, points: Iterable[GridCell], start_date: date, end_date: date
    ) -> dict[str, HourlyWeather]:
        points = list(points)
        results: dict[str, HourlyWeather] = {}
        for batch in self._batched(points):
            params = {
                "latitude": ",".join(str(p.latitude) for p in batch),
                "longitude": ",".join(str(p.longitude) for p in batch),
                "hourly": ",".join(HOURLY_VARIABLES),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "timezone": "UTC",
            }
            try:
                payload = self._request_with_retry(self.base_url, params)
            except WeatherValidationError:
                logger.error("Forecast fetch failed for batch of %d points; skipping batch", len(batch))
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
        return results

    def fetch_recent_history(self, points: Iterable[GridCell], days_back: int) -> dict[str, HourlyWeather]:
        points = list(points)
        end = datetime.now(timezone.utc).date() - timedelta(days=1)
        start = end - timedelta(days=days_back)
        results: dict[str, HourlyWeather] = {}
        for batch in self._batched(points):
            params = {
                "latitude": ",".join(str(p.latitude) for p in batch),
                "longitude": ",".join(str(p.longitude) for p in batch),
                "hourly": ",".join(HOURLY_VARIABLES),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "timezone": "UTC",
            }
            try:
                payload = self._request_with_retry(self.archive_url, params)
            except WeatherValidationError:
                logger.error("History fetch failed for batch of %d points; skipping batch", len(batch))
                continue
            payload_list = payload if isinstance(payload, list) else [payload]
            if len(payload_list) != len(batch):
                logger.error(
                    "Open-Meteo archive returned %d results for %d requested points; skipping mismatched batch",
                    len(payload_list),
                    len(batch),
                )
                continue
            results.update(self._parse_batch(batch, payload_list))
        return results


class SyntheticWeatherProvider:
    """Deterministic synthetic WeatherProvider for sample mode, offline
    development, and tests. Produces plausible seasonal hourly series
    without any network access."""

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

        day_of_year = start.timetuple().tm_yday
        seasonal_mean = 12 + 10 * _math.sin(2 * _math.pi * (day_of_year - 80) / 365)

        seed = int(hashlib.sha256(cell.cell_id.encode()).hexdigest()[:6], 16)

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
        )

    def fetch_forecast(self, points: Iterable[GridCell], start_date: date, end_date: date) -> dict[str, HourlyWeather]:
        hours = (end_date - start_date).days * 24 + 24
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        return {cell.cell_id: self._series_for(cell, start, hours) for cell in points}

    def fetch_recent_history(self, points: Iterable[GridCell], days_back: int) -> dict[str, HourlyWeather]:
        start = datetime.now(timezone.utc) - timedelta(days=days_back)
        return {cell.cell_id: self._series_for(cell, start, days_back * 24) for cell in points}
