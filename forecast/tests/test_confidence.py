from __future__ import annotations

from datetime import datetime, timezone

from confidence import compute_confidence
from feature_engineering import compute_features
from model import compute_score


def _features_and_score(sample_static, synthetic_weather, model_config, hour=14):
    target = datetime(2026, 7, 21, hour, tzinfo=timezone.utc)
    features = compute_features(sample_static, synthetic_weather, target, model_config.development_base_temperature_c)
    score = compute_score(features, model_config, "general")
    return features, score


def test_confidence_between_0_and_1(sample_static, synthetic_weather, model_config):
    features, score = _features_and_score(sample_static, synthetic_weather, model_config)
    result = compute_confidence(features, score, model_config, horizon_hours=0, static_data_is_placeholder=True)
    assert 0.0 <= result.confidence <= 1.0
    assert result.label in {"Low", "Medium", "High"}


def test_confidence_decreases_with_longer_horizon(sample_static, synthetic_weather, model_config):
    features, score = _features_and_score(sample_static, synthetic_weather, model_config)
    near = compute_confidence(features, score, model_config, horizon_hours=1, static_data_is_placeholder=False)
    far = compute_confidence(features, score, model_config, horizon_hours=168, static_data_is_placeholder=False)
    assert far.confidence < near.confidence


def test_confidence_lower_when_static_data_is_placeholder(sample_static, synthetic_weather, model_config):
    features, score = _features_and_score(sample_static, synthetic_weather, model_config)
    real = compute_confidence(features, score, model_config, horizon_hours=12, static_data_is_placeholder=False)
    placeholder = compute_confidence(features, score, model_config, horizon_hours=12, static_data_is_placeholder=True)
    assert placeholder.confidence < real.confidence
    assert any("placeholder" in reason.lower() for reason in placeholder.low_confidence_reasons)


def test_confidence_lower_when_weather_is_synthetic(sample_static, synthetic_weather, model_config):
    features, score = _features_and_score(sample_static, synthetic_weather, model_config)
    assert features.used_synthetic_weather is True
    result = compute_confidence(features, score, model_config, horizon_hours=12, static_data_is_placeholder=False)
    assert any("synthetic" in reason.lower() for reason in result.low_confidence_reasons)
