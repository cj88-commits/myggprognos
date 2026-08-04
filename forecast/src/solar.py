"""Deterministic, offline solar timing (sunrise/sunset/civil twilight).

No external API or dependency: standard NOAA-style simplified solar
position formulas (solar declination, equation of time, hour angle),
consistent in approach and precision with the existing day-length
approximation already used in feature_engineering.py::daylight_hours.
Accurate to within a few minutes for mid/high latitudes -- more than
sufficient for a mosquito-activity timing curve, not a navigation tool.

At high latitude in summer/winter the sun may not cross the horizon at
all (midnight sun / polar night); `SolarTimes.sunrise_utc`/`sunset_utc`
are None in that case, with `is_polar_day`/`is_polar_night` set instead
of raising or returning a nonsensical time. Kiruna (67.85N) sits above the
Arctic Circle, so it hits both conditions at different times of year --
see tests/test_solar.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

# Standard "sunrise/sunset" zenith angle: 90 deg (true horizon) + ~0.833 deg
# for atmospheric refraction near the horizon and the sun's own angular
# radius -- the conventional definition used by almanacs/NOAA's calculator.
SUNRISE_SUNSET_ZENITH_DEG = 90.833
# Civil twilight: sun 6 deg below the horizon -- the usual "still enough
# light to make out shapes" threshold.
CIVIL_TWILIGHT_ZENITH_DEG = 96.0


@dataclass(frozen=True)
class SolarTimes:
    sunrise_utc: datetime | None
    sunset_utc: datetime | None
    solar_noon_utc: datetime
    civil_dawn_utc: datetime | None
    civil_dusk_utc: datetime | None
    # True when the sun never sets / never rises above SUNRISE_SUNSET_ZENITH_DEG
    # that day at this latitude -- mutually exclusive.
    is_polar_day: bool
    is_polar_night: bool


def _equation_of_time_minutes(day_of_year: int) -> float:
    """How far a sundial reads ahead of/behind clock time, in minutes --
    caused by Earth's elliptical orbit and axial tilt. Ranges roughly
    -14 to +16 minutes over the year."""
    b = math.radians(360.0 / 365.0 * (day_of_year - 81))
    return 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)


def _declination_rad(day_of_year: int) -> float:
    """Same approximation as feature_engineering.py::daylight_hours, kept
    identical rather than re-derived so the two stay consistent."""
    return 0.4093 * math.sin(2 * math.pi / 365 * (day_of_year - 81))


def _cos_hour_angle(latitude: float, declination_rad: float, zenith_deg: float) -> float:
    lat_rad = math.radians(latitude)
    return (math.cos(math.radians(zenith_deg)) - math.sin(lat_rad) * math.sin(declination_rad)) / (
        math.cos(lat_rad) * math.cos(declination_rad)
    )


def _hour_angle_rad(latitude: float, declination_rad: float, zenith_deg: float) -> float | None:
    """Half the sun's above-threshold arc, in radians -- None if the sun
    never crosses `zenith_deg` at all that day (permanently above/below)."""
    cos_h = _cos_hour_angle(latitude, declination_rad, zenith_deg)
    if cos_h < -1.0 or cos_h > 1.0:
        return None
    return math.acos(cos_h)


def compute_solar_times(latitude: float, longitude: float, target_date: date) -> SolarTimes:
    day_of_year = target_date.timetuple().tm_yday
    declination = _declination_rad(day_of_year)
    eot_minutes = _equation_of_time_minutes(day_of_year)

    # Solar noon in UTC: clock noon, shifted by the longitude's time-zone-
    # equivalent offset (15 deg per hour, East positive) and the equation
    # of time.
    solar_noon_offset_hours = -(longitude / 15.0) - (eot_minutes / 60.0)
    solar_noon_utc = datetime(
        target_date.year, target_date.month, target_date.day, 12, tzinfo=timezone.utc
    ) + timedelta(hours=solar_noon_offset_hours)

    sunrise_utc = sunset_utc = None
    is_polar_day = is_polar_night = False
    h = _hour_angle_rad(latitude, declination, SUNRISE_SUNSET_ZENITH_DEG)
    if h is not None:
        sunrise_utc = solar_noon_utc - timedelta(hours=math.degrees(h) / 15.0)
        sunset_utc = solar_noon_utc + timedelta(hours=math.degrees(h) / 15.0)
    else:
        cos_h = _cos_hour_angle(latitude, declination, SUNRISE_SUNSET_ZENITH_DEG)
        # cos(H) < -1 means even the *lowest* point of the sun's daily arc
        # stays above the horizon (sun never sets); > 1 means even the
        # *highest* point stays below it (sun never rises).
        is_polar_day = cos_h < -1.0
        is_polar_night = cos_h > 1.0

    civil_dawn_utc = civil_dusk_utc = None
    h_civil = _hour_angle_rad(latitude, declination, CIVIL_TWILIGHT_ZENITH_DEG)
    if h_civil is not None:
        civil_dawn_utc = solar_noon_utc - timedelta(hours=math.degrees(h_civil) / 15.0)
        civil_dusk_utc = solar_noon_utc + timedelta(hours=math.degrees(h_civil) / 15.0)

    return SolarTimes(
        sunrise_utc=sunrise_utc,
        sunset_utc=sunset_utc,
        solar_noon_utc=solar_noon_utc,
        civil_dawn_utc=civil_dawn_utc,
        civil_dusk_utc=civil_dusk_utc,
        is_polar_day=is_polar_day,
        is_polar_night=is_polar_night,
    )
