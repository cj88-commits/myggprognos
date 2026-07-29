"""Central, version-controlled configuration for the mosquito risk model.

All tunable constants live here (or in model.yaml, loaded by this module) so
that nothing important is scattered as magic numbers through the codebase.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FORECAST_DIR = REPO_ROOT / "forecast"
DATA_DIR = REPO_ROOT / "data"
STATIC_DATA_DIR = DATA_DIR / "static"
SAMPLE_DATA_DIR = DATA_DIR / "samples"
GENERATED_DATA_DIR = DATA_DIR / "generated"
DEFAULT_MODEL_CONFIG_PATH = FORECAST_DIR / "model.yaml"

MODEL_VERSION = "0.1.0"

# Sweden bounding box (approximate, WGS84) used to build/filter the grid.
SWEDEN_BBOX = {
    "min_lat": 55.2,
    "max_lat": 69.1,
    "min_lon": 10.9,
    "max_lon": 24.2,
}

GRID_RESOLUTION_KM = 5.0
FORECAST_DAYS = 7
HOURLY_HORIZON_HOURS = 48
FORECAST_UPDATE_INTERVAL_HOURS = 6

OPEN_METEO_BASE_URL = os.environ.get(
    "OPEN_METEO_BASE_URL", "https://api.open-meteo.com/v1/forecast"
)
OPEN_METEO_ARCHIVE_URL = os.environ.get(
    "OPEN_METEO_ARCHIVE_URL", "https://archive-api.open-meteo.com/v1/archive"
)

# Open-Meteo allows many coordinates per request; keep batches well under
# documented/observed limits and comfortably below URL length limits.
WEATHER_BATCH_SIZE = int(os.environ.get("WEATHER_BATCH_SIZE", "50"))
WEATHER_REQUEST_TIMEOUT_S = float(os.environ.get("WEATHER_REQUEST_TIMEOUT_S", "20"))
WEATHER_MAX_RETRIES = int(os.environ.get("WEATHER_MAX_RETRIES", "4"))
WEATHER_BACKOFF_BASE_S = float(os.environ.get("WEATHER_BACKOFF_BASE_S", "1.0"))
WEATHER_CACHE_TTL_S = int(os.environ.get("WEATHER_CACHE_TTL_S", "3600"))
WEATHER_CACHE_DIR = Path(
    os.environ.get("WEATHER_CACHE_DIR", str(DATA_DIR / "cache" / "weather"))
)

RISK_CATEGORIES = [
    (0.0, 1.9, "very_low", "Very low"),
    (2.0, 3.9, "low", "Low"),
    (4.0, 5.9, "moderate", "Moderate"),
    (6.0, 7.9, "high", "High"),
    (8.0, 10.0, "very_high", "Very high"),
]

CONFIDENCE_LABELS = [
    (0.00, 0.39, "low", "Low"),
    (0.40, 0.69, "medium", "Medium"),
    (0.70, 1.00, "high", "High"),
]

DAYPARTS = {
    "morning": (6, 11),
    "afternoon": (11, 17),
    "evening": (17, 22),
    "night": (22, 6),
}


@dataclass
class ModelConfig:
    """Typed view over model.yaml. Falls back to sane defaults if a key is
    missing so the sample pipeline keeps working while the config evolves."""

    version: str = MODEL_VERSION
    development_base_temperature_c: float = 10.0
    population_weights: dict[str, float] = field(default_factory=dict)
    activity_params: dict[str, float] = field(default_factory=dict)
    exposure_params: dict[str, float] = field(default_factory=dict)
    activities: dict[str, float] = field(default_factory=dict)
    confidence_weights: dict[str, float] = field(default_factory=dict)
    report_adjustment: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "ModelConfig":
        path = path or DEFAULT_MODEL_CONFIG_PATH
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        model = raw.get("model", {})
        return cls(
            version=model.get("version", MODEL_VERSION),
            development_base_temperature_c=float(
                model.get("development_base_temperature_c", 10.0)
            ),
            population_weights=model.get("population_weights", {}),
            activity_params=model.get("activity", {}),
            exposure_params=model.get("exposure", {}),
            activities=raw.get("activities", {}),
            confidence_weights=raw.get("confidence", {}),
            report_adjustment=raw.get("report_adjustment", {}),
            raw=raw,
        )


def load_model_config(path: Path | None = None) -> ModelConfig:
    return ModelConfig.load(path)
