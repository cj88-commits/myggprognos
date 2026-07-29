from __future__ import annotations

from config import SWEDEN_BBOX
from grid import GridCell, generate_grid, generate_sample_grid, load_grid, save_grid


def test_generate_grid_produces_cells_within_bbox():
    cells = generate_grid(resolution_km=40, max_cells=200)
    assert cells
    for cell in cells:
        assert SWEDEN_BBOX["min_lat"] <= cell.latitude <= SWEDEN_BBOX["max_lat"]
        assert SWEDEN_BBOX["min_lon"] <= cell.longitude <= SWEDEN_BBOX["max_lon"]


def test_generate_grid_cell_ids_are_unique():
    cells = generate_grid(resolution_km=40, max_cells=200)
    ids = [c.cell_id for c in cells]
    assert len(ids) == len(set(ids))


def test_generate_grid_respects_max_cells_cap():
    cells = generate_grid(resolution_km=5, max_cells=10)
    assert len(cells) <= 10


def test_sample_grid_has_five_named_representative_cells():
    cells = generate_sample_grid()
    ids = {c.cell_id for c in cells}
    assert ids == {"SE_STHLM", "SE_FOREST", "SE_WETLAND", "SE_COAST", "SE_NORTH"}


def test_save_and_load_grid_roundtrip(tmp_path):
    cells = generate_sample_grid()
    path = tmp_path / "grid.json"
    save_grid(cells, path)
    loaded = load_grid(path)
    assert loaded == cells
