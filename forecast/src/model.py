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
    # Exposed for explainability/diagnostics -- see compute_score's
    # docstring for what these mean (modifiers around a neutral midpoint,
    # not raw 0-1 gates).
    activity_modifier: float = 1.0
    exposure_modifier: float = 1.0


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


def _circular_bell(hour: float, optimum: float, width: float) -> float:
    """Like bell_curve, but on a 24h wheel -- an optimum near midnight
    (e.g. sunset at 23:40 during a Swedish summer white night) must read as
    close to hour=0:10 too, not "23 hours away". Needed once dawn/dusk
    become solar-relative (_daypart_activity_curve below): near midsummer
    at northern latitudes, sunrise/sunset genuinely can land within an hour
    or two of midnight."""
    diff = abs(hour - optimum) % 24
    diff = min(diff, 24 - diff)
    if width <= 0:
        return 1.0 if diff == 0 else 0.0
    return math.exp(-0.5 * (diff / width) ** 2)


def _daypart_activity_curve(
    hour: float,
    sunrise_hour_local: float | None,
    sunset_hour_local: float | None,
    is_polar_day: bool,
    is_polar_night: bool,
) -> float:
    """Crepuscular activity pattern typical of common Swedish mosquito
    genera (Aedes/Culex): peaks shortly after sunrise and, more strongly,
    shortly before sunset; lowest during the heat of midday and in the
    coldest overnight hours.

    Solar-relative (see solar.py), not a fixed clock hour: dawn/dusk shift
    with latitude and season instead of assuming a Stockholm-in-August
    sunrise/sunset applies everywhere in Sweden all year. A cell/date with
    no real sunrise or sunset (midnight sun / polar night) has no dawn/dusk
    peak to speak of, so those cases use a distinct, flatter curve instead
    of reusing dawn=05:00/dusk=21:00 as if they still meant something.
    """
    if is_polar_night:
        # No real daylight cycle to be crepuscular around. Real Aedes/Culex
        # activity at continuous near-freezing darkness is poorly
        # characterised; a flat, moderately-suppressed baseline is the
        # honest choice pending real observational data (see final report's
        # "remaining scientific limitations").
        return 0.35
    if is_polar_day or sunrise_hour_local is None or sunset_hour_local is None:
        # Midnight sun: no dusk/dawn transition, but real field observation
        # of Swedish summer mosquitoes still shows a mild activity dip
        # during the sun's (low but continuous) midday peak and a mild rise
        # around local solar midnight, rather than being flat all "day".
        low_sun_hour = 0.0  # solar midnight is ~00:00 local by construction (see solar.py)
        night_ish_lift = 0.15 * _circular_bell(hour, optimum=low_sun_hour, width=3.0)
        midday_dip = 1 - 0.25 * bell_curve(hour, optimum=13, width=4.0)
        return clamp((0.55 + night_ish_lift) * midday_dip, 0.0, 1.0)

    dusk = _circular_bell(hour, optimum=sunset_hour_local - 0.5, width=2.5)
    dawn = _circular_bell(hour, optimum=sunrise_hour_local + 0.5, width=2.0)
    solar_noon_hour = ((sunrise_hour_local + sunset_hour_local) / 2.0) % 24
    midday_dip = 1 - 0.35 * _circular_bell(hour, optimum=solar_noon_hour, width=3.0)
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

    # Rainfall-to-population emergence lag (see feature_engineering.py::
    # _emergence_potential and docs/model-audit-after.md "Rainfall lag"):
    # this used to be a bell curve directly on precipitation_14d_mm, which
    # read heavy rain from *yesterday* as immediately boosting the adult
    # population signal just as much as rain from two weeks ago that's had
    # time to actually develop into adults. emergence_potential is already
    # 0-1 and already accounts for accumulated warmth since each rain
    # event, so it's used directly rather than re-shaped through another
    # bell curve.
    rainfall_term = features.emergence_potential
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

    daypart_activity = _daypart_activity_curve(
        features.hour_of_day,
        features.sunrise_hour_local,
        features.sunset_hour_local,
        features.is_polar_day,
        features.is_polar_night,
    )

    rain_threshold = params.get("rain_suppression_mm_per_hour", 1.0)
    rain_suppression = clamp(1.0 - scale_sigmoid(features.current_precipitation_mm, midpoint=rain_threshold, steepness=2.5), 0.0, 1.0)

    terms = {
        "temp_activity": temperature_activity,
        "humidity_activity": humidity_activity,
        "wind_suppression": wind_suppression,
        "daypart_activity": daypart_activity,
        "rain_suppression": rain_suppression,
    }

    # Plain product: each factor is an independent, real biological
    # constraint on biting behavior (a mosquito hampered by wind is still
    # hampered regardless of how favorable the temperature or time of day
    # is), so a weak factor should pull the result down regardless of how
    # good the others are. A weighted geometric mean was tried here instead
    # (letting good factors partially offset a weak one), but that let
    # merely-mediocre conditions -- e.g. 15°C (well below the 23°C
    # optimum) with a light breeze -- read as ~80% activity, which real
    # field observations contradicted (confirmed live: a case with visibly
    # very few mosquitoes scored 82% under the geometric mean, ~40% under
    # this plain product).
    activity = temperature_activity * humidity_activity * wind_suppression * daypart_activity * rain_suppression
    activity = clamp(activity, 0.0, 1.0)

    return activity * 100.0, terms


def compute_exposure(features: FeatureSet, config: ModelConfig, activity_multiplier: float = 1.0) -> tuple[float, dict[str, float]]:
    """Human-ENCOUNTER conditions: sheltered/open terrain, urban context, and
    personal proximity to water -- deliberately NOT a second pass at habitat
    suitability. `wetland_fraction` and `water_body_density` are excluded on
    purpose: both already drive `compute_population_potential` above (via
    the `wetland` term and `standing_water_persistence`), so reusing them
    here double-counted one raster value as two independent signals (see
    docs/model-audit-before.md #5). `forest_fraction` is still used, but for
    a different reason than in population: here it means "sheltered from
    wind, easier for mosquitoes to reach you," not "more breeding habitat
    exists nearby."
    """
    params = config.exposure_params or {
        "water_proximity_half_distance_km": 1.5, "forest_shelter_weight": 0.20,
        "urban_exposure_weight": -0.20, "water_proximity_weight": 0.35, "base_exposure": 0.55,
    }

    water_proximity = scale_sigmoid(
        features.distance_to_water_km, midpoint=params.get("water_proximity_half_distance_km", 1.5), steepness=-1.2
    )

    terrain_exposure = clamp(
        params.get("base_exposure", 0.55)
        + params.get("forest_shelter_weight", 0.20) * features.forest_fraction
        + params.get("urban_exposure_weight", -0.20) * features.urban_fraction,
        0.0,
        1.0,
    )

    base_exposure = clamp(
        (1.0 - params.get("water_proximity_weight", 0.35)) * terrain_exposure
        + params.get("water_proximity_weight", 0.35) * water_proximity,
        0.0,
        1.0,
    )
    adjusted = clamp(base_exposure * activity_multiplier, 0.0, 1.5)
    exposure_0_100 = clamp(adjusted, 0.0, 1.5) * 100.0
    exposure_0_100 = clamp(exposure_0_100, 0.0, 100.0)

    terms = {
        "terrain_exposure": terrain_exposure,
        "water_proximity": water_proximity,
        "activity_multiplier": activity_multiplier,
        "base_exposure_fraction": base_exposure,
    }
    return exposure_0_100, terms


def compute_score(
    features: FeatureSet,
    config: ModelConfig,
    activity_profile: str = "general",
) -> ScoreResult:
    """Population is the biological gate: with (near-)zero mosquitoes
    present, risk is (near-)zero no matter how favourable the weather.
    Activity and exposure are MODIFIERS around a neutral midpoint rather
    than raw 0-1 gates multiplied straight through -- a plain three-way
    product let any single weak factor (most often midday activity
    suppression from wind/heat) collapse a real population signal to
    "very low," which is the specific problem this combination replaces
    (see docs/model-audit-before.md worked examples B and C).

    `activity_floor`/`activity_weight` and `exposure_floor`/`exposure_weight`
    (model.yaml `combination:`) control how much a modifier can swing the
    population baseline up or down; `scale` rescales the result to 0-100.
    All are configurable, not hardcoded, and were chosen by checking the
    resulting distribution against real full-Sweden output (see
    docs/model-audit-after.md), not accepted blindly from a suggested range.
    """
    params = config.combination_params or {
        "activity_floor": 0.30, "activity_weight": 0.70,
        "exposure_floor": 0.75, "exposure_weight": 0.50, "scale": 105,
    }

    activity_multiplier = (config.activities or {}).get(activity_profile, 1.0)

    population_potential, population_terms = compute_population_potential(features, config)
    biting_activity, activity_terms = compute_biting_activity(features, config)
    exposure, exposure_terms = compute_exposure(features, config, activity_multiplier)

    population_fraction = clamp(population_potential / 100.0, 0.0, 1.0)
    activity_fraction = clamp(biting_activity / 100.0, 0.0, 1.0)
    # Deliberately the pre-activity-profile-multiplier exposure fraction
    # (exposure_terms["base_exposure_fraction"]) rather than the profile-
    # scaled `exposure` value -- the profile multiplier is applied once,
    # explicitly, as part of exposure_modifier below, not baked in twice.
    exposure_fraction = clamp(exposure_terms["base_exposure_fraction"], 0.0, 1.0)

    activity_modifier = params.get("activity_floor", 0.30) + params.get("activity_weight", 0.70) * activity_fraction
    exposure_modifier = (
        params.get("exposure_floor", 0.75) + params.get("exposure_weight", 0.50) * exposure_fraction
    ) * activity_multiplier

    risk_fraction = population_fraction * activity_modifier * exposure_modifier
    final_risk = clamp(risk_fraction * params.get("scale", 105), 0.0, 100.0)

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
        activity_modifier=round(activity_modifier, 4),
        exposure_modifier=round(exposure_modifier, 4),
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
