#!/usr/bin/env python
"""Precompute each grid cell's actual land-clipped polygon.

The frontend previously rendered risk data as a heatmap (blurred, roughly
following the coastline) or as fixed-size squares (blocky, ignored lakes
and sometimes bled onto the sea). Neither is what was actually wanted: the
real Swedish land surface, coloured, with water genuinely excluded.

This script computes the real answer once: for every grid cell, intersect
its nominal ~5km square with (Sweden's land polygon minus its lakes), so
the resulting polygon is exactly the portion of that cell that is real,
paintable land -- never water, and with no gaps beyond the grid's own
resolution. Cached like grid.json (data/static/cell_geometry.json.gz); a
one-off, re-run only when the grid or boundary/lakes data changes, not on
every scheduled forecast run.

Usage:
    python scripts/prepare_cell_geometry.py
"""
from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

import _pathsetup  # noqa: F401  (sets up sys.path for forecast/src imports)
from config import GRID_RESOLUTION_KM, SWEDEN_BBOX, STATIC_DATA_DIR
from grid import load_grid
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

KM_PER_DEGREE_LAT = 111.32
# Matches forecast/src/grid.py::generate_grid(), which derives a single
# longitude step from the bbox's mid-latitude and reuses it for every row
# regardless of each cell's own latitude -- squares must use the same
# fixed reference latitude for their width, or it silently drifts away
# from the grid's actual column spacing away from the midpoint.
SWEDEN_BBOX_MID_LAT_DEG = (SWEDEN_BBOX["min_lat"] + SWEDEN_BBOX["max_lat"]) / 2


def cell_square(lon: float, lat: float, size_km: float):
    half_lat_deg = size_km / 2 / KM_PER_DEGREE_LAT
    half_lon_deg = size_km / 2 / (KM_PER_DEGREE_LAT * math.cos(math.radians(SWEDEN_BBOX_MID_LAT_DEG)))
    return box(lon - half_lon_deg, lat - half_lat_deg, lon + half_lon_deg, lat + half_lat_deg)


def load_parts(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    geoms = [shape(feat["geometry"]) for feat in data["features"]]
    merged = unary_union(geoms)
    if merged.geom_type == "Polygon":
        return [merged]
    return list(merged.geoms)


def main() -> None:
    grid_path = STATIC_DATA_DIR / "grid.json"
    boundary_path = STATIC_DATA_DIR / "sweden_boundary.geojson"
    lakes_path = STATIC_DATA_DIR / "sweden_lakes.geojson"
    out_path = STATIC_DATA_DIR / "cell_geometry.json.gz"

    cells = load_grid(grid_path)
    land_parts = load_parts(boundary_path)
    lake_parts = load_parts(lakes_path) if lakes_path.exists() else []

    # Paintable land = land minus lakes. Index both by bounding box so each
    # cell only tests against nearby parts instead of the whole country.
    land_tree = STRtree(land_parts)
    lake_tree = STRtree(lake_parts) if lake_parts else None

    features = []
    dropped = 0
    widened = 0
    lake_overridden = 0
    # If the nominal ~5km square has no measurable land overlap (thin
    # coastal slivers, or a cell whose center barely qualifies as "on
    # land" per the original point-in-polygon test but whose square edges
    # fall just outside it), progressively widen the search area rather
    # than dropping the cell outright -- every cell that made it into the
    # grid in the first place has a real, confirmed-on-land point, so it
    # should always be paintable with *some* shape.
    WIDEN_FACTORS = (1, 1.5, 2, 3)
    for cell in cells:
        paintable = None
        # Smallest-factor non-empty land intersection, kept *before* the
        # lake subtraction -- a fallback for cells whose lake polygon
        # (e.g. Vänern's, confirmed live to overshoot its true shoreline
        # by more than this loop's widening ever recovers from) swallows
        # the entire square at every factor. Using the smallest factor's
        # shape minimizes how far this fallback overreaches versus the
        # cell's nominal size.
        land_only_fallback = None
        for factor in WIDEN_FACTORS:
            square = cell_square(cell.longitude, cell.latitude, GRID_RESOLUTION_KM * factor)
            nearby_land_idx = land_tree.query(square)
            if len(nearby_land_idx) == 0:
                continue
            nearby_land = unary_union([land_parts[i] for i in nearby_land_idx])
            land_only = square.intersection(nearby_land)
            candidate = land_only
            if lake_tree is not None:
                nearby_lake_idx = lake_tree.query(square)
                if len(nearby_lake_idx) > 0:
                    nearby_lakes = unary_union([lake_parts[i] for i in nearby_lake_idx])
                    candidate = candidate.difference(nearby_lakes)
            if land_only_fallback is None and not land_only.is_empty:
                land_only_fallback = land_only
            if not candidate.is_empty:
                paintable = candidate
                if factor > 1:
                    widened += 1
                break
        if paintable is None and land_only_fallback is not None:
            # Confirmed cause of a real gap: the lake mask ate 100% of
            # this cell's land at every widen factor. Painting the raw
            # (un-lake-clipped) land shape -- a small overlap onto the
            # inaccurate lake edge -- beats leaving the cell fully blank
            # on the map.
            paintable = land_only_fallback
            lake_overridden += 1
        if paintable is None:
            dropped += 1
            continue
        features.append({"cell_id": cell.cell_id, "geometry": mapping(paintable)})

    with gzip.open(out_path, "wt", encoding="utf-8") as fh:
        json.dump(features, fh)
    print(
        f"Wrote {len(features)} land-clipped cell polygons -> {out_path} "
        f"({dropped} cells had no land overlap even after widening, {widened} needed widening, "
        f"{lake_overridden} had land fully masked by lakes even after widening and used the "
        f"un-clipped land shape instead)"
    )


if __name__ == "__main__":
    main()
