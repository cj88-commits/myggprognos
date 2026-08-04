from __future__ import annotations

from datetime import date

import pytest
from feature_engineering import daylight_hours
from solar import compute_solar_times

MALMO = (55.6050, 13.0038)
STOCKHOLM = (59.3293, 18.0686)
LULEA = (65.5848, 22.1567)
KIRUNA = (67.8558, 20.2253)
ABISKO = (68.3557, 18.7871)


def _daylight_span_hours(times) -> float | None:
    if times.sunrise_utc is None or times.sunset_utc is None:
        return None
    return (times.sunset_utc - times.sunrise_utc).total_seconds() / 3600.0


def test_malmo_june_has_a_long_day_with_early_sunrise_and_late_sunset():
    lat, lon = MALMO
    times = compute_solar_times(lat, lon, date(2026, 6, 21))
    assert not times.is_polar_day and not times.is_polar_night
    assert times.sunrise_utc is not None and times.sunset_utc is not None
    # ~04:33 CEST (UTC+2) = ~02:33 UTC; generous tolerance for the
    # simplified formula, tight enough to catch a real bug (e.g. a sign error).
    assert times.sunrise_utc.hour in (1, 2, 3)
    assert times.sunset_utc.hour in (18, 19, 20)
    assert _daylight_span_hours(times) > 16.0


def test_stockholm_april_daylight_matches_existing_daylight_hours_approximation():
    lat, lon = STOCKHOLM
    target = date(2026, 4, 15)
    times = compute_solar_times(lat, lon, target)
    span = _daylight_span_hours(times)
    assert span is not None
    # solar.py and feature_engineering.py::daylight_hours share the same
    # declination approximation, but solar.py additionally accounts for
    # atmospheric refraction + the sun's angular radius (zenith 90.833 deg,
    # the conventional almanac definition), while daylight_hours uses a
    # bare 90 deg horizon -- so solar.py's day is expected to run a bit
    # longer (roughly +8-16 min at Swedish latitudes), not identical.
    expected = daylight_hours(lat, target.timetuple().tm_yday)
    assert span == pytest.approx(expected, abs=0.3)
    assert span > expected


def test_lulea_july_has_a_very_long_day_close_to_but_not_quite_midnight_sun():
    lat, lon = LULEA
    times = compute_solar_times(lat, lon, date(2026, 7, 15))
    # Lulea sits just south of the Arctic Circle -- real (not polar) sunrise
    # and sunset, but only barely: a very long day.
    assert not times.is_polar_day and not times.is_polar_night
    assert _daylight_span_hours(times) > 18.0


def test_kiruna_midsummer_is_midnight_sun():
    lat, lon = KIRUNA
    times = compute_solar_times(lat, lon, date(2026, 6, 21))
    assert times.is_polar_day is True
    assert times.is_polar_night is False
    assert times.sunrise_utc is None and times.sunset_utc is None
    # Solar noon is still always defined, even with no sunrise/sunset.
    assert times.solar_noon_utc is not None


def test_kiruna_midwinter_is_polar_night():
    lat, lon = KIRUNA
    times = compute_solar_times(lat, lon, date(2026, 12, 21))
    assert times.is_polar_night is True
    assert times.is_polar_day is False
    assert times.sunrise_utc is None and times.sunset_utc is None


def test_kiruna_autumn_has_a_normal_short_but_real_day():
    """Northern autumn: neither polar day nor polar night, but a visibly
    shorter day than the same date further south."""
    lat, lon = KIRUNA
    target = date(2026, 10, 15)
    times = compute_solar_times(lat, lon, target)
    assert not times.is_polar_day and not times.is_polar_night
    span = _daylight_span_hours(times)
    assert span is not None
    assert 6.0 < span < 11.0

    stockholm_span = _daylight_span_hours(compute_solar_times(*STOCKHOLM, target))
    assert stockholm_span is not None
    assert span < stockholm_span


def test_abisko_above_kiruna_enters_midnight_sun_earlier_in_spring():
    """A cell further north should reach midnight-sun conditions on an
    earlier date than one further south -- checked around the seam where
    Kiruna itself is right at the edge (early June)."""
    target = date(2026, 6, 5)
    kiruna_times = compute_solar_times(*KIRUNA, target)
    abisko_times = compute_solar_times(*ABISKO, target)
    # Abisko (further north) reaching polar day while Kiruna (further
    # south) has not yet is the expected ordering; both already in polar
    # day, or neither, is also consistent depending on the exact date --
    # what must NOT happen is Kiruna being polar day while Abisko isn't.
    if kiruna_times.is_polar_day:
        assert abisko_times.is_polar_day


def test_sunrise_solar_noon_sunset_are_correctly_ordered():
    for lat, lon in (MALMO, STOCKHOLM):
        times = compute_solar_times(lat, lon, date(2026, 5, 1))
        assert times.sunrise_utc < times.solar_noon_utc < times.sunset_utc
        assert times.civil_dawn_utc < times.sunrise_utc
        assert times.sunset_utc < times.civil_dusk_utc


def test_solar_times_are_deterministic():
    a = compute_solar_times(*STOCKHOLM, date(2026, 5, 1))
    b = compute_solar_times(*STOCKHOLM, date(2026, 5, 1))
    assert a == b
