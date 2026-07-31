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


def _supplementary_island_cells(cells: list[GridCell], boundary, max_cells: int | None) -> list[GridCell]:
    """Add one extra cell for every distinct piece of land (island) the
    regular lattice above misses entirely.

    The lattice only places a point every `resolution_km`, so any island
    smaller than that spacing -- and unluckily positioned between lattice
    points -- gets zero cells and can never be coloured on the map,
    regardless of any frontend rendering technique. Rather than shrinking
    the resolution everywhere (a ~6x cell-count/API-cost increase for 5km
    -> 2km), this surgically fixes just the islands that would otherwise
    be completely uncovered: for every polygon part of the boundary with
    no existing lattice point inside it, add a single cell at that part's
    `representative_point()` (guaranteed to lie inside the polygon, unlike
    a plain centroid which can fall outside for concave/crescent shapes).
    """
    try:
        from shapely.geometry import Point
    except ImportError:
        return []

    if boundary.geom_type == "Polygon":
        parts = [boundary]
    elif boundary.geom_type == "MultiPolygon":
        parts = list(boundary.geoms)
    else:
        return []

    existing_points = [Point(c.longitude, c.latitude) for c in cells]
    extra: list[GridCell] = []
    for i, part in enumerate(parts):
        if any(part.contains(p) for p in existing_points):
            continue
        rep = part.representative_point()
        extra.append(
            GridCell(
                cell_id=f"SE_ISLE_{i:04d}",
                latitude=round(rep.y, 5),
                longitude=round(rep.x, 5),
                region=_approx_region(rep.y),
            )
        )
        if max_cells is not None and len(cells) + len(extra) >= max_cells:
            break

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
