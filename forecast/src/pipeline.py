"""End-to-end forecast pipeline orchestration.

Run via scripts/run_forecast.py. Steps (mirrors the GitHub Actions job):

  1. Load the forecast grid (sample or full) and precomputed static features.
  2. Fetch recent history + forecast weather (Open-Meteo, or synthetic data
     in sample mode) for every cell, batched.
  3. Compute hourly features/scores for the first 48 hours.
  4. Compute daypart features/scores (morning/afternoon/evening/night) for
     all 7 forecast days, and derive a daily summary + explanation from the
     day's peak daypart.
  5. Run sanity checks, then write versioned output assets. If anything
     fails, the previous valid forecast under data/generated/latest is left
     untouched.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from config import (
    DAYPARTS,
    GENERATED_DATA_DIR,
    HOURLY_HORIZON_HOURS,
    SAMPLE_DATA_DIR,
    STATIC_DATA_DIR,
    ModelConfig,
    load_model_config,
)
from confidence import compute_confidence
from explanation import generate_explanation
from feature_engineering import compute_features
from grid import GridCell, generate_sample_grid, load_grid, save_grid
from model import compute_score, risk_category
from output import (
    OutputValidationError,
    load_previous_manifest,
    run_sanity_checks,
    write_cells_file,
    write_daily_file,
    write_hourly_file,
    write_locations_index,
    write_manifest,
)
from static_features import (
    StaticFeatures,
    generate_placeholder_static_features,
    load_static_features,
    save_static_features,
)
from weather import HourlyWeather, OpenMeteoProvider, SyntheticWeatherProvider, WeatherProvider

logger = logging.getLogger("mosquito_forecast.pipeline")

DAYPART_REPRESENTATIVE_HOUR = {"morning": 8, "afternoon": 14, "evening": 20, "night": 23}
HISTORY_DAYS_BACK = 21


def merge_weather(history: HourlyWeather, forecast: HourlyWeather) -> HourlyWeather:
    """Concatenate history + forecast series into one continuous timeline,
    preferring forecast values on overlapping timestamps."""
    times = list(history.times) + [t for t in forecast.times if t not in set(history.times)]

    def field_at(source: HourlyWeather, field_name: str, t: str) -> float | None:
        try:
            i = source.times.index(t)
        except ValueError:
            return None
        return getattr(source, field_name)[i]

    fields = [
        "temperature_2m", "relative_humidity_2m", "precipitation",
        "wind_speed_10m", "wind_gusts_10m", "cloud_cover", "soil_moisture",
    ]
    merged_series: dict[str, list] = {f: [] for f in fields}
    sorted_times = sorted(set(times))
    for t in sorted_times:
        for f in fields:
            value = field_at(forecast, f, t)
            if value is None:
                value = field_at(history, f, t)
            merged_series[f].append(value)

    return HourlyWeather(
        cell_id=history.cell_id,
        latitude=history.latitude,
        longitude=history.longitude,
        times=sorted_times,
        temperature_2m=merged_series["temperature_2m"],
        relative_humidity_2m=merged_series["relative_humidity_2m"],
        precipitation=merged_series["precipitation"],
        wind_speed_10m=merged_series["wind_speed_10m"],
        wind_gusts_10m=merged_series["wind_gusts_10m"],
        cloud_cover=merged_series["cloud_cover"],
        soil_moisture=merged_series["soil_moisture"],
        used_fallback=history.used_fallback or forecast.used_fallback,
    )


def _record_from_score(cell_id: str, features, score, confidence_result) -> dict:
    return {
        "cell_id": cell_id,
        "risk": score.final_risk,
        "population_potential": score.population_potential,
        "biting_activity": score.biting_activity,
        "exposure": score.exposure,
        "base_exposure_fraction": round(score.exposure_terms.get("base_exposure_fraction", 0.5), 4),
        "confidence": confidence_result.confidence,
    }


def run_pipeline(
    sample: bool = True,
    output_dir: Path | None = None,
    weather_provider: WeatherProvider | None = None,
    static_placeholder: bool | None = None,
    run_time: datetime | None = None,
) -> dict:
    output_dir = output_dir or (GENERATED_DATA_DIR / "latest")
    run_time = run_time or datetime.now(timezone.utc)
    config = load_model_config()

    grid_path = SAMPLE_DATA_DIR / "grid.json" if sample else STATIC_DATA_DIR / "grid.json"
    static_path = SAMPLE_DATA_DIR / "static_features.json" if sample else STATIC_DATA_DIR / "cell_features.json"

    if sample:
        cells = generate_sample_grid()
        save_grid(cells, grid_path)
    elif grid_path.exists():
        cells = load_grid(grid_path)
    else:
        raise FileNotFoundError(
            f"No grid found at {grid_path}. Run scripts/prepare_grid.py first, "
            "or use sample=True for sample mode."
        )

    is_placeholder = static_placeholder if static_placeholder is not None else True
    if static_path.exists():
        static_map = load_static_features(static_path)
        missing = [c.cell_id for c in cells if c.cell_id not in static_map]
        if missing:
            logger.warning("%d cells missing static features; generating placeholders", len(missing))
            for cell in cells:
                if cell.cell_id not in static_map:
                    static_map[cell.cell_id] = generate_placeholder_static_features(cell)
    else:
        static_map = {c.cell_id: generate_placeholder_static_features(c) for c in cells}
        save_static_features(list(static_map.values()), static_path)

    provider = weather_provider or (SyntheticWeatherProvider() if sample else OpenMeteoProvider())

    today = run_time.date()
    forecast_end = today + timedelta(days=6)

    history_by_cell = provider.fetch_recent_history(cells, HISTORY_DAYS_BACK)
    forecast_by_cell = provider.fetch_forecast(cells, today, forecast_end)

    weather_by_cell: dict[str, HourlyWeather] = {}
    for cell in cells:
        hist = history_by_cell.get(cell.cell_id)
        fcst = forecast_by_cell.get(cell.cell_id)
        if hist is None and fcst is None:
            logger.error("No weather data available for cell %s; skipping", cell.cell_id)
            continue
        if hist is None:
            weather_by_cell[cell.cell_id] = fcst
        elif fcst is None:
            weather_by_cell[cell.cell_id] = hist
        else:
            weather_by_cell[cell.cell_id] = merge_weather(hist, fcst)

    hour_start = run_time.replace(minute=0, second=0, microsecond=0)

    # --- Hourly (first 48h) ---
    hourly_files: list[str] = []
    for h in range(HOURLY_HORIZON_HOURS + 1):
        target = hour_start + timedelta(hours=h)
        records = []
        for cell in cells:
            weather = weather_by_cell.get(cell.cell_id)
            if weather is None:
                continue
            features = compute_features(static_map[cell.cell_id], weather, target, config.development_base_temperature_c)
            score = compute_score(features, config, "general")
            horizon_hours = max(0.0, (target - run_time).total_seconds() / 3600.0)
            confidence_result = compute_confidence(features, score, config, horizon_hours, is_placeholder)
            records.append(_record_from_score(cell.cell_id, features, score, confidence_result))
        hour_label = target.strftime("%Y-%m-%dT%H")
        write_hourly_file(hour_label, records, output_dir)
        hourly_files.append(f"hourly/{hour_label}.json.gz")

    # --- Daily (7 days, with daypart breakdown) ---
    daily_files: list[str] = []
    daily_records_by_date: dict[str, list[dict]] = {}
    for day_offset in range(7):
        target_date = today + timedelta(days=day_offset)
        date_str = target_date.isoformat()
        records = []
        for cell in cells:
            weather = weather_by_cell.get(cell.cell_id)
            if weather is None:
                continue
            dayparts = {}
            for part, hour in DAYPART_REPRESENTATIVE_HOUR.items():
                target = datetime(target_date.year, target_date.month, target_date.day, hour, tzinfo=timezone.utc)
                features = compute_features(static_map[cell.cell_id], weather, target, config.development_base_temperature_c)
                score = compute_score(features, config, "general")
                horizon_hours = max(0.0, (target - run_time).total_seconds() / 3600.0)
                confidence_result = compute_confidence(features, score, config, horizon_hours, is_placeholder)
                dayparts[part] = {
                    **_record_from_score(cell.cell_id, features, score, confidence_result),
                    "features": features,
                    "score": score,
                }

            peak_part = max(dayparts, key=lambda p: dayparts[p]["risk"])
            peak = dayparts[peak_part]
            explanation = generate_explanation(peak["features"], peak["score"])

            record = {
                "cell_id": cell.cell_id,
                "date": date_str,
                "risk": peak["risk"],
                "population_potential": peak["population_potential"],
                "biting_activity": peak["biting_activity"],
                "exposure": peak["exposure"],
                "base_exposure_fraction": peak["base_exposure_fraction"],
                "confidence": peak["confidence"],
                "peak_period": peak_part,
                "dayparts": {
                    p: {k: v for k, v in d.items() if k not in ("features", "score")}
                    for p, d in dayparts.items()
                },
                "explanation": {
                    "positive_factors": [
                        {"key": f.key, "label": f.label, "contribution": f.contribution}
                        for f in explanation.positive_factors
                    ],
                    "negative_factors": [
                        {"key": f.key, "label": f.label, "contribution": f.contribution}
                        for f in explanation.negative_factors
                    ],
                    "summary": explanation.summary,
                },
            }
            records.append(record)
        write_daily_file(date_str, records, output_dir)
        daily_files.append(f"daily/{date_str}.json.gz")
        daily_records_by_date[date_str] = records

    # --- Sanity checks (before publishing anything else) ---
    previous_manifest = load_previous_manifest(output_dir)
    previous_cell_count = previous_manifest.get("cell_count") if previous_manifest else None
    try:
        warnings = run_sanity_checks(cells, daily_records_by_date, previous_cell_count)
    except OutputValidationError as exc:
        logger.error("Sanity checks failed, aborting publish: %s", exc)
        raise

    write_cells_file(cells, static_map, output_dir)

    places_path = SAMPLE_DATA_DIR / "places.json" if sample else STATIC_DATA_DIR / "places.json"
    places = []
    if places_path.exists():
        import json

        places = json.loads(places_path.read_text(encoding="utf-8"))
    write_locations_index(places, output_dir)

    data_quality = "degraded" if (warnings or sample) else "normal"
    manifest_path = write_manifest(
        out_dir=output_dir,
        generated_at=run_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        forecast_start=today.isoformat(),
        forecast_end=forecast_end.isoformat(),
        hourly_until=(hour_start + timedelta(hours=HOURLY_HORIZON_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        cell_count=len(cells),
        daily_files=daily_files,
        hourly_files=hourly_files,
        data_quality=data_quality,
        model_version=config.version,
        activities=config.activities,
        warnings=warnings,
    )

    logger.info("Pipeline complete: %d cells, %d daily files, %d hourly files", len(cells), len(daily_files), len(hourly_files))
    return {
        "cell_count": len(cells),
        "daily_files": daily_files,
        "hourly_files": hourly_files,
        "warnings": warnings,
        "manifest_path": str(manifest_path),
    }
