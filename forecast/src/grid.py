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


class _PartsContainment:
    """Point-in-boundary test via an STRtree over the boundary's individual
    parts, instead of a single `prep()`-wrapped merged MultiPolygon.

    A raster-derived boundary (see scripts/build_worldcover_boundary.py) can
    legitimately contain overlapping parts -- e.g. a WorldCover blob that's
    supposed to be dropped/clipped for being mostly redundant with the
    original Natural Earth outline, but (confirmed live, see the two
    ~68.2N parts spanning 19-20E and 22-23E) survived a rebuild at its full,
    unclipped extent, ~100% inside the existing mainland part. Combining
    such parts into one MultiPolygon is then topologically invalid (OGC
    requires MultiPolygon members not overlap) -- and confirmed live,
    `.contains(Point)` on that combined geometry (even prepared) can
    silently return False for a point genuinely covered by one of its
    member parts, which is exactly what produced two large (~15-25km
    across) white/uncovered gaps in the far-north grid despite the
    underlying boundary file having real land there. Every individual part
    coming out of this pipeline is independently valid (both
    build_worldcover_boundary.py and build_osm_land_supplement.py run
    make_valid() per-part before writing them out), so testing "does ANY
    part contain this point" via a spatial index sidesteps the invalid-
    combination problem entirely, and confirmed live is also far faster
    than repairing the whole country's geometry with make_valid() once
    (~3s for a full national lattice sweep vs. ~100s for make_valid() on
    the 58,741-part merged multipolygon)."""

    def __init__(self, parts: list):
        from shapely.strtree import STRtree

        self._parts = parts
        self._tree = STRtree(parts)

    def contains(self, point) -> bool:
        return any(self._parts[i].contains(point) for i in self._tree.query(point))


def _load_boundary_polygon(boundary_path: Path | None = None):
    """Return a shapely polygon/multipolygon for Sweden if a boundary file is
    present under data/static, else None. Uses shapely directly (already a
    hard dependency, see forecast/requirements.txt) rather than geopandas,
    so real land/ocean filtering doesn't need the heavier optional GIS
    extras -- just a plain GeoJSON FeatureCollection with one Sweden
    MultiPolygon feature (mainland + islands, incl. Gotland/Oland).

    `boundary_path` lets a caller point at an alternate boundary file (e.g. a
    small local sample being iterated on) instead of the production one."""
    boundary_path = boundary_path or (Path(__file__).resolve().parents[2] / "data" / "static" / "sweden_boundary.geojson")
    if not boundary_path.exists():
        return None
    try:
        from shapely.geometry import MultiPolygon, shape

        with open(boundary_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        geometries = [shape(feature["geometry"]) for feature in data["features"]]
        # A raster-derived boundary (see scripts/build_worldcover_boundary.py)
        # can have tens of thousands of parts (one per resolved skerry), vs.
        # ~172 for the old coarse Natural Earth source. Deliberately NOT
        # passed through unary_union(): confirmed live, dissolving that many
        # parts' shared/touching edges took 180s+ on its own, for a result
        # that behaves identically to the un-dissolved version for every
        # actual use below (.contains(), STRtree indexing, iterating
        # .geoms) -- nothing here needs adjacent parts merged into fewer,
        # bigger ones, so skip the cost entirely and flatten to one
        # MultiPolygon directly. `merged` (returned as-is, invalidity and
        # all) is only ever used downstream for .geom_type/.geoms
        # (_supplementary_island_cells iterates individual parts); the
        # containment test itself goes through _PartsContainment instead of
        # a prepared merged geometry -- see its docstring for why plain
        # prep(merged).contains() is unsafe here.
        parts = [p for geom in geometries for p in (geom.geoms if geom.geom_type == "MultiPolygon" else [geom])]
        merged = parts[0] if len(parts) == 1 else MultiPolygon(parts)
        return _PartsContainment(parts), merged
    except Exception:
        return None


def generate_grid(
    resolution_km: float = 5.0,
    bbox: dict | None = None,
    max_cells: int | None = None,
    boundary_path: Path | None = None,
) -> list[GridCell]:
    """Generate a regular lat/lon grid at approximately `resolution_km`
    spacing, filtered to Sweden's bounding box (and, if available, a real
    boundary polygon).

    `max_cells` is a safety valve for tests/sample mode so a mis-set
    resolution can't accidentally generate millions of cells. `boundary_path`
    overrides which boundary file to load (e.g. a small local sample being
    iterated on) -- also passed through to `_supplementary_island_cells` as
    the bbox it filters candidate points against, so a caller supplying both
    `bbox` and `boundary_path` gets the whole pipeline (main lattice +
    supplementary cells) scoped to that area instead of all of Sweden.
    """
    bbox = bbox or SWEDEN_BBOX
    loaded = _load_boundary_polygon(boundary_path)
    boundary_prepared, boundary_raw = loaded if loaded is not None else (None, None)

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
                if boundary_prepared is not None:
                    try:
                        from shapely.geometry import Point

                        include = boundary_prepared.contains(Point(lon, lat))
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

    if boundary_raw is not None and (max_cells is None or len(cells) < max_cells):
        cells.extend(_supplementary_island_cells(cells, boundary_raw, max_cells, bbox_override=bbox))

    return cells


def _supplementary_island_cells(
    cells: list[GridCell],
    boundary,
    max_cells: int | None,
    resolution_km: float = 5.0,
    bbox_override: dict | None = None,
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
        import shapely
        import numpy as np
    except ImportError:
        return []

    bbox = bbox_override or SWEDEN_BBOX

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
    # A raster-derived boundary (see scripts/build_worldcover_boundary.py)
    # can add tens of thousands of supplementary points -- np.vstack-per-
    # point (the original approach) reallocates and copies the *entire*
    # array on every single addition, making the whole function O(n^2) in
    # the number of points added. `placed` is instead a preallocated buffer
    # grown by doubling (the standard dynamic-array trick), with `placed_n`
    # tracking how much of it is actually in use; min_dist_km only reads
    # the `:placed_n` slice, so each addition is O(1) amortized.
    initial = np.array([[c.longitude, c.latitude] for c in cells], dtype=np.float64)
    placed_n = len(initial)
    placed = np.empty((max(placed_n * 2, 1024), 2), dtype=np.float64)
    placed[:placed_n] = initial

    def min_dist_km(lon: float, lat: float, lon_scale: float) -> float:
        active = placed[:placed_n]
        dlon = (active[:, 0] - lon) * lon_scale * KM_PER_DEGREE_LAT
        dlat = (active[:, 1] - lat) * KM_PER_DEGREE_LAT
        return float(np.sqrt((dlon * dlon + dlat * dlat).min()))

    def add_placed(lon: float, lat: float) -> None:
        nonlocal placed, placed_n
        if placed_n >= len(placed):
            grown = np.empty((len(placed) * 2, 2), dtype=np.float64)
            grown[:placed_n] = placed[:placed_n]
            placed = grown
        placed[placed_n] = (lon, lat)
        placed_n += 1

    extra: list[GridCell] = []
    for i, part in enumerate(parts):
        minx, miny, maxx, maxy = part.bounds
        mid_lat = (miny + maxy) / 2
        lon_scale = math.cos(math.radians(mid_lat))
        lat_step = PROBE_KM / KM_PER_DEGREE_LAT
        lon_step = PROBE_KM / _km_per_degree_lon(mid_lat)

        # A raster-derived boundary (see scripts/build_worldcover_boundary.py)
        # can produce tens of thousands of parts, most of them lone skerries
        # far smaller than the fringe width -- and the mainland's own bbox is
        # ~the whole country, so probing every part's *entire* bbox at fine
        # resolution would mean ~2.9M candidate points just for that one
        # part. shapely.contains_xy batches the containment test into one
        # vectorized call in C rather than a Python-level loop constructing
        # one Point() at a time (confirmed live: a 15k-point piece went from
        # ~10s to ~4ms), which is what makes probing the full bbox for every
        # part -- big or small -- fast enough to not need a separate
        # small-part fast path any more.
        lons = np.arange(minx, maxx + lon_step, lon_step)
        lats = np.arange(miny, maxy + lat_step, lat_step)
        lon_grid, lat_grid = np.meshgrid(lons, lats)
        lon_flat = lon_grid.ravel()
        lat_flat = lat_grid.ravel()
        inside = shapely.contains_xy(part, lon_flat, lat_flat)
        candidate_lons = lon_flat[inside]
        candidate_lats = lat_flat[inside]

        # The main lattice loop only ever considers points inside
        # SWEDEN_BBOX (_in_sweden_bbox); this one didn't apply the same
        # filter, and the raster-derived boundary source turns out to
        # include some geometry beyond it -- confirmed live: part 3446
        # (a real connected piece touching the western coast) spans
        # longitude 9.0-12.0, west of SWEDEN_BBOX's min_lon=10.9, and
        # produced a cell at 9.01 that output.py's bounds validation
        # correctly rejected. This never surfaced before because
        # _supplementary_island_cells never finished running against this
        # boundary source until the perf fix above. Whatever that western
        # sliver actually is (misclassified neighboring territory, a
        # coastline-tracing artifact -- Sweden's real land doesn't reach
        # that far west here), it isn't a cell this pipeline should emit.
        in_bbox = (
            (candidate_lons >= bbox["min_lon"])
            & (candidate_lons <= bbox["max_lon"])
            & (candidate_lats >= bbox["min_lat"])
            & (candidate_lats <= bbox["max_lat"])
        )
        candidate_lons = candidate_lons[in_bbox]
        candidate_lats = candidate_lats[in_bbox]

        # For a part whose bbox has room for a real interior (more than
        # fringe_deg from its own boundary everywhere), restrict to the
        # coastal fringe -- interior points are already covered by the main
        # lattice, and for the mainland skipping this would blow up the
        # (inherently sequential, since it's a greedy nearest-existing-point
        # check) loop below from ~140k candidates to ~1.3M.
        #
        # This used to be computed by eroding the polygon with
        # part.buffer(-fringe_deg) and differencing it back out -- correct,
        # but confirmed live to take 10s+ (once even 35s) on some real parts
        # from this boundary source regardless of vertex count, including
        # cases where the erosion turns out empty (i.e. the whole part is
        # fringe) so the expensive buffer() bought nothing. GEOS's negative
        # buffer is known to be pathological once the erosion distance
        # approaches or exceeds a shape's own width -- exactly the "erodes
        # to empty" case that's common here, since a coastline this
        # convoluted rarely has 15km+ of clearance everywhere. Testing
        # "within fringe_deg of the boundary" directly via shapely.dwithin
        # against part.boundary (a LineString -- no erosion, no self-
        # intersection handling, GEOS builds a spatial index for it once
        # and reuses it across the whole batch) answers the same question
        # without ever calling buffer(): confirmed live, the worst single
        # part (the mainland, 1.27M interior candidates) took 35s this way
        # vs. not finishing at all with the old approach.
        if (maxx - minx) >= 2 * fringe_deg or (maxy - miny) >= 2 * fringe_deg:
            candidate_points = shapely.points(candidate_lons, candidate_lats)
            near_boundary = shapely.dwithin(part.boundary, candidate_points, fringe_deg)
            candidate_lons = candidate_lons[near_boundary]
            candidate_lats = candidate_lats[near_boundary]

        added = 0
        for lon, lat in zip(candidate_lons, candidate_lats):
            # GridCell/json.dump need plain Python floats, not numpy
            # scalars (what a numpy array yields on iteration).
            lon = float(lon)
            lat = float(lat)
            if min_dist_km(lon, lat, lon_scale) > threshold_km:
                extra.append(
                    GridCell(
                        cell_id=f"SE_ISLE_{i:04d}_{added:03d}",
                        latitude=round(lat, 5),
                        longitude=round(lon, 5),
                        region=_approx_region(lat),
                    )
                )
                added += 1
                add_placed(lon, lat)
                if max_cells is not None and len(cells) + len(extra) >= max_cells:
                    return extra

        if added == 0:
            # Sub-probe-resolution part (smaller than PROBE_KM in some
            # direction, or just unlucky with the grid's phase) -- guarantee
            # it still gets *some* cell via its representative_point()
            # (guaranteed inside the polygon, unlike a plain centroid, which
            # can fall outside for concave/crescent shapes).
            rep = part.representative_point()
            rep_in_bbox = (
                bbox["min_lon"] <= rep.x <= bbox["max_lon"]
                and bbox["min_lat"] <= rep.y <= bbox["max_lat"]
            )
            if rep_in_bbox and min_dist_km(rep.x, rep.y, lon_scale) > threshold_km:
                extra.append(
                    GridCell(
                        cell_id=f"SE_ISLE_{i:04d}_000",
                        latitude=round(rep.y, 5),
                        longitude=round(rep.x, 5),
                        region=_approx_region(rep.y),
                    )
                )
                add_placed(rep.x, rep.y)
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
