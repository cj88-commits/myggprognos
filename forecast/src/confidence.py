"""Forecast confidence scoring.

Confidence (0-100) reflects how much the forecast should be trusted, not how
severe the risk is. It is computed from forecast horizon, weather data
completeness, static data quality, agreement between the three model
components, and (optionally) nearby user report support -- see section 10
of the product spec.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from config import CONFIDENCE_LABELS, ModelConfig
from feature_engineering import FeatureSet
from model import ScoreResult, clamp


@dataclass
class ConfidenceResult:
    confidence: float
    label: str
    components: dict[str, float] = field(default_factory=dict)
    low_confidence_reasons: list[str] = field(default_factory=list)


def _horizon_score(horizon_hours: float) -> float:
    """1.0 for now-cast, decaying to ~0.35 at the 7-day (168h) horizon."""
    return clamp(1.0 - 0.65 * (horizon_hours / 168.0), 0.25, 1.0)


def confidence_label(confidence: float) -> str:
    """Pick the highest-lo band the score clears, rather than requiring
    `lo <= x <= hi` -- with adjacent integer bounds (e.g. ...39 / 40...) any
    fractional score landing in the gap (e.g. 39.5) would otherwise match no
    band at all."""
    label = CONFIDENCE_LABELS[0][3]
    for lo, _hi, _key, lab in CONFIDENCE_LABELS:
        if confidence >= lo:
            label = lab
    return label


def _component_agreement(score: ScoreResult) -> float:
    """High agreement (1.0) when population/activity/exposure sub-scores
    point the same direction; lower when they strongly disagree (e.g. very
    high population potential but near-zero activity), since that combination
    is inherently harder to have confidence in."""
    values = [score.population_potential, score.biting_activity, score.exposure]
    mean_v = sum(values) / len(values)
    if mean_v == 0:
        return 0.6
    variance = sum((v - mean_v) ** 2 for v in values) / len(values)
    spread = (variance**0.5) / max(mean_v, 1e-6)
    return clamp(1.0 - spread * 0.5, 0.3, 1.0)


def compute_confidence(
    features: FeatureSet,
    score: ScoreResult,
    config: ModelConfig,
    horizon_hours: float,
    static_data_is_placeholder: bool,
    nearby_report_count: int = 0,
    nearby_report_age_hours: float | None = None,
) -> ConfidenceResult:
    weights = config.confidence_weights or {
        "horizon_weight": 0.30, "weather_completeness_weight": 0.20,
        "static_data_quality_weight": 0.15, "component_agreement_weight": 0.15,
        "report_support_weight": 0.10, "fallback_penalty_weight": 0.10,
    }

    horizon_score = _horizon_score(horizon_hours)
    weather_completeness = clamp(1.0 - features.weather_missing_fraction, 0.0, 1.0)
    static_quality = 0.55 if static_data_is_placeholder else 0.95
    agreement = _component_agreement(score)

    report_support = 0.5
    if nearby_report_count >= 3 and nearby_report_age_hours is not None and nearby_report_age_hours <= 12:
        report_support = clamp(0.5 + 0.05 * min(nearby_report_count, 15), 0.5, 1.0)

    fallback_penalty = 0.4 if (features.soil_moisture_is_fallback or features.used_synthetic_weather) else 1.0

    components = {
        "horizon": round(horizon_score, 3),
        "weather_completeness": round(weather_completeness, 3),
        "static_data_quality": round(static_quality, 3),
        "component_agreement": round(agreement, 3),
        "report_support": round(report_support, 3),
        "fallback_penalty": round(fallback_penalty, 3),
    }

    total_weight = sum(weights.values()) or 1.0
    confidence_fraction = (
        horizon_score * weights.get("horizon_weight", 0.30)
        + weather_completeness * weights.get("weather_completeness_weight", 0.20)
        + static_quality * weights.get("static_data_quality_weight", 0.15)
        + agreement * weights.get("component_agreement_weight", 0.15)
        + report_support * weights.get("report_support_weight", 0.10)
        + fallback_penalty * weights.get("fallback_penalty_weight", 0.10)
    ) / total_weight
    confidence = clamp(confidence_fraction * 100.0, 0.0, 100.0)

    reasons = []
    if horizon_score < 0.6:
        reasons.append("Prognosen gäller flera dagar framåt, vilket gör den mindre exakt.")
    if weather_completeness < 0.8:
        reasons.append("En del väderdata saknades för denna plats/tid.")
    if static_data_is_placeholder:
        reasons.append("Statisk terrängdata är en platshållaruppskattning i denna betaversion.")
    if features.soil_moisture_is_fallback:
        reasons.append("Markfuktighet uppskattades utifrån nederbörd/temperatur, inte uppmätt direkt.")
    if features.used_synthetic_weather:
        reasons.append("Syntetisk exempeldata användes istället för en verklig väderprognos.")
    if agreement < 0.6:
        reasons.append("Modellens delkomponenter är mer oense än vanligt för denna plats/tid.")

    return ConfidenceResult(
        confidence=round(confidence, 3),
        label=confidence_label(confidence),
        components=components,
        low_confidence_reasons=reasons,
    )
