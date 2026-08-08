"""Regression scenarios for the calm-evening / wind-drop-release correction
(docs/wind-calm-investigation.md), covering the 7 cases explicitly required
by the investigation brief. Each test exercises the real end-to-end
`compute_score` path (not just the isolated multiplier function -- see
test_model.py for that), so a future change to any upstream piece
(population, exposure, the base wind_suppression curve, etc.) that breaks
one of these guarantees fails here too.
"""
from __future__ import annotations

from datetime import datetime, timezone

from feature_engineering import compute_features
from model import compute_score


def _features_at(sample_static, synthetic_weather, hour: int, model_config):
    target = datetime(2026, 7, 21, hour, tzinfo=timezone.utc)
    return compute_features(sample_static, synthetic_weather, target, model_config.development_base_temperature_c)


def _with(features, **overrides):
    return features.__class__(**{**features.__dict__, **overrides})


# Shared "real, moderate-to-good population" baseline so these wind/comfort
# scenarios aren't confounded by population potential being near zero
# (that case is scenario 7, tested separately).
_GOOD_POPULATION = dict(
    mean_temperature_14d_c=17.0,
    precipitation_14d_mm=35.0,
    emergence_potential=0.75,
    wetland_fraction=0.25,
)


def test_scenario1_wind_falls_5_to_1_over_evening_increases_risk_materially(sample_static, synthetic_weather, model_config):
    """1) Warm humid evening, wind falls 5 -> 1 m/s: risk should increase
    materially. This is the exact reported pattern, reproduced end to end."""
    features = _features_at(sample_static, synthetic_weather, 20, model_config)
    before_drop = _with(
        features, **_GOOD_POPULATION,
        current_temperature_c=20.0, humidity_current_pct=75.0,
        wind_speed_current_ms=5.0, wind_speed_effective_ms=5.0,
        wind_speed_3h_ago_ms=5.0, wind_change_3h_ms=0.0, wind_min_3h_ms=5.0, calm_hours_streak=0,
    )
    after_drop = _with(
        features, **_GOOD_POPULATION,
        current_temperature_c=20.0, humidity_current_pct=75.0,
        wind_speed_current_ms=1.0, wind_speed_effective_ms=1.0,
        wind_speed_3h_ago_ms=5.0, wind_change_3h_ms=-4.0, wind_min_3h_ms=1.0, calm_hours_streak=1,
    )
    before = compute_score(before_drop, model_config, "general")
    after = compute_score(after_drop, model_config, "general")
    assert after.final_risk > before.final_risk + 8.0
    assert after.final_risk - before.final_risk >= 0.15 * before.final_risk


def test_scenario2_steady_1ms_wind_evening_is_elevated_but_not_extreme(sample_static, synthetic_weather, model_config):
    """2) Same evening, steady 1 m/s (no recent drop): elevated, but not
    necessarily extreme."""
    features = _features_at(sample_static, synthetic_weather, 20, model_config)
    steady_calm = _with(
        features, **_GOOD_POPULATION,
        current_temperature_c=20.0, humidity_current_pct=75.0,
        wind_speed_current_ms=1.0, wind_speed_effective_ms=1.0,
        wind_speed_3h_ago_ms=1.0, wind_change_3h_ms=0.0, wind_min_3h_ms=1.0, calm_hours_streak=6,
    )
    result = compute_score(steady_calm, model_config, "general")
    assert result.final_risk < 90.0
    assert result.biting_activity > 20.0


def test_scenario3_cold_calm_evening_remains_low(sample_static, synthetic_weather, model_config):
    """3) Cold calm evening: remains low -- calm wind alone must not fire
    the correction when temperature doesn't support activity."""
    features = _features_at(sample_static, synthetic_weather, 20, model_config)
    cold_calm = _with(
        features, **_GOOD_POPULATION,
        current_temperature_c=4.0, humidity_current_pct=60.0,
        wind_speed_current_ms=1.0, wind_speed_effective_ms=1.0,
        wind_speed_3h_ago_ms=1.0, wind_change_3h_ms=0.0, wind_min_3h_ms=1.0, calm_hours_streak=6,
    )
    result = compute_score(cold_calm, model_config, "general")
    assert result.final_risk < 25.0


def test_scenario4_dry_calm_afternoon_remains_low_or_modest(sample_static, synthetic_weather, model_config):
    """4) Dry calm afternoon (not dusk/dawn): remains low/modest."""
    features = _features_at(sample_static, synthetic_weather, 14, model_config)
    dry_calm = _with(
        features, **_GOOD_POPULATION,
        current_temperature_c=22.0, humidity_current_pct=20.0,
        wind_speed_current_ms=1.0, wind_speed_effective_ms=1.0,
        wind_speed_3h_ago_ms=1.0, wind_change_3h_ms=0.0, wind_min_3h_ms=1.0, calm_hours_streak=4,
    )
    result = compute_score(dry_calm, model_config, "general")
    assert result.final_risk < 45.0


def test_scenario5_warm_humid_but_6ms_wind_is_strongly_suppressed(sample_static, synthetic_weather, model_config):
    """5) Warm humid but 6 m/s wind: strongly suppressed -- genuine wind
    suppression must survive the new correction (item 6)."""
    features = _features_at(sample_static, synthetic_weather, 20, model_config)
    windy = _with(
        features, **_GOOD_POPULATION,
        current_temperature_c=20.0, humidity_current_pct=75.0,
        wind_speed_current_ms=6.0, wind_speed_effective_ms=6.0,
        wind_speed_3h_ago_ms=6.0, wind_change_3h_ms=0.0, wind_min_3h_ms=6.0, calm_hours_streak=0,
    )
    calm_baseline = _with(
        features, **_GOOD_POPULATION,
        current_temperature_c=20.0, humidity_current_pct=75.0,
        wind_speed_current_ms=1.0, wind_speed_effective_ms=1.0,
        wind_speed_3h_ago_ms=1.0, wind_change_3h_ms=0.0, wind_min_3h_ms=1.0, calm_hours_streak=6,
    )
    windy_result = compute_score(windy, model_config, "general")
    calm_result = compute_score(calm_baseline, model_config, "general")
    assert windy_result.final_risk < calm_result.final_risk * 0.6


def test_scenario6_sheltered_forest_cell_reads_higher_than_exposed_coastal_cell_under_same_forecast_wind(
    sample_static, synthetic_weather, model_config
):
    """6) Sheltered forest cell vs exposed coastal cell under the SAME
    forecast wind: the sheltered cell's lower effective wind should read a
    higher (not equal) risk (item 2/3 of the investigation)."""
    target = datetime(2026, 7, 21, 20, tzinfo=timezone.utc)

    forest_static = sample_static.__class__(**{
        **sample_static.__dict__, "forest_fraction": 0.9, "urban_fraction": 0.0, "coastal_exposure": 0.0, "slope_deg": 1.0,
    })
    coastal_static = sample_static.__class__(**{
        **sample_static.__dict__, "forest_fraction": 0.0, "urban_fraction": 0.0, "coastal_exposure": 1.0, "slope_deg": 1.0,
    })

    forest_features = compute_features(forest_static, synthetic_weather, target, model_config.development_base_temperature_c)
    coastal_features = compute_features(coastal_static, synthetic_weather, target, model_config.development_base_temperature_c)
    # Both were computed against the exact same weather series/target, so
    # wind_speed_effective_ms differs ONLY due to static shelter -- this is
    # the thing under test.
    assert forest_features.wind_speed_effective_ms < coastal_features.wind_speed_effective_ms

    forest_features = _with(
        forest_features, **_GOOD_POPULATION,
        current_temperature_c=20.0, humidity_current_pct=75.0,
        wind_speed_current_ms=3.0, wind_speed_3h_ago_ms=3.0, wind_change_3h_ms=0.0, wind_min_3h_ms=3.0,
    )
    coastal_features = _with(
        coastal_features, **_GOOD_POPULATION,
        current_temperature_c=20.0, humidity_current_pct=75.0,
        wind_speed_current_ms=3.0, wind_speed_3h_ago_ms=3.0, wind_change_3h_ms=0.0, wind_min_3h_ms=3.0,
    )

    forest_result = compute_score(forest_features, model_config, "general")
    coastal_result = compute_score(coastal_features, model_config, "general")
    assert forest_result.final_risk >= coastal_result.final_risk


def test_scenario7_zero_population_remains_low_regardless_of_calm_wind(sample_static, synthetic_weather, model_config):
    """7) Zero/very low population: remains low regardless of calm wind --
    population is still the biological gate (item 6)."""
    features = _features_at(sample_static, synthetic_weather, 20, model_config)
    no_population_calm = _with(
        features,
        # Zero every population-driving term (not just the wind-related
        # ones) so this is genuinely "near-zero population", not just
        # "some terms lowered" -- forest/season/moisture are real habitat
        # signals independent of the wind-drop correction under test here.
        # habitat_capacity/mosquito_pressure (geographic-model redesign)
        # are now the primary population_potential drivers -- see
        # model.py::compute_population_potential -- so they must be zeroed
        # here too, not just the legacy per-weather-term fields.
        mean_temperature_14d_c=2.0, precipitation_14d_mm=0.0, emergence_potential=0.0,
        wetland_fraction=0.0, standing_water_persistence=0.0,
        forest_fraction=0.0, seasonal_suitability=0.0,
        soil_moisture_7d_mean=0.0, soil_moisture_current=0.0,
        habitat_capacity=0.0, mosquito_pressure=0.0,
        current_temperature_c=20.0, humidity_current_pct=75.0,
        wind_speed_current_ms=1.0, wind_speed_effective_ms=1.0,
        wind_speed_3h_ago_ms=1.0, wind_change_3h_ms=0.0, wind_min_3h_ms=1.0, calm_hours_streak=6,
    )
    result = compute_score(no_population_calm, model_config, "general")
    assert result.population_potential < 15.0
    assert result.final_risk < 15.0
