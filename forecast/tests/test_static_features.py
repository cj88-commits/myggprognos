from __future__ import annotations

from grid import GridCell
from static_features import generate_placeholder_static_features


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
