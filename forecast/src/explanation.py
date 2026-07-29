"""Deterministic, template-based forecast explanations.

No external language model is used. Explanations are built directly from
the same named contribution values the scoring model already computed, so
the "why" shown to users is always faithful to the actual score
computation (see model.py). Contribution magnitudes are approximate,
human-readable indicators of relative importance, not precise causal
attributions.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from feature_engineering import FeatureSet
from model import NEGATIVE_LABELS, POSITIVE_LABELS, ScoreResult

POPULATION_LABELS = {
    "temperature": "Warm recent conditions",
    "rainfall": "Wet conditions during the past two weeks",
    "moisture": "Damp/waterlogged ground",
    "wetland": "Nearby wetlands and standing water",
    "forest": "Forest cover providing shelter and breeding sites",
    "season": "Peak mosquito season for this time of year",
    "snowmelt": "Spring snowmelt / floodwater conditions",
}


@dataclass
class Factor:
    key: str
    label: str
    contribution: float


@dataclass
class Explanation:
    positive_factors: list[Factor] = field(default_factory=list)
    negative_factors: list[Factor] = field(default_factory=list)
    summary: str = ""


def _population_candidates(score: ScoreResult) -> list[Factor]:
    candidates = []
    for key, value in score.population_terms.items():
        contribution = round(value / 10.0, 3)  # fraction of population_potential (0-10)
        if contribution > 0.08:
            candidates.append(Factor(key, POPULATION_LABELS.get(key, key), contribution))
    return candidates


def _activity_candidates(score: ScoreResult) -> tuple[list[Factor], list[Factor]]:
    positive, negative = [], []
    boosters = {"temp_activity", "humidity_activity", "daypart_activity"}
    suppressors = {"wind_suppression", "rain_suppression", "dry_air_suppression"}
    for key, value in score.activity_terms.items():
        if key in boosters and value > 0.6:
            positive.append(Factor(key, POSITIVE_LABELS.get(key, key), round((value - 0.5) * 0.4, 3)))
        elif key in suppressors and value < 0.8:
            negative.append(Factor(key, NEGATIVE_LABELS.get(key, key), round((value - 1.0) * 0.4, 3)))
    return positive, negative


def _exposure_candidates(score: ScoreResult, features: FeatureSet) -> list[Factor]:
    positive = []
    terrain = score.exposure_terms.get("terrain_exposure", 0.5)
    water = score.exposure_terms.get("water_proximity", 0.5)
    if terrain > 0.6:
        positive.append(Factor("terrain_exposure", POSITIVE_LABELS["terrain_exposure"], round((terrain - 0.5) * 0.3, 3)))
    if water > 0.6:
        positive.append(Factor("water_proximity", POSITIVE_LABELS["water_proximity"], round((water - 0.5) * 0.3, 3)))
    return positive


def _static_negative_candidates(features: FeatureSet) -> list[Factor]:
    negative = []
    if features.urban_fraction > 0.35:
        negative.append(Factor("urban_suppression", NEGATIVE_LABELS["urban_suppression"], round(-features.urban_fraction * 0.25, 3)))
    if features.freezing_recently:
        negative.append(Factor("freezing", NEGATIVE_LABELS["freezing"], -0.2))
    return negative


def _summary_text(score: ScoreResult, positive: list[Factor], negative: list[Factor]) -> str:
    from model import risk_category

    _key, label = risk_category(score.final_risk)
    if not positive and not negative:
        return f"{label} mosquito risk with no single strongly dominant factor."

    parts = []
    if positive:
        names = [f.label[0].lower() + f.label[1:] for f in positive[:3]]
        if len(names) == 1:
            joined = names[0]
        elif len(names) == 2:
            joined = f"{names[0]} and {names[1]}"
        else:
            joined = f"{names[0]}, {names[1]} and {names[2]}"
        parts.append(f"Risk is {label.lower()} because of {joined}.")
    else:
        parts.append(f"Risk is {label.lower()}.")

    if negative:
        names = [f.label[0].lower() + f.label[1:] for f in negative[:2]]
        joined = " and ".join(names)
        parts.append(f"{joined[0].upper()}{joined[1:]} is reducing activity.")

    return " ".join(parts)


def generate_explanation(features: FeatureSet, score: ScoreResult) -> Explanation:
    population_factors = _population_candidates(score)
    activity_positive, activity_negative = _activity_candidates(score)
    exposure_positive = _exposure_candidates(score, features)
    static_negative = _static_negative_candidates(features)

    all_positive = sorted(
        population_factors + activity_positive + exposure_positive,
        key=lambda f: f.contribution,
        reverse=True,
    )[:3]
    all_negative = sorted(
        activity_negative + static_negative,
        key=lambda f: f.contribution,
    )[:2]

    summary = _summary_text(score, all_positive, all_negative)

    return Explanation(positive_factors=all_positive, negative_factors=all_negative, summary=summary)
