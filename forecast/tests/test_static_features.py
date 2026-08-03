from __future__ import annotations

import pytest

from grid import GridCell
from static_features import compute_static_features_from_rasters, generate_placeholder_static_features


def test_placeholder_features_are_deterministic():
    cell = GridCell(cell_id="SE_ABC", latitude=59.3, longitude=18.0)
    first = generate_placeholder_static_features(cell)
    second = generate_placeholder_static_features(cell)
    assert first == second


def test_placeholder_features_are_bounded_fractions():
    cell = GridCell(cell_id="SE_ABC", latitude=59.3, longitude=18.0)
    features = generate_placeholder_static_features(cell)
    for value in (features.forest_fraction, features.wetland_fraction, features.urban_fraction, features.water_fraction):
        assert 0.0 <= value <= 1.0
    assert features.distance_to_water_km >= 0
    assert features.elevation_m >= 0


def test_placeholder_features_differ_by_cell_id():
    a = generate_placeholder_static_features(GridCell(cell_id="SE_A", latitude=59.3, longitude=18.0))
    b = generate_placeholder_static_features(GridCell(cell_id="SE_B", latitude=59.3, longitude=18.0))
    assert a != b


def test_urban_fraction_high_near_stockholm_center():
    stockholm = GridCell(cell_id="SE_CITY", latitude=59.3293, longitude=18.0686)
    remote = GridCell(cell_id="SE_REMOTE", latitude=64.0, longitude=19.0)
    stockholm_features = generate_placeholder_static_features(stockholm)
    remote_features = generate_placeholder_static_features(remote)
    assert stockholm_features.urban_fraction > remote_features.urban_fraction


def _write_uniform_geotiff(path, *, value: int, bounds: tuple[float, float, float, float], size: int = 200):
    """A tiny synthetic single-band GeoTIFF, uniformly filled with `value`,
    covering `bounds` = (west, south, east, north) in EPSG:4326 -- enough
    to exercise compute_static_features_from_rasters' real tile-reading
    path without needing real multi-GB source data in tests."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds

    west, south, east, north = bounds
    transform = from_bounds(west, south, east, north, size, size)
    data = np.full((size, size), value, dtype=np.uint8)
    with rasterio.open(
        path, "w", driver="GTiff", height=size, width=size, count=1,
        dtype=data.dtype, crs="EPSG:4326", transform=transform,
    ) as ds:
        ds.write(data, 1)


class TestComputeStaticFeaturesFromRasters:
    """Exercises the real (non-placeholder) path against tiny synthetic
    tiles, so the actual windowed-read + fraction/slope logic in
    static_features.py is covered without needing real, multi-GB GIS
    source data in CI. Skipped entirely if rasterio isn't installed --
    it's an optional dependency only needed for this real-data path (see
    forecast/requirements.txt)."""

    rasterio = pytest.importorskip("rasterio")

    FOREST_CLASS = 10
    WATER_CLASS = 80

    def test_missing_tile_dirs_raise(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            compute_static_features_from_rasters(
                [GridCell(cell_id="SE_X", latitude=59.3, longitude=18.0)], tmp_path
            )

    def test_uniform_forest_tile(self, tmp_path):
        bounds = (17.5, 59.0, 18.5, 60.0)
        (tmp_path / "worldcover").mkdir()
        (tmp_path / "dem").mkdir()
        _write_uniform_geotiff(
            tmp_path / "worldcover" / "test.tif", value=self.FOREST_CLASS, bounds=bounds
        )
        _write_uniform_geotiff(tmp_path / "dem" / "test.tif", value=100, bounds=bounds)

        cell = GridCell(cell_id="SE_FOREST", latitude=59.5, longitude=18.0)
        [features] = compute_static_features_from_rasters([cell], tmp_path)

        assert features.forest_fraction == pytest.approx(1.0, abs=0.01)
        assert features.wetland_fraction == 0.0
        assert features.urban_fraction == 0.0
        assert features.water_fraction == 0.0
        # No water anywhere in the tile -- distance should saturate at the
        # search radius, not silently read as 0 or extrapolate past it.
        assert features.distance_to_water_km > 5.0
        assert features.elevation_m == pytest.approx(100.0, abs=0.5)
        # A perfectly flat synthetic DEM should read as ~0 slope.
        assert features.slope_deg == pytest.approx(0.0, abs=0.5)

    def test_uniform_water_tile_reports_zero_distance(self, tmp_path):
        bounds = (17.5, 59.0, 18.5, 60.0)
        (tmp_path / "worldcover").mkdir()
        (tmp_path / "dem").mkdir()
        _write_uniform_geotiff(
            tmp_path / "worldcover" / "test.tif", value=self.WATER_CLASS, bounds=bounds
        )
        _write_uniform_geotiff(tmp_path / "dem" / "test.tif", value=0, bounds=bounds)

        cell = GridCell(cell_id="SE_WATER", latitude=59.5, longitude=18.0)
        [features] = compute_static_features_from_rasters([cell], tmp_path)

        assert features.water_fraction == pytest.approx(1.0, abs=0.01)
        assert features.forest_fraction == 0.0
        # Water is everywhere, so distance should be ~0 -- generous
        # tolerance for the search window's own decimated grid spacing
        # (~200m/pixel over its 30km width), not a claim of sub-pixel
        # precision.
        assert features.distance_to_water_km < 0.5
