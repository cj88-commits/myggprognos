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
    also real coastline within a much larger connected "part" (e.g. the
    mainland, or Gotland) that the old per-part check saw as already
    "covered" (some existing lattice point lies *somewhere* in that huge
    part) while still leaving real coastal land uncovered in the gaps
    between individual lattice points' squares -- confirmed live: a
    fixed-phase 5km lattice regularly leaves a cell's *nearest* point
    barely 1-7km away while still uncovered, wherever the true coastline
    is complex enough (bays, inlets, narrow peninsulas) that individual
    squares only catch slivers of it. This affects the mainland's own
    coast and Gotland just as much as it affects the outer archipelago
    (which a first version of this function fixed, but only for
    genuinely disconnected small islands).

    Probing every part's *entire* bounding box at fine resolution works
    for a small island but is far too much for the mainland (bounding
    box ~ all of Sweden). Instead this only probes a coastal fringe --
    `part` minus an inward erosion of it -- since interior points well
    away from any true edge are already covered by the regular lattice;
    for a part smaller than the fringe width (e.g. most individual
    islands) the erosion is empty and the whole part is probed, same as
    before.

    Within that fringe, tiles at the same `resolution_km` spacing as the
    main lattice would reproduce the exact bug this function exists to
    fix: confirmed live, a 14x13km archipelago "part" (an irregular,
    branching cluster of real skerries -- most of its own bounding box
    is open water) only produced a 3x3 = 9 candidate grid at that
    spacing, of which just 2 happened to land on real land. Probing at a
    *finer* resolution instead finds the true (irregular, branching)
    shape; `threshold_km` below still keeps final point density
    comparable to the main grid by only keeping a candidate when the
    nearest already-placed point (main lattice + supplementary points
    added so far) is farther away than that.
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

    # Only add a point once the nearest existing one is farther than this.
    # Must match a normal cell's actual painted *reach*, not just "close
    # enough to seem redundant": a lattice point sitting on solid land
    # (the common case -- prepare_cell_geometry.py only widens a cell's
    # search past its own un-widened square when that square has *zero*
    # land at all) only ever gets painted out to half of resolution_km
    # from its own center. An earlier version of this threshold used
    # 0.75x resolution_km (3.75km) on the reasoning that adjacent
    # squares "already touch edge-to-edge" at that spacing -- true for
    # the *squares themselves*, but irrelevant, since what's actually
    # painted is each square clipped to real land, not the raw square.
    # That left a real dead zone from 2.5km (true reach) to 3.75km (old
    # threshold) where a point registered as "close enough, skip it" yet
    # sat outside every nearby cell's real painted polygon. Confirmed
    # live: sampling coastal points specifically (land within 3km of the
    # true shoreline, not a whole-country uniform sample which dilutes
    # the coast with the much larger, unaffected interior) found ~12%
    # still uncovered after the first version of this fix, with nearly
    # every uncovered point's nearest cell sitting 3.0-3.8km away --
    # squarely inside that dead zone.
    GAP_FILL_FACTOR = 0.5
    threshold_km = resolution_km * GAP_FILL_FACTOR

    # How far inward from a part's true edge to probe. Must comfortably
    # exceed threshold_km (points deeper inside than that are always
    # already "covered" by definition) with margin for the fact that the
    # nearest existing lattice point to a given spot on the coast isn't
    # necessarily the inland one geometrically closest to the true edge.
    COASTAL_FRINGE_KM = 15.0

    # Fine enough to reliably catch a real ~1km-wide feature regardless of
    # the probe grid's phase (worst-case offset from any point to the
    # nearest probe node is PROBE_KM*sqrt(2)/2 =~ 0.42km at this spacing,
    # comfortably under 1km) without being wastefully slow: confirmed
    # live, resolution_km/3 (~1.67km) still straddle-missed real land
    # 1-1.2km from two separate reported gaps, both sitting inside one
    # single large connected fringe piece (the mainland's own coastal
    # band doesn't fragment into separate per-skerry pieces the way a
    # true archipelago's does -- our boundary source doesn't model those
    # skerries as topologically separate from the mainland at all, so
    # there's no smaller connected piece for a per-piece fallback to
    # catch; only a finer probe helps here). Tested 0.25km directly:
    # ~17 minutes for the mainland's fringe alone, too slow for routine
    # re-runs; 0.6km was ~96s for the same (by far the largest) fringe.
    PROBE_KM = 0.6
    fringe_deg = COASTAL_FRINGE_KM / KM_PER_DEGREE_LAT

    # Kept RAW (unscaled) here -- a single longitude-scale factor for the
    # *whole* placed array would need to pick one fixed reference
    # latitude for all of Sweden (55.3-69.1 deg N), which is exactly the
    # bug this replaced: using SWEDEN_BBOX's overall midpoint (~62 deg N)
    # systematically under-measured true distances in the south and
    # over-measured them in the north (cos(57 deg) is ~16% bigger than
    # cos(62 deg)). Confirmed live: this alone silently sank a real
    # ~4.3km gap on Gotland (57 deg N) to a computed ~3.7km -- just
    # under GAP_FILL_FACTOR's threshold, so no cell ever got added
    # there. min_dist_km below instead takes the *local* scale for
    # whichever part is currently being probed.
    placed = np.array([[c.longitude, c.latitude] for c in cells], dtype=np.float64)

    def min_dist_km(lon: float, lat: float, lon_scale: float) -> float:
        dlon = (placed[:, 0] - lon) * lon_scale * KM_PER_DEGREE_LAT
        dlat = (placed[:, 1] - lat) * KM_PER_DEGREE_LAT
        return float(np.sqrt((dlon * dlon + dlat * dlat).min()))

    def _polygon_pieces(geom) -> list:
        """Flatten a Polygon/MultiPolygon/GeometryCollection (the latter
        can come out of a difference() near self-intersections) down to
        its individual Polygon pieces, dropping any stray lines/points."""
        if geom.is_empty:
            return []
        if geom.geom_type == "Polygon":
            return [geom]
        if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
            pieces: list = []
            for sub in geom.geoms:
                pieces.extend(_polygon_pieces(sub))
            return pieces
        return []

    extra: list[GridCell] = []
    for i, part in enumerate(parts):
        interior = part.buffer(-fringe_deg)
        fringe = part.difference(interior) if not interior.is_empty else part
        # A part's fringe is frequently itself disconnected -- e.g. the
        # mainland's coastal band, intersected with a genuinely
        # fragmented stretch of coast (Bohuslan, the outer archipelago),
        # splits into many separate small pieces, each really its own
        # lone skerry. Probing the fringe as ONE region with a single
        # fixed-phase grid (the previous version of this function) can
        # straddle-miss any piece narrower than the probe spacing --
        # confirmed live: real land 1-1.2km from two separate reported
        # gaps, inside the mainland's fringe, got zero probe hits despite
        # PROBE_KM being well under that. Processing each connected piece
        # separately, with its own guaranteed representative_point()
        # fallback (the same safety net the original per-part version of
        # this function relied on), removes that phase-alignment risk.
        for j, piece in enumerate(_polygon_pieces(fringe)):
            piece_minx, piece_miny, piece_maxx, piece_maxy = piece.bounds
            piece_mid_lat = (piece_miny + piece_maxy) / 2
            piece_lon_scale = math.cos(math.radians(piece_mid_lat))
            lat_step = PROBE_KM / KM_PER_DEGREE_LAT
            lon_step = PROBE_KM / _km_per_degree_lon(piece_mid_lat)

            piece_added = 0
            lat = piece_miny
            while lat <= piece_maxy:
                lon = piece_minx
                while lon <= piece_maxx:
                    if piece.contains(Point(lon, lat)) and min_dist_km(lon, lat, piece_lon_scale) > threshold_km:
                        extra.append(
                            GridCell(
                                cell_id=f"SE_ISLE_{i:04d}_{j:04d}_{piece_added:03d}",
                                latitude=round(lat, 5),
                                longitude=round(lon, 5),
                                region=_approx_region(lat),
                            )
                        )
                        piece_added += 1
                        placed = np.vstack([placed, [[lon, lat]]])
                        if max_cells is not None and len(cells) + len(extra) >= max_cells:
                            return extra
                    lon += lon_step
                lat += lat_step

            if piece_added == 0:
                # Sub-probe-resolution piece (smaller than PROBE_KM in
                # some direction, or just unlucky with the grid's phase)
                # -- guarantee it still gets *some* cell via its
                # representative_point() (guaranteed inside the polygon,
                # unlike a plain centroid, which can fall outside for
                # concave/crescent shapes).
                rep = piece.representative_point()
                if min_dist_km(rep.x, rep.y, piece_lon_scale) > threshold_km:
                    extra.append(
                        GridCell(
                            cell_id=f"SE_ISLE_{i:04d}_{j:04d}_000",
                            latitude=round(rep.y, 5),
                            longitude=round(rep.x, 5),
                            region=_approx_region(rep.y),
                        )
                    )
                    placed = np.vstack([placed, [[rep.x, rep.y]]])
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
