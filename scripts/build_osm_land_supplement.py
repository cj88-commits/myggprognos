#!/usr/bin/env python
"""Supplement sweden_boundary.geojson with land ESA WorldCover misses, using
OSM's own coastline-derived land-polygons dataset.

Background: WorldCover (the current boundary's source, see
build_worldcover_boundary.py) misclassifies many small Baltic skerries as
permanent water -- confirmed live: 68% of 2,055 real, OSM-named Stockholm
archipelago islands are entirely absent from the current boundary, and raw
WorldCover pixel sampling at several of them (Humlan, Bromsen, Ryggen,
Vreden) shows 100% "water" classification across a 210m radius, not a
resolution artifact. This adds OSM's maintained land-polygon extraction
(osmdata.openstreetmap.de) as a second source for whatever WorldCover-derived
land isn't already there.

Membership test: whether a candidate is genuinely Swedish. A first version
of this script reused build_worldcover_boundary.py's distance-based border
buffer (BORDER_BUFFER_DEG around the existing boundary) -- that works for a
SEA gap (the whole archipelago-recovery case) but is unsafe across a LAND
border: confirmed live, a 0.31deg2 piece of real Finnish territory near
Pello (verified against OSM's own admin_level=2 boundary data) sat well
within 17km of already-recognized Swedish land near the border and was kept
whole. Real country borders don't reliably correlate with "close to Sweden's
existing coastline" the way sea gaps do. Fixed by using Sweden's actual
OSM administrative boundary (data/static/sweden_admin_boundary_osm.geojson)
as an authoritative membership test instead of a distance heuristic.

Prerequisite (one-time, not committed -- see .gitignore):
    Download and extract https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip
    to data/static/osm_land/land-polygons-split-4326/land_polygons.shp

sweden_admin_boundary_osm.geojson (committed, small) was fetched once via:
    curl -X POST https://overpass-api.de/api/interpreter --data-urlencode \
      'data=[out:json][timeout:60];relation["boundary"="administrative"]["admin_level"="2"]["ISO3166-1"="SE"];out geom;'
    then assembled from the relation's way members with shapely.ops.polygonize
    (see scripts/build_sweden_admin_boundary.py).

Usage (small local sample first -- see README/plan before running nationally):
    python scripts/build_osm_land_supplement.py \
        --bbox 18.7,59.2,19.2,59.6 \
        --out data/static/sweden_boundary.sample.geojson

Full national run (only after sample verification):
    python scripts/build_osm_land_supplement.py --out data/static/sweden_boundary.geojson
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import geopandas as gpd
import shapely
from shapely.geometry import MultiPolygon, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

import _pathsetup  # noqa: F401  (sets up sys.path for forecast/src imports)
from config import STATIC_DATA_DIR, SWEDEN_BBOX

# Same threshold/reasoning as build_worldcover_boundary.py's
# REDUNDANT_OVERLAP_FRACTION: drop an OSM part only when MOST of its own area
# is already represented in the existing boundary, not merely because it
# touches it somewhere -- see that script's docstring for the two cruder
# alternatives already tried and rejected there.
REDUNDANT_OVERLAP_FRACTION = 0.5


def _load_parts(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    geoms = [shape(feat["geometry"]) for feat in data["features"]]
    return [p for geom in geoms for p in (geom.geoms if geom.geom_type == "MultiPolygon" else [geom])]


def _clip_to_admin_boundary(parts: list, admin_prepared, admin_shape) -> tuple[list, dict]:
    """Keep only the portion of each part that's genuinely inside Sweden's
    real administrative outline -- fully inside kept as-is, straddling parts
    clipped to it, fully outside dropped. Also applies the cheap SWEDEN_BBOX
    bbox pre-filter first."""
    kept = []
    n_dropped_bbox = 0
    n_dropped_outside = 0
    n_clipped = 0
    for part in parts:
        minx, miny, maxx, maxy = part.bounds
        if (
            maxx < SWEDEN_BBOX["min_lon"]
            or minx > SWEDEN_BBOX["max_lon"]
            or maxy < SWEDEN_BBOX["min_lat"]
            or miny > SWEDEN_BBOX["max_lat"]
        ):
            n_dropped_bbox += 1
            continue
        if admin_prepared.contains(part):
            kept.append(part)
            continue
        if not admin_prepared.intersects(part):
            n_dropped_outside += 1
            continue
        clipped = part.intersection(admin_shape)
        if clipped.is_empty:
            n_dropped_outside += 1
            continue
        n_clipped += 1
        if clipped.geom_type == "Polygon":
            kept.append(clipped)
        elif clipped.geom_type in ("MultiPolygon", "GeometryCollection"):
            kept.extend(g for g in clipped.geoms if g.geom_type == "Polygon")
    stats = {"dropped_bbox": n_dropped_bbox, "dropped_outside": n_dropped_outside, "clipped": n_clipped, "kept": len(kept)}
    return kept, stats


def _is_redundant(part, existing_tree: STRtree, existing_parts: list) -> bool:
    if part.area <= 0:
        return False
    idxs = existing_tree.query(part)
    if len(idxs) == 0:
        return False
    # Intersect each nearby existing part against the (small) candidate
    # FIRST, then union only those small results -- same reasoning as the
    # border-buffer fix below: existing_tree.query(part) is a bbox-only
    # test, so it routinely includes the huge mainland part (whose bbox
    # spans nearly the whole country); unioning it in raw, full size, once
    # per candidate, over thousands of candidates, is the exact perf trap
    # already documented in prepare_cell_geometry.py -- confirmed live here
    # too. Mathematically identical to intersecting `part` against the
    # union of the raw nearby parts, just without ever processing a huge
    # geometry in full.
    nearby = unary_union([part.intersection(existing_parts[i]) for i in idxs])
    if nearby.is_empty:
        return False
    return (nearby.area / part.area) > REDUNDANT_OVERLAP_FRACTION


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--osm-shapefile",
        default=str(STATIC_DATA_DIR / "osm_land" / "land-polygons-split-4326" / "land_polygons.shp"),
        help="Path to the extracted OSM land-polygons shapefile.",
    )
    parser.add_argument(
        "--base-boundary", default=str(STATIC_DATA_DIR / "sweden_boundary.geojson"),
        help="Existing boundary to supplement (parts already here are kept as-is).",
    )
    parser.add_argument(
        "--admin-boundary", default=str(STATIC_DATA_DIR / "sweden_admin_boundary_osm.geojson"),
        help="Authoritative Sweden country outline (see scripts/build_sweden_admin_boundary.py) "
             "-- a candidate is kept only where it overlaps this, clipped to it if it straddles "
             "the edge.",
    )
    parser.add_argument(
        "--bbox", default=None,
        help="Restrict the OSM read (and thus the whole run) to "
             "'min_lon,min_lat,max_lon,max_lat' -- for fast local iteration on a sample area. "
             "Omit for a full national run.",
    )
    parser.add_argument("--out", required=True, help="Output boundary geojson path.")
    args = parser.parse_args()

    if args.bbox:
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in args.bbox.split(","))
        osm_bbox = (min_lon, min_lat, max_lon, max_lat)
    else:
        osm_bbox = (SWEDEN_BBOX["min_lon"], SWEDEN_BBOX["min_lat"], SWEDEN_BBOX["max_lon"], SWEDEN_BBOX["max_lat"])

    print(f"Loading existing boundary from {args.base_boundary} ...", flush=True)
    t0 = time.time()
    base_parts = _load_parts(Path(args.base_boundary))
    print(f"  {len(base_parts)} existing parts ({time.time() - t0:.1f}s)", flush=True)
    existing_tree = STRtree(base_parts)

    print(f"Reading OSM land polygons within {osm_bbox} ...", flush=True)
    t0 = time.time()
    gdf = gpd.read_file(args.osm_shapefile, bbox=osm_bbox)
    print(f"  {len(gdf)} OSM polygons read ({time.time() - t0:.1f}s)", flush=True)

    # Same defensive fix as build_worldcover_boundary.py: raw source
    # geometry can be borderline-invalid (self-touching rings etc.); fix
    # once here rather than have every consumer of the merged file hit it.
    import numpy as np

    fixed = shapely.make_valid(np.array(gdf.geometry.values))
    osm_parts = []
    for g in fixed:
        if g.geom_type == "Polygon":
            osm_parts.append(g)
        elif g.geom_type in ("MultiPolygon", "GeometryCollection"):
            osm_parts.extend(sub for sub in g.geoms if sub.geom_type == "Polygon")
    print(f"  {len(osm_parts)} OSM polygon parts after make_valid", flush=True)

    print("Filtering to non-redundant parts ...", flush=True)
    t0 = time.time()
    non_redundant = []
    n_redundant = 0
    for part in osm_parts:
        if _is_redundant(part, existing_tree, base_parts):
            n_redundant += 1
        else:
            non_redundant.append(part)
    print(f"  {n_redundant} already represented, {len(non_redundant)} candidates remain ({time.time() - t0:.1f}s)", flush=True)

    # Authoritative "is this genuinely Swedish territory" test -- NOT a
    # distance-from-existing-land heuristic. A first version of this script
    # used exactly that (buffer around the existing boundary, matching
    # build_worldcover_boundary.py's approach for WorldCover tiles) and it
    # correctly handles the archipelago (a sea gap -- anything nearby really
    # is Sweden), but confirmed live to be unsafe across a LAND border: a
    # 0.31deg2 piece of real Finnish territory near Pello sat well within
    # 17km of already-recognized Swedish land and got kept whole. Real
    # country borders don't reliably correlate with "close to existing
    # Swedish coastline" the way sea gaps do, so this uses Sweden's actual
    # OSM administrative boundary instead.
    print(f"Loading Sweden admin boundary from {args.admin_boundary} ...", flush=True)
    admin_parts = _load_parts(Path(args.admin_boundary))
    admin_shape = MultiPolygon(admin_parts) if len(admin_parts) > 1 else admin_parts[0]
    from shapely.prepared import prep

    admin_prepared = prep(admin_shape)

    print(f"Filtering {len(non_redundant)} new candidates against the admin boundary ...", flush=True)
    t0 = time.time()
    kept, stats = _clip_to_admin_boundary(non_redundant, admin_prepared, admin_shape)
    print(
        f"  {stats['dropped_bbox']} outside SWEDEN_BBOX, {stats['dropped_outside']} outside Sweden's admin boundary, "
        f"{stats['clipped']} straddling parts clipped to it, {stats['kept']} new parts kept ({time.time() - t0:.1f}s)",
        flush=True,
    )

    # Also re-validate the EXISTING parts against the same authoritative
    # boundary -- some of them (e.g. near the Norway border) were only ever
    # clipped against the cruder distance-based buffer this replaced (see
    # this morning's Finland fix, scripts/build_worldcover_boundary.py),
    # which is looser across a land border than a real admin outline.
    # Confirmed live: several existing parts near Värmland/Dalsland (close
    # to Norway) and near Pajala (close to Finland) sit up to ~25km outside
    # this boundary -- genuinely foreign territory that survived the
    # cruder buffer check.
    print(f"Re-validating {len(base_parts)} existing parts against the admin boundary ...", flush=True)
    t0 = time.time()
    revalidated_base, base_stats = _clip_to_admin_boundary(base_parts, admin_prepared, admin_shape)
    print(
        f"  {base_stats['dropped_bbox']} outside SWEDEN_BBOX, {base_stats['dropped_outside']} outside admin boundary, "
        f"{base_stats['clipped']} straddling parts clipped, {base_stats['kept']} kept "
        f"(was {len(base_parts)}) ({time.time() - t0:.1f}s)",
        flush=True,
    )

    all_parts = revalidated_base + kept
    print(f"Writing {len(all_parts)} total parts ({len(revalidated_base)} existing + {len(kept)} new) -> {args.out}", flush=True)
    # Same convention as build_worldcover_boundary.py: one Feature holding a
    # MultiPolygon of every part, NOT unary_union()'d together -- downstream
    # code (grid.py, prepare_cell_geometry.py) only ever needs a flat list of
    # disjoint parts, and dissolving tens of thousands of them buys nothing
    # functionally while costing real time (see that script's docstring).
    national = MultiPolygon(all_parts)
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": "Sweden",
                    "source": (
                        "Existing boundary + OSM land-polygons supplement "
                        "(scripts/build_osm_land_supplement.py) for land WorldCover misclassifies as water"
                    ),
                },
                "geometry": mapping(national),
            }
        ],
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(feature_collection, fh)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
