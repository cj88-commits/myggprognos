""""Jamfort med normalt" -- how unusual today's forecast is relative to
what's typical for this location and time of year.

NOT wired into the production pipeline or exposed in the frontend yet --
see NORMAL_COMPARISON_ENABLED below. Computing a real baseline requires an
archive of historical daily forecast runs spanning at least a few full
seasons (so a given day-of-year window has enough independent samples to
mean something); this repository currently only retains the current
forecast run's output (data/generated/latest) plus a rolling ~21-day raw
weather history cache used for feature lag windows -- neither is a
climatological archive. Building this module now, fully implemented and
tested against synthetic multi-year data, means the mechanism is ready and
correct the moment a real archive exists, rather than needing to be
designed from scratch later.

How "normal" WOULD be calculated once enabled:
  For a given (region, day-of-year window, daypart), collect every
  historical daily risk value recorded for cells in that region whose date
  falls within +/- BASELINE_WINDOW_DAYS of that day-of-year (wrapping
  across the Dec/Jan boundary), across as many past forecast runs as have
  been archived. The mean and standard deviation of that sample are the
  baseline; today's actual value is expressed as a z-score against it and
  bucketed into 5 categories.

  Deliberately per-REGION (Gotaland/Svealand/Norrland), not per-cell: with
  a new archive, any single cell won't have enough historical samples in a
  day-of-year window to compute a meaningful mean/stddev for a long time.
  Falling back to a national baseline instead of labelling a real per-
  region difference as "normal" would be worse than being coarse -- see
  the module-level warning in compute_baseline().
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

# Not exposed anywhere in the frontend or pipeline output while this is
# False. Flip only once a genuine multi-season archive of historical daily
# runs exists to compute compute_baseline() from -- see module docstring.
NORMAL_COMPARISON_ENABLED = False

BASELINE_WINDOW_DAYS = 10
MIN_SAMPLES_FOR_BASELINE = 20

# z-score band edges (symmetric) -> 5 categories.
Z_SCORE_BAND_EDGES = (-1.5, -0.5, 0.5, 1.5)
CATEGORY_KEYS = (
    "mycket_lagre_an_normalt",
    "lagre_an_normalt",
    "normalt",
    "hogre_an_normalt",
    "mycket_hogre_an_normalt",
)


@dataclass(frozen=True)
class HistoricalRiskSample:
    """One historical daily-peak-risk record, the minimal shape
    compute_baseline() needs -- deliberately not the full DailyRecord, so
    a future archive format only needs to supply these four fields."""

    region: str
    day_of_year: int
    daypart: str
    risk: float


@dataclass(frozen=True)
class NormalBaseline:
    region: str
    day_of_year_center: int
    daypart: str
    mean: float
    stddev: float
    sample_count: int


@dataclass(frozen=True)
class BaselineWarning:
    region: str
    day_of_year_center: int
    daypart: str
    sample_count: int
    message: str


@dataclass
class BaselineResult:
    baselines: dict[tuple[str, int, str], NormalBaseline] = field(default_factory=dict)
    warnings: list[BaselineWarning] = field(default_factory=list)


def _day_of_year_distance(a: int, b: int, days_in_year: int = 365) -> int:
    """Circular distance so Dec 28 (day 362) and Jan 3 (day 3) are treated
    as 6 days apart, not 359."""
    diff = abs(a - b)
    return min(diff, days_in_year - diff)


def compute_baseline(
    samples: list[HistoricalRiskSample],
    region: str,
    day_of_year_center: int,
    daypart: str,
    window_days: int = BASELINE_WINDOW_DAYS,
    min_samples: int = MIN_SAMPLES_FOR_BASELINE,
) -> NormalBaseline | BaselineWarning:
    """Returns a NormalBaseline if enough historical samples exist for this
    (region, day-of-year window, daypart), otherwise a BaselineWarning
    explaining why not -- callers must handle both, never silently
    substitute a national or all-time average for a missing regional/
    seasonal baseline (that would mislabel a real difference as "normal"
    just because the archive is thin)."""
    matching = [
        s.risk
        for s in samples
        if s.region == region
        and s.daypart == daypart
        and _day_of_year_distance(s.day_of_year, day_of_year_center) <= window_days
    ]
    if len(matching) < min_samples:
        return BaselineWarning(
            region=region,
            day_of_year_center=day_of_year_center,
            daypart=daypart,
            sample_count=len(matching),
            message=(
                f"Only {len(matching)} historical samples for {region}/{daypart} within "
                f"+/-{window_days} days of day {day_of_year_center} (need >= {min_samples}) -- "
                f"no reliable baseline yet."
            ),
        )
    return NormalBaseline(
        region=region,
        day_of_year_center=day_of_year_center,
        daypart=daypart,
        mean=round(statistics.mean(matching), 3),
        stddev=round(statistics.pstdev(matching), 3) if len(matching) > 1 else 0.0,
        sample_count=len(matching),
    )


def categorize_relative_to_normal(current_value: float, baseline: NormalBaseline) -> str:
    """5-category label from a z-score against the baseline. A near-zero
    stddev (a suspiciously *too* stable historical sample -- see the
    diagnostics warning this would feed) is treated as "normal" rather than
    dividing by ~zero and reporting a wild z-score."""
    if baseline.stddev <= 1e-6:
        return CATEGORY_KEYS[2]
    z = (current_value - baseline.mean) / baseline.stddev
    index = 0
    for edge in Z_SCORE_BAND_EDGES:
        if z >= edge:
            index += 1
    return CATEGORY_KEYS[index]
