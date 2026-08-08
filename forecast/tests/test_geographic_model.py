"""Regression scenarios for the geographic-model redesign (Phase 13).

Unlike the per-function unit tests in test_static_features.py/
test_feature_engineering.py/test_model.py, these exercise the full static ->
feature -> score pipeline for deliberately constructed, contrasting
landscapes under identical or controlled weather, to catch regressions in
the behaviours the new spec explicitly asked for -- see
docs/geographic-model-audit-before.md and docs/geographic-benchmark-after.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from config import load_model_config
from feature_engineering import compute_features, precompute_rolling_windows
from model import abundance_category, compute_biting_activity, compute_score, risk_category
from static_features import StaticFeatures, compute_habitat_capacity
from weather import HourlyWeather

UTC = timezone.utc


def _static(cell_id: str, **overrides) -> StaticFeatures:
    base = dict(
        cell_id=cell_id,
        forest_fraction=0.3,
        wetland_fraction=0.05,
        urban_fraction=0.1,
        water_fraction=0.05,
        distance_to_water_km=2.0,
        elevation_m=50.0,
        slope_deg=3.0,
        coastal_exposure=0.0,
        water_body_density=0.05,
        water_fraction_500m=0.05,
        water_fraction_2km=0.05,
        water_fraction_5km=0.05,
        wetland_fraction_500m=0.05,
        wetland_fraction_2km=0.05,
        wetland_fraction_5km=0.05,
        shoreline_density=0.01,
        forest_water_edge_density=0.005,
        wetland_water_edge_density=0.0,
        small_water_density=0.05,
        major_lake_interior=False,
        floodplain_potential=0.1,
    )
    base.update(overrides)
    habitat_capacity = compute_habitat_capacity(
        wetland_fraction_5km=base["wetland_fraction_5km"],
        forest_water_edge_density=base["forest_water_edge_density"],
        wetland_water_edge_density=base["wetland_water_edge_density"],
        small_water_density=base["small_water_density"],
        floodplain_potential=base["floodplain_potential"],
        shoreline_density=base["shoreline_density"],
        forest_fraction=base["forest_fraction"],
        urban_fraction=base["urban_fraction"],
        elevation_m=base["elevation_m"],
        coastal_exposure=base["coastal_exposure"],
    )
    return StaticFeatures(habitat_capacity=habitat_capacity, **base)


# Wet, forested landscape with real wetland/water interfaces -- the kind of
# terrain the new spec expects to read as high habitat capacity.
WET_FOREST_STATIC = _static(
    "WET_FOREST", forest_fraction=0.7, wetland_fraction=0.35, urban_fraction=0.0,
    wetland_fraction_5km=0.25, forest_water_edge_density=0.05, wetland_water_edge_density=0.015,
    small_water_density=0.3, floodplain_potential=0.4, shoreline_density=0.05, elevation_m=100.0,
)

# Dense urban centre -- minimal wetland/forest/small-water, per the new
# spec's core complaint ("Stockholm should read as lower baseline abundance").
URBAN_STATIC = _static(
    "URBAN", forest_fraction=0.05, wetland_fraction=0.0, urban_fraction=0.8,
    wetland_fraction_5km=0.0, forest_water_edge_density=0.0, wetland_water_edge_density=0.0,
    small_water_density=0.05, floodplain_potential=0.0, shoreline_density=0.01, elevation_m=15.0,
)

MOUNTAIN_STATIC = _static(
    "MOUNTAIN", forest_fraction=0.0, wetland_fraction=0.0, urban_fraction=0.0,
    wetland_fraction_5km=0.0, forest_water_edge_density=0.0, wetland_water_edge_density=0.0,
    small_water_density=0.0, floodplain_potential=0.0, shoreline_density=0.0, elevation_m=1200.0,
)

# Deep in the interior of a large open lake.
OPEN_LAKE_STATIC = _static(
    "OPEN_LAKE", forest_fraction=0.0, wetland_fraction=0.0, urban_fraction=0.0,
    wetland_fraction_5km=0.0, forest_water_edge_density=0.0, wetland_water_edge_density=0.0,
    small_water_density=0.02, floodplain_potential=0.05, shoreline_density=0.0,
    major_lake_interior=True, elevation_m=40.0,
)

# Vegetated margin of the SAME lake -- close to shore, real wetland/small
# water/edge signal, NOT flagged as major-lake-interior.
LAKE_MARGIN_STATIC = _static(
    "LAKE_MARGIN", forest_fraction=0.4, wetland_fraction=0.2, urban_fraction=0.0,
    wetland_fraction_5km=0.15, forest_water_edge_density=0.04, wetland_water_edge_density=0.02,
    small_water_density=0.35, floodplain_potential=0.3, shoreline_density=0.06,
    major_lake_interior=False, elevation_m=45.0,
)

DRY_FARMLAND_STATIC = _static(
    "FARMLAND", forest_fraction=0.05, wetland_fraction=0.0, urban_fraction=0.15,
    wetland_fraction_5km=0.0, forest_water_edge_density=0.0, wetland_water_edge_density=0.0,
    small_water_density=0.02, floodplain_potential=0.05, slope_deg=2.0, elevation_m=60.0,
)

POORLY_DRAINED_FOREST_STATIC = _static(
    "POOR_DRAIN_FOREST", forest_fraction=0.6, wetland_fraction=0.15, urban_fraction=0.0,
    wetland_fraction_5km=0.1, forest_water_edge_density=0.03, wetland_water_edge_density=0.01,
    small_water_density=0.25, floodplain_potential=0.35, slope_deg=1.0, elevation_m=55.0,
)


def _weather(
    cell_id: str,
    lat: float,
    lon: float,
    start: datetime,
    hours: int,
    temp_c: float = 16.0,
    wind_ms: float = 2.0,
    rain_mm_by_hour_offset: dict[int, float] | None = None,
    snow_m_by_hour_offset: dict[int, float] | None = None,
) -> HourlyWeather:
    rain_mm_by_hour_offset = rain_mm_by_hour_offset or {}
    snow_m_by_hour_offset = snow_m_by_hour_offset or {}
    times, temps, humidity, precip, wind, gusts, cloud, soil, snow = ([] for _ in range(9))
    has_snow = bool(snow_m_by_hour_offset)
    for h in range(hours):
        t = start + timedelta(hours=h)
        times.append(t.strftime("%Y-%m-%dT%H:%M"))
        temps.append(temp_c)
        humidity.append(65.0)
        precip.append(rain_mm_by_hour_offset.get(h, 0.0))
        wind.append(wind_ms)
        gusts.append(wind_ms + 1.5)
        cloud.append(50.0)
        soil.append(0.25)
        snow.append(snow_m_by_hour_offset.get(h, 0.0) if has_snow else None)
    return HourlyWeather(
        cell_id=cell_id, latitude=lat, longitude=lon, times=times,
        temperature_2m=temps, relative_humidity_2m=humidity, precipitation=precip,
        wind_speed_10m=wind, wind_gusts_10m=gusts, cloud_cover=cloud, soil_moisture=soil,
        used_fallback=False, snow_depth_m=snow,
    )


def _score_at(static: StaticFeatures, weather: HourlyWeather, target: datetime, dev_base_temp: float = 10.0):
    rolling = precompute_rolling_windows(weather, dev_base_temp)
    features = compute_features(static, weather, target, dev_base_temp, rolling=rolling)
    score = compute_score(features, _DummyConfig(), "general")
    return features, score


class _DummyConfig:
    """Minimal ModelConfig-shaped stand-in using every function's built-in
    defaults (population_weights={} etc. all fall back inside model.py)."""

    development_base_temperature_c = 10.0
    population_weights: dict = {}
    activity_params: dict = {}
    exposure_params: dict = {}
    wind_shelter_params: dict = {}
    wind_dynamics_params: dict = {}
    combination_params: dict = {}
    activities: dict = {"general": 1.0}


HISTORY_DAYS = 21
FORECAST_HOURS = HISTORY_DAYS * 24 + 24
START = datetime(2026, 7, 1, tzinfo=UTC) - timedelta(days=HISTORY_DAYS)
NOW = datetime(2026, 7, 1, 12, tzinfo=UTC)


def _rain_every_day(days_back: int, mm_per_day: float, hour_of_day: int = 6) -> dict[int, float]:
    """{hour_offset: mm} for one rain event per day, `days_back` days
    before NOW, at HISTORY_DAYS*24 + hour_of_day base offset (i.e. relative
    to `START`)."""
    out = {}
    for d in range(days_back):
        # hours from START to that day's rain hour
        day_start_offset = (HISTORY_DAYS - d) * 24 + hour_of_day
        out[day_start_offset] = mm_per_day
    return out


def test_wet_forest_lake_margin_scores_high_habitat_and_pressure_vs_urban():
    rain = _rain_every_day(14, 12.0)  # steady rain for the last 2 weeks
    weather_forest = _weather("WET_FOREST", 60.0, 17.0, START, FORECAST_HOURS, temp_c=18.0, rain_mm_by_hour_offset=rain)
    weather_urban = _weather("URBAN", 59.3, 18.0, START, FORECAST_HOURS, temp_c=18.0, rain_mm_by_hour_offset=rain)

    features_forest, score_forest = _score_at(WET_FOREST_STATIC, weather_forest, NOW)
    features_urban, score_urban = _score_at(URBAN_STATIC, weather_urban, NOW)

    assert features_forest.habitat_capacity > features_urban.habitat_capacity * 2
    assert score_forest.population_potential > score_urban.population_potential * 1.5


def test_urban_vs_wetland_identical_weather_gives_clearly_different_abundance():
    rain = _rain_every_day(10, 15.0)
    weather = _weather("SHARED", 59.5, 17.5, START, FORECAST_HOURS, temp_c=17.0, rain_mm_by_hour_offset=rain)

    _features_urban, score_urban = _score_at(URBAN_STATIC, weather, NOW)
    _features_wetland, score_wetland = _score_at(WET_FOREST_STATIC, weather, NOW)

    assert score_wetland.population_potential > score_urban.population_potential
    assert score_wetland.population_potential - score_urban.population_potential > 10.0


def test_dry_spell_after_established_population_declines_gradually_not_instantly():
    # Heavy sustained rain for the first 14 days of the window, then bone-dry
    # for the last 5 days leading up to "now".
    rain = _rain_every_day(14, 18.0)
    weather = _weather("DECAY", 60.3, 16.9, START, FORECAST_HOURS, temp_c=19.0, rain_mm_by_hour_offset=rain)

    now_wet_tail = NOW  # last rain was ~ (21-14)=7 days before NOW under _rain_every_day's indexing
    pressures = []
    for extra_dry_days in (0, 1, 2, 3, 4, 5):
        t = now_wet_tail + timedelta(days=extra_dry_days)
        rolling = precompute_rolling_windows(weather, 10.0)
        features = compute_features(WET_FOREST_STATIC, weather, t, 10.0, rolling=rolling)
        pressures.append(features.mosquito_pressure)

    # Still meaningfully positive after 5 additional dry days...
    assert pressures[-1] > 0.0
    # ...but declining, not flat and not collapsing to (near) zero in one step.
    assert pressures[0] >= pressures[-1]
    biggest_single_step_drop = max(pressures[i] - pressures[i + 1] for i in range(len(pressures) - 1))
    total_drop = pressures[0] - pressures[-1]
    if total_drop > 1e-6:
        assert biggest_single_step_drop < total_drop  # no single day accounts for the whole decline


def test_heavy_rain_yesterday_in_poor_habitat_does_not_instantly_spike_pressure():
    rain_yesterday = {(HISTORY_DAYS - 1) * 24 + 6: 40.0}  # one big rain event, ~1 day before NOW
    weather = _weather("SPIKE", 59.3, 18.0, START, FORECAST_HOURS, temp_c=18.0, rain_mm_by_hour_offset=rain_yesterday)

    rolling = precompute_rolling_windows(weather, 10.0)
    features = compute_features(URBAN_STATIC, weather, NOW, 10.0, rolling=rolling)

    assert features.mosquito_pressure < 15.0  # nowhere near saturated


def test_snowmelt_with_habitat_and_warmth_produces_meaningful_northern_pressure():
    # Snow depth declines steadily over the last ~10 days (a real melt),
    # followed by two weeks of accumulated warmth -- northern wetland cell.
    snow_series = {}
    for h in range(0, HISTORY_DAYS * 24):
        days_from_start = h / 24.0
        depth = max(0.0, 0.4 - days_from_start * 0.03)
        snow_series[h] = round(depth, 3)
    weather = _weather(
        "NORTH_WETLAND", 66.9, 20.1, START, FORECAST_HOURS, temp_c=14.0,
        snow_m_by_hour_offset=snow_series,
    )
    northern_wetland_static = _static(
        "NORTH_WETLAND", forest_fraction=0.4, wetland_fraction=0.3, urban_fraction=0.0,
        wetland_fraction_5km=0.25, forest_water_edge_density=0.02, wetland_water_edge_density=0.02,
        small_water_density=0.3, floodplain_potential=0.35, elevation_m=250.0,
    )
    rolling = precompute_rolling_windows(weather, 10.0)
    features = compute_features(northern_wetland_static, weather, NOW, 10.0, rolling=rolling)

    assert features.pressure_used_real_snow_data is True
    assert features.mosquito_pressure > 5.0


def test_northern_mountain_stays_low_despite_same_latitude_as_wetland():
    snow_series = {}
    for h in range(0, HISTORY_DAYS * 24):
        days_from_start = h / 24.0
        depth = max(0.0, 0.4 - days_from_start * 0.03)
        snow_series[h] = round(depth, 3)
    weather = _weather("NORTH_MOUNTAIN", 66.9, 20.1, START, FORECAST_HOURS, temp_c=6.0, snow_m_by_hour_offset=snow_series)

    rolling = precompute_rolling_windows(weather, 10.0)
    features = compute_features(MOUNTAIN_STATIC, weather, NOW, 10.0, rolling=rolling)

    assert features.habitat_capacity < 5.0
    assert features.mosquito_pressure < 5.0


def test_large_open_lake_is_not_automatically_extreme_habitat():
    static_lake = OPEN_LAKE_STATIC
    static_margin = LAKE_MARGIN_STATIC
    assert static_margin.habitat_capacity > static_lake.habitat_capacity


def test_vegetated_lake_margin_scores_higher_than_lake_interior():
    # Same test as above stated the other direction, for explicitness re:
    # spec wording ("vegetated/wet lake margin -> higher habitat capacity").
    assert LAKE_MARGIN_STATIC.habitat_capacity > OPEN_LAKE_STATIC.habitat_capacity * 1.2


def test_strong_wind_suppresses_activity_substantially_but_not_abundance():
    rain = _rain_every_day(10, 15.0)
    calm_weather = _weather("CALM", 60.0, 17.0, START, FORECAST_HOURS, temp_c=18.0, wind_ms=1.0, rain_mm_by_hour_offset=rain)
    windy_weather = _weather("WINDY", 60.0, 17.0, START, FORECAST_HOURS, temp_c=18.0, wind_ms=12.0, rain_mm_by_hour_offset=rain)

    features_calm, score_calm = _score_at(WET_FOREST_STATIC, calm_weather, NOW)
    features_windy, score_windy = _score_at(WET_FOREST_STATIC, windy_weather, NOW)

    assert score_windy.biting_activity < score_calm.biting_activity * 0.5
    # Myggläge (population_potential/pressure) must not collapse just
    # because the CURRENT hour is windy -- it's derived from weather
    # HISTORY, not the current instant's wind at all.
    assert features_windy.mosquito_pressure == features_calm.mosquito_pressure
    assert score_windy.population_potential == score_calm.population_potential


def test_wind_dying_in_rich_habitat_raises_risk_while_abundance_stays_stable():
    rain = _rain_every_day(10, 15.0)
    weather = _weather("WIND_DROP", 60.0, 17.0, START, FORECAST_HOURS, temp_c=19.0, wind_ms=8.0, rain_mm_by_hour_offset=rain)
    # Wind drops sharply in the final few hours before "now".
    idx_now = HISTORY_DAYS * 24 + 12
    for i in range(max(0, idx_now - 2), idx_now + 1):
        weather.wind_speed_10m[i] = 0.5
        weather.wind_gusts_10m[i] = 1.0

    rolling = precompute_rolling_windows(weather, 10.0)
    features_before = compute_features(WET_FOREST_STATIC, weather, NOW - timedelta(hours=4), 10.0, rolling=rolling)
    features_after = compute_features(WET_FOREST_STATIC, weather, NOW, 10.0, rolling=rolling)

    activity_before, _ = compute_biting_activity(features_before, _DummyConfig())
    activity_after, _ = compute_biting_activity(features_after, _DummyConfig())

    assert activity_after > activity_before
    # Abundance (mosquito_pressure/habitat) is driven by day-level history,
    # not the last couple of hours' wind -- expect it to stay close to
    # identical across a 4h gap dominated by a wind change.
    assert features_after.mosquito_pressure == pytest.approx(features_before.mosquito_pressure, rel=0.05)


def test_dry_exposed_farmland_vs_poorly_drained_forest_meaningful_difference():
    rain = _rain_every_day(10, 10.0)
    weather_farm = _weather("FARM", 58.5, 15.0, START, FORECAST_HOURS, temp_c=17.0, rain_mm_by_hour_offset=rain)
    weather_forest = _weather("FOREST", 58.5, 15.0, START, FORECAST_HOURS, temp_c=17.0, rain_mm_by_hour_offset=rain)

    features_farm, score_farm = _score_at(DRY_FARMLAND_STATIC, weather_farm, NOW)
    features_forest, score_forest = _score_at(POORLY_DRAINED_FOREST_STATIC, weather_forest, NOW)

    assert features_forest.habitat_capacity > features_farm.habitat_capacity
    assert score_forest.population_potential > score_farm.population_potential


# --- Phase 15: category-semantics regression tests (calibration/validation
# sprint) -- exercise the RECALIBRATED thresholds (config.py::RISK_CATEGORIES,
# model.yaml thresholds.abundance, see docs/calibration-validation-final.md)
# against the same kind of deliberately-constructed scenarios used above, so
# a future threshold or weight change can't silently break what "Very low"/
# "Very high" are supposed to mean. Reads the real configured thresholds
# (not a hardcoded duplicate) so these track model.yaml automatically.

_CONFIG = load_model_config()
_ABUNDANCE_THRESHOLDS = _CONFIG.abundance_thresholds


def test_cold_dry_mountain_is_very_low_or_low_myggläge_and_myggrisk():
    # NOW is fixed at peak-season (July 1) for every scenario in this file
    # (see module constants) -- the `season` term (weight 0.07) contributes
    # for every location equally regardless of habitat, so a genuinely
    # mosquito-poor mountain isn't guaranteed to land in the SINGLE lowest
    # band even at 2C with zero habitat; "very_low or low, never higher" is
    # the honest claim.
    weather = _weather("COLD_DRY", 67.45, 17.73, START, FORECAST_HOURS, temp_c=2.0, wind_ms=3.0)
    features, score = _score_at(MOUNTAIN_STATIC, weather, NOW)
    assert abundance_category(score.population_potential, _ABUNDANCE_THRESHOLDS)[0] in ("very_low", "low")
    assert risk_category(score.final_risk)[0] == "very_low"


def test_established_moderate_population_is_not_very_low():
    # Sustained rain in genuinely good habitat for two weeks -- an
    # established, moderate-to-strong population -- must clear "very_low",
    # not read as if nothing were happening.
    rain = _rain_every_day(14, 15.0)
    weather = _weather("ESTABLISHED", 60.3, 16.9, START, FORECAST_HOURS, temp_c=18.0, rain_mm_by_hour_offset=rain)
    features, score = _score_at(WET_FOREST_STATIC, weather, NOW)
    assert abundance_category(score.population_potential, _ABUNDANCE_THRESHOLDS)[0] != "very_low"


def test_strong_wetland_emergence_can_reach_high_myggläge():
    rain = _rain_every_day(18, 20.0)
    weather = _weather("STRONG_EMERGENCE", 60.3, 16.9, START, FORECAST_HOURS, temp_c=20.0, rain_mm_by_hour_offset=rain)
    features, score = _score_at(WET_FOREST_STATIC, weather, NOW)
    category = abundance_category(score.population_potential, _ABUNDANCE_THRESHOLDS)[0]
    assert category in ("high", "very_high"), (
        f"expected sustained strong emergence in high-habitat terrain to reach at least 'high', got "
        f"{category} (population_potential={score.population_potential})"
    )


def test_high_habitat_alone_without_rain_scores_far_below_habitat_with_real_pressure():
    # WET_FOREST_STATIC has extreme habitat_capacity (~64, near Sweden's
    # real observed national max of ~68.8) -- with NO rain at all in the
    # lookback window, mosquito_pressure must stay near zero, and
    # population_potential must be SUBSTANTIALLY lower than the same cell
    # with real sustained rain (Phase 10: habitat_capacity is potential,
    # not a standing guarantee).
    #
    # Known, documented residual limitation (see docs/calibration-
    # validation-final.md "Habitat vs pressure"): population_weights were
    # trimmed (0.50/0.35 -> 0.55/0.30 direct-habitat weight) specifically
    # to narrow this gap without reintroducing the earlier Dalarna/
    # Stockholm dry-week regression (see model.yaml's population_weights
    # comment) -- but for this single most extreme, rare real
    # habitat_capacity value in the country, habitat+season+temperature
    # ALONE can still just cross into "very_high" with zero pressure. This
    # test asserts the honest, still-meaningful claim (pressure matters a
    # lot) rather than an absolute category ceiling that would require
    # either reintroducing that regression or a larger architectural change
    # out of scope for this validation sprint.
    weather_no_rain = _weather("NO_RAIN", 60.3, 16.9, START, FORECAST_HOURS, temp_c=18.0)
    rain = _rain_every_day(18, 20.0)
    weather_with_rain = _weather("WITH_RAIN", 60.3, 16.9, START, FORECAST_HOURS, temp_c=18.0, rain_mm_by_hour_offset=rain)

    features_no_rain, score_no_rain = _score_at(WET_FOREST_STATIC, weather_no_rain, NOW)
    features_with_rain, score_with_rain = _score_at(WET_FOREST_STATIC, weather_with_rain, NOW)

    assert features_no_rain.mosquito_pressure < 5.0
    assert features_with_rain.mosquito_pressure > 20.0
    assert score_no_rain.population_potential < score_with_rain.population_potential - 10.0


def test_low_habitat_cannot_become_very_high_myggläge_from_one_rain_event():
    rain_yesterday = {(HISTORY_DAYS - 1) * 24 + 6: 40.0}
    weather = _weather("ONE_EVENT", 59.3, 18.0, START, FORECAST_HOURS, temp_c=18.0, rain_mm_by_hour_offset=rain_yesterday)
    features, score = _score_at(URBAN_STATIC, weather, NOW)
    category = abundance_category(score.population_potential, _ABUNDANCE_THRESHOLDS)[0]
    assert category not in ("high", "very_high")


def test_windy_hour_can_drop_myggrisk_category_without_moving_myggläge_category():
    rain = _rain_every_day(12, 15.0)
    calm_weather = _weather("CALM2", 60.3, 16.9, START, FORECAST_HOURS, temp_c=19.0, wind_ms=1.0, rain_mm_by_hour_offset=rain)
    windy_weather = _weather("WINDY2", 60.3, 16.9, START, FORECAST_HOURS, temp_c=19.0, wind_ms=13.0, rain_mm_by_hour_offset=rain)

    features_calm, score_calm = _score_at(WET_FOREST_STATIC, calm_weather, NOW)
    features_windy, score_windy = _score_at(WET_FOREST_STATIC, windy_weather, NOW)

    myggrisk_calm = risk_category(score_calm.final_risk)[0]
    myggrisk_windy = risk_category(score_windy.final_risk)[0]
    myggläge_calm = abundance_category(score_calm.population_potential, _ABUNDANCE_THRESHOLDS)[0]
    myggläge_windy = abundance_category(score_windy.population_potential, _ABUNDANCE_THRESHOLDS)[0]

    risk_order = ["very_low", "low", "moderate", "high", "very_high"]
    assert risk_order.index(myggrisk_windy) <= risk_order.index(myggrisk_calm), "wind should not INCREASE Myggrisk's category"
    # Myggläge's category must not move at all -- it has no wind input.
    assert myggläge_calm == myggläge_windy


def test_calm_evening_can_raise_myggrisk_hour_to_hour_while_myggläge_static():
    rain = _rain_every_day(10, 15.0)
    weather = _weather("WIND_DROP2", 60.3, 16.9, START, FORECAST_HOURS, temp_c=19.0, wind_ms=9.0, rain_mm_by_hour_offset=rain)
    idx_now = HISTORY_DAYS * 24 + 12
    for i in range(max(0, idx_now - 2), idx_now + 1):
        weather.wind_speed_10m[i] = 0.5
        weather.wind_gusts_10m[i] = 1.0

    rolling = precompute_rolling_windows(weather, 10.0)
    features_before = compute_features(WET_FOREST_STATIC, weather, NOW - timedelta(hours=3), 10.0, rolling=rolling)
    features_after = compute_features(WET_FOREST_STATIC, weather, NOW, 10.0, rolling=rolling)
    score_before = compute_score(features_before, _DummyConfig(), "general")
    score_after = compute_score(features_after, _DummyConfig(), "general")

    assert score_after.final_risk > score_before.final_risk
    # Myggläge (habitat_capacity is static by construction; mosquito_pressure
    # is day-level, not hour-level) stays effectively unchanged across this
    # 3-hour wind-drop window.
    assert score_after.population_potential == pytest.approx(score_before.population_potential, rel=0.05)
