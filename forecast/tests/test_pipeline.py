from __future__ import annotations

import gzip
import json
from datetime import date, datetime, timedelta, timezone

from feature_engineering import SWEDEN_TZ
from grid import GridCell
from history_cache import INCREMENTAL_PAST_DAYS
from pipeline import HISTORY_DAYS_BACK, _local_daypart_target, run_pipeline
from weather import SyntheticWeatherProvider


def test_local_daypart_target_resolves_cest_correctly():
    # 2026-07-15 falls in CEST (UTC+2) -- 20:00 local ("evening") is 18:00 UTC.
    target = _local_daypart_target(date(2026, 7, 15), 20)
    assert target == datetime(2026, 7, 15, 18, tzinfo=timezone.utc)


def test_local_daypart_target_resolves_cet_correctly():
    # 2026-01-15 falls in CET (UTC+1) -- 20:00 local is 19:00 UTC, not 20:00.
    target = _local_daypart_target(date(2026, 1, 15), 20)
    assert target == datetime(2026, 1, 15, 19, tzinfo=timezone.utc)


def test_local_daypart_target_night_hour_stays_on_intended_local_calendar_day():
    # Regression for the bug where 23:00 UTC (meant to be 23:00 local) was
    # actually 01:00 the *next* local day in summer.
    target = _local_daypart_target(date(2026, 7, 15), 23)
    local = target.astimezone(SWEDEN_TZ)
    assert local.date() == date(2026, 7, 15)
    assert local.hour == 23


def test_local_daypart_target_morning_hour_is_not_shifted_to_wrong_side_of_midday():
    target = _local_daypart_target(date(2026, 7, 15), 8)
    local = target.astimezone(SWEDEN_TZ)
    assert local.hour == 8


def test_run_pipeline_sample_mode_produces_expected_assets(tmp_path):
    result = run_pipeline(
        sample=True,
        output_dir=tmp_path,
        run_time=datetime(2026, 7, 29, 6, tzinfo=timezone.utc),
    )

    assert result["cell_count"] == 5
    assert len(result["daily_files"]) == 7
    assert len(result["hourly_files"]) == 49

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cell_count"] == 5
    assert manifest["forecast_start"] == "2026-07-29"
    assert manifest["forecast_end"] == "2026-08-04"

    with gzip.open(tmp_path / "cells.json.gz") as fh:
        cells = json.load(fh)
    assert len(cells) == 5

    with gzip.open(tmp_path / "daily" / "2026-07-29.json.gz") as fh:
        daily = json.load(fh)
    assert len(daily) == 5
    for record in daily:
        assert 0.0 <= record["risk"] <= 100.0
        assert 0.0 <= record["confidence"] <= 100.0
        assert set(record["dayparts"]) == {"morning", "afternoon", "evening", "night"}
        assert record["explanation"]["summary"]
        assert isinstance(record["explanation_text"], list)

    with gzip.open(tmp_path / "hourly" / "2026-07-29T06.json.gz") as fh:
        hourly = json.load(fh)
    assert len(hourly) == 5

    assert manifest["series_files"]
    assert manifest["series_shard_count"] > 0
    from output import shard_for_cell_id

    shard = shard_for_cell_id(cells[0]["cell_id"], manifest["series_shard_count"])
    with gzip.open(tmp_path / "series" / f"{shard}.json.gz") as fh:
        series_shard = json.load(fh)
    assert cells[0]["cell_id"] in series_shard
    assert len(series_shard[cells[0]["cell_id"]]["daily"]) == 7
    assert len(series_shard[cells[0]["cell_id"]]["hourly"]) == 49


def test_run_pipeline_publishes_the_three_forecast_product_fields(tmp_path):
    """Myggläge / Myggrisk idag / Myggrisk just nu -- see docs/model-audit-after.md."""
    run_pipeline(
        sample=True,
        output_dir=tmp_path,
        run_time=datetime(2026, 7, 29, 6, tzinfo=timezone.utc),
    )

    with gzip.open(tmp_path / "daily" / "2026-07-29.json.gz") as fh:
        daily = json.load(fh)
    for record in daily:
        # "Myggrisk idag": daily_peak_risk must equal the peak daypart's own
        # risk (i.e. the max across morning/afternoon/evening/night), not a
        # separately-computed value that could silently disagree.
        daypart_risks = [d["risk"] for d in record["dayparts"].values()]
        assert record["daily_peak_risk"] == max(daypart_risks)
        assert record["daily_peak_risk"] == record["risk"]
        # "Myggläge": mosquito_abundance is population_potential, unaffected
        # by which daypart happens to be selected.
        assert record["mosquito_abundance"] == record["population_potential"]
        assert record["daily_peak_local_time"] in ("08:00", "14:00", "20:00", "23:00")
        assert 0.0 <= record["activity_modifier"]
        assert 0.0 <= record["exposure_modifier"]

    with gzip.open(tmp_path / "hourly" / "2026-07-29T06.json.gz") as fh:
        hourly = json.load(fh)
    for record in hourly:
        # "Myggrisk just nu": current_risk is this specific hour's own risk.
        assert record["current_risk"] == record["risk"]
        assert record["mosquito_abundance"] == record["population_potential"]


def test_run_pipeline_publishes_combination_and_threshold_config_in_manifest(tmp_path):
    """The frontend must read these from the manifest rather than holding
    an independently-drifting copy -- see docs/model-audit-before.md #5."""
    run_pipeline(
        sample=True,
        output_dir=tmp_path,
        run_time=datetime(2026, 7, 29, 6, tzinfo=timezone.utc),
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert set(manifest["combination"]) == {
        "activity_floor", "activity_weight", "exposure_floor", "exposure_weight", "scale",
    }
    assert len(manifest["thresholds"]["abundance"]) == 4
    assert manifest["thresholds"]["abundance"] == sorted(manifest["thresholds"]["abundance"])


def test_run_pipeline_lowers_confidence_per_cell_for_placeholder_static_data(tmp_path):
    """docs/model-audit-before.md bug #2: a cell individually falling back
    to placeholder static features (missing from cell_features.json) must
    NOT inherit the rest of the run's real-data confidence bonus. SE_STHLM
    is a known real entry in data/samples/static_features.json;
    SE_NOT_IN_STATIC_FILE deliberately isn't, forcing the missing-cell
    placeholder path for just that one cell within an otherwise
    static_placeholder=False run."""
    cells = [
        GridCell(cell_id="SE_STHLM", latitude=59.33, longitude=18.06, region="Svealand"),
        GridCell(cell_id="SE_NOT_IN_STATIC_FILE", latitude=59.33, longitude=18.06, region="Svealand"),
    ]
    run_pipeline(
        sample=True,
        static_placeholder=False,
        output_dir=tmp_path,
        cells_override=cells,
        run_time=datetime(2026, 7, 29, 6, tzinfo=timezone.utc),
    )

    with gzip.open(tmp_path / "hourly" / "2026-07-29T06.json.gz") as fh:
        hourly = json.load(fh)
    by_id = {r["cell_id"]: r for r in hourly}

    assert by_id["SE_NOT_IN_STATIC_FILE"]["confidence"] < by_id["SE_STHLM"]["confidence"]


def test_run_pipeline_does_not_rewrite_unchanged_files(tmp_path):
    run_time = datetime(2026, 7, 29, 6, tzinfo=timezone.utc)
    run_pipeline(sample=True, output_dir=tmp_path, run_time=run_time)
    manifest_mtime_1 = (tmp_path / "cells.json.gz").stat().st_mtime_ns

    run_pipeline(sample=True, output_dir=tmp_path, run_time=run_time)
    manifest_mtime_2 = (tmp_path / "cells.json.gz").stat().st_mtime_ns

    assert manifest_mtime_1 == manifest_mtime_2


class _RecordingProvider:
    """Wraps SyntheticWeatherProvider (for plausible, deterministic data)
    while recording the past_days/forecast_days every fetch_combined call
    actually requested, so tests can assert on the real pipeline's
    caching decisions rather than re-testing history_cache.py in
    isolation."""

    def __init__(self, run_time: datetime):
        self._inner = SyntheticWeatherProvider(today=run_time)
        self.calls: list[tuple[int, int]] = []

    def fetch_combined(self, points, past_days, forecast_days):
        self.calls.append((past_days, forecast_days))
        return self._inner.fetch_combined(points, past_days, forecast_days)


def test_run_pipeline_fetches_full_history_on_cold_cache_then_incremental_on_warm(tmp_path):
    cells = [GridCell(cell_id="SE_TEST", latitude=59.33, longitude=18.07, region="Svealand")]
    cache_path = tmp_path / "weather_history_cache.json.gz"
    run_time_1 = datetime(2026, 7, 29, 6, tzinfo=timezone.utc)

    provider_1 = _RecordingProvider(run_time_1)
    run_pipeline(
        sample=False,
        output_dir=tmp_path / "out1",
        history_cache_path=cache_path,
        cells_override=cells,
        weather_provider=provider_1,
        run_time=run_time_1,
    )

    assert provider_1.calls == [(HISTORY_DAYS_BACK, 7)]
    assert cache_path.exists()

    # A second run shortly after (well within the freshness threshold)
    # should only need to fill the small gap, not refetch everything.
    run_time_2 = run_time_1 + timedelta(hours=6)
    provider_2 = _RecordingProvider(run_time_2)
    run_pipeline(
        sample=False,
        output_dir=tmp_path / "out2",
        history_cache_path=cache_path,
        cells_override=cells,
        weather_provider=provider_2,
        run_time=run_time_2,
    )

    assert provider_2.calls == [(INCREMENTAL_PAST_DAYS, 7)]


class _CrashesAfterNCallsProvider:
    """Simulates the process being killed mid-fetch (e.g. GitHub's hard 6h
    job ceiling) by raising after a fixed number of fetch_combined calls
    (each call = one chunk, see CACHE_CHECKPOINT_CHUNK_CELLS)."""

    def __init__(self, run_time: datetime, crash_after_calls: int):
        self._inner = SyntheticWeatherProvider(today=run_time)
        self._crash_after_calls = crash_after_calls
        self.calls = 0

    def fetch_combined(self, points, past_days, forecast_days):
        self.calls += 1
        if self.calls > self._crash_after_calls:
            raise RuntimeError("simulated mid-flight kill")
        return self._inner.fetch_combined(points, past_days, forecast_days)


def test_history_cache_survives_a_crash_partway_through_the_fetch(tmp_path):
    from pipeline import CACHE_CHECKPOINT_CHUNK_CELLS
    from history_cache import load_history_cache

    # 2.5 chunks' worth of cells -- the crash happens after chunk 1
    # completes but before chunk 2 does, so only the first chunk's cells
    # should end up cached.
    chunk_size = CACHE_CHECKPOINT_CHUNK_CELLS
    cells = [
        GridCell(cell_id=f"SE_{i:05d}", latitude=59.0, longitude=18.0, region="Svealand")
        for i in range(int(chunk_size * 2.5))
    ]
    cache_path = tmp_path / "weather_history_cache.json.gz"
    run_time = datetime(2026, 7, 29, 6, tzinfo=timezone.utc)

    provider = _CrashesAfterNCallsProvider(run_time, crash_after_calls=1)
    try:
        run_pipeline(
            sample=False,
            output_dir=tmp_path / "out",
            history_cache_path=cache_path,
            cells_override=cells,
            weather_provider=provider,
            run_time=run_time,
        )
        assert False, "expected the simulated crash to propagate"
    except RuntimeError:
        pass

    cached = load_history_cache(cache_path)
    assert len(cached) == chunk_size
    assert set(cached) == {c.cell_id for c in cells[:chunk_size]}
