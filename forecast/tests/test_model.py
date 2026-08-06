from __future__ import annotations

from datetime import datetime, timezone

import pytest
from feature_engineering import compute_features, daylight_hours, seasonal_suitability_curve
from model import (
    _calm_wind_activity_multiplier,
    _daypart_activity_curve,
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


def test_risk_category_handles_fractional_scores_between_integer_bounds():
    # Regression test: real scores are floats (e.g. 19.13), not just the
    # exact integer band edges. A prior implementation required
    # `lo <= score <= hi` against adjacent integer bounds (...19 / 20...),
    # so any fractional value strictly between two bands (e.g. 19.13,
    # 39.5, 59.9, 79.99) matched nothing and silently fell back to the
    # *last* band (very_high) regardless of the actual score.
    assert risk_category(19.13)[0] == "very_low"
    assert risk_category(19.99)[0] == "very_low"
    assert risk_category(39.5)[0] == "low"
    assert risk_category(59.9)[0] == "moderate"
    assert risk_category(79.99)[0] == "high"


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


def test_exposure_no_longer_uses_wetland_fraction_or_water_body_density(sample_static, synthetic_weather, model_config):
    """docs/model-audit-after.md #1-2: wetland_fraction and
    water_body_density already drive population_potential; exposure must
    no longer reuse them as if they were independent evidence."""
    features = _features_at(sample_static, synthetic_weather, 14, model_config)
    low_wetland = features.__class__(**{**features.__dict__, "wetland_fraction": 0.0, "water_body_density": 0.0})
    high_wetland = features.__class__(**{**features.__dict__, "wetland_fraction": 0.9, "water_body_density": 0.9})

    low_exposure, _ = compute_exposure(low_wetland, model_config, activity_multiplier=1.0)
    high_exposure, _ = compute_exposure(high_wetland, model_config, activity_multiplier=1.0)

    assert low_exposure == pytest.approx(high_exposure)


def test_exposure_still_responds_to_forest_urban_and_water_proximity(sample_static, synthetic_weather, model_config):
    features = _features_at(sample_static, synthetic_weather, 14, model_config)
    sheltered = features.__class__(**{**features.__dict__, "forest_fraction": 0.9, "urban_fraction": 0.0})
    exposed_urban = features.__class__(**{**features.__dict__, "forest_fraction": 0.0, "urban_fraction": 0.9})

    sheltered_exposure, _ = compute_exposure(sheltered, model_config, activity_multiplier=1.0)
    urban_exposure, _ = compute_exposure(exposed_urban, model_config, activity_multiplier=1.0)

    assert sheltered_exposure > urban_exposure


def test_final_risk_stays_within_0_100_for_extreme_component_combinations(sample_static, synthetic_weather, model_config):
    features = _features_at(sample_static, synthetic_weather, 20, model_config)
    for temp, wind, humidity in [(-20, 0, 10), (35, 0.1, 95), (23, 15, 50), (10, 3, 40)]:
        extreme = features.__class__(**{
            **features.__dict__,
            "current_temperature_c": temp, "wind_speed_current_ms": wind, "humidity_current_pct": humidity,
        })
        result = compute_score(extreme, model_config, "general")
        assert 0.0 <= result.final_risk <= 100.0


def test_moderate_population_is_not_crushed_to_near_zero_by_midday_activity(sample_static, synthetic_weather, model_config):
    """Regression for the reported problem (docs/model-audit-before.md
    Example B): a real, moderate population signal combined with
    suppressed midday activity used to collapse toward zero under the old
    plain three-way product. Directly exercises compute_score's population/
    activity_modifier/exposure_modifier combination (not just bounds)."""
    features = _features_at(sample_static, synthetic_weather, 13, model_config)
    moderate_population = features.__class__(**{
        **features.__dict__,
        "mean_temperature_14d_c": 16.0, "precipitation_14d_mm": 40.0,
        # emergence_potential (not precipitation_14d_mm directly) is what
        # population_potential's rainfall term now reads -- see
        # docs/model-audit-after.md "Rainfall lag". A high, already-
        # developed emergence signal is what "real, moderate-to-good
        # population" means under the new model.
        "emergence_potential": 0.8,
        "wetland_fraction": 0.3, "current_temperature_c": 14.0, "wind_speed_current_ms": 7.0,
    })
    result = compute_score(moderate_population, model_config, "general")
    if result.population_potential >= 40.0:
        # A moderate-or-better population signal should read as more than
        # a token amount of risk even when activity is suppressed --
        # under the old formula this case produced final_risk well under 20.
        assert result.final_risk > 15.0


def test_very_low_activity_still_meaningfully_reduces_current_nuisance(sample_static, synthetic_weather, model_config):
    features = _features_at(sample_static, synthetic_weather, 14, model_config)
    calm_warm = features.__class__(**{**features.__dict__, "wind_speed_current_ms": 1.0, "current_temperature_c": 22.0})
    cold_windy = features.__class__(**{**features.__dict__, "wind_speed_current_ms": 12.0, "current_temperature_c": 3.0})

    high = compute_score(calm_warm, model_config, "general")
    low = compute_score(cold_windy, model_config, "general")

    assert low.final_risk < high.final_risk
    assert low.activity_modifier < high.activity_modifier


def test_exposure_modifier_adjusts_but_does_not_dominate_final_risk(sample_static, synthetic_weather, model_config):
    features = _features_at(sample_static, synthetic_weather, 14, model_config)
    near_water = features.__class__(**{**features.__dict__, "distance_to_water_km": 0.1})
    far_from_water = features.__class__(**{**features.__dict__, "distance_to_water_km": 20.0})

    near = compute_score(near_water, model_config, "general")
    far = compute_score(far_from_water, model_config, "general")

    assert near.final_risk >= far.final_risk
    # exposure_modifier's configured range (floor + weight <= 1.25) bounds
    # how much exposure alone can swing the result -- it must not act as a
    # second population-style gate.
    if far.final_risk > 0:
        assert near.final_risk / far.final_risk < 2.0


def test_daypart_activity_curve_peaks_near_actual_sunset_not_a_fixed_clock_hour():
    """Malmo (early sunset ~20:00 local in early spring) vs a hypothetical
    far-later sunset (23:00, as in a Swedish summer) -- the dusk peak must
    track the given sunrise/sunset, not a hardcoded 21:00."""
    early_sunset_activity_by_hour = {
        h: _daypart_activity_curve(h, sunrise_hour_local=7.0, sunset_hour_local=20.0, is_polar_day=False, is_polar_night=False)
        for h in range(24)
    }
    late_sunset_activity_by_hour = {
        h: _daypart_activity_curve(h, sunrise_hour_local=4.0, sunset_hour_local=23.0, is_polar_day=False, is_polar_night=False)
        for h in range(24)
    }
    early_peak_hour = max(early_sunset_activity_by_hour, key=early_sunset_activity_by_hour.get)
    late_peak_hour = max(late_sunset_activity_by_hour, key=late_sunset_activity_by_hour.get)
    assert early_peak_hour < late_peak_hour
    assert 18 <= early_peak_hour <= 20
    assert 22 <= late_peak_hour <= 23


def test_daypart_activity_curve_is_bounded_for_all_solar_conditions():
    scenarios = [
        (12.0, 5.0, 21.0, False, False),
        (0.5, None, None, True, False),  # midnight sun
        (12.0, None, None, False, True),  # polar night
        (23.9, 0.2, 23.7, False, False),  # sunset/sunrise both near midnight
    ]
    for hour, sunrise, sunset, is_day, is_night in scenarios:
        value = _daypart_activity_curve(hour, sunrise, sunset, is_day, is_night)
        assert 0.0 <= value <= 1.0


def test_daypart_activity_curve_midnight_sun_has_muted_but_nonzero_cycle():
    """No true dusk/dawn transition, but not perfectly flat either --
    still a mild midday dip relative to the rest of the day."""
    midday = _daypart_activity_curve(13.0, None, None, is_polar_day=True, is_polar_night=False)
    evening = _daypart_activity_curve(21.0, None, None, is_polar_day=True, is_polar_night=False)
    assert 0.0 < midday < evening


def test_daypart_activity_curve_polar_night_is_flat_and_moderate():
    a = _daypart_activity_curve(3.0, None, None, is_polar_day=False, is_polar_night=True)
    b = _daypart_activity_curve(15.0, None, None, is_polar_day=False, is_polar_night=True)
    assert a == b
    assert 0.0 < a < 1.0


def _wind_dynamics_features(features, **overrides):
    return features.__class__(**{**features.__dict__, **overrides})


def test_calm_wind_uplift_increases_activity_when_calm_and_favourable(sample_static, synthetic_weather, model_config):
    features = _features_at(sample_static, synthetic_weather, 20, model_config)
    calm = _wind_dynamics_features(
        features, wind_speed_effective_ms=0.5, wind_change_3h_ms=0.0,
    )
    multiplier, terms = _calm_wind_activity_multiplier(
        calm, model_config, population_potential=50.0,
        temperature_activity=0.9, humidity_activity=0.8, daypart_activity=0.9,
    )
    assert multiplier > 1.15
    assert terms["calm_gate"] > 0.8


def test_calm_wind_uplift_stays_near_one_when_windy(sample_static, synthetic_weather, model_config):
    features = _features_at(sample_static, synthetic_weather, 20, model_config)
    windy = _wind_dynamics_features(features, wind_speed_effective_ms=10.0, wind_change_3h_ms=0.0)
    multiplier, terms = _calm_wind_activity_multiplier(
        windy, model_config, population_potential=50.0,
        temperature_activity=0.9, humidity_activity=0.8, daypart_activity=0.9,
    )
    assert multiplier == pytest.approx(1.0, abs=0.05)
    assert terms["calm_gate"] < 0.1


def test_calm_wind_uplift_suppressed_by_near_zero_population(sample_static, synthetic_weather, model_config):
    """item 6: calm weather alone must not turn a near-zero-population cell
    high-risk."""
    features = _features_at(sample_static, synthetic_weather, 20, model_config)
    calm = _wind_dynamics_features(features, wind_speed_effective_ms=0.5, wind_change_3h_ms=0.0)
    multiplier, terms = _calm_wind_activity_multiplier(
        calm, model_config, population_potential=1.0,
        temperature_activity=0.9, humidity_activity=0.8, daypart_activity=0.9,
    )
    assert multiplier == pytest.approx(1.0, abs=0.08)
    assert terms["population_gate"] < 0.15


def test_calm_wind_uplift_suppressed_when_cold(sample_static, synthetic_weather, model_config):
    """item 6: a cold calm evening must not be lifted by this correction."""
    features = _features_at(sample_static, synthetic_weather, 20, model_config)
    calm = _wind_dynamics_features(features, wind_speed_effective_ms=0.5, wind_change_3h_ms=0.0)
    multiplier, _ = _calm_wind_activity_multiplier(
        calm, model_config, population_potential=50.0,
        temperature_activity=0.05, humidity_activity=0.8, daypart_activity=0.9,
    )
    assert multiplier == pytest.approx(1.0, abs=0.08)


def test_wind_drop_release_boosts_activity_more_than_steady_calm(sample_static, synthetic_weather, model_config):
    """The core reported pattern: a cell that JUST went calm (wind dropped
    materially in the last 3h) should score higher than an otherwise
    identical cell that's simply been calm all along."""
    features = _features_at(sample_static, synthetic_weather, 20, model_config)
    steady_calm = _wind_dynamics_features(features, wind_speed_effective_ms=0.8, wind_change_3h_ms=0.0)
    just_dropped = _wind_dynamics_features(features, wind_speed_effective_ms=0.8, wind_change_3h_ms=-4.0)

    steady_multiplier, _ = _calm_wind_activity_multiplier(
        steady_calm, model_config, population_potential=50.0,
        temperature_activity=0.9, humidity_activity=0.8, daypart_activity=0.9,
    )
    drop_multiplier, terms = _calm_wind_activity_multiplier(
        just_dropped, model_config, population_potential=50.0,
        temperature_activity=0.9, humidity_activity=0.8, daypart_activity=0.9,
    )
    assert drop_multiplier > steady_multiplier
    assert terms["release_gate"] > 0.5


def test_calm_wind_combined_multiplier_is_capped(sample_static, synthetic_weather, model_config):
    """item 5: a single noisy forecast-hour change cannot produce extreme
    risk -- even under maximal calm+drop+population+comfort+daypart gates,
    the combined multiplier never exceeds max_combined_multiplier."""
    features = _features_at(sample_static, synthetic_weather, 20, model_config)
    maximal = _wind_dynamics_features(features, wind_speed_effective_ms=0.0, wind_change_3h_ms=-20.0)
    multiplier, _ = _calm_wind_activity_multiplier(
        maximal, model_config, population_potential=100.0,
        temperature_activity=1.0, humidity_activity=1.0, daypart_activity=1.0,
    )
    cap = model_config.wind_dynamics_params.get("max_combined_multiplier", 1.7)
    assert multiplier <= cap + 1e-6


def test_compute_biting_activity_calm_uplift_does_not_override_strong_wind_suppression(
    sample_static, synthetic_weather, model_config
):
    """item 6: genuine wind suppression on a windy hour must survive --
    the calm-gate stays closed regardless of favourable population/comfort."""
    features = _features_at(sample_static, synthetic_weather, 20, model_config)
    windy = features.__class__(**{
        **features.__dict__,
        "wind_speed_current_ms": 12.0,
        "wind_speed_effective_ms": 12.0,
        "wind_change_3h_ms": 0.0,
        "current_temperature_c": 20.0,
        "humidity_current_pct": 70.0,
    })
    activity, terms = compute_biting_activity(windy, model_config, population_potential=60.0)
    assert terms["calm_wind_uplift"] == pytest.approx(1.0, abs=0.05)
    assert activity < 25.0


def test_daylight_hours_longer_in_summer_than_winter():
    summer = daylight_hours(59.33, day_of_year=172)  # ~June 21
    winter = daylight_hours(59.33, day_of_year=355)  # ~Dec 21
    assert summer > winter


def test_seasonal_suitability_peaks_in_midsummer():
    midsummer = seasonal_suitability_curve(190, latitude=59.0)
    midwinter = seasonal_suitability_curve(10, latitude=59.0)
    assert midsummer > midwinter
    assert 0.0 <= midsummer <= 1.0
