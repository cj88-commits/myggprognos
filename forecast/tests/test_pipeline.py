from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone

from pipeline import merge_weather, run_pipeline
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


def test_merge_weather_prefers_forecast_on_overlap():
    provider = SyntheticWeatherProvider()
    from grid import GridCell

    cell = GridCell(cell_id="X", latitude=59.0, longitude=18.0)
    history = provider.fetch_recent_history([cell], days_back=3)[cell.cell_id]
    forecast = provider.fetch_forecast([cell], datetime(2026, 7, 29).date(), datetime(2026, 7, 29).date())[cell.cell_id]

    merged = merge_weather(history, forecast)

    assert merged.times == sorted(set(merged.times))
    assert len(merged.temperature_2m) == len(merged.times)
