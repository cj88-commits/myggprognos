from __future__ import annotations

from datetime import datetime, timezone

import pytest
from config import ModelConfig, load_model_config
from grid import GridCell
from static_features import StaticFeatures
from weather import HourlyWeather, SyntheticWeatherProvider


@pytest.fixture
def model_config() -> ModelConfig:
    return load_model_config()


@pytest.fixture
def sample_cell() -> GridCell:
    return GridCell(cell_id="SE_TEST", latitude=59.33, longitude=18.07, region="Svealand")


@pytest.fixture
def sample_static() -> StaticFeatures:
    return StaticFeatures(
        cell_id="SE_TEST",
        forest_fraction=0.4,
        wetland_fraction=0.2,
        urban_fraction=0.1,
        water_fraction=0.05,
        distance_to_water_km=1.0,
        elevation_m=30.0,
        slope_deg=1.5,
        coastal_exposure=0.3,
        water_body_density=0.2,
    )


@pytest.fixture
def synthetic_weather(sample_cell) -> HourlyWeather:
    provider = SyntheticWeatherProvider()
    start = datetime(2026, 7, 15, tzinfo=timezone.utc).date()
    end = datetime(2026, 7, 22, tzinfo=timezone.utc).date()
    result = provider.fetch_forecast([sample_cell], start, end)
    return result[sample_cell.cell_id]
