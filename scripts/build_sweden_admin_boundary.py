#!/usr/bin/env python
"""Fetch Sweden's real administrative boundary from OSM and write it to
data/static/sweden_admin_boundary_osm.geojson.

This is an authoritative "is this genuinely Swedish territory" reference --
used by build_osm_land_supplement.py to filter candidate land parts near a
land border (Norway, Finland), where a simple distance-from-existing-land
heuristic isn't safe (see that script's docstring for the Pello/Finland
incident this replaced). A one-off, re-run only if Sweden's borders somehow
change or the reference file is lost; small enough (~350KB) to commit.

Usage:
    python scripts/build_sweden_admin_boundary.py
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from shapely.geometry import LineString, mapping
from shapely.ops import polygonize, unary_union

import _pathsetup  # noqa: F401  (sets up sys.path for forecast/src imports)
from config import STATIC_DATA_DIR

OVERPASS_QUERY = (
    '[out:json][timeout:60];'
    'relation["boundary"="administrative"]["admin_level"="2"]["ISO3166-1"="SE"];'
    "out geom;"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(STATIC_DATA_DIR / "sweden_admin_boundary_osm.geojson"))
    args = parser.parse_args()

    print("Querying Overpass API for Sweden's admin_level=2 relation ...", flush=True)
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", "https://overpass-api.de/api/interpreter", "--data-urlencode", f"data={OVERPASS_QUERY}"],
        capture_output=True, text=True, timeout=90,
    )
    data = json.loads(result.stdout)
    if not data.get("elements"):
        raise SystemExit("Overpass returned no matching relation -- query or API may have changed")
    rel = data["elements"][0]
    print(f"  relation {rel['id']}, {len(rel['members'])} members", flush=True)

    outer_lines = []
    inner_lines = []
    for m in rel["members"]:
        if m["type"] != "way" or "geometry" not in m:
            continue
        coords = [(pt["lon"], pt["lat"]) for pt in m["geometry"]]
        if len(coords) < 2:
            continue
        (inner_lines if m.get("role") == "inner" else outer_lines).append(LineString(coords))

    # Standard OSM multipolygon assembly: individual way segments only form
    # closed rings once joined at shared endpoints -- polygonize() does that
    # joining and returns the resulting closed polygons directly.
    outer_polys = list(polygonize(outer_lines))
    inner_polys = list(polygonize(inner_lines)) if inner_lines else []
    print(f"  assembled {len(outer_polys)} outer part(s), {len(inner_polys)} inner (hole) part(s)", flush=True)

    merged = unary_union(outer_polys)
    if inner_polys:
        merged = merged.difference(unary_union(inner_polys))
    if not merged.is_valid:
        raise SystemExit("Assembled Sweden admin polygon is invalid -- inspect before using")

    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": "Sweden",
                    "source": "OSM admin_level=2 relation, via Overpass API (scripts/build_sweden_admin_boundary.py)",
                },
                "geometry": mapping(merged),
            }
        ],
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(feature_collection, fh)
    print(f"Wrote {args.out} (area={merged.area:.2f}deg2)", flush=True)


if __name__ == "__main__":
    main()
