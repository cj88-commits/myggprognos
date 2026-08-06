"""Deterministic, template-based forecast explanations (in Swedish).

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
    "temperature": "Varma senaste dagarna",
    "rainfall": "Mycket nederbörd de senaste två veckorna",
    "moisture": "Fuktig/vattensjuk mark",
    "standing_water": "Ihållande stående vatten",
    "wetland": "Närliggande våtmarker och stående vatten",
    "forest": "Skogsmark som ger skydd och häckningsplatser",
    "season": "Högsäsong för mygg vid denna tid på året",
    "snowmelt": "Vårflod / snösmältning",
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
        contribution = round(value / 100.0, 3)  # fraction of population_potential (0-100)
        if contribution > 0.08:
            candidates.append(Factor(key, POPULATION_LABELS.get(key, key), contribution))
    return candidates


def _activity_candidates(score: ScoreResult) -> tuple[list[Factor], list[Factor]]:
    positive, negative = [], []
    boosters = {"temp_activity", "humidity_activity", "daypart_activity"}
    suppressors = {"wind_suppression", "rain_suppression"}
    for key, value in score.activity_terms.items():
        if key in boosters and value > 0.6:
            positive.append(Factor(key, POSITIVE_LABELS.get(key, key), round((value - 0.5) * 0.4, 3)))
        elif key in suppressors and value < 0.8:
            negative.append(Factor(key, NEGATIVE_LABELS.get(key, key), round((value - 1.0) * 0.4, 3)))

    # calm_wind_uplift is a multiplier (>= 1.0), not a 0-1 fraction like the
    # boosters above -- surfaced separately (docs/wind-calm-investigation.md)
    # so a meaningful calm-evening/wind-drop correction is visible in the
    # "why" explanation, not just in raw diagnostics.
    calm_uplift = score.activity_terms.get("calm_wind_uplift", 1.0)
    if calm_uplift > 1.1:
        positive.append(
            Factor("calm_wind_uplift", POSITIVE_LABELS["calm_wind_uplift"], round((calm_uplift - 1.0) * 0.5, 3))
        )
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


def _wind_descriptor(wind_ms: float) -> str:
    if wind_ms < 2.5:
        return "vinden är svag"
    if wind_ms >= 6.0:
        return "det blåser en del"
    return "vinden är måttlig"


def _join_swedish(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} och {parts[1]}"
    return f"{', '.join(parts[:-1])} och {parts[-1]}"


def _narrative_details(features: FeatureSet) -> list[str]:
    """Build the concrete, value-grounded clauses used in the summary
    sentence -- e.g. actual rainfall/temperature/wind, not just factor
    labels -- so the "why is it like this?" text reads like a real
    explanation rather than a list of tags."""
    parts: list[str] = []

    if features.precipitation_7d_mm >= 15:
        parts.append(f"det har regnat mycket den senaste veckan ({round(features.precipitation_7d_mm)} mm)")
    elif features.precipitation_3d_mm >= 8:
        parts.append(f"det har regnat en del de senaste dagarna ({round(features.precipitation_3d_mm)} mm)")
    elif features.days_since_meaningful_rain >= 10:
        parts.append("det har varit torrt en längre tid")

    if features.current_temperature_c is not None:
        parts.append(f"temperaturen ligger runt {round(features.current_temperature_c)} °C")

    if features.wind_speed_current_ms is not None:
        parts.append(_wind_descriptor(features.wind_speed_current_ms))

    return parts


def _summary_text(score: ScoreResult, features: FeatureSet, positive: list[Factor], negative: list[Factor]) -> str:
    from model import risk_category

    _key, label = risk_category(score.final_risk)
    label_lower = label[0].lower() + label[1:]

    detail_parts = _narrative_details(features)

    if not positive and not negative and not detail_parts:
        return f"Myggrisken är {label_lower} idag utan någon enskild tydligt dominerande faktor."

    if detail_parts:
        summary = f"Myggrisken är {label_lower} idag eftersom {_join_swedish(detail_parts)}."
    else:
        names = [f.label[0].lower() + f.label[1:] for f in positive[:3]]
        summary = f"Myggrisken är {label_lower} idag på grund av {_join_swedish(names)}."

    if negative:
        names = [f.label[0].lower() + f.label[1:] for f in negative[:2]]
        joined = " och ".join(names)
        summary += f" {joined[0].upper()}{joined[1:]} dämpar dock aktiviteten."

    return summary


def format_factor_strings(explanation: Explanation) -> list[str]:
    """Flat, spec-literal list of human-readable factor strings, e.g.
    "Hög temperatur (+18)" -- additive to (not a replacement for) the
    structured positive/negative factor lists, which the UI's +/- list and
    any future locale switching still rely on."""
    lines: list[str] = []
    for factor in explanation.positive_factors + explanation.negative_factors:
        magnitude = round(factor.contribution * 100)
        sign = "+" if magnitude > 0 else ""
        lines.append(f"{factor.label} ({sign}{magnitude})")
    return lines


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

    summary = _summary_text(score, features, all_positive, all_negative)

    return Explanation(positive_factors=all_positive, negative_factors=all_negative, summary=summary)
