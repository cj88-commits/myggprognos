"""Transparent, rule-based mosquito risk scoring model.

Deliberately not machine learning: every sub-score is a named, bounded
transformation of an explainable feature, combined with configurable
weights from model.yaml. This keeps the model auditable and lets us
generate faithful "why is this risk high/low" explanations (see
explanation.py) directly from the same contribution values used to compute
the score.

    population potential = weighted sum of bounded (0-1) suitability terms
    biting activity       = product of bounded (0-1) activity multipliers
    exposure               = weighted sum of bounded (0-1) terrain/proximity terms
    final risk              = population potential x biting activity x exposure,
                               rescaled to 0-100
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from config import ModelConfig
from feature_engineering import FeatureSet


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def scale_sigmoid(value: float, midpoint: float, steepness: float) -> float:
    """Logistic curve mapped to (0, 1); `steepness` > 0 means increasing
    with value, < 0 means decreasing."""
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (value - midpoint)))
    except OverflowError:
        return 0.0 if steepness * (value - midpoint) < 0 else 1.0


def bell_curve(value: float, optimum: float, width: float) -> float:
    """Gaussian bump peaking at 1.0 when value == optimum, decaying to 0 as
    |value - optimum| grows relative to `width`."""
    if width <= 0:
        return 1.0 if value == optimum else 0.0
    return math.exp(-0.5 * ((value - optimum) / width) ** 2)


@dataclass
class Contribution:
    key: str
    label: str
    value: float  # signed contribution to the relevant 0-100 component


@dataclass
class ScoreResult:
    population_potential: float
    biting_activity: float
    exposure: float
    final_risk: float
    population_terms: dict[str, float] = field(default_factory=dict)
    activity_terms: dict[str, float] = field(default_factory=dict)
    exposure_terms: dict[str, float] = field(default_factory=dict)
    activity_multiplier_applied: float = 1.0
    activity_profile: str = "general"


POSITIVE_LABELS = {
    "temperature": "Varma senaste dagarna",
    "rainfall": "Mycket nederbörd senaste veckorna",
    "moisture": "Fuktig/vattensjuk mark",
    "standing_water": "Ihållande stående vatten",
    "wetland": "Närliggande våtmarker och stående vatten",
    "forest": "Skogsmark som ger skydd",
    "season": "Högsäsong för mygg",
    "snowmelt": "Vårflod / snösmältning",
    "temp_activity": "Temperatur som gynnar myggaktivitet",
    "humidity_activity": "Hög luftfuktighet som gynnar aktivitet",
    "daypart_activity": "Skymning/gryning med hög aktivitet",
    "terrain_exposure": "Vegetation med lite vind",
    "water_proximity": "Nära vatten",
}

NEGATIVE_LABELS = {
    "wind_suppression": "Vind som dämpar myggaktivitet",
    "rain_suppression": "Aktivt regn som dämpar aktivitet",
    "freezing": "Nyligt minusgrader",
    "urban_suppression": "Stadsmiljö",
}


def _daypart_activity_curve(hour: int) -> float:
    """Crepuscular activity pattern typical of common Swedish mosquito
    genera (Aedes/Culex): peaks around dawn and, more strongly, dusk;
    lowest during the heat of midday and in the coldest overnight hours."""
    dusk = bell_curve(hour, optimum=21, width=2.5)
    dawn = bell_curve(hour, optimum=5, width=2.0)
    midday_dip = 1 - 0.35 * bell_curve(hour, optimum=13, width=3.0)
    return clamp(max(dusk, dawn * 0.8) * midday_dip + 0.15, 0.0, 1.0)


def compute_population_potential(features: FeatureSet, config: ModelConfig) -> tuple[float, dict[str, float]]:
    weights = config.population_weights or {
        "temperature": 0.22, "rainfall": 0.22, "moisture": 0.14,
        "wetland": 0.13, "forest": 0.07, "season": 0.07, "snowmelt": 0.05,
        "standing_water": 0.10,
    }

    temp_input = features.mean_temperature_14d_c if features.mean_temperature_14d_c is not None else features.current_temperature_c or 10.0
    temperature_term = scale_sigmoid(temp_input, midpoint=config.development_base_temperature_c + 3, steepness=0.35)
    if features.freezing_recently:
        temperature_term *= 0.5

    rainfall_term = bell_curve(features.precipitation_14d_mm, optimum=40.0, width=35.0)
    if features.days_since_meaningful_rain >= 18:
        rainfall_term *= 0.4

    moisture_input = features.soil_moisture_7d_mean if features.soil_moisture_7d_mean is not None else 0.2
    moisture_term = scale_sigmoid(moisture_input, midpoint=0.28, steepness=8.0)

    wetland_term = clamp(features.wetland_fraction * 1.8, 0.0, 1.0)
    forest_term = clamp(features.forest_fraction * 1.3, 0.0, 1.0)
    season_term = clamp(features.seasonal_suitability, 0.0, 1.0)

    spring_window = bell_curve(features.day_of_year, optimum=135, width=40)
    snowmelt_term = spring_window * (0.35 if features.freezing_recently else 1.0)

    standing_water_term = clamp(features.standing_water_persistence, 0.0, 1.0)

    terms = {
        "temperature": temperature_term,
        "rainfall": rainfall_term,
        "moisture": moisture_term,
        "wetland": wetland_term,
        "forest": forest_term,
        "season": season_term,
        "snowmelt": snowmelt_term,
        "standing_water": standing_water_term,
    }

    weighted_sum = sum(terms[k] * weights.get(k, 0.0) for k in terms)
    total_weight = sum(weights.get(k, 0.0) for k in terms) or 1.0
    normalized = clamp(weighted_sum / total_weight, 0.0, 1.0)

    contributions = {k: round(terms[k] * weights.get(k, 0.0) / total_weight * 100, 3) for k in terms}
    return normalized * 100.0, contributions


_ACTIVITY_WEIGHTS_DEFAULT = {
    "temp_activity": 0.25,
    "humidity_activity": 0.15,
    "wind_suppression": 0.20,
    "daypart_activity": 0.25,
    "rain_suppression": 0.15,
}
_LOG_FLOOR = 1e-6  # avoids log(0) for a term that's genuinely fully suppressed


def compute_biting_activity(features: FeatureSet, config: ModelConfig) -> tuple[float, dict[str, float]]:
    params = config.activity_params or {
        "optimum_temperature_c": 23, "temperature_width": 10,
        "wind_half_suppression_ms": 3.5, "wind_full_suppression_ms": 9.0,
        "minimum_humidity_percent": 35, "optimum_humidity_percent": 75,
        "rain_suppression_mm_per_hour": 1.0,
    }

    temp = features.current_temperature_c if features.current_temperature_c is not None else 15.0
    temperature_activity = bell_curve(
        temp, optimum=params.get("optimum_temperature_c", 23), width=params.get("temperature_width", 10)
    )
    if temp <= 5:
        temperature_activity *= 0.15

    humidity = features.humidity_current_pct if features.humidity_current_pct is not None else 55.0
    # A single sigmoid on humidity -- a separate binary "dry air" cutoff on
    # the same underlying value used to be multiplied in here too, which
    # double-penalized low humidity rather than adding new information.
    humidity_activity = scale_sigmoid(
        humidity, midpoint=params.get("minimum_humidity_percent", 35) + 5, steepness=0.12
    )

    wind = features.wind_speed_current_ms if features.wind_speed_current_ms is not None else 2.0
    wind_full = params.get("wind_full_suppression_ms", 9.0)
    wind_half = params.get("wind_half_suppression_ms", 3.5)
    wind_suppression = clamp(1.0 - scale_sigmoid(wind, midpoint=wind_half, steepness=4.0 / max(wind_full - wind_half, 0.1)), 0.0, 1.0)

    daypart_activity = _daypart_activity_curve(features.hour_of_day)

    rain_threshold = params.get("rain_suppression_mm_per_hour", 1.0)
    rain_suppression = clamp(1.0 - scale_sigmoid(features.current_precipitation_mm, midpoint=rain_threshold, steepness=2.5), 0.0, 1.0)

    terms = {
        "temp_activity": temperature_activity,
        "humidity_activity": humidity_activity,
        "wind_suppression": wind_suppression,
        "daypart_activity": daypart_activity,
        "rain_suppression": rain_suppression,
    }

    # Weighted geometric mean rather than a plain product: each factor still
    # suppresses activity multiplicatively (a genuinely near-zero factor,
    # e.g. gale-force wind, still crushes the result), but several merely
    # mediocre-but-not-bad factors (~0.7 each) no longer compound into an
    # unrealistically tiny number just because there happen to be five of
    # them. A plain product of five ~0.8 terms is ~0.33; the weighted
    # geometric mean below keeps that same case around ~0.8.
    weights = {k: params.get(f"{k}_weight", _ACTIVITY_WEIGHTS_DEFAULT[k]) for k in terms}
    total_weight = sum(weights.values()) or 1.0
    log_sum = sum(weights[k] * math.log(max(terms[k], _LOG_FLOOR)) for k in terms)
    activity = clamp(math.exp(log_sum / total_weight), 0.0, 1.0)

    return activity * 100.0, terms


def compute_exposure(features: FeatureSet, config: ModelConfig, activity_multiplier: float = 1.0) -> tuple[float, dict[str, float]]:
    params = config.exposure_params or {
        "water_proximity_half_distance_km": 1.5, "wetland_exposure_weight": 0.35,
        "forest_exposure_weight": 0.25, "water_exposure_weight": 0.25,
        "urban_exposure_weight": -0.15, "base_exposure": 0.5,
    }

    water_proximity = scale_sigmoid(
        features.distance_to_water_km, midpoint=params.get("water_proximity_half_distance_km", 1.5), steepness=-1.2
    )

    terrain_exposure = clamp(
        params.get("base_exposure", 0.5)
        + params.get("wetland_exposure_weight", 0.35) * features.wetland_fraction
        + params.get("forest_exposure_weight", 0.25) * features.forest_fraction
        + params.get("urban_exposure_weight", -0.15) * features.urban_fraction,
        0.0,
        1.0,
    )
    water_term = clamp(
        params.get("water_exposure_weight", 0.25) * water_proximity + 0.5 * features.water_body_density,
        0.0,
        1.0,
    )

    base_exposure = clamp(0.5 * terrain_exposure + 0.5 * water_term, 0.0, 1.0)
    adjusted = clamp(base_exposure * activity_multiplier, 0.0, 1.5)
    exposure_0_100 = clamp(adjusted, 0.0, 1.5) * 100.0
    exposure_0_100 = clamp(exposure_0_100, 0.0, 100.0)

    terms = {
        "terrain_exposure": terrain_exposure,
        "water_proximity": water_term,
        "activity_multiplier": activity_multiplier,
        "base_exposure_fraction": base_exposure,
    }
    return exposure_0_100, terms


def compute_score(
    features: FeatureSet,
    config: ModelConfig,
    activity_profile: str = "general",
) -> ScoreResult:
    activity_multiplier = (config.activities or {}).get(activity_profile, 1.0)

    population_potential, population_terms = compute_population_potential(features, config)
    biting_activity, activity_terms = compute_biting_activity(features, config)
    exposure, exposure_terms = compute_exposure(features, config, activity_multiplier)

    # Combine multiplicatively (each normalised 0-1) then rescale to 0-100,
    # which keeps risk low unless population potential, activity AND
    # exposure are all non-trivial -- matching the product-of-factors
    # framing in the spec while avoiding false precision from raw sums.
    combined_fraction = (population_potential / 100.0) * (biting_activity / 100.0) * clamp(exposure / 100.0, 0.0, 1.0)
    final_risk = clamp(combined_fraction * 100.0 * 2.6, 0.0, 100.0)

    return ScoreResult(
        population_potential=round(population_potential, 3),
        biting_activity=round(biting_activity, 3),
        exposure=round(exposure, 3),
        final_risk=round(final_risk, 3),
        population_terms=population_terms,
        activity_terms=activity_terms,
        exposure_terms=exposure_terms,
        activity_multiplier_applied=activity_multiplier,
        activity_profile=activity_profile,
    )


def risk_category(score: float) -> tuple[str, str]:
    from config import RISK_CATEGORIES

    # Pick the highest-lo band the score clears, rather than requiring
    # `lo <= x <= hi` -- with adjacent integer bounds (e.g. ...19 / 20...)
    # any fractional score landing in the gap (e.g. 19.13) would otherwise
    # match no band and silently fall back to the *last* (very_high) band,
    # regardless of the actual score.
    key, label = RISK_CATEGORIES[0][2], RISK_CATEGORIES[0][3]
    for lo, _hi, band_key, band_label in RISK_CATEGORIES:
        if score >= lo:
            key, label = band_key, band_label
    return key, label
