from __future__ import annotations

import pytest
from normal_baseline import (
    BaselineWarning,
    HistoricalRiskSample,
    NormalBaseline,
    _day_of_year_distance,
    categorize_relative_to_normal,
    compute_baseline,
)


def _samples(region: str, daypart: str, day_of_year: int, risks: list[float]) -> list[HistoricalRiskSample]:
    return [HistoricalRiskSample(region=region, day_of_year=day_of_year, daypart=daypart, risk=r) for r in risks]


def test_day_of_year_distance_wraps_across_the_year_boundary():
    assert _day_of_year_distance(362, 3, days_in_year=365) == 6
    assert _day_of_year_distance(10, 20) == 10
    assert _day_of_year_distance(1, 1) == 0


def test_compute_baseline_returns_warning_when_too_few_samples():
    samples = _samples("Svealand", "evening", 190, [40.0] * 5)
    result = compute_baseline(samples, "Svealand", 190, "evening", min_samples=20)
    assert isinstance(result, BaselineWarning)
    assert result.sample_count == 5


def test_compute_baseline_returns_baseline_with_enough_samples():
    samples = _samples("Svealand", "evening", 190, [40.0, 42.0, 38.0, 41.0, 39.0] * 5)
    result = compute_baseline(samples, "Svealand", 190, "evening", min_samples=20)
    assert isinstance(result, NormalBaseline)
    assert result.sample_count == 25
    assert result.mean == pytest.approx(40.0, abs=0.5)


def test_compute_baseline_only_uses_samples_within_the_window_and_matching_region_daypart():
    near = _samples("Svealand", "evening", 190, [50.0] * 25)
    far = _samples("Svealand", "evening", 250, [10.0] * 25)  # outside the day-of-year window
    wrong_region = _samples("Norrland", "evening", 190, [90.0] * 25)
    wrong_daypart = _samples("Svealand", "morning", 190, [5.0] * 25)

    result = compute_baseline(near + far + wrong_region + wrong_daypart, "Svealand", 190, "evening", min_samples=20)
    assert isinstance(result, NormalBaseline)
    assert result.mean == pytest.approx(50.0, abs=0.01)
    assert result.sample_count == 25


def test_compute_baseline_wraps_the_day_of_year_window_across_new_year():
    # Center day 3 (Jan 3), window should include late-December samples too.
    late_dec = _samples("Svealand", "evening", 362, [20.0] * 25)
    result = compute_baseline(late_dec, "Svealand", 3, "evening", window_days=10, min_samples=20)
    assert isinstance(result, NormalBaseline)


def test_categorize_relative_to_normal_bands():
    baseline = NormalBaseline(region="Svealand", day_of_year_center=190, daypart="evening", mean=40.0, stddev=10.0, sample_count=25)
    assert categorize_relative_to_normal(20.0, baseline) == "mycket_lagre_an_normalt"  # z = -2.0
    assert categorize_relative_to_normal(32.0, baseline) == "lagre_an_normalt"  # z = -0.8
    assert categorize_relative_to_normal(40.0, baseline) == "normalt"  # z = 0.0
    assert categorize_relative_to_normal(48.0, baseline) == "hogre_an_normalt"  # z = 0.8
    assert categorize_relative_to_normal(60.0, baseline) == "mycket_hogre_an_normalt"  # z = 2.0


def test_categorize_relative_to_normal_handles_zero_stddev_without_dividing_by_zero():
    baseline = NormalBaseline(region="Svealand", day_of_year_center=190, daypart="evening", mean=40.0, stddev=0.0, sample_count=25)
    assert categorize_relative_to_normal(90.0, baseline) == "normalt"
