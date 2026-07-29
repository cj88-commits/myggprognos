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
) -> Path:
    manifest = {
        "generated_at": generated_at,
        "model_version": model_version,
        "forecast_start": forecast_start,
        "forecast_end": forecast_end,
        "hourly_until": hourly_until,
        "cell_count": cell_count,
        "data_quality": data_quality,
        "daily_files": daily_files,
        "hourly_files": hourly_files,
        "activities": activities or {},
        "warnings": warnings or [],
    }
    path = out_dir / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


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
            if not (0.0 <= record["risk"] <= 10.0):
                raise OutputValidationError(f"Risk {record['risk']} out of [0,10] for {record['cell_id']} on {date_str}")
            if not (0.0 <= record["confidence"] <= 1.0):
                raise OutputValidationError(f"Confidence {record['confidence']} out of [0,1] for {record['cell_id']} on {date_str}")
            for component in ("population_potential", "biting_activity", "exposure"):
                if not (0.0 <= record[component] <= 10.0):
                    raise OutputValidationError(
                        f"{component} {record[component]} out of [0,10] for {record['cell_id']} on {date_str}"
                    )

    return warnings
