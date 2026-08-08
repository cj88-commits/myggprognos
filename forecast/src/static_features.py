"""Static geographic features per forecast cell.

Real features are derived from three free, no-login, publicly-hosted
sources:
  * ESA WorldCover 10m 2021 (s3://esa-worldcover, Cloud-Optimized GeoTIFF)
    -- land cover, 11 classes including forest ("tree cover"), "herbaceous
    wetland", "built-up", and "permanent water bodies", which drive
    forest/wetland/urban/water fraction and distance-to-water directly.
    Covers all of Sweden but conflates tree-covered wetland (e.g. northern
    fjallmyrar, sumpskog) into the single "tree cover" class -- see
    scripts/download_static_gis_data.py.
  * Nationella Marktackedata (NMD) 2023 v2.x, from Naturvardsverket
    (geodata.naturvardsverket.se) -- 10m land cover with 54 classes,
    crucially distinguishing forest-on-wetland from forest-on-firm-ground
    (by species) and subdividing open wetland into ~15 mire/non-mire
    types. Used to override the WorldCover-derived fraction for any cell
    where NMD has real (non-placeholder) coverage; falls back to
    WorldCover elsewhere. As of v2.1, NMD production has finished southern
    Sweden (<1% uncovered) but is still rolling out north of ~62N (~19%
    uncovered) and especially in the far-north mountains (~46%
    uncovered) -- see scripts/download_nmd_data.py. Single national
    raster in SWEREF99 TM (EPSG:3006), not WGS84.
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

# NMD2023 v2.x class codes (see Bilaga 5 of Naturvardsverket's product
# description, geodata.naturvardsverket.se/nedladdning/marktacke/NMD2023/).
# Unlike WorldCover, forest is split by what's underneath it -- "on wetland"
# classes (121-128, 23) are real tree-covered wetland (e.g. sumpskog,
# tallmossar) and are counted toward *both* forest_fraction and
# wetland_fraction, since that's exactly the terrain WorldCover's single
# "tree cover" class was hiding.
NMD_FOREST_ON_FIRM_CLASSES = {111, 112, 113, 114, 115, 116, 117, 118}
NMD_FOREST_ON_WETLAND_CLASSES = {121, 122, 123, 124, 125, 126, 127, 128}
NMD_ALPINE_TREES_ON_FIRM_CLASSES = {43}
NMD_ALPINE_TREES_ON_WETLAND_CLASSES = {23}
NMD_FOREST_CLASSES = (
    NMD_FOREST_ON_FIRM_CLASSES | NMD_FOREST_ON_WETLAND_CLASSES
    | NMD_ALPINE_TREES_ON_FIRM_CLASSES | NMD_ALPINE_TREES_ON_WETLAND_CLASSES
)
NMD_OPEN_WETLAND_ON_MIRE_CLASSES = {200, 211, 212, 213, 214, 215, 216, 217, 218}
NMD_OPEN_WETLAND_NOT_ON_MIRE_CLASSES = {221, 222, 223, 224, 225, 226, 227, 228}
NMD_WETLAND_CLASSES = (
    NMD_OPEN_WETLAND_ON_MIRE_CLASSES | NMD_OPEN_WETLAND_NOT_ON_MIRE_CLASSES
    | NMD_FOREST_ON_WETLAND_CLASSES | NMD_ALPINE_TREES_ON_WETLAND_CLASSES
)
NMD_URBAN_CLASSES = {51, 52, 53}  # Building, other artificial, road/railway
NMD_WATER_CLASSES = {61, 62}  # Inland water, marine water
NMD_NODATA_VALUE = 0  # Not (yet) classified -- see module docstring re. rollout


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
    # True for generate_placeholder_static_features() output, False for real
    # raster-derived values. Previously there was no way to tell the two
    # apart once written to cell_features.json -- a cell that individually
    # fell back to placeholder generation (e.g. missing from the file, or
    # outside downloaded raster tile coverage) was indistinguishable from
    # one with real GIS data, so pipeline.py's confidence calculation used
    # one dataset-wide flag instead of the per-cell truth (see
    # docs/model-audit-before.md bug #2). Defaults to False so a
    # pre-existing cell_features.json written before this field existed
    # loads as "real" -- correct for this repo's current committed data,
    # which was fully raster-derived with no missing-cell fallback.
    is_placeholder: bool = False

    # --- Multi-scale water/wetland (geographic-model redesign, Phase 4) ---
    # See docs/geographic-model-audit-before.md #4.1/#4.3: `water_fraction`/
    # `water_body_density` above are single-scale (2.5km window) and, in the
    # real data path, `water_body_density` was found to be an exact
    # duplicate of `water_fraction` rather than an independent signal. These
    # new fields are genuinely multi-scale, all derived from ONE wider
    # raster read per cell (see `_land_cover_and_habitat_features`) so a
    # large deep lake (high water_fraction_5km, near-zero shoreline/edge
    # density) reads differently from a marshy pond-and-margin landscape
    # with the same raw water_fraction. Defaults are neutral/zero so old
    # cached cell_features.json rows without these fields still load.
    water_fraction_500m: float = 0.0
    water_fraction_2km: float = 0.0
    water_fraction_5km: float = 0.0
    wetland_fraction_500m: float = 0.0
    wetland_fraction_2km: float = 0.0
    wetland_fraction_5km: float = 0.0
    # Fraction of adjacent-pixel-pairs, in a 2km window, that cross a
    # water/non-water (or forest/water, wetland/water) boundary -- a cheap
    # proxy for interface length without full vector boundary geometry. High
    # for many small ponds/irregular margins, low for both a solid forest
    # block and the deep interior of one big lake.
    shoreline_density: float = 0.0
    forest_water_edge_density: float = 0.0
    wetland_water_edge_density: float = 0.0
    # water_fraction_2km, discounted where the cell sits deep inside one of
    # the 47 named major lakes in data/static/sweden_lakes.geojson (see
    # `_major_lake_status`) -- open lake interior is not breeding habitat,
    # small ponds/streams/lake margins are.
    small_water_density: float = 0.0
    major_lake_interior: bool = False
    # Static, weather-independent proxy for "does this landscape resemble
    # floodplain terrain" (gentle slope + near water + wetland-adjacent) --
    # NOT an actual flood event, which remains weather-driven (see
    # feature_engineering.py's emergence/pressure functions, Phase 5/6).
    floodplain_potential: float = 0.0
    # Explicit, slow-changing "how capable is this landscape of supporting
    # large mosquito populations if weather is favourable" score (Phase 3).
    # See `compute_habitat_capacity` for the formula. Computed once here
    # (not per hourly/daypart score call) since it depends only on static
    # inputs. Default 50.0 (neutral/moderate) rather than 0.0 so fixtures/
    # cached data predating this field don't silently read as "no habitat".
    habitat_capacity: float = 50.0


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

    # Multi-scale/edge placeholders (Phase 4): deterministic, seeded, and
    # loosely consistent with the base fractions above (more water/wetland
    # nearby at wider radii than immediately in-cell is the norm for real
    # terrain), not independently random -- so placeholder-mode habitat
    # capacity behaves plausibly for sample-mode/local dev, without
    # pretending to be real GIS data (is_placeholder=True is still set).
    water_fraction_500m = round(clamp(water_fraction * (0.6 + 0.4 * _seeded_unit(cell.cell_id, "w500")), 0, 1), 3)
    water_fraction_2km = round(clamp(water_fraction * (0.9 + 0.4 * _seeded_unit(cell.cell_id, "w2k")), 0, 1), 3)
    water_fraction_5km = round(clamp(water_fraction * (1.0 + 0.6 * _seeded_unit(cell.cell_id, "w5k")), 0, 1), 3)
    wetland_fraction_500m = round(clamp(wetland_base * (0.6 + 0.4 * _seeded_unit(cell.cell_id, "wl500")), 0, 1), 3)
    wetland_fraction_2km = round(clamp(wetland_base * (0.9 + 0.4 * _seeded_unit(cell.cell_id, "wl2k")), 0, 1), 3)
    wetland_fraction_5km = round(clamp(wetland_base * (1.0 + 0.6 * _seeded_unit(cell.cell_id, "wl5k")), 0, 1), 3)

    shoreline_density = round(0.15 * water_fraction_2km * _seeded_unit(cell.cell_id, "shoreline"), 4)
    forest_water_edge_density = round(0.12 * forest_base * water_fraction_2km * _seeded_unit(cell.cell_id, "fw_edge"), 4)
    wetland_water_edge_density = round(0.15 * wetland_fraction_2km * _seeded_unit(cell.cell_id, "wlw_edge"), 4)

    major_lake_interior = water_fraction_5km > 0.6 and _seeded_unit(cell.cell_id, "major_lake") > 0.6
    small_water_density = round(water_fraction_2km * (0.05 if major_lake_interior else 1.0), 4)

    floodplain_potential = compute_floodplain_potential(
        slope_deg, wetland_fraction_2km, distance_to_water_km, major_lake_interior
    )

    habitat_capacity = compute_habitat_capacity(
        wetland_fraction_5km=wetland_fraction_5km,
        forest_water_edge_density=forest_water_edge_density,
        wetland_water_edge_density=wetland_water_edge_density,
        small_water_density=small_water_density,
        floodplain_potential=floodplain_potential,
        shoreline_density=shoreline_density,
        forest_fraction=forest_base,
        urban_fraction=urban_base,
        elevation_m=elevation_m,
        coastal_exposure=coastal_exposure,
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
        is_placeholder=True,
        water_fraction_500m=water_fraction_500m,
        water_fraction_2km=water_fraction_2km,
        water_fraction_5km=water_fraction_5km,
        wetland_fraction_500m=wetland_fraction_500m,
        wetland_fraction_2km=wetland_fraction_2km,
        wetland_fraction_5km=wetland_fraction_5km,
        shoreline_density=shoreline_density,
        forest_water_edge_density=forest_water_edge_density,
        wetland_water_edge_density=wetland_water_edge_density,
        small_water_density=small_water_density,
        major_lake_interior=major_lake_interior,
        floodplain_potential=floodplain_potential,
        habitat_capacity=habitat_capacity,
    )


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Local copy -- see feature_engineering.py::clamp for why this isn't a
    shared import (avoids a circular import chain)."""
    return max(minimum, min(maximum, value))


# --- Habitat capacity (Phase 3) --------------------------------------------
#
# Weights were chosen to put the heaviest weight on the features the new
# spec's ecology (Phase 4/5) argues are most predictive of real mosquito
# breeding habitat -- small/temporary water and forest/wetland-water
# interfaces -- and the lightest weight on generic forest cover, which the
# audit (docs/geographic-model-audit-before.md #5) found saturates almost
# everywhere forested in Sweden and so can't discriminate habitat quality on
# its own. Not fit against any ground truth (none exists yet, see
# docs/mosquito-ecology-evidence.md) -- a transparent, bounded weighted sum
# in the same style as model.py's other scoring functions, calibrated by
# checking the resulting spread against the real benchmark locations
# (docs/geographic-benchmark-before.md / -after.md), not asserted blindly.
HABITAT_CAPACITY_WEIGHTS = {
    "wetland": 0.20,
    "forest_water_edge": 0.15,
    "wetland_water_edge": 0.15,
    "small_water": 0.20,
    "floodplain": 0.15,
    "shoreline": 0.10,
    "forest": 0.05,
}

# Multipliers that map the raw edge/small-water/wetland density measures
# onto a 0-1 term before weighting. Raster edge-density and multi-scale
# fractions never approach 1.0 for any real Swedish terrain (confirmed by
# computing these for all 55 real benchmark locations before picking these
# constants: forest_water_edge_density maxed at 0.06, wetland_water_edge_
# density at 0.009, shoreline_density at 0.08, wetland_fraction_5km at 0.19
# -- see docs/geographic-benchmark-before.md) -- each constant is
# `1 / (a round number a bit above that observed sample max)`, leaving
# headroom for more extreme cells nationally than appeared in the 55-
# location sample, rather than an arbitrary guess.
WETLAND_5KM_SATURATION = 1.0 / 0.30
FOREST_WATER_EDGE_SATURATION = 1.0 / 0.08
WETLAND_WATER_EDGE_SATURATION = 1.0 / 0.02
SMALL_WATER_SATURATION = 1.0 / 0.50
SHORELINE_SATURATION = 1.0 / 0.10


def compute_habitat_capacity(
    wetland_fraction_5km: float,
    forest_water_edge_density: float,
    wetland_water_edge_density: float,
    small_water_density: float,
    floodplain_potential: float,
    shoreline_density: float,
    forest_fraction: float,
    urban_fraction: float,
    elevation_m: float,
    coastal_exposure: float = 0.0,
) -> float:
    """0-100, slow-changing "how capable is this landscape of supporting
    large mosquito populations if weather is favourable" -- see module
    docstring and docs/geographic-model-audit-before.md §6 for why this
    exists (previously habitat "quality" was smeared implicitly across
    three separate population_potential terms with no shared concept
    behind them). Deliberately excludes anything weather-derived -- see
    feature_engineering.py's mosquito_pressure for the persistent,
    weather-driven layer built ON TOP of this.

    Urban land cover and high elevation act as multiplicative SUPPRESSION
    gates on the whole capacity, not as just another additive term -- a
    fully built-up cell should read as low capacity regardless of how much
    incidental wetland/water sits in the same 5km window (see audit finding
    #4.5: urban_fraction previously had zero effect on population
    potential at all), and the same for a high-alpine cell (#4.2: elevation
    was computed and never used).
    """
    # WorldCover/NMD's "water" class does not distinguish open sea from
    # fresh water, so raw water-adjacency signals (shoreline/forest-water/
    # wetland-water edge, small-water density) all pick up open, wave-
    # exposed Baltic/Kattegat coastline as if it were small-pond breeding
    # habitat -- confirmed empirically against the 55-location benchmark
    # (see docs/geographic-benchmark-before.md): before this correction,
    # exposed archipelago/coast locations dominated the TOP of the national
    # habitat_capacity ranking, ahead of real wet inland forest, directly
    # contradicting the new spec's explicit "exposed rocky coastline should
    # score lower" example. `coastal_exposure` (already computed from the
    # real Sweden coastline boundary) is used as a freshwater-confidence
    # discount on exactly these four water-adjacency terms -- NOT on
    # wetland_fraction_5km (a genuinely vegetated-wetland land-cover class,
    # not generic "water") or floodplain_potential (already slope/wetland-
    # weighted, water proximity is only half its own formula). This is a
    # PARTIAL, not total, fix: Sweden's real archipelago also has genuine
    # brackish lagoon ("flador") breeding habitat this raster-only signal
    # cannot separate from open exposed sea -- see docs/mosquito-ecology-
    # evidence.md's stated limitations.
    freshwater_confidence = 1.0 - clamp(coastal_exposure, 0.0, 1.0)

    wetland_term = clamp(wetland_fraction_5km * WETLAND_5KM_SATURATION, 0.0, 1.0)
    forest_edge_term = clamp(forest_water_edge_density * FOREST_WATER_EDGE_SATURATION * freshwater_confidence, 0.0, 1.0)
    wetland_edge_term = clamp(wetland_water_edge_density * WETLAND_WATER_EDGE_SATURATION * freshwater_confidence, 0.0, 1.0)
    small_water_term = clamp(small_water_density * SMALL_WATER_SATURATION * freshwater_confidence, 0.0, 1.0)
    floodplain_term = clamp(floodplain_potential, 0.0, 1.0)
    shoreline_term = clamp(shoreline_density * SHORELINE_SATURATION * freshwater_confidence, 0.0, 1.0)
    forest_term = clamp(forest_fraction * 1.1, 0.0, 1.0)

    w = HABITAT_CAPACITY_WEIGHTS
    raw = (
        w["wetland"] * wetland_term
        + w["forest_water_edge"] * forest_edge_term
        + w["wetland_water_edge"] * wetland_edge_term
        + w["small_water"] * small_water_term
        + w["floodplain"] * floodplain_term
        + w["shoreline"] * shoreline_term
        + w["forest"] * forest_term
    )

    # Urban suppression: floor at 0.05 (not 0), since even dense cities have
    # occasional catch basins/park ponds -- never claim literally zero.
    urban_suppression = clamp(1.0 - clamp(urban_fraction, 0.0, 1.0) * 1.3, 0.05, 1.0)
    # Elevation suppression: no penalty below 400m (most of inhabited/
    # forested Sweden), linearly declining to a 0.1 floor by 1200m -- a
    # defensible round proxy for the alpine/subalpine treeline band in
    # Scandinavia (roughly 600-900m, higher in the south, lower in the far
    # north), not a species-specific validated cutoff. Floored, not zeroed,
    # since sheltered valley habitat can exist even at altitude (e.g. Abisko
    # valley floor vs. surrounding peaks).
    elevation_suppression = clamp(1.0 - max(0.0, elevation_m - 400.0) / 800.0, 0.1, 1.0)

    return round(100.0 * clamp(raw, 0.0, 1.0) * urban_suppression * elevation_suppression, 2)


def compute_floodplain_potential(
    slope_deg: float, wetland_fraction_2km: float, distance_to_water_km: float, major_lake_interior: bool = False
) -> float:
    """0-1 static proxy for "does this landscape resemble floodplain
    terrain" -- gentle slope (poor drainage) + close to mapped water +
    wetland-adjacent. Deliberately NOT a hydrological flood model (no
    river-network or water-level data used, per the new spec's "do not
    introduce a complicated external dependency unless it provides
    meaningful value") -- see docs/geographic-model-audit-before.md Phase 5
    discussion. Actual flood-driven emergence remains weather-driven (recent
    rainfall), computed separately in feature_engineering.py; this only
    describes the landscape's static POTENTIAL.

    `major_lake_interior` discount (found during the historical calibration
    sprint, see docs/calibration-validation-final.md Phase 9): a cell deep
    inside a large permanent lake has `distance_to_water_km` near 0 --
    trivially maximal "water proximity" -- which previously let it score a
    HIGHER floodplain_potential than a real vegetated lake margin a few
    cells away, despite being exactly the "middle of a large lake is not
    breeding habitat" case the new spec explicitly warns against (found via
    a real Vanern-interior-vs-Vanern-shore contrast that came out inverted
    in the reference-cell time series). "Close to water" is only a
    floodplain signal when that water is small/seasonal enough to plausibly
    overflow onto the surrounding land -- being IN a large lake is the
    opposite case. Same discount factor as `small_water_density`'s."""
    slope_norm = clamp((slope_deg or 0.0) / 8.0, 0.0, 1.0)
    drainage_term = 1.0 - slope_norm
    water_proximity = clamp(1.0 - distance_to_water_km / 5.0, 0.0, 1.0)
    if major_lake_interior:
        water_proximity *= 0.05
    wetland_term = clamp(wetland_fraction_2km * 1.5, 0.0, 1.0)
    return round(clamp(drainage_term * (0.5 * wetland_term + 0.5 * water_proximity), 0.0, 1.0), 4)


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


def _water_distance_km(ds, lon: float, lat: float) -> float:
    """Nearest-water search over a much wider (15km) window than the
    fraction/multiscale windows -- kept as its own read since it needs a
    different physical extent, not mergeable with the others."""
    import numpy as np

    search_arr = _read_window(ds, lon, lat, _WATER_SEARCH_RADIUS_KM, _WATER_SEARCH_OUT_SIZE)
    water_mask = np.isin(search_arr, list(WORLDCOVER_WATER_CLASSES))
    if water_mask.any():
        center = (_WATER_SEARCH_OUT_SIZE - 1) / 2
        rows, cols = np.nonzero(water_mask)
        km_per_px_y = (2 * _WATER_SEARCH_RADIUS_KM) / _WATER_SEARCH_OUT_SIZE
        km_per_px_x = km_per_px_y  # window is a square in degrees at this lat, so ~equal
        return float(np.min(np.hypot((rows - center) * km_per_px_y, (cols - center) * km_per_px_x)))
    return _WATER_SEARCH_RADIUS_KM  # "at least this far", i.e. genuinely far from water


# Multi-scale/edge window (Phase 4): one read at the widest radius needed
# (5km), same ~50m/px resolution as the existing fraction window, with
# 500m/2km fractions derived by cropping this SAME array rather than
# re-reading from disk -- keeps the added I/O cost to one extra window read
# per cell (not three), since rasterio window reads (not the crops) are the
# expensive part.
_MULTISCALE_RADIUS_KM = 5.0
_MULTISCALE_OUT_SIZE = 200  # ~50m/pixel over the 10km-wide window
# Radius used for the edge-density (shoreline/forest-water/wetland-water)
# calculation -- a fixed 2km window regardless of the multi-scale radii
# above, since edge density is meant to characterise the immediate
# neighbourhood, not the full 5km context.
_EDGE_RADIUS_KM = 2.0


def _crop_center(arr, radius_km: float, full_radius_km: float):
    """Center crop of a square array corresponding to a smaller radius than
    the one it was read at -- e.g. a 5km-radius array cropped to its
    innermost 500m. Approximate (assumes uniform px/km, true by
    construction for _read_window's output), not a new raster read."""
    size = arr.shape[0]
    frac = min(1.0, radius_km / full_radius_km)
    half = max(1, int(round(size * frac / 2)))
    center = size // 2
    lo = max(0, center - half)
    hi = min(size, center + half)
    return arr[lo:hi, lo:hi]


def _edge_density(mask_a, mask_b) -> float:
    """Fraction of 4-connected adjacent pixel pairs where one pixel is in
    mask_a and the other in mask_b (or vice versa) -- a cheap raster proxy
    for interface/boundary length between two land-cover classes, without
    full vector boundary geometry. 0 if the two classes never touch inside
    the window (e.g. no water at all, or water present but nowhere near
    forest/wetland); highest for finely interleaved terrain (many small
    ponds threaded through forest/wetland), not for one large homogeneous
    block of either class."""
    h_adj = (mask_a[:, :-1] & mask_b[:, 1:]) | (mask_b[:, :-1] & mask_a[:, 1:])
    v_adj = (mask_a[:-1, :] & mask_b[1:, :]) | (mask_b[:-1, :] & mask_a[1:, :])
    total_pairs = h_adj.size + v_adj.size
    if total_pairs == 0:
        return 0.0
    return float((h_adj.sum() + v_adj.sum()) / total_pairs)


def _land_cover_and_multiscale_features(ds, lon: float, lat: float) -> dict:
    """ONE 5km-radius raster read producing both the base (2.5km-equivalent)
    forest/wetland/urban/water fractions AND the full multi-scale/edge
    feature set (Phase 4) -- merges what were previously two separate reads
    (the old `_land_cover_features`'s fraction portion, and
    `_multiscale_habitat_features`) into one, since the 5km window's data is
    a strict superset of the 2.5km window's. Confirmed empirically (see
    docs/geographic-model-final-report.md "Performance") that each
    `ds.read()` call on this project's raster setup has a substantial fixed
    cost (~15-20ms) largely independent of window size -- so reducing the
    NUMBER of reads per cell matters far more than shrinking any one of
    them. distance_to_water_km still needs its own much-wider (15km) read
    -- see `_water_distance_km` -- since it can't be derived from this
    narrower window."""
    import numpy as np

    arr = _read_window(ds, lon, lat, _MULTISCALE_RADIUS_KM, _MULTISCALE_OUT_SIZE)
    water_mask = np.isin(arr, list(WORLDCOVER_WATER_CLASSES))
    wetland_mask = np.isin(arr, list(WORLDCOVER_WETLAND_CLASSES))
    forest_mask = np.isin(arr, list(WORLDCOVER_FOREST_CLASSES))
    urban_mask = np.isin(arr, list(WORLDCOVER_URBAN_CLASSES))
    land_mask = ~water_mask

    def _frac(mask, radius_km: float) -> float:
        cropped = _crop_center(mask, radius_km, _MULTISCALE_RADIUS_KM)
        return float(cropped.mean()) if cropped.size else 0.0

    base_forest = _frac(forest_mask, _FRACTION_RADIUS_KM)
    base_wetland = _frac(wetland_mask, _FRACTION_RADIUS_KM)
    base_urban = _frac(urban_mask, _FRACTION_RADIUS_KM)
    base_water = _frac(water_mask, _FRACTION_RADIUS_KM)

    water_500m, water_2km, water_5km = (_frac(water_mask, r) for r in (0.5, 2.0, 5.0))
    wetland_500m, wetland_2km, wetland_5km = (_frac(wetland_mask, r) for r in (0.5, 2.0, 5.0))

    edge_water = _crop_center(water_mask, _EDGE_RADIUS_KM, _MULTISCALE_RADIUS_KM)
    edge_land = _crop_center(land_mask, _EDGE_RADIUS_KM, _MULTISCALE_RADIUS_KM)
    edge_forest = _crop_center(forest_mask, _EDGE_RADIUS_KM, _MULTISCALE_RADIUS_KM)
    edge_wetland = _crop_center(wetland_mask, _EDGE_RADIUS_KM, _MULTISCALE_RADIUS_KM)

    return {
        "forest": base_forest,
        "wetland": base_wetland,
        "urban": base_urban,
        "water": base_water,
        "water_fraction_500m": round(water_500m, 4),
        "water_fraction_2km": round(water_2km, 4),
        "water_fraction_5km": round(water_5km, 4),
        "wetland_fraction_500m": round(wetland_500m, 4),
        "wetland_fraction_2km": round(wetland_2km, 4),
        "wetland_fraction_5km": round(wetland_5km, 4),
        "shoreline_density": round(_edge_density(edge_water, edge_land), 4),
        "forest_water_edge_density": round(_edge_density(edge_forest, edge_water), 4),
        "wetland_water_edge_density": round(_edge_density(edge_wetland, edge_water), 4),
    }


def _load_major_lakes(static_data_dir: Path):
    """STRtree of the named major-lake polygons in
    data/static/sweden_lakes.geojson (47 lakes, e.g. Vanern/Vattern/Malaren/
    Siljan -- see scripts/prepare_cell_geometry.py, the only other current
    consumer of this file). Returns (tree, polygons) or (None, []) if the
    file isn't present."""
    path = static_data_dir / "sweden_lakes.geojson"
    if not path.exists():
        return None, []
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    polys = [shape(feat["geometry"]) for feat in data["features"]]
    if not polys:
        return None, []
    return STRtree(polys), polys


def _major_lake_status(tree, polys: list, lon: float, lat: float) -> bool:
    """True if (lon, lat) sits at least 1km inside the boundary of one of
    the named major lakes -- the "middle of a large open lake" case the new
    spec wants distinguished from shoreline/small-water habitat. Shoreline
    cells (< 1km from the lake's own edge) are NOT considered "interior"
    even though they're technically inside the polygon, since real breeding
    habitat concentrates at the margin, not the open interior."""
    if tree is None:
        return False
    from shapely.geometry import Point

    p = Point(lon, lat)
    try:
        candidate_idx = tree.query(p, predicate="intersects")
    except TypeError:
        # Older shapely/STRtree API (pre-2.0) has no `predicate` kwarg --
        # query returns candidate geometries directly, filter manually.
        candidates = tree.query(p)
        candidate_idx = [i for i, poly in enumerate(polys) if poly in candidates and poly.contains(p)]
    for idx in candidate_idx:
        poly = polys[idx]
        if not poly.contains(p):
            continue
        dist_km = poly.boundary.distance(p) * KM_PER_DEGREE_LAT
        if dist_km >= 1.0:
            return True
    return False


def _read_window_projected(ds, x: float, y: float, radius_km: float, out_size: int):
    """Like _read_window, but for a dataset in a projected (metric) CRS such
    as NMD's native SWEREF99 TM -- no lon/lat-dependent degree scaling
    needed, just a square window in the CRS's own meters."""
    import numpy as np  # noqa: local import
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds

    half_m = radius_km * 1000.0
    window = from_bounds(x - half_m, y - half_m, x + half_m, y + half_m, transform=ds.transform)
    arr = ds.read(
        1,
        window=window,
        out_shape=(out_size, out_size),
        resampling=Resampling.nearest,
        boundless=True,
        fill_value=NMD_NODATA_VALUE,
    )
    return np.asarray(arr)


def _nmd_land_cover_features(ds, x: float, y: float) -> tuple[float, float, float, float, float]:
    """(forest, wetland, urban, water, nodata_fraction) for one cell,
    sampled directly against NMD's native SWEREF99 TM grid at projected
    coordinates (x, y). nodata_fraction is the share of the fraction window
    NMD hasn't classified yet (rollout still in progress, see module
    docstring) -- callers should blend proportionally with WorldCover
    rather than switching sources outright, to avoid a visible seam at the
    coverage edge.

    Deliberately does NOT compute its own distance_to_water_km (unlike
    earlier versions of this function): NMD's raw raster has no overview/
    pyramid support (confirmed: `ds.overviews(1)` returns `[]` on the
    committed NMD2023 GeoTIFF, an ~11.3-billion-pixel single national
    raster), so a 15km-radius nearest-water search against it -- needed for
    every one of ~23k cells -- measured at ~88ms/cell, by far the single
    most expensive operation in the whole static-feature pipeline (see
    docs/geographic-model-final-report.md "Performance"), for a value
    (nearest-water distance) NMD's water class is not meaningfully more
    accurate about than WorldCover's at this coarse a scale. The
    already-computed WorldCover `distance_to_water_km` is used for every
    cell instead, real or NMD-blended alike -- NMD's genuine advantage
    (forest-on-wetland/mire-subtype detail, see module docstring) is fully
    preserved via the forest/wetland/urban blend below."""
    import numpy as np

    frac_arr = _read_window_projected(ds, x, y, _FRACTION_RADIUS_KM, _FRACTION_OUT_SIZE)
    total = frac_arr.size
    nodata_fraction = float((frac_arr == NMD_NODATA_VALUE).sum()) / total
    forest = float(np.isin(frac_arr, list(NMD_FOREST_CLASSES)).sum()) / total
    wetland = float(np.isin(frac_arr, list(NMD_WETLAND_CLASSES)).sum()) / total
    urban = float(np.isin(frac_arr, list(NMD_URBAN_CLASSES)).sum()) / total
    water = float(np.isin(frac_arr, list(NMD_WATER_CLASSES)).sum()) / total

    return forest, wetland, urban, water, nodata_fraction


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


def _wc_chunk_worker(cell_list: list[tuple[str, str, float, float]]) -> dict[str, dict]:
    """One chunk of (cell_id, tile_path, lon, lat) tuples -- NOT
    necessarily all from the same WorldCover tile. Cells are chunked
    EVENLY across workers for load balance (Sweden's real cell density
    varies hugely between the 22 WorldCover tiles -- grouping work by tile
    instead left some workers idle while one large-tile worker dominated
    wall-clock time), then grouped by tile INSIDE this function so each
    distinct tile this particular chunk touches is still only opened once.
    Module-level (not a closure) so it's picklable for ProcessPoolExecutor
    on Windows, which uses spawn (re-imports this module fresh in each
    worker rather than forking)."""
    import rasterio

    by_tile: dict[str, list[tuple[str, float, float]]] = {}
    for cell_id, tile_path, lon, lat in cell_list:
        by_tile.setdefault(tile_path, []).append((cell_id, lon, lat))

    out: dict[str, dict] = {}
    for tile_path, tile_cells in by_tile.items():
        with rasterio.open(tile_path) as ds:
            for cell_id, lon, lat in tile_cells:
                merged = _land_cover_and_multiscale_features(ds, lon, lat)
                merged["dist_water"] = _water_distance_km(ds, lon, lat)
                out[cell_id] = merged
    return out


def _dem_chunk_worker(cell_list: list[tuple[str, str, float, float]]) -> dict[str, tuple[float, float]]:
    """DEM equivalent of `_wc_chunk_worker` -- evenly-chunked across
    workers, grouped by tile internally."""
    import rasterio

    by_tile: dict[str, list[tuple[str, float, float]]] = {}
    for cell_id, tile_path, lon, lat in cell_list:
        by_tile.setdefault(tile_path, []).append((cell_id, lon, lat))

    out: dict[str, tuple[float, float]] = {}
    for tile_path, tile_cells in by_tile.items():
        with rasterio.open(tile_path) as ds:
            for cell_id, lon, lat in tile_cells:
                out[cell_id] = _elevation_features(ds, lon, lat)
    return out


def _nmd_chunk_worker(payload: tuple[str, list[tuple[str, float, float]]]) -> dict[str, tuple[float, float, float, float, float]]:
    """One NMD chunk -- an arbitrary slice of ALL cells (NMD is a single
    national raster, not tile-grouped like WorldCover/DEM), processed in a
    worker process. Chunking evenly across all cells (rather than by
    geographic tile, which doesn't apply here) keeps worker load balanced."""
    import rasterio
    from pyproj import Transformer

    path_str, cell_list = payload
    out: dict[str, tuple[float, float, float, float, float]] = {}
    with rasterio.open(path_str) as ds:
        to_nmd_crs = Transformer.from_crs("EPSG:4326", ds.crs.to_wkt(), always_xy=True)
        for cell_id, lon, lat in cell_list:
            x, y = to_nmd_crs.transform(lon, lat)
            out[cell_id] = _nmd_land_cover_features(ds, x, y)
    return out


def compute_static_features_from_rasters(
    cells: list[GridCell], static_data_dir: Path, max_workers: int | None = None
) -> list[StaticFeatures]:
    """Real implementation, using ESA WorldCover (land cover) and
    Copernicus DEM GLO-30 (elevation) tiles downloaded to
    static_data_dir/"worldcover"/*.tif and static_data_dir/"dem"/*.tif --
    see scripts/download_static_gis_data.py. Requires rasterio (and
    shapely, already a core dependency, for the coastal-exposure term).
    Raises FileNotFoundError with a helpful message if the expected tile
    directories aren't present, so callers can fall back to placeholders.

    Parallelized across WorldCover tiles / DEM tiles / NMD cell-chunks
    (`max_workers`, default `min(8, os.cpu_count())`) via
    `ProcessPoolExecutor` -- confirmed necessary at full-Sweden (~23,194
    cell) scale: profiling found each `ds.read()` call costs ~15-90ms
    (dominated by fixed per-call overhead, not window size -- see
    `_land_cover_and_multiscale_features`'s docstring), and the NMD water-
    search specifically cost ~88ms/cell against a non-overview-having
    11.3-billion-pixel raster before being removed entirely (see
    `_nmd_land_cover_features`'s docstring). See docs/geographic-model-
    final-report.md "Performance" for the full before/after measurement.
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

    import os
    from concurrent.futures import ProcessPoolExecutor

    workers = max_workers or min(8, os.cpu_count() or 4)

    def _even_chunks(items: list, n: int) -> list[list]:
        if not items:
            return []
        size = max(1, -(-len(items) // n))  # ceiling division
        return [items[i : i + size] for i in range(0, len(items), size)]

    # Cell -> tile-path lookups (by_wc_tile/by_dem_tile, built below for the
    # unmatched-tile FileNotFoundError checks) also directly give us the
    # tile assignment needed for evenly-chunked work below -- reused rather
    # than recomputing _tile_for_point a second time.
    wc_tile_for_cell = {c.cell_id: str(path) for path, tile_cells in by_wc_tile.items() for c in tile_cells}

    land_cover_by_cell: dict[str, tuple[float, float, float, float, float]] = {}
    # Multi-scale/edge features (Phase 4) are computed from WorldCover only
    # (not NMD-blended, unlike the base forest/wetland/urban/water fraction
    # below) -- a documented scope reduction, not an oversight: WorldCover
    # alone already covers all of Sweden uniformly at 10m, which is what
    # multi-scale/edge density needs; NMD's finer classes matter most for
    # the single-point base fraction's forest-on-wetland distinction (see
    # module docstring), not for edge geometry. See docs/geographic-
    # benchmark-after.md "Known scope reductions".
    multiscale_by_cell: dict[str, dict] = {}

    with ProcessPoolExecutor(max_workers=workers) as executor:
        wc_tuples = [(c.cell_id, wc_tile_for_cell[c.cell_id], c.longitude, c.latitude) for c in cells]
        for chunk_result in executor.map(_wc_chunk_worker, _even_chunks(wc_tuples, workers)):
            for cell_id, merged in chunk_result.items():
                land_cover_by_cell[cell_id] = (
                    merged["forest"], merged["wetland"], merged["urban"], merged["water"], merged["dist_water"],
                )
                multiscale_by_cell[cell_id] = merged

        lake_tree, lake_polys = _load_major_lakes(static_data_dir)

        # NMD2023 override: optional, higher-detail Sweden-only source (see
        # module docstring). Where its rollout has reached, it replaces the
        # WorldCover-derived forest/wetland/urban values above; elsewhere the
        # WorldCover value stands as the fallback. water_fraction and
        # distance_to_water_km are deliberately left as pure WorldCover
        # values always -- NMD no longer computes its own (see
        # `_nmd_land_cover_features`'s docstring for why).
        nmd_tifs = sorted((static_data_dir / "nmd").glob("*.tif")) if (static_data_dir / "nmd").is_dir() else []
        if nmd_tifs:
            cell_tuples = [(c.cell_id, c.longitude, c.latitude) for c in cells]
            nmd_pure = 0
            nmd_blended = 0
            nmd_payloads = [
                (str(nmd_tifs[0]), chunk) for chunk in _even_chunks(cell_tuples, workers)
            ]
            for chunk_result in executor.map(_nmd_chunk_worker, nmd_payloads):
                for cell_id, (forest, wetland, urban, _water, nodata_frac) in chunk_result.items():
                    if nodata_frac >= 1.0:
                        continue  # no NMD signal at all here -- pure WorldCover stands
                    # Linearly blend forest/wetland/urban with the WorldCover-
                    # derived tuple already in land_cover_by_cell, weighted by
                    # how much of this cell's window NMD actually classified --
                    # a hard cutover (fully NMD vs. fully WorldCover from one
                    # cell to the next) drew a visible seam on the map exactly
                    # where NMD's south-to-north rollout currently ends, since
                    # the two sources don't agree on typical wetland/forest
                    # values. Blending means cells straddling that edge grade
                    # smoothly between the two instead of jumping.
                    nmd_weight = 1.0 - nodata_frac
                    wc = land_cover_by_cell[cell_id]
                    blended = (
                        nmd_weight * forest + (1.0 - nmd_weight) * wc[0],
                        nmd_weight * wetland + (1.0 - nmd_weight) * wc[1],
                        nmd_weight * urban + (1.0 - nmd_weight) * wc[2],
                        wc[3],  # water: pure WorldCover, unchanged
                        wc[4],  # distance_to_water_km: pure WorldCover, unchanged
                    )
                    land_cover_by_cell[cell_id] = blended
                    if nodata_frac <= 0.0:
                        nmd_pure += 1
                    else:
                        nmd_blended += 1
            print(
                f"NMD2023 used for {nmd_pure}/{len(cells)} cells (pure), "
                f"{nmd_blended} blended with WorldCover at the coverage edge."
            )

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
        dem_tile_for_cell = {c.cell_id: str(path) for path, tile_cells in by_dem_tile.items() for c in tile_cells}

        elevation_by_cell: dict[str, tuple[float, float]] = {}
        dem_tuples = [(c.cell_id, dem_tile_for_cell[c.cell_id], c.longitude, c.latitude) for c in cells]
        for chunk_result in executor.map(_dem_chunk_worker, _even_chunks(dem_tuples, workers)):
            elevation_by_cell.update(chunk_result)

    results: list[StaticFeatures] = []
    for cell in cells:
        forest, wetland, urban, water, dist_water = land_cover_by_cell[cell.cell_id]
        elevation_m, slope_deg = elevation_by_cell[cell.cell_id]
        ms = multiscale_by_cell[cell.cell_id]

        cell_coastal_exposure = coastal_exposure_for(cell.longitude, cell.latitude)
        major_lake_interior = _major_lake_status(lake_tree, lake_polys, cell.longitude, cell.latitude)
        # Discount water_fraction_2km heavily (not to exactly zero -- even a
        # lake-interior cell's window edge can graze a small inlet/pond)
        # when this cell sits deep inside a named major lake, per
        # docs/geographic-model-audit-before.md Phase 4: "the middle of a
        # large lake" should not read as strong breeding-habitat water the
        # same way a marshy shoreline/small-pond landscape does. This field
        # is stored RAW (no coastal/marine discount baked in here -- that's
        # applied inside compute_habitat_capacity instead, see its
        # docstring) so it stays an honest, independently-interpretable
        # diagnostic value.
        small_water_density = round(ms["water_fraction_2km"] * (0.05 if major_lake_interior else 1.0), 4)

        floodplain_potential = compute_floodplain_potential(
            slope_deg, ms["wetland_fraction_2km"], dist_water, major_lake_interior
        )

        habitat_capacity = compute_habitat_capacity(
            wetland_fraction_5km=ms["wetland_fraction_5km"],
            forest_water_edge_density=ms["forest_water_edge_density"],
            wetland_water_edge_density=ms["wetland_water_edge_density"],
            small_water_density=small_water_density,
            floodplain_potential=floodplain_potential,
            shoreline_density=ms["shoreline_density"],
            forest_fraction=forest,
            urban_fraction=urban,
            elevation_m=elevation_m,
            coastal_exposure=cell_coastal_exposure,
        )

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
                coastal_exposure=cell_coastal_exposure,
                water_body_density=round(water, 3),
                water_fraction_500m=ms["water_fraction_500m"],
                water_fraction_2km=ms["water_fraction_2km"],
                water_fraction_5km=ms["water_fraction_5km"],
                wetland_fraction_500m=ms["wetland_fraction_500m"],
                wetland_fraction_2km=ms["wetland_fraction_2km"],
                wetland_fraction_5km=ms["wetland_fraction_5km"],
                shoreline_density=ms["shoreline_density"],
                forest_water_edge_density=ms["forest_water_edge_density"],
                wetland_water_edge_density=ms["wetland_water_edge_density"],
                small_water_density=small_water_density,
                major_lake_interior=major_lake_interior,
                floodplain_potential=floodplain_potential,
                habitat_capacity=habitat_capacity,
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
