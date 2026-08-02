#!/usr/bin/env python
"""Build the nearest-neighbor index mapping our grid cells to SMHI's static
point grid, and cache it to data/static/smhi_grid_index.json.

SMHI's SNOW forecast model and MESAN analysis product both serve data over
the exact same ~1M-point grid (confirmed live against the API), covering a
much larger Nordic/European domain than just Sweden. Every SMHI MultiPoint
response is a flat array of one value per grid point, in a fixed order given
by a separate static "geotype/multipoint.json" geometry request. Rather than
re-fetch and re-search that ~1M-point geometry file on every pipeline run,
this one-off script does the nearest-neighbor matching once (our ~18.6k
cells against their ~1M points) and caches just the small result: cell_id ->
SMHI array index.

This is a one-off (re-run only if our grid or SMHI's changes), kept separate
from the scheduled pipeline for the same reason as prepare_grid.py.

Usage:
    python scripts/prepare_smhi_grid_index.py
"""
from __future__ import annotations

import argparse
import json
import math

import httpx
import numpy as np

import _pathsetup  # noqa: F401
from config import SMHI_FORECAST_BASE_URL, SMHI_GRID_INDEX_PATH, STATIC_DATA_DIR
from grid import load_grid

# Sweden spans ~55-69 degN, where a degree of longitude is meaningfully
# shorter than a degree of latitude -- scale longitude distances by this
# factor (evaluated at Sweden's approximate mid-latitude) so nearest-point
# matching isn't skewed east-west. Only needs to be roughly right: it's
# selecting the closest of a ~2.8km-spaced grid, not computing true distances.
_LON_SCALE = math.cos(math.radians(62.0))

# Matching 18.6k cells against ~1M candidate points at once would allocate a
# ~300GB intermediate array. Even a modest chunk blows past typical CI
# runner memory (e.g. GitHub-hosted runners have ~7GB RAM) -- 500 cells at
# once would still need several GB. Keep chunks small; there's no speed
# pressure here, this runs once.
CHUNK_SIZE = 10


def fetch_smhi_geometry(base_url: str) -> np.ndarray:
    url = f"{base_url}/geotype/multipoint.json"
    with httpx.Client(timeout=60) as client:
        resp = client.get(url, headers={"Accept-Encoding": "gzip"})
        resp.raise_for_status()
        payload = resp.json()
    coords = payload["coordinates"]
    return np.array(coords, dtype=np.float64)  # shape (N, 2): [lon, lat]


def nearest_indices(cell_lonlat: np.ndarray, smhi_lonlat: np.ndarray) -> np.ndarray:
    smhi_scaled = smhi_lonlat.copy()
    smhi_scaled[:, 0] *= _LON_SCALE

    result = np.empty(len(cell_lonlat), dtype=np.int64)
    for start in range(0, len(cell_lonlat), CHUNK_SIZE):
        chunk = cell_lonlat[start : start + CHUNK_SIZE].copy()
        chunk[:, 0] *= _LON_SCALE
        dlon = chunk[:, 0:1] - smhi_scaled[None, :, 0]  # (chunk_n, smhi_n)
        dlat = chunk[:, 1:2] - smhi_scaled[None, :, 1]
        dist2 = dlon * dlon + dlat * dlat
        result[start : start + CHUNK_SIZE] = np.argmin(dist2, axis=1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", default=str(STATIC_DATA_DIR / "grid.json"))
    parser.add_argument("--out", default=str(SMHI_GRID_INDEX_PATH))
    args = parser.parse_args()

    cells = load_grid(__import__("pathlib").Path(args.grid))
    print(f"Loaded {len(cells)} of our grid cells")

    print("Fetching SMHI's static grid geometry (~1M points)...")
    smhi_lonlat = fetch_smhi_geometry(SMHI_FORECAST_BASE_URL)
    print(f"SMHI grid has {len(smhi_lonlat)} points")

    cell_lonlat = np.array([[c.longitude, c.latitude] for c in cells], dtype=np.float64)
    print("Matching each of our cells to its nearest SMHI grid point...")
    indices = nearest_indices(cell_lonlat, smhi_lonlat)

    # Sanity-check match quality: report the worst (largest) offset found,
    # in degrees, so a badly wrong domain/projection assumption would show
    # up as an obviously large number here rather than fail silently.
    matched = smhi_lonlat[indices]
    offsets_deg = np.sqrt(((cell_lonlat - matched) ** 2).sum(axis=1))
    print(f"Worst match offset: {offsets_deg.max():.4f} degrees (median {np.median(offsets_deg):.4f})")

    mapping = {cell.cell_id: int(idx) for cell, idx in zip(cells, indices)}
    out_path = __import__("pathlib").Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh)

    print(f"Wrote {len(mapping)} cell -> SMHI-index mappings to {out_path}")


if __name__ == "__main__":
    main()
