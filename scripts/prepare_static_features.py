#!/usr/bin/env python
"""Precompute static geographic features (land cover, wetlands, forest,
water proximity, elevation, etc.) for every cell in the full Sweden grid
and cache them to data/static/cell_features.json.

Real GIS layers are NOT bundled in this repository (they are large and/or
license-encumbered for redistribution). To use real data:

  1. Download source layers into data/static/ (not committed to git):
       - Copernicus CORINE Land Cover (land_cover.tif), see
         https://land.copernicus.eu/pan-european/corine-land-cover
       - A water bodies / hydrography layer (water_bodies.gpkg), e.g. from
         Lantmateriet open data or OpenStreetMap water polygons.
       - A DEM, e.g. Copernicus GLO-30 (elevation.tif).
  2. Install the optional GIS extras: pip install geopandas rasterio
  3. Run: python scripts/prepare_static_features.py --real

Without --real (the default), this script generates deterministic
placeholder features so the pipeline is runnable without any downloads --
see forecast/src/static_features.py for details and limitations.
"""
from __future__ import annotations

import argparse

import _pathsetup  # noqa: F401
from config import STATIC_DATA_DIR
from grid import load_grid
from static_features import (
    compute_static_features_from_rasters,
    generate_placeholder_static_features,
    save_static_features,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", default=str(STATIC_DATA_DIR / "grid.json"))
    parser.add_argument("--out", default=str(STATIC_DATA_DIR / "cell_features.json"))
    parser.add_argument("--real", action="store_true", help="Use real GIS layers instead of placeholders")
    args = parser.parse_args()

    from pathlib import Path

    cells = load_grid(Path(args.grid))

    if args.real:
        features = compute_static_features_from_rasters(cells, STATIC_DATA_DIR)
    else:
        features = [generate_placeholder_static_features(c) for c in cells]
        print("Using deterministic placeholder static features (pass --real for GIS-derived data).")

    save_static_features(features, Path(args.out))
    print(f"Wrote static features for {len(features)} cells -> {args.out}")


if __name__ == "__main__":
    main()
