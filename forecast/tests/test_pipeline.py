from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta, timezone

from grid import GridCell
from history_cache import INCREMENTAL_PAST_DAYS
from pipeline import HISTORY_DAYS_BACK, run_pipeline
from weather import SyntheticWeatherProvider


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
