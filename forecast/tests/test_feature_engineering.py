from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from feature_engineering import (
    GDD_TO_ADULT_C,
    DEFAULT_CALM_THRESHOLD_MS,
    _calm_streak,
    _development_progress,
    _emergence_potential,
    _site_persistence_factor,
    compute_effective_wind,
    compute_features,
)
from static_features import StaticFeatures
from weather import HourlyWeather


def test_development_progress_is_near_zero_immediately_after_a_rain_event():
    assert _development_progress(0.0) == 0.0
    assert _development_progress(5.0) < 0.15


def test_development_progress_reaches_full_after_enough_accumulated_warmth():
    assert _development_progress(GDD_TO_ADULT_C) == 1.0
    assert _development_progress(GDD_TO_ADULT_C * 2) == 1.0  # clamped, not >1


def test_development_progress_is_monotonic_with_accumulated_gdd():
    values = [_development_progress(g) for g in (0, 10, 20, 30, 40, 50, 60, 70)]
    assert values == sorted(values)


def test_emergence_heavy_rain_yesterday_alone_does_not_spike_immediately():
    """The exact reported problem: rain that fell 0-2 days ago has had
    almost no time (and thus almost no accumulated warmth) to develop into
    adults, regardless of how much rain fell."""
    heavy_rain_yesterday_only = _emergence_potential(
        rain_0_2d_mm=40.0, rain_3_6d_mm=0.0, rain_7_14d_mm=0.0, rain_15_21d_mm=0.0,
        gdd_since_0_2d=5.0,  # only ~1-2 days of modest warmth so far
        gdd_since_3_6d=0.0, gdd_since_7_14d=0.0, gdd_since_15_21d=0.0,
        site_persistence=0.8,
    )
    assert heavy_rain_yesterday_only < 0.15


def test_emergence_warm_rain_7_to_14_days_ago_raises_potential():
    """Rain old enough, in warm-enough weather, to have actually developed
    into adults should read as real emergence potential -- the case the
    old bell-curve-on-precipitation_14d_mm term treated identically to
    rain from yesterday."""
    old_rain_fully_developed = _emergence_potential(
        rain_0_2d_mm=0.0, rain_3_6d_mm=0.0, rain_7_14d_mm=25.0, rain_15_21d_mm=0.0,
        gdd_since_0_2d=0.0, gdd_since_3_6d=0.0,
        gdd_since_7_14d=70.0,  # comfortably past GDD_TO_ADULT_C
        gdd_since_15_21d=0.0,
        site_persistence=0.8,
    )
    no_rain_at_all = _emergence_potential(0, 0, 0, 0, 0, 0, 0, 0, site_persistence=0.8)
    assert old_rain_fully_developed > 0.15
    assert old_rain_fully_developed > no_rain_at_all


def test_emergence_cold_weather_delays_development_relative_to_warm():
    """Same rain, same bucket, but far less accumulated warmth since (cold
    northern weather) -- development, and therefore emergence potential,
    should be measurably lower."""
    warm = _emergence_potential(
        rain_0_2d_mm=0, rain_3_6d_mm=0, rain_7_14d_mm=25.0, rain_15_21d_mm=0,
        gdd_since_0_2d=0, gdd_since_3_6d=0, gdd_since_7_14d=70.0, gdd_since_15_21d=0,
        site_persistence=0.8,
    )
    cold = _emergence_potential(
        rain_0_2d_mm=0, rain_3_6d_mm=0, rain_7_14d_mm=25.0, rain_15_21d_mm=0,
        gdd_since_0_2d=0, gdd_since_3_6d=0, gdd_since_7_14d=8.0, gdd_since_15_21d=0,
        site_persistence=0.8,
    )
    assert cold < warm


def test_emergence_prolonged_dry_spell_reduces_potential_to_zero():
    dry = _emergence_potential(
        rain_0_2d_mm=0, rain_3_6d_mm=0, rain_7_14d_mm=0, rain_15_21d_mm=0,
        gdd_since_0_2d=40, gdd_since_3_6d=40, gdd_since_7_14d=80, gdd_since_15_21d=100,
        site_persistence=0.8,
    )
    assert dry == 0.0


def test_emergence_potential_is_bounded_0_to_1():
    saturated = _emergence_potential(
        rain_0_2d_mm=999, rain_3_6d_mm=999, rain_7_14d_mm=999, rain_15_21d_mm=999,
        gdd_since_0_2d=999, gdd_since_3_6d=999, gdd_since_7_14d=999, gdd_since_15_21d=999,
        site_persistence=1.0,
    )
    assert 0.0 <= saturated <= 1.0


def test_emergence_potential_scales_with_site_persistence():
    poor_site = _emergence_potential(0, 0, 25.0, 0, 0, 0, 70.0, 0, site_persistence=0.1)
    good_site = _emergence_potential(0, 0, 25.0, 0, 0, 0, 70.0, 0, site_persistence=1.0)
    assert poor_site < good_site


def test_site_persistence_factor_bounded_and_favours_wetland_low_slope():
    flat_wetland = _site_persistence_factor(slope_deg=0.5, wetland_fraction=0.9, water_body_density=0.9)
    steep_dry = _site_persistence_factor(slope_deg=14.0, wetland_fraction=0.0, water_body_density=0.0)
    assert 0.0 <= flat_wetland <= 1.0
    assert 0.0 <= steep_dry <= 1.0
    assert flat_wetland > steep_dry


# --- Wind history / effective wind (docs/wind-calm-investigation.md) ---


def _make_hourly_weather(wind_series: list[float | None], start: datetime, cell_id: str = "SE_WIND_TEST") -> HourlyWeather:
    n = len(wind_series)
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(n)]
    return HourlyWeather(
        cell_id=cell_id,
        latitude=59.33,
        longitude=18.07,
        times=times,
        temperature_2m=[18.0] * n,
        relative_humidity_2m=[70.0] * n,
        precipitation=[0.0] * n,
        wind_speed_10m=wind_series,
        wind_gusts_10m=[v * 1.5 if v is not None else None for v in wind_series],
        cloud_cover=[50.0] * n,
        soil_moisture=[0.25] * n,
    )


def _static(**overrides) -> StaticFeatures:
    base = dict(
        cell_id="SE_WIND_TEST", forest_fraction=0.1, wetland_fraction=0.1, urban_fraction=0.1,
        water_fraction=0.05, distance_to_water_km=2.0, elevation_m=20.0, slope_deg=2.0,
        coastal_exposure=0.1, water_body_density=0.1,
    )
    base.update(overrides)
    return StaticFeatures(**base)


def test_compute_effective_wind_reduces_wind_in_sheltered_forest():
    open_field = compute_effective_wind(10.0, forest_fraction=0.0, urban_fraction=0.0, slope_deg=0.0, coastal_exposure=0.0)
    forest = compute_effective_wind(10.0, forest_fraction=0.9, urban_fraction=0.0, slope_deg=0.0, coastal_exposure=0.0)
    assert forest < open_field


def test_compute_effective_wind_increases_with_coastal_exposure():
    inland = compute_effective_wind(10.0, forest_fraction=0.0, urban_fraction=0.0, slope_deg=0.0, coastal_exposure=0.0)
    coastal = compute_effective_wind(10.0, forest_fraction=0.0, urban_fraction=0.0, slope_deg=0.0, coastal_exposure=1.0)
    assert coastal > inland


def test_compute_effective_wind_is_bounded_regardless_of_extreme_shelter():
    params = {
        "forest_shelter_weight": 5.0, "urban_shelter_weight": 5.0, "slope_shelter_weight": 5.0,
        "slope_reference_deg": 10.0, "coastal_exposure_weight": 5.0, "min_multiplier": 0.55, "max_multiplier": 1.15,
    }
    maximally_sheltered = compute_effective_wind(10.0, 1.0, 1.0, 0.0, 0.0, params)
    maximally_exposed = compute_effective_wind(10.0, 0.0, 0.0, 0.0, 1.0, params)
    assert maximally_sheltered == pytest.approx(10.0 * 0.55)
    assert maximally_exposed == pytest.approx(10.0 * 1.15)


def test_compute_effective_wind_none_when_no_forecast_wind():
    assert compute_effective_wind(None, 0.5, 0.1, 2.0, 0.2) is None


def test_calm_streak_counts_consecutive_calm_hours_ending_now():
    assert _calm_streak([5.0, 5.0, 1.0, 0.5, 0.8], calm_threshold_ms=1.5) == 3
    assert _calm_streak([0.5, 0.5, 0.5], calm_threshold_ms=1.5) == 3
    assert _calm_streak([5.0, 5.0], calm_threshold_ms=1.5) == 0


def test_calm_streak_stops_at_first_missing_hour():
    assert _calm_streak([0.5, None, 0.5, 0.5], calm_threshold_ms=1.5) == 2


def test_compute_features_reports_wind_drop_and_min_and_streak():
    """Directly reproduces the reported pattern's wind shape: steady ~5 m/s
    wind, then a sharp drop to ~1 m/s that holds for a few hours."""
    start = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)
    wind_series = [5.0, 5.2, 4.8, 5.1, 1.0, 0.8, 0.9]  # drop happens at index 4
    weather = _make_hourly_weather(wind_series, start)
    static = _static()

    # Evaluate one hour after the drop (index 5).
    target = start + timedelta(hours=5)
    features = compute_features(static, weather, target, calm_threshold_ms=1.5)

    assert features.wind_speed_current_ms == pytest.approx(0.8)
    assert features.wind_speed_1h_ago_ms == pytest.approx(1.0)
    assert features.wind_speed_3h_ago_ms == pytest.approx(4.8)
    assert features.wind_change_1h_ms == pytest.approx(0.8 - 1.0)
    assert features.wind_change_3h_ms == pytest.approx(0.8 - 4.8)
    assert features.wind_change_3h_ms < -3.0  # a materially large drop
    assert features.wind_min_3h_ms == pytest.approx(0.8)
    assert features.calm_hours_streak == 2  # index 5 and 4 are both <=1.5

    # Before the drop, no calm streak and no material 3h drop yet.
    pre_drop = compute_features(static, weather, start + timedelta(hours=3), calm_threshold_ms=1.5)
    assert pre_drop.calm_hours_streak == 0
    assert pre_drop.wind_change_3h_ms is None or pre_drop.wind_change_3h_ms > -3.0


def test_compute_features_wind_speed_effective_reflects_static_shelter():
    start = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)
    wind_series = [6.0] * 5
    weather = _make_hourly_weather(wind_series, start)
    target = start + timedelta(hours=2)

    sheltered = compute_features(_static(forest_fraction=0.9, urban_fraction=0.0, coastal_exposure=0.0), weather, target)
    exposed = compute_features(_static(forest_fraction=0.0, urban_fraction=0.0, coastal_exposure=1.0), weather, target)

    assert sheltered.wind_speed_effective_ms < sheltered.wind_speed_current_ms
    assert exposed.wind_speed_effective_ms > exposed.wind_speed_current_ms
    assert sheltered.wind_speed_effective_ms < exposed.wind_speed_effective_ms
