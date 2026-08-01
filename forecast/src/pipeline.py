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
    FORECAST_DAYS,
    GENERATED_DATA_DIR,
    HOURLY_HORIZON_HOURS,
    SAMPLE_DATA_DIR,
    STATIC_DATA_DIR,
    ModelConfig,
    load_model_config,
)
from confidence import compute_confidence
from explanation import format_factor_strings, generate_explanation
from feature_engineering import compute_features, precompute_rolling_windows
from grid import GridCell, generate_sample_grid, load_grid, save_grid
from history_cache import (
    load_history_cache,
    merge_cached_and_fresh,
    past_days_to_fetch,
    save_history_cache,
    split_history_for_cache,
)
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
    write_series_shards,
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
    history_cache_path: Path | None = None,
    cells_override: list[GridCell] | None = None,
) -> dict:
    output_dir = output_dir or (GENERATED_DATA_DIR / "latest")
    # Deliberately a sibling of output_dir, not inside it -- output_dir
    # (data/generated/latest) gets bundled straight into the public
    # frontend build; this raw weather cache never should be.
    history_cache_path = history_cache_path or (GENERATED_DATA_DIR / "weather_history_cache.json.gz")
    run_time = run_time or datetime.now(timezone.utc)
    config = load_model_config()

    grid_path = SAMPLE_DATA_DIR / "grid.json" if sample else STATIC_DATA_DIR / "grid.json"
    static_path = SAMPLE_DATA_DIR / "static_features.json" if sample else STATIC_DATA_DIR / "cell_features.json"

    if cells_override is not None:
        # Test-only escape hatch: exercise the real (non-sample) fetch +
        # caching path against a small in-memory grid instead of the real
        # ~18.6k-cell data/static/grid.json, which would make this a slow,
        # environment-dependent integration test rather than a unit test.
        cells = cells_override
    elif sample:
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

    # SyntheticWeatherProvider anchors its seasonal-mean calculation to
    # `run_time` (not real wall-clock time) so sample-mode/test runs stay
    # reproducible regardless of the actual date they're executed on. The
    # real provider needs no such anchor -- Open-Meteo's past_days /
    # forecast_days are inherently relative to whenever the request is
    # actually made, which is what we want in production anyway.
    provider = weather_provider or (SyntheticWeatherProvider(today=run_time) if sample else OpenMeteoProvider())

    today = run_time.date()
    forecast_end = today + timedelta(days=6)

    if sample:
        # Sample mode uses synthetic, instant, free data -- no caching
        # benefit, and always-full-fetch keeps existing tests' assertions
        # (which check specific reproducible values) simple.
        weather_by_cell = provider.fetch_combined(cells, HISTORY_DAYS_BACK, FORECAST_DAYS)
    else:
        # Forecast data (today..+FORECAST_DAYS) must always be refetched
        # fresh -- it changes as Open-Meteo's models update. A given PAST
        # hour's observed weather never changes once it's in the past
        # though, so a warm cache only needs a small gap-filling fetch
        # instead of the full HISTORY_DAYS_BACK window every single run
        # (see history_cache.py -- refetching the full 21 days from
        # scratch on every 6-hourly run was the dominant driver of both
        # pipeline runtime and Open-Meteo rate-limiting).
        cached_history = load_history_cache(history_cache_path)
        needed_past_days = past_days_to_fetch(history_cache_path, HISTORY_DAYS_BACK)
        logger.info(
            "Weather history cache: %s -> fetching %d day(s) of history this run",
            "warm" if needed_past_days < HISTORY_DAYS_BACK else "cold/stale (full backfill)",
            needed_past_days,
        )
        fresh_by_cell = provider.fetch_combined(cells, needed_past_days, FORECAST_DAYS)

        weather_by_cell = {}
        new_cache: dict[str, HourlyWeather] = {}
        for cell in cells:
            fresh = fresh_by_cell.get(cell.cell_id)
            if fresh is None:
                continue
            merged = merge_cached_and_fresh(cached_history.get(cell.cell_id), fresh, run_time)
            weather_by_cell[cell.cell_id] = merged
            new_cache[cell.cell_id] = split_history_for_cache(merged, run_time, HISTORY_DAYS_BACK)

        save_history_cache(history_cache_path, new_cache)

    for cell in cells:
        if cell.cell_id not in weather_by_cell:
            logger.error("No weather data available for cell %s; skipping", cell.cell_id)

    hour_start = run_time.replace(minute=0, second=0, microsecond=0)

    # Precompute expensive per-cell rolling-window state once (rather than
    # re-parsing/re-scanning the full weather series on every one of the 49
    # hourly + 28 daypart compute_features calls below) -- see
    # feature_engineering.py module docstring. This is the dominant
    # performance win at full-Sweden (~15-20k cell) scale.
    rolling_by_cell = {
        cell_id: precompute_rolling_windows(weather, config.development_base_temperature_c)
        for cell_id, weather in weather_by_cell.items()
    }

    series_by_cell: dict[str, dict] = {cell.cell_id: {"daily": [], "hourly": []} for cell in cells}

    # --- Hourly (first 48h) ---
    hourly_files: list[str] = []
    for h in range(HOURLY_HORIZON_HOURS + 1):
        target = hour_start + timedelta(hours=h)
        records = []
        for cell in cells:
            weather = weather_by_cell.get(cell.cell_id)
            if weather is None:
                continue
            features = compute_features(
                static_map[cell.cell_id], weather, target, config.development_base_temperature_c,
                rolling=rolling_by_cell.get(cell.cell_id),
            )
            score = compute_score(features, config, "general")
            horizon_hours = max(0.0, (target - run_time).total_seconds() / 3600.0)
            confidence_result = compute_confidence(features, score, config, horizon_hours, is_placeholder)
            record = _record_from_score(cell.cell_id, features, score, confidence_result)
            records.append(record)
            series_by_cell[cell.cell_id]["hourly"].append(record)
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
                features = compute_features(
                    static_map[cell.cell_id], weather, target, config.development_base_temperature_c,
                    rolling=rolling_by_cell.get(cell.cell_id),
                )
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
                "explanation_text": format_factor_strings(explanation),
            }
            records.append(record)
            series_by_cell[cell.cell_id]["daily"].append(record)
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
    series_files = write_series_shards(series_by_cell, output_dir)

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
        series_files=series_files,
    )

    logger.info("Pipeline complete: %d cells, %d daily files, %d hourly files", len(cells), len(daily_files), len(hourly_files))
    return {
        "cell_count": len(cells),
        "daily_files": daily_files,
        "hourly_files": hourly_files,
        "warnings": warnings,
        "manifest_path": str(manifest_path),
    }
