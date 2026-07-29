from __future__ import annotations

from datetime import datetime, timezone

from explanation import generate_explanation
from feature_engineering import compute_features
from model import compute_score


def test_explanation_has_at_most_three_positive_and_two_negative_factors(sample_static, synthetic_weather, model_config):
    target = datetime(2026, 7, 21, 20, tzinfo=timezone.utc)
    features = compute_features(sample_static, synthetic_weather, target, model_config.development_base_temperature_c)
    score = compute_score(features, model_config, "general")

    explanation = generate_explanation(features, score)

    assert len(explanation.positive_factors) <= 3
    assert len(explanation.negative_factors) <= 2
    assert explanation.summary
    assert isinstance(explanation.summary, str)


def test_explanation_summary_mentions_risk_category(sample_static, synthetic_weather, model_config):
    target = datetime(2026, 7, 21, 20, tzinfo=timezone.utc)
    features = compute_features(sample_static, synthetic_weather, target, model_config.development_base_temperature_c)
    score = compute_score(features, model_config, "general")

    explanation = generate_explanation(features, score)

    from model import risk_category

    _key, label = risk_category(score.final_risk)
    assert label.lower() in explanation.summary.lower()


def test_explanation_is_deterministic(sample_static, synthetic_weather, model_config):
    target = datetime(2026, 7, 21, 20, tzinfo=timezone.utc)
    features = compute_features(sample_static, synthetic_weather, target, model_config.development_base_temperature_c)
    score = compute_score(features, model_config, "general")

    first = generate_explanation(features, score)
    second = generate_explanation(features, score)

    assert [f.key for f in first.positive_factors] == [f.key for f in second.positive_factors]
    assert first.summary == second.summary
