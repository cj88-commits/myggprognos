"""Generated forecast output assets.

Writes the versioned, compact static assets consumed by the frontend:

    data/generated/latest/
      manifest.json
      cells.json.gz
      daily/<YYYY-MM-DD>.json.gz
      hourly/<YYYY-MM-DDTHH>.json.gz
      locations/index.json.gz

Files are only rewritten when their content actually changed (compared by
content hash), so unrelated scheduled runs don't churn the git history /
Pages deployment unnecessarily. Sanity checks (score ranges, coordinate
bounds, ordering, cell-count drift) run before anything is published so a
bad pipeline run cannot overwrite the last known-good forecast.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from config import GENERATED_DATA_DIR, MODEL_VERSION, SWEDEN_BBOX
from grid import GridCell
from static_features import StaticFeatures

logger = logging.getLogger("mosquito_forecast.output")


class OutputValidationError(Exception):
    pass


def _content_hash(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_gzip_json_if_changed(path: Path, obj: Any) -> bool:
    """Write gzip-compressed JSON only if content differs from what's on
    disk (compared via a sidecar .hash file, since gzip output isn't
    byte-stable across writes). Returns True if the file was (re)written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    hash_path = path.with_suffix(path.suffix + ".hash")
    new_hash = _content_hash(obj)

    if path.exists() and hash_path.exists():
        try:
            if hash_path.read_text(encoding="utf-8").strip() == new_hash:
                return False
        except OSError:
            pass

    payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp_path, "wb") as fh:
        fh.write(payload)
    tmp_path.replace(path)
    hash_path.write_text(new_hash, encoding="utf-8")
    return True


def write_cells_file(cells: list[GridCell], static_map: dict[str, StaticFeatures], out_dir: Path) -> Path:
    records = []
    for cell in cells:
        static = static_map.get(cell.cell_id)
        record = {
            "cell_id": cell.cell_id,
            "latitude": cell.latitude,
            "longitude": cell.longitude,
            "region": cell.region,
        }
        if static:
            record.update(
                {
                    "forest_fraction": static.forest_fraction,
                    "wetland_fraction": static.wetland_fraction,
                    "urban_fraction": static.urban_fraction,
                    "distance_to_water_km": static.distance_to_water_km,
                    "elevation_m": static.elevation_m,
                    "coastal_exposure": static.coastal_exposure,
                    # Geographic-model redesign (Phase 3/4/14): published so
                    # a future frontend can explain WHY a location's
                    # baseline differs geographically, independent of
                    # current weather -- see static_features.py.
                    "habitat_capacity": static.habitat_capacity,
                    "wetland_fraction_5km": static.wetland_fraction_5km,
                    "water_fraction_5km": static.water_fraction_5km,
                    "small_water_density": static.small_water_density,
                    "floodplain_potential": static.floodplain_potential,
                    "major_lake_interior": static.major_lake_interior,
                }
            )
        records.append(record)
    path = out_dir / "cells.json.gz"
    _write_gzip_json_if_changed(path, records)
    return path


def write_daily_file(date_str: str, records: list[dict], out_dir: Path) -> Path:
    path = out_dir / "daily" / f"{date_str}.json.gz"
    _write_gzip_json_if_changed(path, records)
    return path


def write_hourly_file(hour_str: str, records: list[dict], out_dir: Path) -> Path:
    path = out_dir / "hourly" / f"{hour_str}.json.gz"
    _write_gzip_json_if_changed(path, records)
    return path


def write_locations_index(places: list[dict], out_dir: Path) -> Path:
    path = out_dir / "locations" / "index.json.gz"
    _write_gzip_json_if_changed(path, places)
    return path


DEFAULT_SERIES_SHARD_COUNT = 128


def shard_for_cell_id(cell_id: str, shard_count: int = DEFAULT_SERIES_SHARD_COUNT) -> int:
    """Stable djb2 hash -> shard index. Deterministic across processes/
    languages (unlike Python's randomized-per-process `hash()`), so the
    frontend can independently compute the same shard for a cell_id without
    needing a lookup table. Ported to frontend/src/lib/sharding.ts -- keep
    both in sync."""
    h = 5381
    for ch in cell_id:
        h = ((h * 33) + ord(ch)) & 0xFFFFFFFF
    return h % shard_count


def write_series_shards(
    series_by_cell: dict[str, dict],
    out_dir: Path,
    shard_count: int = DEFAULT_SERIES_SHARD_COUNT,
) -> list[str]:
    """Write small, sharded per-cell time-series files
    (series/<shard>.json.gz, each {cell_id: {"daily": [...], "hourly": [...]}}),
    so the frontend's location panel can fetch one small file instead of all
    7 daily + 49 hourly full-grid files just to chart a single cell. See
    README "Location series data" and frontend/src/hooks/useForecastData.ts.
    """
    shards: dict[int, dict[str, dict]] = {i: {} for i in range(shard_count)}
    for cell_id, series in series_by_cell.items():
        shard = shard_for_cell_id(cell_id, shard_count)
        shards[shard][cell_id] = series

    written: list[str] = []
    for shard_index, payload in shards.items():
        rel_path = f"series/{shard_index}.json.gz"
        path = out_dir / "series" / f"{shard_index}.json.gz"
        _write_gzip_json_if_changed(path, payload)
        written.append(rel_path)
    return written


def write_manifest(
    out_dir: Path,
    generated_at: str,
    forecast_start: str,
    forecast_end: str,
    hourly_until: str,
    cell_count: int,
    daily_files: list[str],
    hourly_files: list[str],
    data_quality: str = "normal",
    model_version: str = MODEL_VERSION,
    activities: dict[str, float] | None = None,
    warnings: list[str] | None = None,
    series_files: list[str] | None = None,
    series_shard_count: int = DEFAULT_SERIES_SHARD_COUNT,
    combination: dict[str, float] | None = None,
    thresholds: dict[str, list[float]] | None = None,
    build_sha: str | None = None,
) -> Path:
    manifest = {
        "generated_at": generated_at,
        "model_version": model_version,
        # Exact source commit this run's code came from (docs/wind-calm-
        # investigation.md item 11) -- lets a future "why did the forecast
        # change on date X" question be answered by `git show <sha>`
        # instead of guessing from generated_at/model_version alone (the
        # model.yaml version only changes on deliberate formula edits, not
        # every commit). "unknown" if it couldn't be resolved (e.g. no git
        # history available in the build environment).
        "build_sha": build_sha or "unknown",
        "forecast_start": forecast_start,
        "forecast_end": forecast_end,
        "hourly_until": hourly_until,
        "cell_count": cell_count,
        "data_quality": data_quality,
        "daily_files": daily_files,
        "hourly_files": hourly_files,
        "activities": activities or {},
        "warnings": warnings or [],
        "series_files": series_files or [],
        "series_shard_count": series_shard_count,
        # The exact combination constants model.py::compute_score used for
        # this run (see model.yaml `combination:`) -- published so the
        # frontend's client-side re-derivation (for a different activity
        # profile) reads them from here instead of holding an independent,
        # potentially-drifting hardcoded copy (see docs/model-audit-before.md
        # #8 and #5 on backend/frontend duplication risk).
        "combination": combination or {},
        # Category-band boundaries per product (see model.yaml `thresholds:`)
        # -- published so the frontend never holds an independently-
        # drifting copy of what counts as "high" abundance vs. "high" risk.
        "thresholds": thresholds or {},
    }
    path = out_dir / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def prune_stale_output(out_dir: Path, daily_files: list[str], hourly_files: list[str]) -> list[str]:
    """Delete daily/ and hourly/ files (plus their .hash sidecars) that fall
    outside the window the just-written manifest actually references.

    `write_daily_file`/`write_hourly_file` only ever add files -- nothing
    upstream ever removed the ones a rolling forecast window has since moved
    past, so every date/hour this pipeline has ever produced was
    accumulating on disk (and, historically, in git) forever. The active
    window is derived directly from `daily_files`/`hourly_files` (the same
    lists just passed to `write_manifest`) rather than a hardcoded day count,
    so this stays correct if FORECAST_DAYS/HOURLY_HORIZON_HOURS ever change.

    series/<shard>.json.gz and cells.json.gz are deliberately never touched
    here: series shards hold each cell's full historical daily+hourly
    series by design (see write_series_shards), not a rolling window, and
    cells.json.gz has no date-keyed siblings to accumulate.
    """
    keep = set(daily_files) | set(hourly_files)
    removed: list[str] = []
    for subdir in ("daily", "hourly"):
        dir_path = out_dir / subdir
        if not dir_path.exists():
            continue
        for file_path in sorted(dir_path.glob("*.json.gz")):
            rel_path = f"{subdir}/{file_path.name}"
            if rel_path in keep:
                continue
            file_path.unlink()
            hash_path = file_path.with_suffix(file_path.suffix + ".hash")
            if hash_path.exists():
                hash_path.unlink()
            removed.append(rel_path)
    if removed:
        logger.info("Pruned %d stale forecast file(s) outside the active window", len(removed))
    return removed


def load_previous_manifest(out_dir: Path) -> dict | None:
    path = out_dir / "manifest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def run_sanity_checks(
    cells: list[GridCell],
    daily_records_by_date: dict[str, list[dict]],
    previous_cell_count: int | None,
    min_cell_count_ratio: float = 0.9,
) -> list[str]:
    """Raise OutputValidationError on any failed check; return a list of
    non-fatal warnings otherwise (per spec section 20)."""
    warnings: list[str] = []

    if not cells:
        raise OutputValidationError("Generated grid has zero cells")

    for cell in cells:
        if not (SWEDEN_BBOX["min_lat"] - 0.5 <= cell.latitude <= SWEDEN_BBOX["max_lat"] + 0.5):
            raise OutputValidationError(f"Cell {cell.cell_id} latitude {cell.latitude} out of expected bounds")
        if not (SWEDEN_BBOX["min_lon"] - 0.5 <= cell.longitude <= SWEDEN_BBOX["max_lon"] + 0.5):
            raise OutputValidationError(f"Cell {cell.cell_id} longitude {cell.longitude} out of expected bounds")

    if previous_cell_count is not None and previous_cell_count > 0:
        ratio = len(cells) / previous_cell_count
        if ratio < min_cell_count_ratio:
            raise OutputValidationError(
                f"Cell count dropped from {previous_cell_count} to {len(cells)} "
                f"({ratio:.0%} of previous) -- refusing to publish"
            )

    dates = sorted(daily_records_by_date.keys())
    if dates != list(daily_records_by_date.keys()) and dates:
        warnings.append("Daily records were not supplied in chronological order")

    required_fields = {"cell_id", "risk", "population_potential", "biting_activity", "exposure", "confidence"}
    for date_str, records in daily_records_by_date.items():
        for record in records:
            missing = required_fields - record.keys()
            if missing:
                raise OutputValidationError(f"Daily record for {date_str} missing fields: {missing}")
            if not (0.0 <= record["risk"] <= 100.0):
                raise OutputValidationError(f"Risk {record['risk']} out of [0,100] for {record['cell_id']} on {date_str}")
            if not (0.0 <= record["confidence"] <= 100.0):
                raise OutputValidationError(f"Confidence {record['confidence']} out of [0,100] for {record['cell_id']} on {date_str}")
            for component in ("population_potential", "biting_activity", "exposure"):
                if not (0.0 <= record[component] <= 100.0):
                    raise OutputValidationError(
                        f"{component} {record[component]} out of [0,100] for {record['cell_id']} on {date_str}"
                    )

    return warnings
