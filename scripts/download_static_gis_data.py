#!/usr/bin/env python
"""Download the real GIS source tiles needed for static feature computation
(scripts/prepare_static_features.py --real).

Two free, no-login, publicly-hosted sources, both served as Cloud-Optimized
GeoTIFFs on public AWS S3 (confirmed live -- see forecast/src/static_features.py
for exactly which classes/bands each drives):

  * ESA WorldCover 10m 2021 v200 -- land cover, tiled 3x3 degrees, tile names
    like "N57E012". s3://esa-worldcover/v200/2021/map/
  * Copernicus DEM GLO-30 -- 30m elevation, tiled 1x1 degree, tile names like
    "Copernicus_DSM_COG_10_N59_00_E018_00_DEM". s3://copernicus-dem-30m/

Only downloads the tiles that actually contain at least one current
data/static/grid.json cell (computed from the grid, not the full bounding
box -- Sweden's bbox rectangle also covers a lot of Norway/Finland/Denmark/
open sea that doesn't need any tiles), and skips any tile already present on
disk, so re-running after a grid.py change only fetches what's newly needed.

Usage:
    python scripts/download_static_gis_data.py
"""
from __future__ import annotations

import math
from pathlib import Path

import httpx

import _pathsetup  # noqa: F401
from config import STATIC_DATA_DIR
from grid import load_grid

WORLDCOVER_TILE_DEG = 3
WORLDCOVER_URL = "https://esa-worldcover.s3.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
DEM_URL = "https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"

REQUEST_TIMEOUT_S = 120.0


def _lat_tag(lat: int) -> str:
    return f"N{lat:02d}" if lat >= 0 else f"S{-lat:02d}"


def _lon_tag(lon: int) -> str:
    return f"E{lon:03d}" if lon >= 0 else f"W{-lon:03d}"


def worldcover_tiles_for_grid(cells) -> list[str]:
    tiles = set()
    for c in cells:
        lat0 = math.floor(c.latitude / WORLDCOVER_TILE_DEG) * WORLDCOVER_TILE_DEG
        lon0 = math.floor(c.longitude / WORLDCOVER_TILE_DEG) * WORLDCOVER_TILE_DEG
        tiles.add((int(lat0), int(lon0)))
    return sorted(f"{_lat_tag(la)}{_lon_tag(lo)}" for la, lo in tiles)


def dem_tiles_for_grid(cells) -> list[str]:
    tiles = set()
    for c in cells:
        tiles.add((math.floor(c.latitude), math.floor(c.longitude)))
    return sorted(
        f"Copernicus_DSM_COG_10_{_lat_tag(la)}_00_{_lon_tag(lo)}_00_DEM" for la, lo in tiles
    )


def _download(client: httpx.Client, url: str, out_path: Path) -> None:
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  {out_path.name}: already present, skipping")
        return
    resp = client.get(url)
    if resp.status_code == 404:
        # A candidate tile with no grid cells close enough to its edge to
        # actually need it, or (rare) a WorldCover tile that's 100% ocean
        # and was never published. Not an error.
        print(f"  {out_path.name}: 404 (no tile published here), skipping")
        return
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    print(f"  {out_path.name}: {len(resp.content) / 1e6:.1f} MB")


def main() -> None:
    cells = load_grid(STATIC_DATA_DIR / "grid.json")
    print(f"Loaded {len(cells)} grid cells")

    wc_dir = STATIC_DATA_DIR / "worldcover"
    dem_dir = STATIC_DATA_DIR / "dem"
    wc_dir.mkdir(parents=True, exist_ok=True)
    dem_dir.mkdir(parents=True, exist_ok=True)

    wc_tiles = worldcover_tiles_for_grid(cells)
    dem_tiles = dem_tiles_for_grid(cells)
    print(f"{len(wc_tiles)} WorldCover tiles, {len(dem_tiles)} DEM tiles needed")

    with httpx.Client(timeout=REQUEST_TIMEOUT_S, follow_redirects=True) as client:
        print("Downloading WorldCover land cover tiles...")
        for tile in wc_tiles:
            url = WORLDCOVER_URL.format(tile=tile)
            _download(client, url, wc_dir / f"{tile}.tif")

        print("Downloading Copernicus DEM elevation tiles...")
        for name in dem_tiles:
            url = DEM_URL.format(name=name)
            _download(client, url, dem_dir / f"{name}.tif")

    print("Done.")


if __name__ == "__main__":
    main()
