#!/usr/bin/env python
"""Rebuild data/static/sweden_boundary.geojson from ESA WorldCover 10m tiles.

The previous boundary source (Natural Earth 10m-scale "Land + Minor
Islands", 172 polygon parts nationally) is far too coarse for the Swedish
archipelago: it omits most of the tens of thousands of small skerries in
areas like the Stockholm archipelago entirely, which then also propagates
into missing/gappy grid cells (grid.py) and gappy painted cell polygons
(prepare_cell_geometry.py), since both derive from this one file.

This rebuilds the boundary from the ESA WorldCover 10m rasters already
downloaded to data/static/worldcover/*.tif (the same source already used
for per-cell land-cover features in static_features.py, so "land" now means
the same thing everywhere in the pipeline). For each tile: any WorldCover
class except "permanent water" (80) or nodata (0) counts as land; the 10m
pixel mask is downsampled by max-pooling (a block is land if ANY of its
native pixels is land, so small islands survive) before polygonizing, since
polygonizing at full 10m resolution nationally is not tractable, then
lightly simplified to control vertex count.

Deliberately does NOT union same-tile or cross-tile parts together: the
per-tile parts from rasterio's shapes() are already disjoint (one polygon
per connected same-value pixel region, by construction), and every consumer
of this file (grid.py's boundary.contains(Point), prepare_cell_geometry.py's
STRtree-indexed clipping, static_features.py's coastline STRtree) only cares
about geometric truth, not about whether adjacent same-tile parts were
dissolved into fewer, bigger ones -- so a real unary_union pass buys nothing
functionally. It was tried first and confirmed live to be the dominant cost
by far (union of ~4,700 parts alone took 41s on one tile, after
polygonize+simplify together took under 7s), so it's skipped entirely; the
final file is just every tile's simplified parts concatenated into one
MultiPolygon.

Usage:
    python scripts/build_worldcover_boundary.py [--downsample 5] [--simplify-deg 0.0003]
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import rasterio
import shapely
from rasterio.features import shapes
from shapely.geometry import MultiPolygon, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

import _pathsetup  # noqa: F401  (sets up sys.path for forecast/src imports)
from config import STATIC_DATA_DIR

WATER_CLASS = 80
NODATA_VALUE = 0

# A raw part is dropped only when MOST of its own area is already inside the
# original Natural Earth boundary -- not merely because it touches it
# somewhere. Two cruder criteria were tried first and both re-created the
# "white island" bug this rebuild exists to fix, just for different land:
#   1. Bounding-box size (anything over ~8km assumed to be an already-
#      covered landmass) silently dropped real Stockholm-archipelago
#      islands in the 8-20km range (Ingmarsö, Blidoe, Yxlan, ...) that
#      Natural Earth never resolved either.
#   2. ANY overlap with Natural Earth (boolean .intersects()) is closer but
#      still wrong: a part that only brushes NE's coarse edge gets dropped
#      *entirely*, losing whatever real extra area WorldCover resolved
#      beyond NE's cruder outline for that same piece of land -- confirmed
#      live, a reported coastal point's local coverage dropped from 38% to
#      29% switching from the bbox filter to a plain intersects() filter.
# A part connected to the mainland's own coastline (the actual cause of the
# original performance blowup -- one part with ~25,000 vertices, minutes to
# simplify alone) is overwhelmingly *inside* Natural Earth's mainland
# polygon, so the >50%-area-overlap threshold below still drops it (and
# still avoids ever calling .simplify() on it), while a real island that
# only clips a corner of NE's rough outline stays in at its full extent.
REDUNDANT_OVERLAP_FRACTION = 0.5


def _load_ne_index(base_boundary_path: Path):
    """Return (parts, STRtree(parts)) for the original Natural Earth
    boundary, or (None, None) if it isn't present."""
    if not base_boundary_path.exists():
        return None, None
    with open(base_boundary_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    geoms = [shape(feat["geometry"]) for feat in data["features"]]
    parts = [p for g in geoms for p in (g.geoms if g.geom_type == "MultiPolygon" else [g])]
    return parts, STRtree(parts)


def _redundant_with_ne(part, ne_parts, ne_tree) -> bool:
    if ne_tree is None or part.area <= 0:
        return False
    idxs = ne_tree.query(part)
    if len(idxs) == 0:
        return False
    nearby = unary_union([ne_parts[i] for i in idxs])
    if not part.intersects(nearby):
        return False
    return (part.intersection(nearby).area / part.area) > REDUNDANT_OVERLAP_FRACTION


def tile_land_parts(
    tif_path: Path, downsample: int, simplify_deg: float, ne_parts=None, ne_tree=None, verbose: bool = False
) -> list:
    """Return a list of simplified, NOT unioned, land Polygons for one tile --
    excluding only parts that are mostly redundant with the original Natural
    Earth boundary (`ne_parts`/`ne_tree`), see _redundant_with_ne."""
    t0 = time.time()
    with rasterio.open(tif_path) as ds:
        arr = ds.read(1)
        transform = ds.transform

    land = (arr != WATER_CLASS) & (arr != NODATA_VALUE)
    del arr
    h, w = land.shape
    bh, bw = h // downsample, w // downsample
    land_ds = (
        land[: bh * downsample, : bw * downsample]
        .reshape(bh, downsample, bw, downsample)
        .any(axis=(1, 3))
        .astype(np.uint8)
    )
    del land
    if land_ds.sum() == 0:
        return []
    if verbose:
        print(f"    read+downsample: {time.time() - t0:.1f}s", flush=True)

    block_transform = transform * transform.scale(downsample, downsample)
    t0 = time.time()
    raw_geoms = [shape(geom) for geom, _ in shapes(land_ds, mask=(land_ds == 1), transform=block_transform)]
    del land_ds
    n_raw = len(raw_geoms)

    if ne_tree is not None:
        kept = [p for p in raw_geoms if not _redundant_with_ne(p, ne_parts, ne_tree)]
        n_dropped = n_raw - len(kept)
        raw_geoms = np.array(kept)
    else:
        n_dropped = 0
        raw_geoms = np.array(raw_geoms)
    if verbose:
        print(
            f"    polygonize: {time.time() - t0:.1f}s, {n_raw} raw parts "
            f"({n_dropped} >{REDUNDANT_OVERLAP_FRACTION:.0%} redundant with Natural Earth, dropped; "
            f"{len(raw_geoms)} kept)",
            flush=True,
        )

    if len(raw_geoms) == 0:
        return []

    t0 = time.time()
    # shapely's top-level array function applies simplify to the whole
    # numpy array of geometries in one C-level loop -- confirmed live,
    # ~65x faster than the equivalent per-part `.simplify()` Python list
    # comprehension (2+ min -> ~2s for a comparable 8,364-part tile).
    simplified = shapely.simplify(raw_geoms, simplify_deg, preserve_topology=True)
    if verbose:
        print(f"    per-part simplify (vectorized): {time.time() - t0:.1f}s", flush=True)

    t0 = time.time()
    # Raster-to-vector output from shapes() occasionally has borderline-
    # invalid topology (e.g. a ring touching itself at one point where two
    # same-value pixel blocks meet only diagonally) that simplify() doesn't
    # necessarily clean up. Downstream code used to get this fixed for free
    # as a side effect of unary_union() -- confirmed live, removing that
    # union (see module docstring) surfaced a real
    # "TopologyException: side location conflict" from a plain
    # square.intersection(MultiPolygon(these parts)) call in
    # prepare_cell_geometry.py. make_valid() here fixes it once, at the
    # source, for every consumer of this file instead of papering over it
    # per-caller. A fixed part can occasionally split into multiple pieces
    # (or, rarely, degrade to a stray line/point) -- flatten to Polygons
    # only, dropping non-polygonal debris.
    fixed = shapely.make_valid(simplified)
    parts = []
    for g in fixed:
        if g.geom_type == "Polygon":
            parts.append(g)
        elif g.geom_type in ("MultiPolygon", "GeometryCollection"):
            parts.extend(sub for sub in g.geoms if sub.geom_type == "Polygon")
    if verbose:
        print(f"    make_valid: {time.time() - t0:.1f}s, {len(simplified)} -> {len(parts)} parts", flush=True)

    return parts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--downsample", type=int, default=5, help="Block size in native 10m pixels (5 = 50m)")
    parser.add_argument("--simplify-deg", type=float, default=0.0003, help="Simplify tolerance in degrees (~33m at 0.0003)")
    parser.add_argument("--out", default=str(STATIC_DATA_DIR / "sweden_boundary.geojson"))
    parser.add_argument(
        "--cache-dir",
        default=str(STATIC_DATA_DIR / "worldcover_boundary_cache"),
        help="Per-tile simplified parts are cached here so a long run can be resumed/chunked across calls",
    )
    parser.add_argument("--finalize", action="store_true", help="Skip tile processing; just concatenate cached tiles and write --out")
    parser.add_argument("--limit", type=int, default=None, help="Process at most this many NOT-yet-cached tiles, then exit (for chunked runs)")
    parser.add_argument(
        "--base-boundary",
        default=str(STATIC_DATA_DIR / "sweden_boundary.natural_earth_original.geojson"),
        help="Original (pre-rebuild) boundary -- parts mostly redundant with it are dropped; see _redundant_with_ne",
    )
    args = parser.parse_args()

    worldcover_dir = STATIC_DATA_DIR / "worldcover"
    tiles = sorted(worldcover_dir.glob("*.tif"))
    if not tiles:
        raise SystemExit(f"No WorldCover tiles found under {worldcover_dir}")

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if not args.finalize:
        ne_parts, ne_tree = _load_ne_index(Path(args.base_boundary))
        processed = 0
        for i, tif_path in enumerate(tiles, 1):
            cache_path = cache_dir / f"{tif_path.stem}.json"
            if cache_path.exists():
                print(f"[{i}/{len(tiles)}] {tif_path.name}: cached, skipping", flush=True)
                continue
            if args.limit is not None and processed >= args.limit:
                print(f"Reached --limit {args.limit}, stopping (resume by re-running)", flush=True)
                break
            t0 = time.time()
            parts = tile_land_parts(
                tif_path, args.downsample, args.simplify_deg, ne_parts=ne_parts, ne_tree=ne_tree, verbose=True
            )
            elapsed = time.time() - t0
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump([mapping(p) for p in parts], fh)
            processed += 1
            print(f"[{i}/{len(tiles)}] {tif_path.name}: {len(parts)} parts, {elapsed:.1f}s", flush=True)
        return

    small_parts = []
    for tif_path in tiles:
        cache_path = cache_dir / f"{tif_path.stem}.json"
        if not cache_path.exists():
            raise SystemExit(f"Missing cached tile {cache_path} -- run without --finalize first for all tiles")
        with open(cache_path, "r", encoding="utf-8") as fh:
            geoms = json.load(fh)
        small_parts.extend(shape(g) for g in geoms)
    n_small_raw = len(small_parts)

    base_path = Path(args.base_boundary)
    base_parts = []
    if base_path.exists():
        with open(base_path, "r", encoding="utf-8") as fh:
            base_data = json.load(fh)
        for feat in base_data["features"]:
            geom = shape(feat["geometry"])
            raw_base = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
            # Same defensive fix as tile_land_parts(): downstream code (e.g.
            # prepare_cell_geometry.py) builds a plain, non-unioned
            # MultiPolygon straight out of these parts, which surfaces any
            # borderline-invalid input as a hard GEOSException instead of
            # GEOS quietly fixing it as a union side effect.
            for fixed_geom in shapely.make_valid(np.array(list(raw_base))):
                if fixed_geom.geom_type == "Polygon":
                    base_parts.append(fixed_geom)
                elif fixed_geom.geom_type in ("MultiPolygon", "GeometryCollection"):
                    base_parts.extend(sub for sub in fixed_geom.geoms if sub.geom_type == "Polygon")

    # Downloaded WorldCover tiles are fixed 3x3 degree blocks that extend
    # past SWEDEN_BBOX on every edge (needed so tiles fully cover the bbox
    # at all), so small_parts can include real land that's actually in a
    # neighbouring country -- confirmed live: 2,300 spurious grid cells
    # appeared across Denmark/Germany (as far south as 54.6N, a full degree
    # below SWEDEN_BBOX's 55.2N floor) after the first version of this
    # script, since unlike the original Natural Earth source (already
    # clipped to Sweden's actual country shape), raw WorldCover has no
    # country-boundary awareness at all. Two-stage filter: SWEDEN_BBOX
    # first (cheap, catches anything clearly outside the country, like the
    # Denmark/Germany case above) and a buffer around the real Sweden
    # shape second (catches near-border false positives the bbox alone
    # can't, e.g. Norway/Finland land inside the bbox rectangle) --
    # BORDER_BUFFER_DEG is deliberately modest (~17km) since Sweden and
    # Denmark are only ~4km apart at the narrowest point of Oresund
    # (Helsingborg/Helsingor) -- close enough that this buffer alone can't
    # fully rule out a genuine Danish town leaking in there (verify near
    # Helsingborg specifically after any rebuild, alongside the archipelago
    # check this script exists for).
    from config import SWEDEN_BBOX

    BORDER_BUFFER_DEG = 0.15
    sweden_shape_prepared = None
    if base_parts:
        from shapely.prepared import prep

        # prep() so the ~83k .intersects() calls below are STRtree-indexed
        # instead of unindexed O(parts) checks against the buffered shape.
        sweden_shape_prepared = prep(MultiPolygon(base_parts).buffer(BORDER_BUFFER_DEG))

    kept = []
    n_dropped_bbox = 0
    n_dropped_border = 0
    for p in small_parts:
        minx, miny, maxx, maxy = p.bounds
        if maxx < SWEDEN_BBOX["min_lon"] or minx > SWEDEN_BBOX["max_lon"] or maxy < SWEDEN_BBOX["min_lat"] or miny > SWEDEN_BBOX["max_lat"]:
            n_dropped_bbox += 1
            continue
        if sweden_shape_prepared is not None and not sweden_shape_prepared.intersects(p):
            n_dropped_border += 1
            continue
        kept.append(p)
    small_parts = kept
    n_small_islands = len(small_parts)
    print(
        f"{n_small_raw} raw small-island parts -> {n_dropped_bbox} outside SWEDEN_BBOX, "
        f"{n_dropped_border} outside {BORDER_BUFFER_DEG}deg border buffer, {n_small_islands} kept",
        flush=True,
    )

    all_parts = small_parts + base_parts
    n_base = len(base_parts)
    print(f"{n_small_islands} small WorldCover-derived island parts + {n_base} original landmass parts", flush=True)

    if not all_parts:
        raise SystemExit("No land found in any cached tile")

    print(f"Combining {len(all_parts)} parts into one national MultiPolygon (no union)...", flush=True)
    national = MultiPolygon(all_parts)

    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": "Sweden",
                    "source": (
                        f"Hybrid: original Natural Earth 10m Land + 10m Minor Islands boundary "
                        f"({n_base} landmass parts, kept as-is) UNION ESA WorldCover 10m 2021 v200 "
                        f"(public domain) land parts not overlapping Natural Earth, of any size "
                        f"({n_small_islands} parts: non-water/non-nodata classes, max-pooled to "
                        f"{args.downsample * 10}m blocks, simplified at {args.simplify_deg} deg "
                        f"tolerance) -- see scripts/build_worldcover_boundary.py"
                    ),
                },
                "geometry": mapping(national),
            }
        ],
    }

    out_path = Path(args.out)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(feature_collection, fh)

    print(f"Wrote {out_path} ({len(national.geoms)} parts)")


if __name__ == "__main__":
    main()
