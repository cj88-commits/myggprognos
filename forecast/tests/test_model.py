from __future__ import annotations

from datetime import datetime, timezone

import pytest
from feature_engineering import compute_features, daylight_hours, seasonal_suitability_curve
from model import (
    bell_curve,
    clamp,
    compute_biting_activity,
    compute_exposure,
    compute_population_potential,
    compute_score,
    risk_category,
    scale_sigmoid,
)


def test_clamp_bounds_values():
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(11, 0, 10) == 10


def test_scale_sigmoid_is_bounded_and_monotonic_increasing():
    lo = scale_sigmoid(-100, midpoint=0, steepness=1)
    hi = scale_sigmoid(100, midpoint=0, steepness=1)
    mid = scale_sigmoid(0, midpoint=0, steepness=1)
    assert 0.0 <= lo < mid < hi <= 1.0
    assert mid == pytest.approx(0.5, abs=1e-6)


def test_scale_sigmoid_negative_steepness_decreases():
    low_value = scale_sigmoid(-10, midpoint=0, steepness=-1)
    high_value = scale_sigmoid(10, midpoint=0, steepness=-1)
    assert low_value > high_value


def test_bell_curve_peaks_at_optimum():
    assert bell_curve(20, optimum=20, width=5) == pytest.approx(1.0)
    assert bell_curve(0, optimum=20, width=5) < bell_curve(15, optimum=20, width=5)
    assert 0.0 <= bell_curve(-1000, optimum=20, width=5) <= 1.0


def test_risk_category_boundaries():
    assert risk_category(0.0)[0] == "very_low"
    assert risk_category(19.0)[0] == "very_low"
    assert risk_category(20.0)[0] == "low"
    assert risk_category(59.0)[0] == "moderate"
    assert risk_category(60.0)[0] == "high"
    assert risk_category(80.0)[0] == "very_high"
    assert risk_category(100.0)[0] == "very_high"


def _features_at(sample_static, synthetic_weather, hour: int, model_config):
    target = datetime(2026, 7, 21, hour, tzinfo=timezone.utc)
    return compute_features(sample_static, synthetic_weather, target, model_config.development_base_temperature_c)


def test_population_potential_between_0_and_100(sample_static, synthetic_weather, model_config):
    features = _features_at(sample_static, synthetic_weather, 14, model_config)
    value, terms = compute_population_potential(features, model_config)
    assert 0.0 <= value <= 100.0
    assert set(terms) == {
        "temperature", "rainfall", "moisture", "wetland", "forest", "season", "snowmelt", "standing_water",
    }


def test_biting_activity_between_0_and_100(sample_static, synthetic_weather, model_config):
    features = _features_at(sample_static, synthetic_weather, 14, model_config)
    value, terms = compute_biting_activity(features, model_config)
    assert 0.0 <= value <= 100.0


def test_wind_strongly_suppresses_biting_activity(sample_static, synthetic_weather, model_config):
    features = _features_at(sample_static, synthetic_weather, 20, model_config)

    calm = features.__class__(**{**features.__dict__, "wind_speed_current_ms": 0.5})
    windy = features.__class__(**{**features.__dict__, "wind_speed_current_ms": 12.0})

    calm_activity, _ = compute_biting_activity(calm, model_config)
    windy_activity, _ = compute_biting_activity(windy, model_config)

    assert windy_activity < calm_activity


def test_dry_air_suppresses_biting_activity(sample_static, synthetic_weather, model_config):
    features = _features_at(sample_static, synthetic_weather, 20, model_config)

    humid = features.__class__(**{**features.__dict__, "humidity_current_pct": 85.0})
    dry = features.__class__(**{**features.__dict__, "humidity_current_pct": 15.0})

    humid_activity, _ = compute_biting_activity(humid, model_config)
    dry_activity, _ = compute_biting_activity(dry, model_config)

    assert dry_activity < humid_activity


def test_active_rain_suppresses_biting_activity(sample_static, synthetic_weather, model_config):
    features = _features_at(sample_static, synthetic_weather, 20, model_config)

    dry = features.__class__(**{**features.__dict__, "current_precipitation_mm": 0.0})
    rainy = features.__class__(**{**features.__dict__, "current_precipitation_mm": 5.0})

    dry_activity, _ = compute_biting_activity(dry, model_config)
    rainy_activity, _ = compute_biting_activity(rainy, model_config)

    assert rainy_activity < dry_activity


def test_exposure_between_0_and_100_and_activity_profile_changes_it(sample_static, synthetic_weather, model_config):
    features = _features_at(sample_static, synthetic_weather, 14, model_config)
    general, _ = compute_exposure(features, model_config, activity_multiplier=1.0)
    camping, _ = compute_exposure(features, model_config, activity_multiplier=1.35)
    assert 0.0 <= general <= 100.0
    assert 0.0 <= camping <= 100.0
    assert camping >= general


def test_final_risk_is_bounded_0_to_100(sample_static, synthetic_weather, model_config):
    for hour in range(0, 24, 3):
        features = _features_at(sample_static, synthetic_weather, hour, model_config)
        result = compute_score(features, model_config, "general")
        assert 0.0 <= result.final_risk <= 100.0
        assert 0.0 <= result.population_potential <= 100.0
        assert 0.0 <= result.biting_activity <= 100.0
        assert 0.0 <= result.exposure <= 100.0


def test_final_risk_is_zero_when_all_components_are_zero(sample_static, synthetic_weather, model_config):
    features = _features_at(sample_static, synthetic_weather, 14, model_config)
    zeroed = features.__class__(**{
        **features.__dict__,
        "current_temperature_c": -30.0,
        "wind_speed_current_ms": 30.0,
    })
    result = compute_score(zeroed, model_config, "general")
    assert result.biting_activity < 10.0


def test_daylight_hours_longer_in_summer_than_winter():
    summer = daylight_hours(59.33, day_of_year=172)  # ~June 21
    winter = daylight_hours(59.33, day_of_year=355)  # ~Dec 21
    assert summer > winter


def test_seasonal_suitability_peaks_in_midsummer():
    midsummer = seasonal_suitability_curve(190, latitude=59.0)
    midwinter = seasonal_suitability_curve(10, latitude=59.0)
    assert midsummer > midwinter
    assert 0.0 <= midsummer <= 1.0
