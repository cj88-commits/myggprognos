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

# A single endpoint serves both recent history and forward forecast (see
# weather.py::OpenMeteoProvider.fetch_combined, using the "past_days"
# parameter) -- there's no separate archive-API endpoint/env var anymore.
OPEN_METEO_BASE_URL = os.environ.get(
    "OPEN_METEO_BASE_URL", "https://api.open-meteo.com/v1/forecast"
)

# Open-Meteo allows many coordinates per request; keep batches well under
# documented/observed limits and comfortably below URL length limits.
WEATHER_BATCH_SIZE = int(os.environ.get("WEATHER_BATCH_SIZE", "50"))
WEATHER_REQUEST_TIMEOUT_S = float(os.environ.get("WEATHER_REQUEST_TIMEOUT_S", "20"))
WEATHER_MAX_RETRIES = int(os.environ.get("WEATHER_MAX_RETRIES", "4"))
WEATHER_BACKOFF_BASE_S = float(os.environ.get("WEATHER_BACKOFF_BASE_S", "1.0"))
# Proactive, fixed delay before every real (non-cached) request, spacing
# consecutive batches out regardless of success/failure. Discovered
# necessary in production: firing ~700+ batched requests back-to-back at
# full-Sweden (~18k cell) scale gets Open-Meteo's free archive API to
# rate-limit (HTTP 429) almost every request, and short exponential
# backoff alone just re-hits the same quota window without ever letting it
# reset -- see WEATHER_RATE_LIMIT_BACKOFF_S below.
WEATHER_REQUEST_PACING_S = float(os.environ.get("WEATHER_REQUEST_PACING_S", "2.0"))
# Backoff specifically for HTTP 429 (rate limited), used instead of the
# generic exponential backoff above -- a 429 means "over quota right now",
# so a 1s/2s/4s ramp is nearly useless; this waits much longer per attempt.
WEATHER_RATE_LIMIT_BACKOFF_S = float(os.environ.get("WEATHER_RATE_LIMIT_BACKOFF_S", "30.0"))
WEATHER_CACHE_TTL_S = int(os.environ.get("WEATHER_CACHE_TTL_S", "3600"))
WEATHER_CACHE_DIR = Path(
    os.environ.get("WEATHER_CACHE_DIR", str(DATA_DIR / "cache" / "weather"))
)

# SMHI Open Data (see forecast/src/smhi_weather.py) -- evaluated in parallel
# with Open-Meteo, not yet the default. Both the SNOW forecast model and the
# MESAN analysis product share the exact same ~1M-point grid (confirmed live
# against the API), so a single precomputed nearest-neighbor index covers
# both.
SMHI_FORECAST_BASE_URL = os.environ.get(
    "SMHI_FORECAST_BASE_URL",
    "https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1",
)
SMHI_ANALYSIS_BASE_URL = os.environ.get(
    "SMHI_ANALYSIS_BASE_URL",
    "https://opendata-download-metanalys.smhi.se/api/category/mesan2g/version/3",
)
SMHI_GRID_INDEX_PATH = STATIC_DATA_DIR / "smhi_grid_index.json"
SMHI_REQUEST_TIMEOUT_S = float(os.environ.get("SMHI_REQUEST_TIMEOUT_S", "30"))
SMHI_MAX_RETRIES = int(os.environ.get("SMHI_MAX_RETRIES", "4"))
SMHI_BACKOFF_BASE_S = float(os.environ.get("SMHI_BACKOFF_BASE_S", "1.0"))

# Risk is a 0-100 score (see forecast/src/model.py). Labels are emitted as
# Swedish content data directly from the pipeline (not frontend UI chrome),
# so no frontend i18n lookup is needed to display them.
RISK_CATEGORIES = [
    (0, 19, "very_low", "Mycket låg"),
    (20, 39, "low", "Låg"),
    (40, 59, "moderate", "Måttlig"),
    (60, 79, "high", "Hög"),
    (80, 100, "very_high", "Mycket hög"),
]

CONFIDENCE_LABELS = [
    (0, 39, "low", "Låg"),
    (40, 69, "medium", "Medel"),
    (70, 100, "high", "Hög"),
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
