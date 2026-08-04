from __future__ import annotations

from feature_engineering import (
    GDD_TO_ADULT_C,
    _development_progress,
    _emergence_potential,
    _site_persistence_factor,
)


def test_development_progress_is_near_zero_immediately_after_a_rain_event():
    assert _development_progress(0.0) == 0.0
    assert _development_progress(5.0) < 0.15


def test_development_progress_reaches_full_after_enough_accumulated_warmth():
    assert _development_progress(GDD_TO_ADULT_C) == 1.0
    assert _development_progress(GDD_TO_ADULT_C * 2) == 1.0  # clamped, not >1


def test_development_progress_is_monotonic_with_accumulated_gdd():
    values = [_development_progress(g) for g in (0, 10, 20, 30, 40, 50, 60, 70)]
    assert values == sorted(values)


def test_emergence_heavy_rain_yesterday_alone_does_not_spike_immediately():
    """The exact reported problem: rain that fell 0-2 days ago has had
    almost no time (and thus almost no accumulated warmth) to develop into
    adults, regardless of how much rain fell."""
    heavy_rain_yesterday_only = _emergence_potential(
        rain_0_2d_mm=40.0, rain_3_6d_mm=0.0, rain_7_14d_mm=0.0, rain_15_21d_mm=0.0,
        gdd_since_0_2d=5.0,  # only ~1-2 days of modest warmth so far
        gdd_since_3_6d=0.0, gdd_since_7_14d=0.0, gdd_since_15_21d=0.0,
        site_persistence=0.8,
    )
    assert heavy_rain_yesterday_only < 0.15


def test_emergence_warm_rain_7_to_14_days_ago_raises_potential():
    """Rain old enough, in warm-enough weather, to have actually developed
    into adults should read as real emergence potential -- the case the
    old bell-curve-on-precipitation_14d_mm term treated identically to
    rain from yesterday."""
    old_rain_fully_developed = _emergence_potential(
        rain_0_2d_mm=0.0, rain_3_6d_mm=0.0, rain_7_14d_mm=25.0, rain_15_21d_mm=0.0,
        gdd_since_0_2d=0.0, gdd_since_3_6d=0.0,
        gdd_since_7_14d=70.0,  # comfortably past GDD_TO_ADULT_C
        gdd_since_15_21d=0.0,
        site_persistence=0.8,
    )
    no_rain_at_all = _emergence_potential(0, 0, 0, 0, 0, 0, 0, 0, site_persistence=0.8)
    assert old_rain_fully_developed > 0.15
    assert old_rain_fully_developed > no_rain_at_all


def test_emergence_cold_weather_delays_development_relative_to_warm():
    """Same rain, same bucket, but far less accumulated warmth since (cold
    northern weather) -- development, and therefore emergence potential,
    should be measurably lower."""
    warm = _emergence_potential(
        rain_0_2d_mm=0, rain_3_6d_mm=0, rain_7_14d_mm=25.0, rain_15_21d_mm=0,
        gdd_since_0_2d=0, gdd_since_3_6d=0, gdd_since_7_14d=70.0, gdd_since_15_21d=0,
        site_persistence=0.8,
    )
    cold = _emergence_potential(
        rain_0_2d_mm=0, rain_3_6d_mm=0, rain_7_14d_mm=25.0, rain_15_21d_mm=0,
        gdd_since_0_2d=0, gdd_since_3_6d=0, gdd_since_7_14d=8.0, gdd_since_15_21d=0,
        site_persistence=0.8,
    )
    assert cold < warm


def test_emergence_prolonged_dry_spell_reduces_potential_to_zero():
    dry = _emergence_potential(
        rain_0_2d_mm=0, rain_3_6d_mm=0, rain_7_14d_mm=0, rain_15_21d_mm=0,
        gdd_since_0_2d=40, gdd_since_3_6d=40, gdd_since_7_14d=80, gdd_since_15_21d=100,
        site_persistence=0.8,
    )
    assert dry == 0.0


def test_emergence_potential_is_bounded_0_to_1():
    saturated = _emergence_potential(
        rain_0_2d_mm=999, rain_3_6d_mm=999, rain_7_14d_mm=999, rain_15_21d_mm=999,
        gdd_since_0_2d=999, gdd_since_3_6d=999, gdd_since_7_14d=999, gdd_since_15_21d=999,
        site_persistence=1.0,
    )
    assert 0.0 <= saturated <= 1.0


def test_emergence_potential_scales_with_site_persistence():
    poor_site = _emergence_potential(0, 0, 25.0, 0, 0, 0, 70.0, 0, site_persistence=0.1)
    good_site = _emergence_potential(0, 0, 25.0, 0, 0, 0, 70.0, 0, site_persistence=1.0)
    assert poor_site < good_site


def test_site_persistence_factor_bounded_and_favours_wetland_low_slope():
    flat_wetland = _site_persistence_factor(slope_deg=0.5, wetland_fraction=0.9, water_body_density=0.9)
    steep_dry = _site_persistence_factor(slope_deg=14.0, wetland_fraction=0.0, water_body_density=0.0)
    assert 0.0 <= flat_wetland <= 1.0
    assert 0.0 <= steep_dry <= 1.0
    assert flat_wetland > steep_dry
