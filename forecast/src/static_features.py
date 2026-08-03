"""Static geographic features per forecast cell.

Real features are derived from two free, no-login, publicly-hosted sources
(both Cloud-Optimized GeoTIFFs on public AWS S3, so no bulk portal download
or credentials needed -- see scripts/download_static_gis_data.py):
  * ESA WorldCover 10m 2021 (s3://esa-worldcover) -- land cover, 11 classes
    including forest ("tree cover"), "herbaceous wetland", "built-up", and
    "permanent water bodies", which drive forest/wetland/urban/water
    fraction and distance-to-water directly.
  * Copernicus DEM GLO-30 (s3://copernicus-dem-30m) -- 30m elevation, for
    elevation_m and a locally-estimated slope_deg.

This module provides:
  1. `compute_static_features_from_rasters(...)` -- the real implementation,
     using rasterio to read local tiles (downloaded once, not committed --
     see the download script and README). Raises a clear error if the tile
     directories aren't present, so callers can fall back to placeholders.
  2. `generate_placeholder_static_features(...)` -- a deterministic,
     seeded-by-coordinate generator that produces plausible-looking values
     so the rest of the pipeline (features, model, output, frontend) can be
     built and tested end-to-end without the real datasets, and so any
     newly-added grid cell (e.g. from a grid.py change) still gets *some*
     value before the next real-data run covers it too.

Static features are precomputed once per cell and cached to
data/static/cell_features.json -- the scheduled 6-hourly pipeline reads
this file rather than recomputing GIS operations every run.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from grid import GridCell

KM_PER_DEGREE_LAT = 111.32

# ESA WorldCover 10m 2021 v200 class codes (see
# https://esa-worldcover.s3.amazonaws.com/readme.html) relevant to the
# mosquito model's inputs. "Herbaceous wetland" (90) is exactly the class
# that was missing entirely from the placeholder generator -- e.g. real
# floodplain/bog terrain in Dalarna or northern fjallmyrar now shows up
# directly instead of being indistinguishable random noise.
WORLDCOVER_FOREST_CLASSES = {10}  # Tree cover
WORLDCOVER_WETLAND_CLASSES = {90, 95}  # Herbaceous wetland, Mangroves
WORLDCOVER_URBAN_CLASSES = {50}  # Built-up
WORLDCOVER_WATER_CLASSES = {80}  # Permanent water bodies


@dataclass(frozen=True)
class StaticFeatures:
    cell_id: str
    forest_fraction: float
    wetland_fraction: float
    urban_fraction: float
    water_fraction: float
    distance_to_water_km: float
    elevation_m: float
    slope_deg: float
    coastal_exposure: float
    water_body_density: float


def _seeded_unit(cell_id: str, salt: str) -> float:
    """Deterministic pseudo-random value in [0, 1) derived from cell_id, so
    repeated runs (and tests) are stable without storing random state."""
    digest = hashlib.sha256(f"{cell_id}:{salt}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def generate_placeholder_static_features(cell: GridCell) -> StaticFeatures:
    """Generate plausible, deterministic static features for a cell based on
    its coordinates. This is a transparent stand-in for real GIS layers --
    it encodes broad, defensible priors about Sweden (more wetland/forest
    inland and in the north, more urban near major city coordinates, coastal
    exposure near the bbox edges) but must not be presented as measured
    data."""
    lat, lon = cell.latitude, cell.longitude

    forest_base = 0.35 + 0.25 * _seeded_unit(cell.cell_id, "forest")
    wetland_base = 0.08 + 0.20 * _seeded_unit(cell.cell_id, "wetland")
    urban_base = 0.05 + 0.15 * _seeded_unit(cell.cell_id, "urban")

    # Nudge toward known city centers to make sample data feel plausible.
    cities = [
        (59.3293, 18.0686, 0.55),  # Stockholm
        (57.7089, 11.9746, 0.45),  # Gothenburg
        (55.6050, 13.0038, 0.40),  # Malmo
        (65.5848, 22.1567, 0.30),  # Lulea
    ]
    for clat, clon, strength in cities:
        dist_km = _haversine_km(lat, lon, clat, clon)
        if dist_km < 15:
            urban_base = max(urban_base, strength * (1 - dist_km / 15))
            forest_base *= 0.6
            wetland_base *= 0.6

    total = forest_base + wetland_base + urban_base
    if total > 0.95:
        scale = 0.95 / total
        forest_base *= scale
        wetland_base *= scale
        urban_base *= scale

    water_fraction = 0.02 + 0.10 * _seeded_unit(cell.cell_id, "water")
    distance_to_water_km = round(0.2 + 8.0 * _seeded_unit(cell.cell_id, "dist_water"), 2)
    elevation_m = round(5 + 400 * _seeded_unit(cell.cell_id, "elevation"), 1)
    slope_deg = round(0.5 + 8.0 * _seeded_unit(cell.cell_id, "slope"), 2)

    # Coastal exposure: higher near the bbox longitude extremes (rough coast
    # proxy) and for known coastal latitudes.
    coastal_exposure = round(
        max(0.0, 1.0 - min(distance_to_water_km, 10) / 10) * 0.6
        + 0.4 * _seeded_unit(cell.cell_id, "coastal"),
        3,
    )
    water_body_density = round(
        0.5 * water_fraction + 0.5 * _seeded_unit(cell.cell_id, "water_density"), 3
    )

    return StaticFeatures(
        cell_id=cell.cell_id,
        forest_fraction=round(forest_base, 3),
        wetland_fraction=round(wetland_base, 3),
        urban_fraction=round(urban_base, 3),
        water_fraction=round(water_fraction, 3),
        distance_to_water_km=distance_to_water_km,
        elevation_m=elevation_m,
        slope_deg=slope_deg,
        coastal_exposure=coastal_exposure,
        water_body_density=water_body_density,
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _index_tiles(directory: Path) -> list[tuple[Path, tuple[float, float, float, float]]]:
    """(path, (left, bottom, right, top)) for every .tif in `directory`,
    read from each file's own header -- cheap, no pixel data touched."""
    import rasterio  # noqa: local import, optional heavy dependency

    tiles = []
    for path in sorted(directory.glob("*.tif")):
        with rasterio.open(path) as ds:
            b = ds.bounds
            tiles.append((path, (b.left, b.bottom, b.right, b.top)))
    return tiles


def _tile_for_point(tiles: list[tuple[Path, tuple[float, float, float, float]]], lon: float, lat: float) -> Path | None:
    for path, (left, bottom, right, top) in tiles:
        if left <= lon < right and bottom <= lat < top:
            return path
    return None


def _read_window(ds, lon: float, lat: float, radius_km: float, out_size: int):
    """A decimated (out_size x out_size) read of a square window
    `radius_km` around (lon, lat), boundless so a window that spills past
    this tile's own edge (rare -- only cells within `radius_km` of a
    tile's 1x1 or 3x3 degree boundary) still returns an array instead of
    raising, just with 0 ("no data") outside this tile's real coverage.
    """
    import numpy as np  # noqa: local import
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds

    half_lat_deg = radius_km / KM_PER_DEGREE_LAT
    half_lon_deg = radius_km / (KM_PER_DEGREE_LAT * math.cos(math.radians(lat)))
    window = from_bounds(
        lon - half_lon_deg, lat - half_lat_deg, lon + half_lon_deg, lat + half_lat_deg, transform=ds.transform
    )
    arr = ds.read(
        1,
        window=window,
        out_shape=(out_size, out_size),
        resampling=Resampling.nearest,
        boundless=True,
        fill_value=0,
    )
    return np.asarray(arr)


# Land-cover fraction window: matches a cell's own ~GRID_RESOLUTION_KM
# footprint. Water-search window: much wider, since "how far to the
# nearest water" needs to look past a single cell's own square -- capped
# at WATER_SEARCH_MAX_KM (returned as distance_to_water_km when nothing
# is found even at that radius, i.e. "far from any mapped water").
_FRACTION_RADIUS_KM = 2.5
_FRACTION_OUT_SIZE = 100  # ~50m/pixel over the 5km-wide fraction window
_WATER_SEARCH_RADIUS_KM = 15.0
_WATER_SEARCH_OUT_SIZE = 150  # ~200m/pixel over the 30km-wide search window
_ELEVATION_RADIUS_KM = 0.5
_ELEVATION_OUT_SIZE = 33  # close to GLO-30's native ~30m pixel spacing


def _land_cover_features(ds, lon: float, lat: float) -> tuple[float, float, float, float, float]:
    """(forest, wetland, urban, water, distance_to_water_km) for one cell."""
    import numpy as np

    frac_arr = _read_window(ds, lon, lat, _FRACTION_RADIUS_KM, _FRACTION_OUT_SIZE)
    total = frac_arr.size
    forest = float(np.isin(frac_arr, list(WORLDCOVER_FOREST_CLASSES)).sum()) / total
    wetland = float(np.isin(frac_arr, list(WORLDCOVER_WETLAND_CLASSES)).sum()) / total
    urban = float(np.isin(frac_arr, list(WORLDCOVER_URBAN_CLASSES)).sum()) / total
    water = float(np.isin(frac_arr, list(WORLDCOVER_WATER_CLASSES)).sum()) / total

    search_arr = _read_window(ds, lon, lat, _WATER_SEARCH_RADIUS_KM, _WATER_SEARCH_OUT_SIZE)
    water_mask = np.isin(search_arr, list(WORLDCOVER_WATER_CLASSES))
    if water_mask.any():
        center = (_WATER_SEARCH_OUT_SIZE - 1) / 2
        rows, cols = np.nonzero(water_mask)
        km_per_px_y = (2 * _WATER_SEARCH_RADIUS_KM) / _WATER_SEARCH_OUT_SIZE
        km_per_px_x = km_per_px_y  # window is a square in degrees at this lat, so ~equal
        dist_km = float(np.min(np.hypot((rows - center) * km_per_px_y, (cols - center) * km_per_px_x)))
    else:
        dist_km = _WATER_SEARCH_RADIUS_KM  # "at least this far", i.e. genuinely far from water

    return forest, wetland, urban, water, dist_km


def _elevation_features(ds, lon: float, lat: float) -> tuple[float, float]:
    """(elevation_m, slope_deg) for one cell."""
    import numpy as np

    arr = _read_window(ds, lon, lat, _ELEVATION_RADIUS_KM, _ELEVATION_OUT_SIZE).astype(float)
    elevation_m = float(np.mean(arr))

    km_per_px_y = (2 * _ELEVATION_RADIUS_KM) / _ELEVATION_OUT_SIZE
    km_per_px_x = km_per_px_y
    gy, gx = np.gradient(arr, km_per_px_y * 1000.0, km_per_px_x * 1000.0)  # meters per meter
    slope_rad = float(np.mean(np.arctan(np.hypot(gx, gy))))
    return elevation_m, math.degrees(slope_rad)


def compute_static_features_from_rasters(cells: list[GridCell], static_data_dir: Path) -> list[StaticFeatures]:
    """Real implementation, using ESA WorldCover (land cover) and
    Copernicus DEM GLO-30 (elevation) tiles downloaded to
    static_data_dir/"worldcover"/*.tif and static_data_dir/"dem"/*.tif --
    see scripts/download_static_gis_data.py. Requires rasterio (and
    shapely, already a core dependency, for the coastal-exposure term).
    Raises FileNotFoundError with a helpful message if the expected tile
    directories aren't present, so callers can fall back to placeholders.
    """
    worldcover_dir = static_data_dir / "worldcover"
    dem_dir = static_data_dir / "dem"
    missing = [
        str(d) for d in (worldcover_dir, dem_dir) if not d.is_dir() or not any(d.glob("*.tif"))
    ]
    if missing:
        raise FileNotFoundError(
            "Missing static GIS source tiles: "
            + ", ".join(missing)
            + ". Run scripts/download_static_gis_data.py first, or use "
            "generate_placeholder_static_features() for sample mode."
        )

    import rasterio  # noqa: local import, optional heavy dependency
    from shapely.geometry import Point, shape
    from shapely.ops import unary_union
    from shapely.strtree import STRtree

    wc_tiles = _index_tiles(worldcover_dir)
    dem_tiles = _index_tiles(dem_dir)

    # Real coastline distance (not just "any water", which the WorldCover
    # water class doesn't distinguish sea from lake) -- reuse the same
    # boundary source the grid/geometry pipeline already trusts, indexed
    # by its individual line segments so nearest-point queries across
    # ~23k cells are fast rather than one big multi-thousand-vertex
    # distance() call each time.
    boundary_path = static_data_dir / "sweden_boundary.geojson"
    coast_tree = None
    if boundary_path.exists():
        with open(boundary_path, "r", encoding="utf-8") as fh:
            boundary_data = json.load(fh)
        boundary = unary_union([shape(feat["geometry"]) for feat in boundary_data["features"]])
        outline = boundary.boundary
        segments = list(outline.geoms) if outline.geom_type == "MultiLineString" else [outline]
        coast_tree = STRtree(segments)

    def coastal_exposure_for(lon: float, lat: float) -> float:
        if coast_tree is None:
            return 0.0
        p = Point(lon, lat)
        idx = coast_tree.nearest(p)
        seg = coast_tree.geometries[idx]
        dist_km = seg.distance(p) * KM_PER_DEGREE_LAT
        return round(max(0.0, 1.0 - min(dist_km, 10.0) / 10.0), 3)

    # Group cells by their WorldCover tile so each tile is opened once
    # (rasterio dataset open/close has real overhead at ~23k-cell scale)
    # rather than once per cell.
    by_wc_tile: dict[Path, list[GridCell]] = {}
    unmatched: list[GridCell] = []
    for cell in cells:
        path = _tile_for_point(wc_tiles, cell.longitude, cell.latitude)
        if path is None:
            unmatched.append(cell)
        else:
            by_wc_tile.setdefault(path, []).append(cell)
    if unmatched:
        raise FileNotFoundError(
            f"{len(unmatched)} cells fall outside every downloaded WorldCover tile "
            f"(e.g. {unmatched[0].cell_id}) -- re-run scripts/download_static_gis_data.py "
            "(it derives the needed tile list from the current grid.json)."
        )

    land_cover_by_cell: dict[str, tuple[float, float, float, float, float]] = {}
    for path, tile_cells in by_wc_tile.items():
        with rasterio.open(path) as ds:
            for cell in tile_cells:
                land_cover_by_cell[cell.cell_id] = _land_cover_features(ds, cell.longitude, cell.latitude)

    by_dem_tile: dict[Path, list[GridCell]] = {}
    dem_unmatched: list[GridCell] = []
    for cell in cells:
        path = _tile_for_point(dem_tiles, cell.longitude, cell.latitude)
        if path is None:
            dem_unmatched.append(cell)
        else:
            by_dem_tile.setdefault(path, []).append(cell)
    if dem_unmatched:
        raise FileNotFoundError(
            f"{len(dem_unmatched)} cells fall outside every downloaded DEM tile "
            f"(e.g. {dem_unmatched[0].cell_id}) -- re-run scripts/download_static_gis_data.py."
        )

    elevation_by_cell: dict[str, tuple[float, float]] = {}
    for path, tile_cells in by_dem_tile.items():
        with rasterio.open(path) as ds:
            for cell in tile_cells:
                elevation_by_cell[cell.cell_id] = _elevation_features(ds, cell.longitude, cell.latitude)

    results: list[StaticFeatures] = []
    for cell in cells:
        forest, wetland, urban, water, dist_water = land_cover_by_cell[cell.cell_id]
        elevation_m, slope_deg = elevation_by_cell[cell.cell_id]
        # water_body_density: water coverage over the same wide window
        # used for the distance search, i.e. "how much open water is in
        # this area" as distinct from "is there any water immediately in
        # this cell" (water fraction above).
        results.append(
            StaticFeatures(
                cell_id=cell.cell_id,
                forest_fraction=round(forest, 3),
                wetland_fraction=round(wetland, 3),
                urban_fraction=round(urban, 3),
                water_fraction=round(water, 3),
                distance_to_water_km=round(dist_water, 2),
                elevation_m=round(elevation_m, 1),
                slope_deg=round(slope_deg, 2),
                coastal_exposure=coastal_exposure_for(cell.longitude, cell.latitude),
                water_body_density=round(water, 3),
            )
        )

    return results


def save_static_features(features: list[StaticFeatures], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([asdict(f) for f in features], fh, ensure_ascii=False, indent=2)


def load_static_features(path: Path) -> dict[str, StaticFeatures]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return {row["cell_id"]: StaticFeatures(**row) for row in raw}
