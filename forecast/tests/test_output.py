from __future__ import annotations

import gzip
import json

import pytest
from grid import generate_sample_grid
from output import (
    OutputValidationError,
    prune_stale_output,
    run_sanity_checks,
    write_cells_file,
    write_daily_file,
    write_hourly_file,
    write_manifest,
    write_series_shards,
)
from static_features import generate_placeholder_static_features


def _valid_daily_record(cell_id: str) -> dict:
    return {
        "cell_id": cell_id,
        "risk": 42.0,
        "population_potential": 50.0,
        "biting_activity": 40.0,
        "exposure": 35.0,
        "confidence": 70.0,
    }


def test_write_cells_file_produces_readable_gzip(tmp_path):
    cells = generate_sample_grid()
    static_map = {c.cell_id: generate_placeholder_static_features(c) for c in cells}

    path = write_cells_file(cells, static_map, tmp_path)

    with gzip.open(path) as fh:
        records = json.load(fh)
    assert len(records) == len(cells)
    assert records[0]["cell_id"] == cells[0].cell_id


def test_write_daily_file_skips_rewrite_when_unchanged(tmp_path):
    cells = generate_sample_grid()
    records = [_valid_daily_record(c.cell_id) for c in cells]

    path1 = write_daily_file("2026-07-29", records, tmp_path)
    mtime1 = path1.stat().st_mtime_ns

    path2 = write_daily_file("2026-07-29", records, tmp_path)
    mtime2 = path2.stat().st_mtime_ns

    assert mtime1 == mtime2  # not rewritten


def test_write_daily_file_rewrites_when_content_changes(tmp_path):
    cells = generate_sample_grid()
    records = [_valid_daily_record(c.cell_id) for c in cells]
    write_daily_file("2026-07-29", records, tmp_path)

    records[0]["risk"] = 99.0
    path = write_daily_file("2026-07-29", records, tmp_path)

    with gzip.open(path) as fh:
        reloaded = json.load(fh)
    assert reloaded[0]["risk"] == 99.0


def test_sanity_checks_reject_out_of_range_score():
    cells = generate_sample_grid()
    bad_record = _valid_daily_record(cells[0].cell_id)
    bad_record["risk"] = 150.0
    with pytest.raises(OutputValidationError):
        run_sanity_checks(cells, {"2026-07-29": [bad_record]}, previous_cell_count=None)


def test_sanity_checks_reject_out_of_range_confidence():
    cells = generate_sample_grid()
    bad_record = _valid_daily_record(cells[0].cell_id)
    bad_record["confidence"] = 150.0
    with pytest.raises(OutputValidationError):
        run_sanity_checks(cells, {"2026-07-29": [bad_record]}, previous_cell_count=None)


def test_sanity_checks_reject_missing_field():
    cells = generate_sample_grid()
    bad_record = _valid_daily_record(cells[0].cell_id)
    del bad_record["exposure"]
    with pytest.raises(OutputValidationError):
        run_sanity_checks(cells, {"2026-07-29": [bad_record]}, previous_cell_count=None)


def test_sanity_checks_reject_empty_grid():
    with pytest.raises(OutputValidationError):
        run_sanity_checks([], {}, previous_cell_count=None)


def test_sanity_checks_reject_large_cell_count_drop():
    cells = generate_sample_grid()
    records = [_valid_daily_record(c.cell_id) for c in cells]
    with pytest.raises(OutputValidationError):
        run_sanity_checks(cells, {"2026-07-29": records}, previous_cell_count=1000)


def test_sanity_checks_pass_for_valid_data():
    cells = generate_sample_grid()
    records = [_valid_daily_record(c.cell_id) for c in cells]
    warnings = run_sanity_checks(cells, {"2026-07-29": records}, previous_cell_count=None)
    assert warnings == []


def test_manifest_written_as_valid_json(tmp_path):
    path = write_manifest(
        out_dir=tmp_path,
        generated_at="2026-07-29T06:00:00Z",
        forecast_start="2026-07-29",
        forecast_end="2026-08-04",
        hourly_until="2026-07-31T06:00:00Z",
        cell_count=5,
        daily_files=["daily/2026-07-29.json.gz"],
        hourly_files=["hourly/2026-07-29T06.json.gz"],
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["cell_count"] == 5
    assert manifest["model_version"]


def test_prune_stale_output_removes_files_outside_active_window(tmp_path):
    cells = generate_sample_grid()
    records = [_valid_daily_record(c.cell_id) for c in cells]

    # One stale date/hour from a previous run's window, plus one current.
    write_daily_file("2026-07-01", records, tmp_path)
    write_daily_file("2026-07-29", records, tmp_path)
    write_hourly_file("2026-07-01T06", records, tmp_path)
    write_hourly_file("2026-07-29T06", records, tmp_path)

    removed = prune_stale_output(
        tmp_path,
        daily_files=["daily/2026-07-29.json.gz"],
        hourly_files=["hourly/2026-07-29T06.json.gz"],
    )

    assert sorted(removed) == ["daily/2026-07-01.json.gz", "hourly/2026-07-01T06.json.gz"]
    assert not (tmp_path / "daily" / "2026-07-01.json.gz").exists()
    assert not (tmp_path / "daily" / "2026-07-01.json.gz.hash").exists()
    assert not (tmp_path / "hourly" / "2026-07-01T06.json.gz").exists()
    assert (tmp_path / "daily" / "2026-07-29.json.gz").exists()
    assert (tmp_path / "hourly" / "2026-07-29T06.json.gz").exists()


def test_prune_stale_output_keeps_everything_in_the_active_window(tmp_path):
    cells = generate_sample_grid()
    records = [_valid_daily_record(c.cell_id) for c in cells]
    write_daily_file("2026-07-29", records, tmp_path)
    write_hourly_file("2026-07-29T06", records, tmp_path)

    removed = prune_stale_output(
        tmp_path,
        daily_files=["daily/2026-07-29.json.gz"],
        hourly_files=["hourly/2026-07-29T06.json.gz"],
    )

    assert removed == []
    assert (tmp_path / "daily" / "2026-07-29.json.gz").exists()
    assert (tmp_path / "hourly" / "2026-07-29T06.json.gz").exists()


def test_prune_stale_output_never_touches_series_shards_or_cells_file(tmp_path):
    cells = generate_sample_grid()
    static_map = {c.cell_id: generate_placeholder_static_features(c) for c in cells}
    write_cells_file(cells, static_map, tmp_path)
    series_by_cell = {c.cell_id: {"daily": [], "hourly": []} for c in cells}
    write_series_shards(series_by_cell, tmp_path, shard_count=4)

    removed = prune_stale_output(tmp_path, daily_files=[], hourly_files=[])

    assert removed == []
    assert (tmp_path / "cells.json.gz").exists()
    for shard_index in range(4):
        assert (tmp_path / "series" / f"{shard_index}.json.gz").exists()


def test_prune_stale_output_no_op_when_directories_missing(tmp_path):
    removed = prune_stale_output(tmp_path, daily_files=["daily/2026-07-29.json.gz"], hourly_files=[])
    assert removed == []
