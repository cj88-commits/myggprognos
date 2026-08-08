"""Feature engineering: turn raw weather + static GIS data into biologically
plausible, explainable inputs for the scoring model.

All functions here are pure and deterministic given their inputs, which
keeps them easy to unit test and easy to explain to end users (every model
input maps to a named, human-readable feature).

Performance note: at full-Sweden scale (~15-20k cells x 49 hourly + 28
daypart target-times each), naively re-parsing `weather.times` and
re-scanning multi-week windows on every single `compute_features` call
becomes the dominant cost of the whole pipeline. `precompute_rolling_windows`
does the expensive parsing/cumulative-sum work once per cell; passing the
result in via the optional `rolling` parameter turns repeated windowed
sums/means into O(1) index lookups. Passing no `rolling` (the default)
keeps the original, simpler per-call behaviour, so existing callers/tests
are unaffected.
"""
from __future__ import annotations

import bisect
import itertools
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from solar import compute_solar_times
from static_features import StaticFeatures
from weather import HourlyWeather

HEAVY_RAIN_MM_PER_DAY = 15.0
MEANINGFUL_RAIN_MM = 1.0
WARM_NIGHT_THRESHOLD_C = 15.0
FREEZING_THRESHOLD_C = 0.0

# Every weather timestamp we handle is UTC; but the model's daypart/dusk-dawn
# curve (see model.py::_daypart_activity_curve) and the DAYPARTS bucket
# labels (config.py) are calibrated against actual Swedish clock time. Using
# raw UTC hours there silently shifted "dusk" and "dawn" by 1-2 hours
# (CET/CEST), which mattered most in summer (CEST, UTC+2) -- exactly
# mosquito season.
SWEDEN_TZ = ZoneInfo("Europe/Stockholm")


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

    # Standing water (breeding-site persistence, distinct from raw soil
    # moisture: how long rain-fed pools are likely to persist given recent
    # rainfall, terrain drainage, and nearby wetlands/lakes).
    standing_water_persistence: float

    # Rainfall-to-population emergence lag (see _emergence_potential): how
    # many newly-emerged adult mosquitoes are plausible RIGHT NOW, given
    # both how much rain fell in each of the last few weeks AND how much
    # accumulated warmth has passed since each of those rain events --
    # distinct from precipitation_Xd_mm, which says nothing about whether
    # that rain has had time (and warmth) to actually produce adults yet.
    emergence_potential: float

    # Wind
    wind_speed_current_ms: float | None
    wind_speed_forecast_ms: float | None
    wind_gusts_ms: float | None
    evening_wind_ms: float | None

    # Wind history/trend (added for the calm-evening / wind-drop-release
    # false-negative investigation -- see docs/wind-calm-investigation.md).
    # All None when there isn't enough history in the series (e.g. the
    # very first hour of a run) rather than silently defaulting to 0, so
    # callers can tell "genuinely calm" apart from "no data yet".
    wind_speed_1h_ago_ms: float | None
    wind_speed_3h_ago_ms: float | None
    # current - Nh_ago: negative means wind has DROPPED since then.
    wind_change_1h_ms: float | None
    wind_change_3h_ms: float | None
    # Minimum observed wind over the trailing 3-hour window ending at (and
    # including) the current hour.
    wind_min_3h_ms: float | None
    # Consecutive hours, ending now and counting backward, with wind at or
    # below `calm_threshold_ms` (see compute_features' parameter of the
    # same name). Stops counting at the first missing/unknown hour.
    calm_hours_streak: int

    # Effective (shelter-adjusted) local wind (item 3 of the investigation):
    # forecast_wind_ms transformed by static terrain shelter (forest/urban/
    # slope/coastal). This is NOT measured local wind -- see
    # compute_effective_wind's docstring for the (bounded, configurable)
    # transform and its stated limitations.
    wind_speed_effective_ms: float | None

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

    # Solar timing (see solar.py) -- local decimal hours (e.g. 21.5 =
    # 21:30), used by model.py's activity curve to place the dawn/dusk
    # activity peaks relative to the actual sunrise/sunset for this cell's
    # latitude and date, instead of a fixed clock hour. None precisely
    # when is_polar_day/is_polar_night is True (no sunrise/sunset that day).
    sunrise_hour_local: float | None
    sunset_hour_local: float | None
    is_polar_day: bool
    is_polar_night: bool

    # Static
    forest_fraction: float
    wetland_fraction: float
    urban_fraction: float
    distance_to_water_km: float
    elevation_m: float
    slope_deg: float
    coastal_exposure: float
    water_body_density: float

    # Habitat capacity (geographic-model redesign, Phase 3): slow-changing,
    # weather-independent "how capable is this landscape of supporting
    # large mosquito populations if weather is favourable" -- see
    # static_features.py::compute_habitat_capacity. Copied straight from
    # the static layer since it's computed once per cell there, not
    # recomputed on every hourly/daypart call.
    habitat_capacity: float

    # Persistent mosquito pressure (Phase 6): decay-weighted accumulation of
    # daily rain/degree-day-driven AND snowmelt-driven emergence, gated by
    # habitat_capacity -- see _compute_mosquito_pressure. This is the
    # primary driver of Myggläge (model.py's population_potential) as of
    # this iteration; unlike the old population_potential, it does not
    # collapse to the current instant's weather alone.
    mosquito_pressure: float
    # True if a real snow_depth history was available and used for the
    # snowmelt contribution to mosquito_pressure (Open-Meteo); False if the
    # latitude/timing fallback proxy was used instead (SMHI -- see
    # _fallback_snowmelt_day_signal). Surfaced for confidence/explainability,
    # not used in scoring itself.
    pressure_used_real_snow_data: bool

    # Data quality flags (feed into confidence.py)
    weather_missing_fraction: float
    used_synthetic_weather: bool


@dataclass
class RollingWindows:
    """Precomputed per-cell rolling-window state, built once per cell before
    the hourly/daypart loops in pipeline.py. See module docstring."""

    parsed_times: list[datetime]
    development_base_temperature_c: float
    temp_cumsum: np.ndarray
    temp_count_cumsum: np.ndarray
    gdd_cumsum: np.ndarray
    precip_cumsum: np.ndarray
    soil_cumsum: np.ndarray
    soil_count_cumsum: np.ndarray
    temperature: np.ndarray
    humidity: np.ndarray
    wind: np.ndarray


def _mean(values: list[float | None]) -> float | None:
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Local copy of model.py::clamp -- feature_engineering.py must not
    import from model.py (model.py already imports FeatureSet from here;
    the reverse would be circular)."""
    return max(minimum, min(maximum, value))


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


DEFAULT_CALM_THRESHOLD_MS = 1.8

DEFAULT_WIND_SHELTER_PARAMS = {
    "forest_shelter_weight": 0.35,
    "urban_shelter_weight": 0.15,
    "slope_shelter_weight": 0.10,
    "slope_reference_deg": 10.0,
    "coastal_exposure_weight": 0.25,
    "min_multiplier": 0.55,
    "max_multiplier": 1.15,
}

# How far back _calm_streak is willing to look, regardless of how long an
# actual calm spell has run -- bounds the loop cost and keeps the reported
# streak meaningful ("calm all day" and "calm for 12+ hours" are both
# already well past the point where one more hour changes the calm-gate's
# near-saturated sigmoid response in model.py).
CALM_STREAK_LOOKBACK_HOURS = 12


def compute_effective_wind(
    forecast_wind_ms: float | None,
    forest_fraction: float,
    urban_fraction: float,
    slope_deg: float,
    coastal_exposure: float,
    params: dict | None = None,
) -> float | None:
    """Estimate the near-ground wind actually experienced at this cell, from
    the forecast's exposed/meteorological wind plus static terrain shelter
    (investigation item 2/3 -- see docs/wind-calm-investigation.md). This is
    a coarse, transparent, BOUNDED adjustment, NOT measured local wind: real
    micro-siting (a specific sheltered garden vs. an open field 200m away,
    both inside the same ~5km cell) varies far more than any cell-average
    static feature captures, and this function does not and cannot know
    which one a given report refers to.

        shelter_multiplier = clamp(
            1
            - forest_shelter_weight * forest_fraction
            - urban_shelter_weight * urban_fraction
            - slope_shelter_weight * min(slope_deg, slope_reference_deg) / slope_reference_deg
            + coastal_exposure_weight * coastal_exposure,
            min_multiplier, max_multiplier,
        )
        effective_wind = forecast_wind * shelter_multiplier

    Forest/urban terrain and gentle local topography reduce wind (multiplier
    < 1); high coastal exposure increases it (multiplier can exceed 1, up to
    `max_multiplier`). The clamp means this can never fully zero out or
    wildly amplify the forecast wind on its own, however sheltered/exposed
    the static features suggest -- deliberately conservative given how
    coarse an approximation this is.
    """
    if forecast_wind_ms is None:
        return None
    p = params or DEFAULT_WIND_SHELTER_PARAMS
    slope_reference = p.get("slope_reference_deg", 10.0) or 10.0
    slope_term = min(max(slope_deg or 0.0, 0.0), slope_reference) / slope_reference
    multiplier = (
        1.0
        - p.get("forest_shelter_weight", 0.35) * clamp(forest_fraction, 0.0, 1.0)
        - p.get("urban_shelter_weight", 0.15) * clamp(urban_fraction, 0.0, 1.0)
        - p.get("slope_shelter_weight", 0.10) * slope_term
        + p.get("coastal_exposure_weight", 0.25) * clamp(coastal_exposure, 0.0, 1.0)
    )
    multiplier = clamp(multiplier, p.get("min_multiplier", 0.55), p.get("max_multiplier", 1.15))
    return round(forecast_wind_ms * multiplier, 3)


def _calm_streak(values: list[float | None], calm_threshold_ms: float) -> int:
    """Consecutive hours, counting backward from the LAST element of
    `values` (chronological, oldest-first, ending at "now"), with wind at or
    below `calm_threshold_ms`. Stops at the first missing or
    above-threshold hour -- a single None (no data) does not count as calm,
    and does not "skip past" to keep counting further back."""
    streak = 0
    for v in reversed(values):
        if v is None or v > calm_threshold_ms:
            break
        streak += 1
    return streak


def _daypart(hour: int) -> str:
    if 6 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def precompute_rolling_windows(weather: HourlyWeather, development_base_temperature_c: float = 10.0) -> RollingWindows:
    """One-time (per cell) parse + cumulative-sum precompute. Assumes
    `weather.times` is sorted ascending and (approximately) uniformly hourly,
    which holds for both OpenMeteoProvider and SyntheticWeatherProvider
    (weather.py::fetch_combined returns a single continuous series from
    Open-Meteo directly, already sorted with no duplicates)."""
    parsed_times = _parse_times(weather.times)

    temp = np.array([v if v is not None else np.nan for v in weather.temperature_2m], dtype=float)
    precip = np.array([v if v is not None else 0.0 for v in weather.precipitation], dtype=float)
    humidity = np.array([v if v is not None else np.nan for v in weather.relative_humidity_2m], dtype=float)
    wind = np.array([v if v is not None else np.nan for v in weather.wind_speed_10m], dtype=float)
    soil = np.array([v if v is not None else np.nan for v in weather.soil_moisture], dtype=float)

    temp_filled = np.nan_to_num(temp, nan=0.0)
    temp_valid = (~np.isnan(temp)).astype(float)
    temp_cumsum = np.concatenate(([0.0], np.cumsum(temp_filled)))
    temp_count_cumsum = np.concatenate(([0.0], np.cumsum(temp_valid)))

    gdd_values = np.clip(np.nan_to_num(temp, nan=development_base_temperature_c) - development_base_temperature_c, 0.0, None)
    gdd_cumsum = np.concatenate(([0.0], np.cumsum(gdd_values)))

    precip_cumsum = np.concatenate(([0.0], np.cumsum(precip)))

    soil_filled = np.nan_to_num(soil, nan=0.0)
    soil_valid = (~np.isnan(soil)).astype(float)
    soil_cumsum = np.concatenate(([0.0], np.cumsum(soil_filled)))
    soil_count_cumsum = np.concatenate(([0.0], np.cumsum(soil_valid)))

    return RollingWindows(
        parsed_times=parsed_times,
        development_base_temperature_c=development_base_temperature_c,
        temp_cumsum=temp_cumsum,
        temp_count_cumsum=temp_count_cumsum,
        gdd_cumsum=gdd_cumsum,
        precip_cumsum=precip_cumsum,
        soil_cumsum=soil_cumsum,
        soil_count_cumsum=soil_count_cumsum,
        temperature=temp,
        humidity=humidity,
        wind=wind,
    )


def _nearest_index(times: list[datetime], target: datetime) -> int:
    pos = bisect.bisect_left(times, target)
    if pos <= 0:
        return 0
    if pos >= len(times):
        return len(times) - 1
    before, after = times[pos - 1], times[pos]
    return pos - 1 if (target - before) <= (after - target) else pos


def _range_sum(cumsum: np.ndarray, end_idx: int, hours_back: int, total_len: int) -> float:
    end_idx = max(-1, min(end_idx, total_len - 1))
    start_idx = max(0, end_idx - hours_back + 1)
    if end_idx < 0:
        return 0.0
    return float(cumsum[end_idx + 1] - cumsum[start_idx])


def _range_mean(cumsum: np.ndarray, count_cumsum: np.ndarray, end_idx: int, hours_back: int, total_len: int) -> float | None:
    end_idx = max(-1, min(end_idx, total_len - 1))
    if end_idx < 0:
        return None
    start_idx = max(0, end_idx - hours_back + 1)
    count = count_cumsum[end_idx + 1] - count_cumsum[start_idx]
    if count <= 0:
        return None
    total = cumsum[end_idx + 1] - cumsum[start_idx]
    return float(total / count)


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


def _site_persistence_factor(slope_deg: float, wetland_fraction: float, water_body_density: float) -> float:
    """How well this terrain holds water once it's there -- independent of
    *when* rain fell (timing is handled separately by _emergence_potential
    below). Steeper slope drains faster; nearby wetlands/lakes hold water
    longer once it arrives."""
    drainage_factor = max(0.15, min(1.0, 1.0 - (slope_deg or 0.0) / 15.0))
    return clamp((0.4 + 0.6 * wetland_fraction) * (0.5 + 0.5 * water_body_density) * drainage_factor, 0.0, 1.0)


def _standing_water_persistence(
    precipitation_3d_mm: float,
    precipitation_7d_mm: float,
    precipitation_14d_mm: float,
    slope_deg: float,
    wetland_fraction: float,
    water_body_density: float,
) -> float:
    """How likely rain-fed standing water is to persist long enough to
    support mosquito breeding: heavier weight on the most recent (1-5 day)
    rainfall, tempered by terrain drainage (steeper slope drains faster) and
    boosted by nearby wetlands/lakes that already hold water."""
    recent_weighted_rain = (
        0.5 * precipitation_3d_mm
        + 0.3 * max(0.0, precipitation_7d_mm - precipitation_3d_mm)
        + 0.1 * max(0.0, precipitation_14d_mm - precipitation_7d_mm)
    )
    value = (recent_weighted_rain / 40.0) * _site_persistence_factor(slope_deg, wetland_fraction, water_body_density)
    return round(max(0.0, min(1.0, value)), 4)


# Rough, deliberately NOT species-specific accumulated-warmth threshold for
# egg-to-adult mosquito development (temperate Aedes/Culex development is
# commonly modelled in the 40-80 degree-day range above a ~10C base
# temperature in entomological literature; 60 is a defensible round
# midpoint, not a validated figure for any one species -- see the "Rainfall
# lag" section of the final report for this caveat stated explicitly).
GDD_TO_ADULT_C = 60.0

# A single rain event of this size or more is treated as "fully meaningful"
# for emergence purposes; larger events aren't weighted proportionally
# harder (there's a diminishing-returns ceiling on how much one storm can
# matter), consistent with population_potential's other bell/sigmoid terms
# already being bounded rather than unbounded linear responses.
EMERGENCE_RAIN_REFERENCE_MM = 25.0


def _development_progress(accumulated_gdd: float) -> float:
    """0 (just laid, no development yet) to 1 (fully developed to adult),
    based on growing-degree-days accumulated since the rain event that
    likely created the breeding site -- NOT calendar days. Warmer weather
    accumulates degree-days faster (faster development); freezing or very
    cold conditions accumulate almost none (little/no development), the
    same poikilothermic-insect assumption already used for
    growing_degree_days elsewhere in this module."""
    if GDD_TO_ADULT_C <= 0:
        return 1.0
    return max(0.0, min(1.0, accumulated_gdd / GDD_TO_ADULT_C))


def _emergence_potential(
    rain_0_2d_mm: float,
    rain_3_6d_mm: float,
    rain_7_14d_mm: float,
    rain_15_21d_mm: float,
    gdd_since_0_2d: float,
    gdd_since_3_6d: float,
    gdd_since_7_14d: float,
    gdd_since_15_21d: float,
    site_persistence: float,
) -> float:
    """Transparent, rule-based "how many newly-emerged adult mosquitoes are
    plausible right now" signal: each rainfall-lag bucket's contribution is
    weighted by how far its resulting larvae have actually developed given
    the REAL temperature history since (not by calendar time alone), then
    scaled by how well this site holds water at all.

        emergence_potential = lagged_wetness_event x development_progress x site_persistence

    This directly addresses the reported issue that heavy rain *today*
    should not read as an immediate adult-population signal: rain in the
    0-2-day bucket almost always has near-zero accumulated degree-days
    (_development_progress ~ 0) this soon after falling, regardless of how
    much rain fell, so it contributes almost nothing here -- while the same
    rain, once it's had a week or two of warm weather to develop, moves
    into the 7-14d/15-21d buckets and contributes fully. Each bucket's
    "how long ago" is approximated by its own outer boundary (e.g. the
    7-14 day bucket uses degree-days accumulated over the last 14 days) --
    a coarse but transparent choice, not a precise per-event simulation.
    """
    buckets = (
        (rain_0_2d_mm, gdd_since_0_2d),
        (rain_3_6d_mm, gdd_since_3_6d),
        (rain_7_14d_mm, gdd_since_7_14d),
        (rain_15_21d_mm, gdd_since_15_21d),
    )
    weighted = sum(
        min(rain_mm, EMERGENCE_RAIN_REFERENCE_MM) * _development_progress(gdd)
        for rain_mm, gdd in buckets
    )
    max_possible = EMERGENCE_RAIN_REFERENCE_MM * len(buckets)
    raw = weighted / max_possible if max_possible else 0.0
    return round(max(0.0, min(1.0, raw * site_persistence)), 4)


# --- Persistent mosquito pressure (Phase 6) --------------------------------
#
# pressure_today = surviving_adults + recent_emergence
#     surviving_adults = previous_pressure x survival
#     recent_emergence = habitat_capacity x emergence_conditions
#
# Implemented as the closed form of that recursion (an exponentially-
# weighted sum over the available history window) rather than literal
# day-over-day state, per the new spec's stated preference: "If storing
# state between forecast runs creates undesirable architectural complexity,
# investigate deriving the state deterministically from a sufficiently long
# historical weather window. Prefer reproducibility." Every forecast run
# re-derives the same pressure from the same weather history, with no
# database/cache of "yesterday's computed pressure" to keep in sync --
# genuinely reproducible from weather alone, and trivially backfillable for
# any past date the history cache covers.
#
# Bounded by construction: normalizing by (1 - survival) means pressure
# reaches 1.0 only in the limit of maximal emergence sustained forever, not
# from a single big day.
PRESSURE_LOOKBACK_DAYS_DEFAULT = 21  # bounded by HISTORY_DAYS_BACK (pipeline.py) -- see docs/geographic-model-audit-before.md Phase 6 for the trade-off
PRESSURE_SURVIVAL_DAILY_DEFAULT = 0.90  # ~10% daily adult loss -- see docs/mosquito-ecology-evidence.md

SNOW_MELT_RATE_REFERENCE_M = 0.02  # 2cm/day snow-depth decline treated as a strong, fully-saturating melt signal

# Fallback-only (no real snow_depth history, e.g. SMHI): a physically-
# motivated LATITUDE SHIFT of the assumed spring melt window, not a bonus
# multiplier -- later melt further north, consistent with well-documented
# Nordic climatology (see docs/mosquito-ecology-evidence.md). Still requires
# real per-cell temperature (via freezing_recently) to actually contribute;
# a warm, dry, low-habitat cell at the same latitude gets no boost from this
# alone (habitat_capacity and the rain-driven series still gate the total).
FALLBACK_MELT_BASE_DAY = 55.0
FALLBACK_MELT_LATITUDE_SHIFT_DAYS_PER_DEGREE = 3.0
FALLBACK_MELT_WINDOW_WIDTH_DAYS = 25.0
FALLBACK_MELT_EMERGENCE_LAG_DAYS = 15.0  # meltwater pools need time to develop into adults too


def _bell(value: float, optimum: float, width: float) -> float:
    """Local copy of model.py::bell_curve -- see clamp() above for why
    feature_engineering.py can't import from model.py."""
    if width <= 0:
        return 1.0 if value == optimum else 0.0
    return math.exp(-0.5 * ((value - optimum) / width) ** 2)


def _fallback_snowmelt_day_signal(day_of_year: int, latitude: float) -> float:
    """0-1 snowmelt-emergence signal for ONE calendar day, used only when no
    real snow_depth history is available (see _snowmelt_daily_series). A
    bell curve centered on the assumed local melt date (shifted later with
    latitude) plus a fixed development lag -- deliberately NOT a step
    function, and deliberately not scaled by latitude directly (only the
    TIMING shifts; the peak height is the same everywhere, so this cannot
    become a disguised "Norrland bonus" -- actual pressure still requires
    habitat_capacity and the real per-cell temperature/rain series)."""
    assumed_melt_day = FALLBACK_MELT_BASE_DAY + max(0.0, latitude - 55.0) * FALLBACK_MELT_LATITUDE_SHIFT_DAYS_PER_DEGREE
    return _bell(day_of_year, optimum=assumed_melt_day + FALLBACK_MELT_EMERGENCE_LAG_DAYS, width=FALLBACK_MELT_WINDOW_WIDTH_DAYS)


def _daily_rain_emergence_series(rolling: RollingWindows, idx: int, total_len: int, lookback_days: int) -> list[float]:
    """0-1 per day, today first (index 0), for as many days back as the
    available history covers (up to lookback_days) -- generalizes
    _emergence_potential's four coarse buckets to per-day resolution, reusing
    the same rain-lag x degree-day-development logic."""
    series = []
    for day_offset in range(lookback_days):
        day_end_idx = idx - day_offset * 24
        if day_end_idx < 0:
            break
        day_rain = _range_sum(rolling.precip_cumsum, day_end_idx, 24, total_len)
        gdd_since = _range_sum(rolling.gdd_cumsum, idx, day_offset * 24 + 24, total_len) / 24.0
        rain_signal = clamp(min(day_rain, EMERGENCE_RAIN_REFERENCE_MM) / EMERGENCE_RAIN_REFERENCE_MM, 0.0, 1.0)
        series.append(rain_signal * _development_progress(gdd_since))
    return series


def _snowmelt_daily_series(
    weather: HourlyWeather,
    rolling: RollingWindows,
    idx: int,
    total_len: int,
    target_date,
    latitude: float,
    lookback_days: int,
) -> tuple[list[float], bool]:
    """(series, used_real_snow_data) -- see FeatureSet.pressure_used_real_snow_data."""
    has_real_snow = (
        bool(weather.snow_depth_m)
        and len(weather.snow_depth_m) == len(weather.times)
        and any(v is not None for v in weather.snow_depth_m)
    )
    if has_real_snow:
        series = []
        n_snow = len(weather.snow_depth_m)
        for day_offset in range(lookback_days):
            day_end_idx = idx - day_offset * 24
            day_start_idx = day_end_idx - 24
            if day_start_idx < 0 or day_end_idx < 0 or day_end_idx >= n_snow or day_start_idx >= n_snow:
                break
            snow_start = weather.snow_depth_m[day_start_idx]
            snow_end = weather.snow_depth_m[day_end_idx]
            if snow_start is None or snow_end is None:
                series.append(0.0)
                continue
            melt_m = max(0.0, snow_start - snow_end)
            melt_signal = clamp(melt_m / SNOW_MELT_RATE_REFERENCE_M, 0.0, 1.0)
            gdd_since = _range_sum(rolling.gdd_cumsum, idx, day_offset * 24 + 24, total_len) / 24.0
            series.append(melt_signal * _development_progress(gdd_since))
        return series, True

    series = []
    for day_offset in range(lookback_days):
        d = target_date - timedelta(days=day_offset)
        doy = d.timetuple().tm_yday
        series.append(_fallback_snowmelt_day_signal(doy, latitude))
    return series, False


def _mosquito_pressure_fraction(daily_emergence: list[float], habitat_capacity_fraction: float, survival_daily: float) -> float:
    """Closed-form exponentially-weighted sum -- see module section header.
    `daily_emergence` must be today-first (index 0 = today, index d = d days
    ago), already combining rain- and snowmelt-driven contributions."""
    if not daily_emergence:
        return 0.0
    survival_daily = clamp(survival_daily, 0.0, 0.999)
    total = 0.0
    weight = 1.0
    for emergence in daily_emergence:
        total += clamp(emergence, 0.0, 1.0) * weight
        weight *= survival_daily
    normalization = 1.0 - survival_daily
    return clamp(normalization * total * habitat_capacity_fraction, 0.0, 1.0)


def compute_features(
    static: StaticFeatures,
    weather: HourlyWeather,
    target_time: datetime,
    development_base_temperature_c: float = 10.0,
    rolling: RollingWindows | None = None,
    calm_threshold_ms: float = DEFAULT_CALM_THRESHOLD_MS,
    wind_shelter_params: dict | None = None,
    pressure_survival_daily: float = PRESSURE_SURVIVAL_DAILY_DEFAULT,
    pressure_lookback_days: int = PRESSURE_LOOKBACK_DAYS_DEFAULT,
) -> FeatureSet:
    if target_time.tzinfo is None:
        target_time = target_time.replace(tzinfo=timezone.utc)
    local_time = target_time.astimezone(SWEDEN_TZ)

    parsed_times = rolling.parsed_times if rolling is not None else _parse_times(weather.times)
    total = len(weather.times) or 1
    missing = sum(1 for v in weather.temperature_2m if v is None)
    weather_missing_fraction = missing / total

    if rolling is not None:
        idx = _nearest_index(parsed_times, target_time) if parsed_times else None
    else:
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

    # Wind history/trend (investigation items 1/4/5 -- see
    # docs/wind-calm-investigation.md): plain index lookups into
    # weather.wind_speed_10m around `idx`, independent of the rolling/
    # non-rolling branch below (idx is already resolved either way at this
    # point) since these only ever need a handful of nearby hourly points,
    # not a full-series cumulative sum.
    def _wind_at(offset: int) -> float | None:
        if idx is None:
            return None
        i = idx + offset
        if i < 0 or i >= len(weather.wind_speed_10m):
            return None
        return weather.wind_speed_10m[i]

    wind_1h_ago = _wind_at(-1)
    wind_3h_ago = _wind_at(-3)
    wind_change_1h = (
        round(current_wind - wind_1h_ago, 3) if current_wind is not None and wind_1h_ago is not None else None
    )
    wind_change_3h = (
        round(current_wind - wind_3h_ago, 3) if current_wind is not None and wind_3h_ago is not None else None
    )
    wind_3h_window = [_wind_at(o) for o in (-2, -1, 0)]
    wind_3h_window_valid = [v for v in wind_3h_window if v is not None]
    wind_min_3h = round(min(wind_3h_window_valid), 3) if wind_3h_window_valid else None
    calm_lookback = [_wind_at(-o) for o in range(CALM_STREAK_LOOKBACK_HOURS - 1, -1, -1)]
    calm_hours_streak = _calm_streak(calm_lookback, calm_threshold_ms)

    wind_speed_effective_ms = compute_effective_wind(
        current_wind,
        static.forest_fraction,
        static.urban_fraction,
        static.slope_deg,
        static.coastal_exposure,
        wind_shelter_params,
    )

    total_len = len(parsed_times)

    if rolling is not None and idx is not None:
        day_temps = weather.temperature_2m[max(0, idx - 23) : idx + 1]
        daily_min = min([v for v in day_temps if v is not None], default=None)
        daily_max = max([v for v in day_temps if v is not None], default=None)

        mean_3d = _range_mean(rolling.temp_cumsum, rolling.temp_count_cumsum, idx, 72, total_len)
        mean_7d = _range_mean(rolling.temp_cumsum, rolling.temp_count_cumsum, idx, 168, total_len)
        mean_14d = _range_mean(rolling.temp_cumsum, rolling.temp_count_cumsum, idx, 336, total_len)

        growing_degree_days = _range_sum(rolling.gdd_cumsum, idx, 336, total_len) / 24.0

        def gdd_sum(hours_back: int) -> float:
            return round(_range_sum(rolling.gdd_cumsum, idx, hours_back, total_len) / 24.0, 2)

        gdd_3d = gdd_sum(24 * 3)
        gdd_7d = gdd_sum(24 * 7)
        gdd_21d = gdd_sum(24 * 21)

        night_start = max(0, idx - 23)
        night_temps = [
            v
            for t, v in zip(parsed_times[night_start : idx + 1], weather.temperature_2m[night_start : idx + 1])
            if v is not None and (t.astimezone(SWEDEN_TZ).hour >= 22 or t.astimezone(SWEDEN_TZ).hour <= 5)
        ]
        warm_night = bool(night_temps) and min(night_temps) >= WARM_NIGHT_THRESHOLD_C
        freezing_recently = daily_min is not None and daily_min <= FREEZING_THRESHOLD_C

        def rain_sum(hours_back: int) -> float:
            return round(_range_sum(rolling.precip_cumsum, idx, hours_back, total_len), 2)

        precip_24h = rain_sum(24)
        precip_3d = rain_sum(24 * 3)
        precip_7d = rain_sum(24 * 7)
        precip_14d = rain_sum(24 * 14)
        precip_21d = rain_sum(24 * 21)

        days_since_meaningful_rain = 21
        for days_back in range(0, 22):
            day_end_idx = idx - days_back * 24
            if day_end_idx < 0:
                break
            day_sum = _range_sum(rolling.precip_cumsum, day_end_idx, 24, total_len)
            if day_sum >= MEANINGFUL_RAIN_MM:
                days_since_meaningful_rain = days_back
                break

        heavy_rain_recent = precip_24h >= HEAVY_RAIN_MM_PER_DAY
        seasonal_norm_mm = 2.0 * 14
        rainfall_anomaly = round((precip_14d - seasonal_norm_mm) / seasonal_norm_mm, 3) if seasonal_norm_mm else 0.0

        soil_7d_mean = _range_mean(rolling.soil_cumsum, rolling.soil_count_cumsum, idx, 168, total_len)
        soil_older_mean = _range_mean(rolling.soil_cumsum, rolling.soil_count_cumsum, idx - 84, 84, total_len)
        soil_recent_mean = _range_mean(rolling.soil_cumsum, rolling.soil_count_cumsum, idx, 84, total_len)
        soil_is_fallback = all(v is None for v in weather.soil_moisture)

        if soil_is_fallback:
            fallback_index = min(1.0, max(0.0, 0.1 + precip_14d / 60.0 - (mean_7d or 10) / 200.0))
            current_soil = fallback_index
            soil_7d_mean = fallback_index
            soil_trend = 0.0
        else:
            soil_trend = round((soil_recent_mean or 0) - (soil_older_mean or soil_recent_mean or 0), 4) if soil_recent_mean is not None else 0.0

        wet_ground = (current_soil or 0) >= 0.30 or precip_3d >= 10

        window_start = max(0, idx - 24)
        window_end = min(total_len, idx + 25)
        local_times = parsed_times[window_start:window_end]
        local_wind = weather.wind_speed_10m[window_start:window_end]
        local_humidity = weather.relative_humidity_2m[window_start:window_end]

        evening_idx_local = [i for i, t in enumerate(local_times) if t.date() == target_time.date() and 18 <= t.hour <= 21]
        evening_wind = _mean([local_wind[i] for i in evening_idx_local]) if evening_idx_local else current_wind
        evening_humidity = _mean([local_humidity[i] for i in evening_idx_local]) if evening_idx_local else current_humidity

        daily_humidity_vals = weather.relative_humidity_2m[max(0, idx - 23) : idx + 1]
        humidity_daily_mean = _mean(daily_humidity_vals)

        forecast_target = target_time + timedelta(hours=6)
        forecast_wind_idx = _nearest_index(parsed_times, forecast_target) if parsed_times else None
        wind_forecast = weather.wind_speed_10m[forecast_wind_idx] if forecast_wind_idx is not None else current_wind
    else:
        day_temps = _window(parsed_times, weather.temperature_2m, target_time, 24)
        daily_min = min([v for v in day_temps if v is not None], default=None)
        daily_max = max([v for v in day_temps if v is not None], default=None)

        mean_3d = _mean(_window(parsed_times, weather.temperature_2m, target_time, 72))
        mean_7d = _mean(_window(parsed_times, weather.temperature_2m, target_time, 168))
        mean_14d = _mean(_window(parsed_times, weather.temperature_2m, target_time, 336))

        gdd_window = _window(parsed_times, weather.temperature_2m, target_time, 336)
        gdd_valid = [v for v in gdd_window if v is not None]
        growing_degree_days = sum(max(0.0, v - development_base_temperature_c) for v in gdd_valid) / 24.0

        def gdd_sum(hours_back: int) -> float:
            vals = _window(parsed_times, weather.temperature_2m, target_time, hours_back)
            return round(sum(max(0.0, v - development_base_temperature_c) for v in vals if v is not None) / 24.0, 2)

        gdd_3d = gdd_sum(24 * 3)
        gdd_7d = gdd_sum(24 * 7)
        gdd_21d = gdd_sum(24 * 21)

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
            window_start_t = target_time - timedelta(days=days_back + 1)
            window_end_t = target_time - timedelta(days=days_back)
            day_vals = [
                v for t, v in zip(parsed_times, weather.precipitation)
                if v is not None and window_start_t <= t <= window_end_t
            ]
            if sum(day_vals) >= MEANINGFUL_RAIN_MM:
                days_since_meaningful_rain = days_back
                break
        else:
            days_since_meaningful_rain = 21

        heavy_rain_recent = precip_24h >= HEAVY_RAIN_MM_PER_DAY
        seasonal_norm_mm = 2.0 * 14
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
            fallback_index = min(1.0, max(0.0, 0.1 + precip_14d / 60.0 - (mean_7d or 10) / 200.0))
            current_soil = fallback_index
            soil_7d_mean = fallback_index
            soil_trend = 0.0
        else:
            soil_trend = round((soil_recent_mean or 0) - (soil_older_mean or soil_recent_mean or 0), 4) if soil_recent_mean is not None else 0.0

        wet_ground = (current_soil or 0) >= 0.30 or precip_3d >= 10

        evening_times_idx = [
            i for i, t in enumerate(parsed_times)
            if t.astimezone(SWEDEN_TZ).date() == local_time.date() and 18 <= t.astimezone(SWEDEN_TZ).hour <= 21
        ]
        evening_wind = _mean([weather.wind_speed_10m[i] for i in evening_times_idx]) if evening_times_idx else current_wind
        evening_humidity = _mean([weather.relative_humidity_2m[i] for i in evening_times_idx]) if evening_times_idx else current_humidity

        daily_humidity_vals = _window(parsed_times, weather.relative_humidity_2m, target_time, 24)
        humidity_daily_mean = _mean(daily_humidity_vals)

        forecast_wind_idx = min(range(len(parsed_times)), key=lambda i: abs((parsed_times[i] - (target_time + timedelta(hours=6))).total_seconds())) if parsed_times else None
        wind_forecast = weather.wind_speed_10m[forecast_wind_idx] if forecast_wind_idx is not None else current_wind

    day_of_year = local_time.timetuple().tm_yday
    hours = daylight_hours(weather.latitude, day_of_year)
    seasonal = seasonal_suitability_curve(day_of_year, weather.latitude)

    solar = compute_solar_times(weather.latitude, weather.longitude, local_time.date())

    def _local_decimal_hour(dt: datetime | None) -> float | None:
        if dt is None:
            return None
        local_dt = dt.astimezone(SWEDEN_TZ)
        return local_dt.hour + local_dt.minute / 60.0

    sunrise_hour_local = _local_decimal_hour(solar.sunrise_utc)
    sunset_hour_local = _local_decimal_hour(solar.sunset_utc)

    standing_water_persistence = _standing_water_persistence(
        precipitation_3d_mm=precip_3d,
        precipitation_7d_mm=precip_7d,
        precipitation_14d_mm=precip_14d,
        slope_deg=static.slope_deg,
        wetland_fraction=static.wetland_fraction,
        water_body_density=static.water_body_density,
    )

    # Rainfall-to-population emergence lag (see _emergence_potential
    # docstring): buckets are derived from the already-computed cumulative
    # precip_Xd_mm sums by subtraction, and from gdd_Xd sums the same way,
    # anchored at each bucket's outer day boundary.
    site_persistence = _site_persistence_factor(static.slope_deg, static.wetland_fraction, static.water_body_density)
    emergence_potential = _emergence_potential(
        rain_0_2d_mm=precip_3d,
        rain_3_6d_mm=max(0.0, precip_7d - precip_3d),
        rain_7_14d_mm=max(0.0, precip_14d - precip_7d),
        rain_15_21d_mm=max(0.0, precip_21d - precip_14d),
        gdd_since_0_2d=gdd_3d,
        gdd_since_3_6d=gdd_7d,
        gdd_since_7_14d=growing_degree_days,
        gdd_since_15_21d=gdd_21d,
        site_persistence=site_persistence,
    )

    # Persistent mosquito pressure (Phase 6/7) -- see module section header.
    # Requires `rolling` for the per-day cumsum lookups the daily series
    # needs; the no-`rolling` direct-call path (module docstring: "keeps
    # the original, simpler per-call behaviour") falls back to a same-
    # instant approximation with no decay, which is fine for the few
    # direct-call test paths that don't pass `rolling` but would be far too
    # slow/duplicative to implement as a second full O(days) computation.
    habitat_capacity_fraction = clamp(static.habitat_capacity / 100.0, 0.0, 1.0)
    if rolling is not None and idx is not None:
        rain_series = _daily_rain_emergence_series(rolling, idx, total_len, pressure_lookback_days)
        snow_series, used_real_snow = _snowmelt_daily_series(
            weather, rolling, idx, total_len, local_time.date(), weather.latitude, pressure_lookback_days
        )
        combined_series = [
            clamp(r + s, 0.0, 1.0)
            for r, s in itertools.zip_longest(rain_series, snow_series, fillvalue=0.0)
        ]
        mosquito_pressure_fraction = _mosquito_pressure_fraction(
            combined_series, habitat_capacity_fraction, pressure_survival_daily
        )
        pressure_used_real_snow_data = used_real_snow
    else:
        mosquito_pressure_fraction = clamp(habitat_capacity_fraction * emergence_potential, 0.0, 1.0)
        pressure_used_real_snow_data = False

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
        standing_water_persistence=standing_water_persistence,
        emergence_potential=emergence_potential,
        wind_speed_current_ms=current_wind,
        wind_speed_forecast_ms=wind_forecast,
        wind_gusts_ms=current_gusts,
        evening_wind_ms=evening_wind,
        wind_speed_1h_ago_ms=wind_1h_ago,
        wind_speed_3h_ago_ms=wind_3h_ago,
        wind_change_1h_ms=wind_change_1h,
        wind_change_3h_ms=wind_change_3h,
        wind_min_3h_ms=wind_min_3h,
        calm_hours_streak=calm_hours_streak,
        wind_speed_effective_ms=wind_speed_effective_ms,
        humidity_current_pct=current_humidity,
        humidity_daily_mean_pct=humidity_daily_mean,
        humidity_evening_pct=evening_humidity,
        day_of_year=day_of_year,
        latitude=weather.latitude,
        daylight_hours=hours,
        hour_of_day=local_time.hour,
        daypart=_daypart(local_time.hour),
        seasonal_suitability=round(seasonal, 4),
        sunrise_hour_local=sunrise_hour_local,
        sunset_hour_local=sunset_hour_local,
        is_polar_day=solar.is_polar_day,
        is_polar_night=solar.is_polar_night,
        forest_fraction=static.forest_fraction,
        wetland_fraction=static.wetland_fraction,
        urban_fraction=static.urban_fraction,
        distance_to_water_km=static.distance_to_water_km,
        elevation_m=static.elevation_m,
        slope_deg=static.slope_deg,
        coastal_exposure=static.coastal_exposure,
        water_body_density=static.water_body_density,
        habitat_capacity=static.habitat_capacity,
        mosquito_pressure=round(mosquito_pressure_fraction * 100.0, 3),
        pressure_used_real_snow_data=pressure_used_real_snow_data,
        weather_missing_fraction=round(weather_missing_fraction, 4),
        used_synthetic_weather=weather.used_fallback,
    )
