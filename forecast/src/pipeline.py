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
import os
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from config import (
    DAYPARTS,
    FORECAST_DAYS,
    GENERATED_DATA_DIR,
    HOURLY_HORIZON_HOURS,
    REPO_ROOT,
    SAMPLE_DATA_DIR,
    STATIC_DATA_DIR,
    ModelConfig,
    load_model_config,
)
from confidence import compute_confidence
from explanation import format_factor_strings, generate_explanation
from feature_engineering import SWEDEN_TZ, compute_features, precompute_rolling_windows
from grid import GridCell, generate_sample_grid, load_grid, save_grid
from history_cache import (
    INCREMENTAL_PAST_DAYS,
    cell_needs_full_backfill,
    load_history_cache,
    merge_cached_and_fresh,
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

# Above this share of the grid using placeholder (not real GIS-derived)
# static features on a real (non-sample) run, add a manifest warning -- see
# "Production guard" below.
STATIC_PLACEHOLDER_WARN_FRACTION = 0.05


def _local_daypart_target(target_date: date, local_hour: int) -> datetime:
    """The UTC instant corresponding to `local_hour`:00 Swedish clock time
    on `target_date`.

    Bug fixed here (see docs/model-audit-before.md #6): this used to attach
    `tzinfo=timezone.utc` directly to `local_hour`, i.e. treat a Swedish
    wall-clock hour as if it were already UTC. In CEST (summer, UTC+2) that
    silently shifted "evening" (meant to be ~20:00 local) to 22:00 local,
    and "night" (23:00 local) to 01:00 local the *next* calendar day --
    worst exactly during mosquito season. Building a naive local datetime,
    attaching Europe/Stockholm via `replace` (not `astimezone`, which would
    reinterpret already-correct UTC), then converting to UTC is the
    standard zoneinfo pattern and resolves CET/CEST correctly for the given
    date automatically.
    """
    local_naive = datetime(target_date.year, target_date.month, target_date.day, local_hour)
    local_dt = local_naive.replace(tzinfo=SWEDEN_TZ)
    return local_dt.astimezone(timezone.utc)
HISTORY_DAYS_BACK = 21
# Cells per fetch+cache-checkpoint chunk (~1000 cells = ~20 batches at the
# default WEATHER_BATCH_SIZE). GitHub-hosted runners have a hard 6-hour job
# ceiling that even a live-succeeding fetch can still hit at full-Sweden
# scale; checkpointing the history cache after every chunk (not just once
# at the very end) means a mid-flight kill still leaves every
# already-processed chunk cached, so the next attempt only has to redo
# what's left instead of starting completely over.
#
# This default assumes a provider whose request cost scales with the
# number of cells in a batch (true for OpenMeteoProvider). SMHIProvider is
# the opposite: each fetch_combined call re-fetches a whole-domain
# times.json plus every needed (time, parameter) array regardless of how
# many cells were asked for, so calling it once per 1000-cell chunk
# repeats that whole-domain cost ~19x for the full grid instead of paying
# it once -- confirmed live (a full-grid run using the 1000-cell default
# was still going after 42 minutes of real progress, on pace to take far
# longer). run_forecast.py passes a much larger cache_checkpoint_chunk_cells
# for --provider smhi so the whole grid is fetched in one call.
CACHE_CHECKPOINT_CHUNK_CELLS = 1000


def _resolve_build_sha() -> str:
    """Best-effort source commit SHA for this build, published in the
    manifest (docs/wind-calm-investigation.md item 11). Prefers the CI-
    provided GITHUB_SHA (the exact commit the scheduled workflow checked
    out) over a local `git rev-parse HEAD` (convenient for local dev runs,
    but reflects the working tree's current HEAD, not necessarily what
    ends up published if there are uncommitted changes). Never raises --
    manifest publishing must not fail just because git/CI metadata is
    unavailable in some environment."""
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5, check=True
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _record_from_score(cell_id: str, features, score, confidence_result) -> dict:
    return {
        "cell_id": cell_id,
        "risk": score.final_risk,
        "population_potential": score.population_potential,
        "biting_activity": score.biting_activity,
        "exposure": score.exposure,
        "base_exposure_fraction": round(score.exposure_terms.get("base_exposure_fraction", 0.5), 4),
        "confidence": confidence_result.confidence,
        # Clearer-named aliases for the "forecast products" iteration (see
        # docs/model-audit-after.md) -- published alongside the original
        # fields above rather than replacing them, per the backward-
        # compatibility requirement (existing frontend/consumers keep
        # working unchanged; new consumers can read the clearer names).
        "mosquito_abundance": score.population_potential,
        "activity_modifier": score.activity_modifier,
        "exposure_modifier": score.exposure_modifier,
        # Forecast context (docs/wind-calm-investigation.md item 10) --
        # published so the frontend can attach exactly what the model knew
        # to a user report at submission time, letting a future false-
        # negative analysis join reports back to their forecast context
        # without needing generated forecast archives that may no longer
        # be retained. wind_speed_current_ms is genuinely the wind AT the
        # record's own target time (see feature_engineering.py), despite
        # the "current" name -- not real-time "right now" wind.
        "forecast_wind_ms": features.wind_speed_current_ms,
        "effective_wind_ms": features.wind_speed_effective_ms,
        "temperature_c": features.current_temperature_c,
        "humidity_pct": features.humidity_current_pct,
        # Geographic-model redesign (Phase 3/6/14): published separately
        # from population_potential/mosquito_abundance so a future frontend
        # can distinguish "this landscape is generally good mosquito
        # habitat" (habitat_capacity, slow-changing) from "mosquitoes have
        # probably actually built up here recently" (mosquito_pressure,
        # persistent but weather-responsive) -- see feature_engineering.py
        # and docs/geographic-model-audit-before.md.
        "habitat_capacity": features.habitat_capacity,
        "mosquito_pressure": features.mosquito_pressure,
    }


def run_pipeline(
    sample: bool = True,
    output_dir: Path | None = None,
    weather_provider: WeatherProvider | None = None,
    static_placeholder: bool | None = None,
    run_time: datetime | None = None,
    history_cache_path: Path | None = None,
    cells_override: list[GridCell] | None = None,
    cache_checkpoint_chunk_cells: int | None = None,
    min_cell_count_ratio: float | None = None,
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
        logger.info(
            "Weather history cache loaded: %d/%d cells have some cached history",
            len(cached_history),
            len(cells),
        )

        chunk_size = cache_checkpoint_chunk_cells or CACHE_CHECKPOINT_CHUNK_CELLS
        weather_by_cell = {}
        new_cache: dict[str, HourlyWeather] = {}
        for chunk_start in range(0, len(cells), chunk_size):
            chunk = cells[chunk_start : chunk_start + chunk_size]

            # Decide per cell, not once for the whole run: a cell with no
            # cached history yet (e.g. a prior backfill was killed before
            # reaching it) needs the full HISTORY_DAYS_BACK window; a cell
            # whose cache already covers that window only needs a small
            # incremental top-up. See cell_needs_full_backfill's docstring
            # for why a single global "is the cache fresh" check is wrong
            # here.
            full_backfill_cells = [
                c for c in chunk
                if cell_needs_full_backfill(cached_history.get(c.cell_id), run_time, HISTORY_DAYS_BACK)
            ]
            full_backfill_ids = {c.cell_id for c in full_backfill_cells}
            incremental_cells = [c for c in chunk if c.cell_id not in full_backfill_ids]

            fresh_by_cell: dict[str, HourlyWeather] = {}
            if full_backfill_cells:
                fresh_by_cell.update(provider.fetch_combined(full_backfill_cells, HISTORY_DAYS_BACK, FORECAST_DAYS))
            if incremental_cells:
                fresh_by_cell.update(provider.fetch_combined(incremental_cells, INCREMENTAL_PAST_DAYS, FORECAST_DAYS))

            # Merging/splitting each cell's series is plain per-cell Python
            # work (unlike SMHIProvider's fetch, which is vectorized) --
            # for a large chunk (e.g. the whole grid in one chunk, as
            # run_forecast.py does for --provider smhi) this alone can run
            # long enough with zero log output to look stalled. Confirmed
            # live: the log went silent here for 19+ minutes (past even
            # the fetch-progress logging) before a run got cancelled.
            for i, cell in enumerate(chunk):
                if i == 0 or (i + 1) % 2000 == 0 or i == len(chunk) - 1:
                    logger.info("Merging fetched weather into cache: %d/%d cells in this chunk", i + 1, len(chunk))
                fresh = fresh_by_cell.get(cell.cell_id)
                if fresh is None:
                    continue
                merged = merge_cached_and_fresh(cached_history.get(cell.cell_id), fresh, run_time)
                weather_by_cell[cell.cell_id] = merged
                new_cache[cell.cell_id] = split_history_for_cache(merged, run_time, HISTORY_DAYS_BACK)

            # Checkpoint after every chunk, not just once at the very end
            # -- see CACHE_CHECKPOINT_CHUNK_CELLS above.
            save_history_cache(history_cache_path, new_cache)
            logger.info(
                "Weather history cache checkpointed: %d/%d cells done (%d full backfill, %d incremental this chunk)",
                len(new_cache),
                len(cells),
                len(full_backfill_cells),
                len(incremental_cells),
            )

    for cell in cells:
        if cell.cell_id not in weather_by_cell:
            logger.error("No weather data available for cell %s; skipping", cell.cell_id)

    hour_start = run_time.replace(minute=0, second=0, microsecond=0)

    logger.info("Weather fetch done for %d/%d cells; starting scoring", len(weather_by_cell), len(cells))

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
                calm_threshold_ms=config.wind_dynamics_params.get("calm_threshold_ms", 1.8),
                wind_shelter_params=config.wind_shelter_params,
                pressure_survival_daily=config.mosquito_pressure_params.get("pressure_survival_daily", 0.90),
                pressure_lookback_days=int(config.mosquito_pressure_params.get("pressure_lookback_days", 21)),
            )
            score = compute_score(features, config, "general")
            horizon_hours = max(0.0, (target - run_time).total_seconds() / 3600.0)
            # Per-cell, not the dataset-wide `is_placeholder` flag alone --
            # a cell that individually fell back to a placeholder (missing
            # from cell_features.json, outside raster tile coverage) must
            # not inherit the rest of the run's real-data confidence bonus
            # (see docs/model-audit-before.md bug #2).
            cell_is_placeholder = is_placeholder or static_map[cell.cell_id].is_placeholder
            confidence_result = compute_confidence(features, score, config, horizon_hours, cell_is_placeholder)
            record = _record_from_score(cell.cell_id, features, score, confidence_result)
            # "Myggrisk just nu" -- this hourly record already IS the
            # selected-hour risk; current_risk is just a clearer-named alias
            # of the same value (see docs/model-audit-after.md).
            record["current_risk"] = record["risk"]
            records.append(record)
            series_by_cell[cell.cell_id]["hourly"].append(record)
        hour_label = target.strftime("%Y-%m-%dT%H")
        write_hourly_file(hour_label, records, output_dir)
        hourly_files.append(f"hourly/{hour_label}.json.gz")
        # Scoring ~18.6k cells x 49 hours + 28 dayparts has no per-request
        # network activity to log, unlike the weather fetch -- without
        # this, a full-Sweden run produces a long stretch of zero log
        # output during the CPU-bound scoring phase. Confirmed live: a
        # 6+ minute silent gap here got a GitHub Actions job cancelled
        # ("The operation was canceled.") with no other error, well before
        # any configured timeout -- extended silence itself appears to be
        # the trigger, not the actual compute time.
        if h == 0 or (h + 1) % 10 == 0 or h == HOURLY_HORIZON_HOURS:
            logger.info("Hourly scoring: %d/%d hours done", h + 1, HOURLY_HORIZON_HOURS + 1)

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
                target = _local_daypart_target(target_date, hour)
                features = compute_features(
                    static_map[cell.cell_id], weather, target, config.development_base_temperature_c,
                    rolling=rolling_by_cell.get(cell.cell_id),
                    calm_threshold_ms=config.wind_dynamics_params.get("calm_threshold_ms", 1.8),
                    wind_shelter_params=config.wind_shelter_params,
                    pressure_survival_daily=config.mosquito_pressure_params.get("pressure_survival_daily", 0.90),
                    pressure_lookback_days=int(config.mosquito_pressure_params.get("pressure_lookback_days", 21)),
                )
                score = compute_score(features, config, "general")
                horizon_hours = max(0.0, (target - run_time).total_seconds() / 3600.0)
                cell_is_placeholder = is_placeholder or static_map[cell.cell_id].is_placeholder
                confidence_result = compute_confidence(features, score, config, horizon_hours, cell_is_placeholder)
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
                # "Myggrisk idag" / "Myggläge" product fields -- aliases of
                # the peak daypart's own values above, published under
                # clearer names (see docs/model-audit-after.md). Kept
                # alongside (not instead of) the original fields for
                # backward compatibility.
                "daily_peak_risk": peak["risk"],
                "mosquito_abundance": peak["mosquito_abundance"],
                "activity_modifier": peak["activity_modifier"],
                "exposure_modifier": peak["exposure_modifier"],
                # Geographic-model redesign (Phase 3/6/14): published at the
                # daily record's top level too (already present nested under
                # dayparts.<part>, via _record_from_score), so a consumer
                # that only reads the daily/peak record still gets Myggläge's
                # habitat/pressure breakdown without needing to reach into
                # dayparts.
                "habitat_capacity": peak["habitat_capacity"],
                "mosquito_pressure": peak["mosquito_pressure"],
                # Representative LOCAL time for the peak daypart (e.g.
                # "20:00") -- honestly reflects the model's daypart-level
                # (not true hourly) resolution over the 7-day horizon,
                # rather than implying more precision than it has.
                "daily_peak_local_time": f"{DAYPART_REPRESENTATIVE_HOUR[peak_part]:02d}:00",
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
        logger.info("Daily scoring: %d/7 days done", day_offset + 1)

    # --- Sanity checks (before publishing anything else) ---
    previous_manifest = load_previous_manifest(output_dir)
    previous_cell_count = previous_manifest.get("cell_count") if previous_manifest else None
    sanity_kwargs = {} if min_cell_count_ratio is None else {"min_cell_count_ratio": min_cell_count_ratio}
    try:
        warnings = run_sanity_checks(cells, daily_records_by_date, previous_cell_count, **sanity_kwargs)
    except OutputValidationError as exc:
        logger.error("Sanity checks failed, aborting publish: %s", exc)
        raise

    # Production guard (docs/model-audit-before.md bug #2 / static-data
    # audit): a real (non-sample) run relying heavily on per-cell
    # placeholder static features would previously publish silently at
    # full confidence. This doesn't block publishing -- individual
    # placeholder cells already get correctly lowered per-cell confidence
    # above -- but a WIDESPREAD placeholder fallback (most of the grid
    # missing from cell_features.json, or outside raster tile coverage)
    # means something is wrong with the static-data pipeline itself and
    # deserves a loud, visible warning, not just quietly-lower per-cell
    # numbers nobody notices in aggregate.
    if not sample:
        placeholder_count = sum(1 for f in static_map.values() if f.is_placeholder)
        placeholder_fraction = placeholder_count / len(static_map) if static_map else 0.0
        if placeholder_fraction > STATIC_PLACEHOLDER_WARN_FRACTION:
            warnings.append(
                f"{placeholder_count}/{len(static_map)} cells ({placeholder_fraction:.0%}) are using placeholder "
                f"static features, not real GIS data -- check cell_features.json coverage and raster tile downloads."
            )
            logger.warning(
                "%d/%d cells (%.0f%%) using placeholder static features -- exceeds %.0f%% warning threshold",
                placeholder_count, len(static_map), placeholder_fraction * 100, STATIC_PLACEHOLDER_WARN_FRACTION * 100,
            )

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
        combination=config.combination_params or {
            "activity_floor": 0.30, "activity_weight": 0.70,
            "exposure_floor": 0.75, "exposure_weight": 0.50, "scale": 105,
        },
        thresholds={"abundance": config.abundance_thresholds},
        build_sha=_resolve_build_sha(),
    )

    logger.info("Pipeline complete: %d cells, %d daily files, %d hourly files", len(cells), len(daily_files), len(hourly_files))
    return {
        "cell_count": len(cells),
        "daily_files": daily_files,
        "hourly_files": hourly_files,
        "warnings": warnings,
        "manifest_path": str(manifest_path),
    }
