from __future__ import annotations

from datetime import datetime, timedelta, timezone

from history_cache import (
    cell_needs_full_backfill,
    load_history_cache,
    merge_cached_and_fresh,
    save_history_cache,
    split_history_for_cache,
)
from weather import HourlyWeather


def _weather(cell_id: str, times: list[str], base: float = 10.0) -> HourlyWeather:
    n = len(times)
    return HourlyWeather(
        cell_id=cell_id,
        latitude=59.0,
        longitude=18.0,
        times=times,
        temperature_2m=[base + i for i in range(n)],
        relative_humidity_2m=[60.0] * n,
        precipitation=[0.0] * n,
        wind_speed_10m=[2.0] * n,
        wind_gusts_10m=[4.0] * n,
        cloud_cover=[50.0] * n,
        soil_moisture=[0.2] * n,
    )


def test_load_history_cache_missing_file_returns_empty(tmp_path):
    assert load_history_cache(tmp_path / "nope.json.gz") == {}


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "cache.json.gz"
    weather = _weather("A", ["2026-07-01T00:00", "2026-07-01T01:00"])
    save_history_cache(path, {"A": weather})

    loaded = load_history_cache(path)

    assert loaded["A"].times == weather.times
    assert loaded["A"].temperature_2m == weather.temperature_2m


def test_cell_needs_full_backfill_when_no_cache_entry():
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    assert cell_needs_full_backfill(None, now, full_history_days=21) is True


def test_cell_needs_full_backfill_false_when_cache_covers_full_window():
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    # Cached history reaches back the full 21 days -> only a small
    # incremental top-up is needed, not a full re-fetch.
    cached = _weather("A", ["2026-06-29T00:00", "2026-07-19T00:00"])

    assert cell_needs_full_backfill(cached, now, full_history_days=21) is False


def test_cell_needs_full_backfill_true_when_cache_does_not_reach_back_far_enough():
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    # Cell was only ever incrementally topped up (e.g. a killed backfill
    # never reached it before this) -- earliest entry is nowhere near the
    # 21-day cutoff, so it still needs a full backfill.
    cached = _weather("A", ["2026-07-19T00:00"])

    assert cell_needs_full_backfill(cached, now, full_history_days=21) is True


def test_merge_cached_and_fresh_prefers_fresh_on_overlap():
    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    cached = _weather("A", ["2026-07-19T00:00", "2026-07-19T01:00"], base=1.0)
    fresh = _weather("A", ["2026-07-19T01:00", "2026-07-19T02:00"], base=100.0)

    merged = merge_cached_and_fresh(cached, fresh, now)

    assert merged.times == ["2026-07-19T00:00", "2026-07-19T01:00", "2026-07-19T02:00"]
    # 07-19T00:00 only in cached -> cached value; 07-19T01:00 in both -> fresh wins.
    assert merged.temperature_2m == [1.0, 100.0, 101.0]


def test_merge_cached_and_fresh_with_no_cache_returns_fresh():
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    fresh = _weather("A", ["2026-07-19T00:00"])

    merged = merge_cached_and_fresh(None, fresh, now)

    assert merged.times == fresh.times


def test_split_history_for_cache_drops_forecast_and_old_entries():
    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    times = [
        "2026-06-01T00:00",  # far older than the 21-day window -> dropped
        "2026-07-19T00:00",  # within window, in the past -> kept
        "2026-07-25T00:00",  # in the future (forecast) -> dropped
    ]
    weather = _weather("A", times)

    history_only = split_history_for_cache(weather, now, keep_days=21)

    assert history_only.times == ["2026-07-19T00:00"]
