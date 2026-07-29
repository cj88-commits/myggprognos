#!/usr/bin/env python
"""Generate the full Sweden 5km forecast grid and cache it to
data/static/grid.json.

This is a one-off (re-run only when resolution/bbox changes) step, kept
separate from the scheduled forecast pipeline so grid geometry is never
recomputed on every 6-hourly run.

Usage:
    python scripts/prepare_grid.py [--resolution-km 5] [--max-cells N]
"""
from __future__ import annotations

import argparse

import _pathsetup  # noqa: F401  (sets up sys.path for forecast/src imports)
from config import GRID_RESOLUTION_KM, STATIC_DATA_DIR
from grid import generate_grid, save_grid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution-km", type=float, default=GRID_RESOLUTION_KM)
    parser.add_argument("--max-cells", type=int, default=None, help="Safety cap on generated cell count")
    parser.add_argument("--out", default=str(STATIC_DATA_DIR / "grid.json"))
    args = parser.parse_args()

    cells = generate_grid(resolution_km=args.resolution_km, max_cells=args.max_cells)
    save_grid(cells, __import__("pathlib").Path(args.out))
    print(f"Generated {len(cells)} grid cells at ~{args.resolution_km}km resolution -> {args.out}")
    if not cells:
        raise SystemExit("No cells generated -- check bounding box / boundary file")


if __name__ == "__main__":
    main()
