"""Snapshot-style fixture tests: given fixed synthetic inputs, the same
locations should always produce the same scores. This guards against
accidental non-determinism (e.g. reliance on wall-clock time, unseeded
randomness, or dict/set ordering) creeping into the model.

Covers the five representative Swedish locations named in the product
spec: central Stockholm, a forested inland location, a wetland location,
a coastal location, and a northern Sweden location.
"""
from __future__ import annotations

from datetime import datetime, timezone

from confidence import compute_confidence
from feature_engineering import compute_features
from grid import generate_sample_grid
from model import compute_score
from static_features import generate_placeholder_static_features
from weather import SyntheticWeatherProvider

TARGET_TIME = datetime(2026, 7, 15, 20, tzinfo=timezone.utc)


def _score_for_all_sample_cells(model_config):
    cells = {c.cell_id: c for c in generate_sample_grid()}
    provider = SyntheticWeatherProvider()
    weather_by_cell = provider.fetch_forecast(
        list(cells.values()), datetime(2026, 6, 25).date(), datetime(2026, 7, 16).date()
    )

    scores = {}
    for cell_id, cell in cells.items():
        static = generate_placeholder_static_features(cell)
        weather = weather_by_cell[cell_id]
        features = compute_features(static, weather, TARGET_TIME, model_config.development_base_temperature_c)
        score = compute_score(features, model_config, "general")
        scores[cell_id] = score
    return scores


def test_representative_locations_produce_stable_scores(model_config):
    first = _score_for_all_sample_cells(model_config)
    second = _score_for_all_sample_cells(model_config)

    for cell_id in first:
        assert first[cell_id].final_risk == second[cell_id].final_risk
        assert first[cell_id].population_potential == second[cell_id].population_potential
        assert first[cell_id].biting_activity == second[cell_id].biting_activity


def test_representative_locations_all_produce_valid_scores(model_config):
    scores = _score_for_all_sample_cells(model_config)

    expected_ids = {"SE_STHLM", "SE_FOREST", "SE_WETLAND", "SE_COAST", "SE_NORTH"}
    assert set(scores) == expected_ids

    for cell_id, score in scores.items():
        assert 0.0 <= score.final_risk <= 10.0, f"{cell_id} risk out of range"


def test_forested_location_has_higher_population_potential_than_dense_urban(model_config):
    scores = _score_for_all_sample_cells(model_config)
    # Central Stockholm has a much higher urban_fraction (placeholder GIS
    # data), which should never increase population potential relative to
    # a forested/wetland-adjacent location under the same weather.
    assert scores["SE_FOREST"].population_potential >= scores["SE_STHLM"].population_potential - 1e-6
