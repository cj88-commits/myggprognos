"""Feature engineering: turn raw weather + static GIS data into biologically
plausible, explainable inputs for the scoring model.

All functions here are pure and deterministic given their inputs, which
keeps them easy to unit test and easy to explain to end users (every model
input maps to a named, human-readable feature).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from static_features import StaticFeatures
from weather import HourlyWeather

HEAVY_RAIN_MM_PER_DAY = 15.0
MEANINGFUL_RAIN_MM = 1.0
WARM_NIGHT_THRESHOLD_C = 15.0
FREEZING_THRESHOLD_C = 0.0


@dataclass
class FeatureSet:
    # Temperature
    current_temperature_c: float | None
    daily_min_temperature_c: float | None
    daily_max_temperature_c: float | None
    mean_temperature_3d_c: float | None
    mean_temperature_7d_c: float | None
    mean_temperature_14d_c: float | None
    growing_degree_days: float
    warm_night: bool
    freezing_recently: bool

    # Rainfall
    current_precipitation_mm: float
    precipitation_24h_mm: float
    precipitation_3d_mm: float
    precipitation_7d_mm: float
    precipitation_14d_mm: float
    precipitation_21d_mm: float
    days_since_meaningful_rain: int
    heavy_rain_recent: bool
    rainfall_anomaly: float

    # Moisture
    soil_moisture_current: float | None
    soil_moisture_7d_mean: float | None
    soil_moisture_trend: float
    wet_ground: bool
    soil_moisture_is_fallback: bool

    # Wind
    wind_speed_current_ms: float | None
    wind_speed_forecast_ms: float | None
    wind_gusts_ms: float | None
    evening_wind_ms: float | None

    # Humidity
    humidity_current_pct: float | None
    humidity_daily_mean_pct: float | None
    humidity_evening_pct: float | None

    # Time / season
    day_of_year: int
    latitude: float
    daylight_hours: float
    hour_of_day: int
    daypart: str
    seasonal_suitability: float

    # Static
    forest_fraction: float
    wetland_fraction: float
    urban_fraction: float
    distance_to_water_km: float
    elevation_m: float
    slope_deg: float
    coastal_exposure: float
    water_body_density: float

    # Data quality flags (feed into confidence.py)
    weather_missing_fraction: float
    used_synthetic_weather: bool


def _mean(values: list[float | None]) -> float | None:
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def _parse_times(times: list[str]) -> list[datetime]:
    out = []
    for t in times:
        try:
            out.append(datetime.fromisoformat(t).replace(tzinfo=timezone.utc))
        except ValueError:
            out.append(datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc))
    return out


def _window(parsed_times: list[datetime], series: list[float | None], end: datetime, hours_back: int) -> list[float | None]:
    start = end - timedelta(hours=hours_back)
    return [v for t, v in zip(parsed_times, series) if start <= t <= end]


def _daypart(hour: int) -> str:
    if 6 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def daylight_hours(latitude: float, day_of_year: int) -> float:
    """Approximate day length in hours using a standard astronomical
    approximation (accurate to within a few minutes for mid/high
    latitudes, which is more than sufficient for a suitability feature)."""
    lat_rad = math.radians(latitude)
    declination = 0.4093 * math.sin(2 * math.pi / 365 * (day_of_year - 81))
    cos_hour_angle = -math.tan(lat_rad) * math.tan(declination)
    cos_hour_angle = max(-1.0, min(1.0, cos_hour_angle))
    hour_angle = math.acos(cos_hour_angle)
    return round((2 * hour_angle * 24) / (2 * math.pi), 2)


def seasonal_suitability_curve(day_of_year: int, latitude: float) -> float:
    """Bell-shaped seasonal suitability peaking in Swedish mid-summer
    (approx. day 190, early July), narrower at higher latitudes where the
    mosquito season is more compressed."""
    peak_day = 190
    width = 70 - min(25, max(0, (latitude - 55) * 1.2))
    diff = min(abs(day_of_year - peak_day), 365 - abs(day_of_year - peak_day))
    return math.exp(-0.5 * (diff / width) ** 2)


def compute_features(
    static: StaticFeatures,
    weather: HourlyWeather,
    target_time: datetime,
    development_base_temperature_c: float = 10.0,
) -> FeatureSet:
    if target_time.tzinfo is None:
        target_time = target_time.replace(tzinfo=timezone.utc)

    parsed_times = _parse_times(weather.times)
    total = len(weather.times) or 1
    missing = sum(1 for v in weather.temperature_2m if v is None)
    weather_missing_fraction = missing / total

    idx = None
    best_delta = None
    for i, t in enumerate(parsed_times):
        delta = abs((t - target_time).total_seconds())
        if best_delta is None or delta < best_delta:
            best_delta = delta
            idx = i

    current_temp = weather.temperature_2m[idx] if idx is not None else None
    current_humidity = weather.relative_humidity_2m[idx] if idx is not None else None
    current_wind = weather.wind_speed_10m[idx] if idx is not None else None
    current_gusts = weather.wind_gusts_10m[idx] if idx is not None else None
    current_soil = weather.soil_moisture[idx] if idx is not None else None
    current_precip = weather.precipitation[idx] if idx is not None else 0.0

    day_temps = _window(parsed_times, weather.temperature_2m, target_time, 24)
    daily_min = min([v for v in day_temps if v is not None], default=None)
    daily_max = max([v for v in day_temps if v is not None], default=None)

    mean_3d = _mean(_window(parsed_times, weather.temperature_2m, target_time, 72))
    mean_7d = _mean(_window(parsed_times, weather.temperature_2m, target_time, 168))
    mean_14d = _mean(_window(parsed_times, weather.temperature_2m, target_time, 336))

    gdd_window = _window(parsed_times, weather.temperature_2m, target_time, 336)
    gdd_valid = [v for v in gdd_window if v is not None]
    growing_degree_days = sum(max(0.0, v - development_base_temperature_c) for v in gdd_valid) / 24.0

    night_temps = [
        v
        for t, v in zip(parsed_times, weather.temperature_2m)
        if v is not None and (t.hour >= 22 or t.hour <= 5) and target_time - timedelta(hours=24) <= t <= target_time
    ]
    warm_night = bool(night_temps) and min(night_temps) >= WARM_NIGHT_THRESHOLD_C
    freezing_recently = daily_min is not None and daily_min <= FREEZING_THRESHOLD_C

    def rain_sum(hours_back: int) -> float:
        vals = _window(parsed_times, weather.precipitation, target_time, hours_back)
        return round(sum(v for v in vals if v is not None), 2)

    precip_24h = rain_sum(24)
    precip_3d = rain_sum(24 * 3)
    precip_7d = rain_sum(24 * 7)
    precip_14d = rain_sum(24 * 14)
    precip_21d = rain_sum(24 * 21)

    days_since_meaningful_rain = 0
    for days_back in range(0, 22):
        window_start = target_time - timedelta(days=days_back + 1)
        window_end = target_time - timedelta(days=days_back)
        day_vals = [
            v for t, v in zip(parsed_times, weather.precipitation)
            if v is not None and window_start <= t <= window_end
        ]
        if sum(day_vals) >= MEANINGFUL_RAIN_MM:
            days_since_meaningful_rain = days_back
            break
    else:
        days_since_meaningful_rain = 21

    heavy_rain_recent = precip_24h >= HEAVY_RAIN_MM_PER_DAY
    seasonal_norm_mm = 2.0 * 14  # crude ~2mm/day seasonal baseline over 14d
    rainfall_anomaly = round((precip_14d - seasonal_norm_mm) / seasonal_norm_mm, 3) if seasonal_norm_mm else 0.0

    soil_series_7d = _window(parsed_times, weather.soil_moisture, target_time, 168)
    soil_7d_mean = _mean(soil_series_7d)
    soil_older = _window(
        parsed_times, weather.soil_moisture, target_time - timedelta(hours=84), 84
    )
    soil_older_mean = _mean(soil_older)
    soil_recent_mean = _mean(_window(parsed_times, weather.soil_moisture, target_time, 84))
    soil_is_fallback = all(v is None for v in weather.soil_moisture)

    if soil_is_fallback:
        # Transparent fallback: derive a pseudo soil-moisture index from
        # recent rainfall (wetting) and temperature (drying via evaporation).
        fallback_index = min(1.0, max(0.0, 0.1 + precip_14d / 60.0 - (mean_7d or 10) / 200.0))
        current_soil = fallback_index
        soil_7d_mean = fallback_index
        soil_trend = 0.0
    else:
        soil_trend = round((soil_recent_mean or 0) - (soil_older_mean or soil_recent_mean or 0), 4) if soil_recent_mean is not None else 0.0

    wet_ground = (current_soil or 0) >= 0.30 or precip_3d >= 10

    evening_times_idx = [
        i for i, t in enumerate(parsed_times)
        if t.date() == target_time.date() and 18 <= t.hour <= 21
    ]
    evening_wind = _mean([weather.wind_speed_10m[i] for i in evening_times_idx]) if evening_times_idx else current_wind
    evening_humidity = _mean([weather.relative_humidity_2m[i] for i in evening_times_idx]) if evening_times_idx else current_humidity

    daily_humidity_vals = _window(parsed_times, weather.relative_humidity_2m, target_time, 24)
    humidity_daily_mean = _mean(daily_humidity_vals)

    forecast_wind_idx = min(range(len(parsed_times)), key=lambda i: abs((parsed_times[i] - (target_time + timedelta(hours=6))).total_seconds())) if parsed_times else None
    wind_forecast = weather.wind_speed_10m[forecast_wind_idx] if forecast_wind_idx is not None else current_wind

    day_of_year = target_time.timetuple().tm_yday
    hours = daylight_hours(weather.latitude, day_of_year)
    seasonal = seasonal_suitability_curve(day_of_year, weather.latitude)

    return FeatureSet(
        current_temperature_c=current_temp,
        daily_min_temperature_c=daily_min,
        daily_max_temperature_c=daily_max,
        mean_temperature_3d_c=mean_3d,
        mean_temperature_7d_c=mean_7d,
        mean_temperature_14d_c=mean_14d,
        growing_degree_days=round(growing_degree_days, 2),
        warm_night=warm_night,
        freezing_recently=freezing_recently,
        current_precipitation_mm=round(current_precip or 0.0, 2),
        precipitation_24h_mm=precip_24h,
        precipitation_3d_mm=precip_3d,
        precipitation_7d_mm=precip_7d,
        precipitation_14d_mm=precip_14d,
        precipitation_21d_mm=precip_21d,
        days_since_meaningful_rain=days_since_meaningful_rain,
        heavy_rain_recent=heavy_rain_recent,
        rainfall_anomaly=rainfall_anomaly,
        soil_moisture_current=current_soil,
        soil_moisture_7d_mean=soil_7d_mean,
        soil_moisture_trend=soil_trend,
        wet_ground=wet_ground,
        soil_moisture_is_fallback=soil_is_fallback,
        wind_speed_current_ms=current_wind,
        wind_speed_forecast_ms=wind_forecast,
        wind_gusts_ms=current_gusts,
        evening_wind_ms=evening_wind,
        humidity_current_pct=current_humidity,
        humidity_daily_mean_pct=humidity_daily_mean,
        humidity_evening_pct=evening_humidity,
        day_of_year=day_of_year,
        latitude=weather.latitude,
        daylight_hours=hours,
        hour_of_day=target_time.hour,
        daypart=_daypart(target_time.hour),
        seasonal_suitability=round(seasonal, 4),
        forest_fraction=static.forest_fraction,
        wetland_fraction=static.wetland_fraction,
        urban_fraction=static.urban_fraction,
        distance_to_water_km=static.distance_to_water_km,
        elevation_m=static.elevation_m,
        slope_deg=static.slope_deg,
        coastal_exposure=static.coastal_exposure,
        water_body_density=static.water_body_density,
        weather_missing_fraction=round(weather_missing_fraction, 4),
        used_synthetic_weather=weather.used_fallback,
    )
