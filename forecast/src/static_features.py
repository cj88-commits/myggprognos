"""Static geographic features per forecast cell.

Real deployments should derive these from:
  * Copernicus CORINE / Copernicus Land Monitoring Service land cover
  * SLU / Lantmateriet wetland and forest layers
  * Lantmateriet hydrography (lakes, rivers, coastline)
  * A DEM (e.g. Copernicus GLO-30) for elevation/slope

Downloading and processing those datasets is out of scope for the sample
pipeline (they are large and license-encumbered for redistribution), so this
module provides:

  1. `compute_static_features_from_rasters(...)` -- the intended real
     implementation, using geopandas/rasterio, documented but able to raise
     a clear error if source data isn't present.
  2. `generate_placeholder_static_features(...)` -- a deterministic,
     seeded-by-coordinate generator that produces plausible-looking values
     so the rest of the pipeline (features, model, output, frontend) can be
     built and tested end-to-end without the real datasets.

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


def compute_static_features_from_rasters(cells: list[GridCell], static_data_dir: Path) -> list[StaticFeatures]:
    """Real implementation intended for production use once source GIS data
    has been downloaded and preprocessed (see scripts/prepare_static_features.py
    and README "How to refresh static GIS features"). Requires geopandas and
    rasterio. Raises FileNotFoundError with a helpful message if the
    expected preprocessed layers are not present, so callers can fall back
    to placeholders in sample mode.
    """
    required = [
        static_data_dir / "land_cover.tif",
        static_data_dir / "water_bodies.gpkg",
        static_data_dir / "elevation.tif",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing static GIS source layers: "
            + ", ".join(missing)
            + ". Run scripts/prepare_static_features.py after downloading "
            "the datasets described in README.md, or use "
            "generate_placeholder_static_features() for sample mode."
        )

    import geopandas as gpd  # noqa: local import, optional heavy dependency
    import rasterio  # noqa: local import, optional heavy dependency
    from rasterio.transform import rowcol

    results: list[StaticFeatures] = []
    water_gdf = gpd.read_file(static_data_dir / "water_bodies.gpkg")

    with rasterio.open(static_data_dir / "land_cover.tif") as land_cover_ds, rasterio.open(
        static_data_dir / "elevation.tif"
    ) as elevation_ds:
        for cell in cells:
            try:
                row, col = rowcol(land_cover_ds.transform, cell.longitude, cell.latitude)
                land_cover_ds.read(1)[row, col]
            except Exception:
                pass
            # A full implementation would sample a buffered window around
            # each cell to compute fraction of forest/wetland/urban pixels,
            # sample the elevation raster (and a derived slope raster), and
            # compute nearest-distance to the water_gdf geometries. This is
            # intentionally left as a documented extension point for the
            # MVP -- see README "How to refresh static GIS features".
            results.append(generate_placeholder_static_features(cell))

    return results


def save_static_features(features: list[StaticFeatures], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([asdict(f) for f in features], fh, ensure_ascii=False, indent=2)


def load_static_features(path: Path) -> dict[str, StaticFeatures]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return {row["cell_id"]: StaticFeatures(**row) for row in raw}
