"""Forecast grid generation for Sweden.

Produces a nominal 5 km grid of cells covering Sweden, each with a stable
ID and lat/lon. Filtering "clearly outside Sweden" cells is done with a
lightweight point-in-country test: if geopandas + a Sweden boundary polygon
are available we use a real polygon test; otherwise we fall back to a
bounding-box + coarse land mask so the pipeline still runs in sample mode
without heavy GIS dependencies.

Static features are intentionally NOT computed here -- see
static_features.py. Grid geometry should be computed once and cached
(grid.py is deterministic given resolution + bbox), not recomputed on every
scheduled forecast run.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from config import SWEDEN_BBOX

KM_PER_DEGREE_LAT = 111.32


@dataclass(frozen=True)
class GridCell:
    cell_id: str
    latitude: float
    longitude: float
    region: str = "unknown"


def _km_per_degree_lon(lat_deg: float) -> float:
    return KM_PER_DEGREE_LAT * math.cos(math.radians(lat_deg))


def _approx_region(lat: float) -> str:
    """Very coarse north/middle/south banding used as a stand-in for real
    administrative (lan) boundaries in sample mode. Real deployments should
    join against SCB/Lantmateriet administrative polygons instead."""
    if lat >= 63.5:
        return "Norrland"
    if lat >= 60.0:
        return "Svealand"
    return "Gotaland"


def _in_sweden_bbox(lat: float, lon: float) -> bool:
    return (
        SWEDEN_BBOX["min_lat"] <= lat <= SWEDEN_BBOX["max_lat"]
        and SWEDEN_BBOX["min_lon"] <= lon <= SWEDEN_BBOX["max_lon"]
    )


def _load_boundary_polygon():
    """Return a shapely polygon/multipolygon for Sweden if a boundary file is
    present under data/static, else None. Uses shapely directly (already a
    hard dependency, see forecast/requirements.txt) rather than geopandas,
    so real land/ocean filtering doesn't need the heavier optional GIS
    extras -- just a plain GeoJSON FeatureCollection with one Sweden
    MultiPolygon feature (mainland + islands, incl. Gotland/Oland)."""
    boundary_path = Path(__file__).resolve().parents[2] / "data" / "static" / "sweden_boundary.geojson"
    if not boundary_path.exists():
        return None
    try:
        from shapely.geometry import shape
        from shapely.ops import unary_union

        with open(boundary_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        geometries = [shape(feature["geometry"]) for feature in data["features"]]
        return unary_union(geometries)
    except Exception:
        return None


def generate_grid(
    resolution_km: float = 5.0,
    bbox: dict | None = None,
    max_cells: int | None = None,
) -> list[GridCell]:
    """Generate a regular lat/lon grid at approximately `resolution_km`
    spacing, filtered to Sweden's bounding box (and, if available, a real
    boundary polygon).

    `max_cells` is a safety valve for tests/sample mode so a mis-set
    resolution can't accidentally generate millions of cells.
    """
    bbox = bbox or SWEDEN_BBOX
    boundary = _load_boundary_polygon()

    lat_step = resolution_km / KM_PER_DEGREE_LAT
    mid_lat = (bbox["min_lat"] + bbox["max_lat"]) / 2
    lon_step = resolution_km / _km_per_degree_lon(mid_lat)

    cells: list[GridCell] = []
    lat = bbox["min_lat"]
    row = 0
    while lat <= bbox["max_lat"]:
        lon = bbox["min_lon"]
        col = 0
        while lon <= bbox["max_lon"]:
            if _in_sweden_bbox(lat, lon):
                include = True
                if boundary is not None:
                    try:
                        from shapely.geometry import Point

                        include = boundary.contains(Point(lon, lat))
                    except Exception:
                        include = True
                if include:
                    cell_id = f"SE_{row:04d}_{col:04d}"
                    cells.append(
                        GridCell(
                            cell_id=cell_id,
                            latitude=round(lat, 5),
                            longitude=round(lon, 5),
                            region=_approx_region(lat),
                        )
                    )
                    if max_cells is not None and len(cells) >= max_cells:
                        return cells
            lon += lon_step
            col += 1
        lat += lat_step
        row += 1

    if boundary is not None and (max_cells is None or len(cells) < max_cells):
        cells.extend(_supplementary_island_cells(cells, boundary, max_cells))

    return cells


def _supplementary_island_cells(
    cells: list[GridCell], boundary, max_cells: int | None, resolution_km: float = 5.0
) -> list[GridCell]:
    """Add extra cells wherever real land (per `boundary`) sits too far
    from every existing point to ever be reached by that point's own
    ~resolution_km square -- not just entirely-disconnected islands, but
    also real coastline within a much larger connected "part" that the
    old per-part check saw as already "covered" (some existing lattice
    point lies *somewhere* in that huge part) while still leaving real
    land uncovered in the gaps between individual lattice points'
    squares. Confirmed live in the Stockholm archipelago: ~15% of real
    land within a few km of sampled coastal points had zero cell
    covering it, purely because the fixed-phase lattice's points didn't
    happen to land on those specific skerries, even though the
    surrounding "part" already had cells elsewhere.

    Tiles each boundary part with the same `resolution_km` spacing as
    the main lattice, offset to the part's own bounding box (reusing the
    main lattice's phase would just rediscover the exact points it
    already tried and missed -- that's why the part was uncovered in the
    first place). Adds a point for every candidate that lands on real
    land and is farther than `resolution_km * GAP_FILL_FACTOR` from every
    already-placed point (main lattice + supplementary points added so
    far this run), so density stays proportional to the main grid
    instead of clustering points arbitrarily close together.
    """
    try:
        from shapely.geometry import Point
        import numpy as np
    except ImportError:
        return []

    if boundary.geom_type == "Polygon":
        parts = [boundary]
    elif boundary.geom_type == "MultiPolygon":
        parts = list(boundary.geoms)
    else:
        return []

    # Only add a point once the nearest existing one is farther than this
    # -- loose enough to not double up on cells the main lattice already
    # placed, tight enough to actually catch gaps between adjacent
    # squares (two squares centered `resolution_km` apart already touch
    # edge-to-edge along that axis, but can still leave a real gap
    # diagonally or where the coastline doesn't run straight).
    GAP_FILL_FACTOR = 0.75
    threshold_km = resolution_km * GAP_FILL_FACTOR

    # Candidates are tested at a *finer* resolution than they're placed
    # at. Using resolution_km-spaced candidates (one lattice phase per
    # part, same as the main lattice) reproduces the exact bug this
    # function exists to fix: confirmed live, a 14x13km archipelago
    # "part" (an irregular, branching cluster of real skerries -- most
    # of its own bounding box is open water) only produced a 3x3 = 9
    # candidate grid, of which just 2 happened to land on real land,
    # leaving most of the part's actual coastline more than 5km from any
    # cell. A finer probe finds the true (irregular, branching) shape of
    # each part; `threshold_km` below still keeps final point density
    # comparable to the main grid.
    PROBE_KM = resolution_km / 3

    mid_lat = (SWEDEN_BBOX["min_lat"] + SWEDEN_BBOX["max_lat"]) / 2
    lon_scale = math.cos(math.radians(mid_lat))

    placed = np.array([[c.longitude * lon_scale, c.latitude] for c in cells], dtype=np.float64)

    def min_dist_km(lon: float, lat: float) -> float:
        dlon = (placed[:, 0] - lon * lon_scale) * KM_PER_DEGREE_LAT
        dlat = (placed[:, 1] - lat) * KM_PER_DEGREE_LAT
        return float(np.sqrt((dlon * dlon + dlat * dlat).min()))

    extra: list[GridCell] = []
    for i, part in enumerate(parts):
        part_minx, part_miny, part_maxx, part_maxy = part.bounds
        part_mid_lat = (part_miny + part_maxy) / 2
        lat_step = PROBE_KM / KM_PER_DEGREE_LAT
        lon_step = PROBE_KM / _km_per_degree_lon(part_mid_lat)

        part_added = 0
        lat = part_miny
        while lat <= part_maxy:
            lon = part_minx
            while lon <= part_maxx:
                if part.contains(Point(lon, lat)) and min_dist_km(lon, lat) > threshold_km:
                    extra.append(
                        GridCell(
                            cell_id=f"SE_ISLE_{i:04d}_{part_added:03d}",
                            latitude=round(lat, 5),
                            longitude=round(lon, 5),
                            region=_approx_region(lat),
                        )
                    )
                    part_added += 1
                    placed = np.vstack([placed, [[lon * lon_scale, lat]]])
                    if max_cells is not None and len(cells) + len(extra) >= max_cells:
                        return extra
                lon += lon_step
            lat += lat_step

        if part_added == 0:
            # Sub-resolution part (smaller than one grid cell in every
            # direction) -- the tiling above can legitimately land zero
            # candidates inside it. Fall back to its representative_point()
            # (guaranteed inside the polygon, unlike a plain centroid,
            # which can fall outside for concave/crescent shapes) so it
            # still gets *some* cell rather than none.
            rep = part.representative_point()
            if min_dist_km(rep.x, rep.y) > threshold_km:
                extra.append(
                    GridCell(
                        cell_id=f"SE_ISLE_{i:04d}_000",
                        latitude=round(rep.y, 5),
                        longitude=round(rep.x, 5),
                        region=_approx_region(rep.y),
                    )
                )
                placed = np.vstack([placed, [[rep.x * lon_scale, rep.y]]])
                if max_cells is not None and len(cells) + len(extra) >= max_cells:
                    return extra

    return extra


def generate_sample_grid() -> list[GridCell]:
    """A small, hand-picked, deterministic set of cells used for fast tests
    and the sample pipeline. Includes representative Swedish locations:
    central Stockholm, a forested inland spot, a wetland area, a coastal
    location and a northern-Sweden location."""
    named = [
        ("SE_STHLM", 59.3293, 18.0686, "Svealand"),   # Central Stockholm
        ("SE_FOREST", 59.6749, 14.5211, "Svealand"),  # Forested inland (Karlskoga area)
        ("SE_WETLAND", 58.6900, 16.1200, "Gotaland"), # Kolmarden wetland-adjacent
        ("SE_COAST", 57.7089, 11.9746, "Gotaland"),   # Gothenburg coastal
        ("SE_NORTH", 65.5848, 22.1567, "Norrland"),   # Lulea, northern Sweden
    ]
    return [
        GridCell(cell_id=cid, latitude=lat, longitude=lon, region=region)
        for cid, lat, lon, region in named
    ]


def save_grid(cells: list[GridCell], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([asdict(c) for c in cells], fh, ensure_ascii=False, indent=2)


def load_grid(path: Path) -> list[GridCell]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return [GridCell(**row) for row in raw]
