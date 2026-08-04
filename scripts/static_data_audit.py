#!/usr/bin/env python
"""Production static-feature audit.

Item 21 of the "biologically coherent map" iteration: before trusting
geographical variation on the map, verify how much of it is backed by real
GIS data (ESA WorldCover / NMD2023 / Copernicus DEM, see static_features.py)
versus the deterministic-but-synthetic placeholder generator. This is a
read-only report -- it makes NO model or pipeline changes.

Coverage is checked two ways:
  1. Grid coverage: does data/static/cell_features.json (the file the
     pipeline actually reads) have an entry for every cell in the current
     grid.json? A cell missing here is exactly the case that triggers
     per-cell placeholder generation in pipeline.py at run time.
  2. Recorded provenance: for cells that DO have an entry, does that entry
     carry `is_placeholder: true` (see static_features.py::StaticFeatures)?
     This catches an already-materialized cell_features.json that itself
     was built from placeholders (e.g. a `--sample`-style run, or a
     dataset generated before raster tiles were downloaded).

Usage:
    python scripts/static_data_audit.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import _pathsetup  # noqa: F401
from config import GENERATED_DATA_DIR, STATIC_DATA_DIR

# Raster-derived fields -- checked for source directory presence, not
# per-feature provenance (StaticFeatures only records one whole-record
# is_placeholder flag, not per-field source; see module docstring).
RASTER_SOURCES = {
    "forest_fraction / wetland_fraction / urban_fraction / water_fraction / distance_to_water_km": [
        "worldcover", "nmd",
    ],
    "elevation_m / slope_deg": ["dem"],
}


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def build_audit(static_data_dir: Path) -> dict[str, Any]:
    grid_path = static_data_dir / "grid.json"
    features_path = static_data_dir / "cell_features.json"

    grid_cell_ids = {c["cell_id"] for c in _load_json(grid_path)} if grid_path.exists() else set()
    features = _load_json(features_path) if features_path.exists() else []
    features_by_id = {f["cell_id"]: f for f in features}

    covered_ids = grid_cell_ids & set(features_by_id)
    missing_ids = grid_cell_ids - set(features_by_id)  # would placeholder-fallback at pipeline run time
    recorded_placeholder_ids = {
        cid for cid, f in features_by_id.items() if cid in grid_cell_ids and f.get("is_placeholder", False)
    }

    total = len(grid_cell_ids)
    placeholder_total = len(missing_ids) + len(recorded_placeholder_ids)
    real_total = total - placeholder_total

    raster_source_status = {}
    for feature_group, dirs in RASTER_SOURCES.items():
        present = {d: (static_data_dir / d).is_dir() and any((static_data_dir / d).glob("*.tif")) for d in dirs}
        raster_source_status[feature_group] = present

    return {
        "grid_cell_count": total,
        "cell_features_entry_count": len(features_by_id),
        "cells_missing_from_cell_features_json": len(missing_ids),
        "cells_recorded_as_placeholder_in_cell_features_json": len(recorded_placeholder_ids),
        "placeholder_cells_total": placeholder_total,
        "real_data_cells_total": real_total,
        "placeholder_fraction": round(placeholder_total / total, 4) if total else None,
        "raster_source_tiles_present": raster_source_status,
        "sample_missing_cell_ids": sorted(missing_ids)[:20],
        "sample_recorded_placeholder_cell_ids": sorted(recorded_placeholder_ids)[:20],
    }


def render_markdown(audit: dict[str, Any]) -> str:
    total = audit["grid_cell_count"]
    placeholder = audit["placeholder_cells_total"]
    pct = f"{audit['placeholder_fraction']:.1%}" if audit["placeholder_fraction"] is not None else "n/a"

    lines = [
        "# Production static-feature audit",
        "",
        f"**Placeholder cells: {placeholder} of {total} ({pct})**",
        "",
        f"- Cells in current grid: {total}",
        f"- Entries found in cell_features.json: {audit['cell_features_entry_count']}",
        f"- Missing from cell_features.json (would placeholder-fallback at run time): "
        f"{audit['cells_missing_from_cell_features_json']}",
        f"- Recorded as placeholder inside cell_features.json itself: "
        f"{audit['cells_recorded_as_placeholder_in_cell_features_json']}",
        f"- Real GIS-derived data: {audit['real_data_cells_total']} of {total}",
        "",
        "## Raster source tile presence",
        "",
    ]
    for feature_group, dirs in audit["raster_source_tiles_present"].items():
        status = ", ".join(f"{d}: {'present' if present else 'MISSING'}" for d, present in dirs.items())
        lines.append(f"- {feature_group}: {status}")

    if audit["sample_missing_cell_ids"]:
        lines += ["", "## Sample of missing cell IDs (first 20)", ""]
        lines += [f"- {cid}" for cid in audit["sample_missing_cell_ids"]]

    if audit["sample_recorded_placeholder_cell_ids"]:
        lines += ["", "## Sample of recorded-placeholder cell IDs (first 20)", ""]
        lines += [f"- {cid}" for cid in audit["sample_recorded_placeholder_cell_ids"]]

    lines += [
        "",
        "## What this does NOT check",
        "",
        "- Per-feature provenance: a cell_features.json entry is either fully real or fully "
        "placeholder (see static_features.py::StaticFeatures.is_placeholder) -- there is no "
        "record of e.g. \"forest_fraction real, elevation_m placeholder\" for a single cell.",
        "- Raster tile *coverage gaps within* a present tile directory (e.g. NMD's north-of-62N "
        "rollout, see static_features.py module docstring) -- only directory/file presence is "
        "checked here, not per-cell raster hit/miss inside compute_static_features_from_rasters.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-dir", type=Path, default=STATIC_DATA_DIR)
    parser.add_argument("--out", type=Path, default=GENERATED_DATA_DIR / "diagnostics")
    args = parser.parse_args()

    audit = build_audit(args.static_dir)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "static-data-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown = render_markdown(audit)
    (args.out / "static-data-audit.md").write_text(markdown, encoding="utf-8")

    print(markdown)
    print(f"\nWritten to {args.out / 'static-data-audit.json'} and {args.out / 'static-data-audit.md'}")


if __name__ == "__main__":
    main()
