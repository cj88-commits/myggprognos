#!/usr/bin/env python
"""Reproduce and diagnose the model's output for one location + timestamp.

Built for the wind-drop false-negative investigation
(docs/wind-calm-investigation.md) but generally useful for any "why did the
model say X here" question: prints every input the score depends on (raw
forecast wind, shelter-adjusted effective wind, 1h/3h wind history and
trend, temperature, humidity, daypart activity, population potential, raw
biting activity, activity modifier, final risk/category), and can run the
CURRENT model.yaml against a CANDIDATE config side by side so a proposed
change's effect on one concrete, real scenario is visible before running
the full-Sweden diagnostics (scripts/diagnose_wind_distribution.py).

Usage:
    # Real grid + live Open-Meteo weather (needs network)
    python scripts/diagnose_scenario.py --lat 59.33 --lon 18.07 \\
        --timestamp 2026-08-05T20:00:00Z

    # Compare current vs. a candidate model.yaml
    python scripts/diagnose_scenario.py --lat 59.33 --lon 18.07 \\
        --timestamp 2026-08-05T20:00:00Z --candidate-config forecast/model_candidate.yaml

    # Offline, deterministic (sample grid + synthetic weather) -- useful for
    # a quick smoke test without network access
    python scripts/diagnose_scenario.py --lat 59.33 --lon 18.07 \\
        --timestamp 2026-07-20T20:00:00Z --sample

    # "What if the observed wind was actually 1 m/s?" override, for testing
    # a report where the forecast's own wind reading is suspected wrong
    # (investigation item 1: is this an input-accuracy problem or a model-
    # sensitivity problem?)
    python scripts/diagnose_scenario.py --lat 59.33 --lon 18.07 \\
        --timestamp 2026-08-05T20:00:00Z --observed-wind-ms 1.0
"""
from __future__ import annotations

import argparse
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _pathsetup  # noqa: F401
from config import GENERATED_DATA_DIR, SAMPLE_DATA_DIR, STATIC_DATA_DIR, ModelConfig, load_model_config
from feature_engineering import FeatureSet, compute_features, precompute_rolling_windows
from grid import GridCell, generate_sample_grid, load_grid
from history_cache import load_history_cache
from model import ScoreResult, compute_score, risk_category
from static_features import (
    StaticFeatures,
    generate_placeholder_static_features,
    load_static_features,
)
from weather import HourlyWeather, OpenMeteoProvider, SyntheticWeatherProvider


def _parse_timestamp(raw: str) -> datetime:
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _nearest_cell(cells: list[GridCell], lat: float, lon: float) -> GridCell:
    def dist2(c: GridCell) -> float:
        # Plain squared lat/lon distance (with a coarse longitude-scale
        # correction) is enough to pick a nearest cell on a ~5km grid --
        # no need for a real haversine at this precision.
        lon_scale = math.cos(math.radians(lat))
        return (c.latitude - lat) ** 2 + ((c.longitude - lon) * lon_scale) ** 2

    return min(cells, key=dist2)


def _load_cells_and_static(use_sample: bool) -> tuple[list[GridCell], dict[str, StaticFeatures]]:
    grid_path = STATIC_DATA_DIR / "grid.json"
    static_path = STATIC_DATA_DIR / "cell_features.json"
    if use_sample or not grid_path.exists():
        cells = generate_sample_grid()
        static_map = {c.cell_id: generate_placeholder_static_features(c) for c in cells}
        return cells, static_map

    cells = load_grid(grid_path)
    static_map = load_static_features(static_path) if static_path.exists() else {}
    for cell in cells:
        if cell.cell_id not in static_map:
            static_map[cell.cell_id] = generate_placeholder_static_features(cell)
    return cells, static_map


def _fetch_weather(cell: GridCell, target: datetime, use_sample: bool, past_days: int) -> HourlyWeather:
    # A cached history entry (from the scheduled production pipeline) is
    # preferred when it actually covers the requested timestamp -- it's
    # the exact data the live forecast was computed from, not a fresh
    # re-fetch that may have since updated (Open-Meteo's historical
    # reanalysis can revise recent hours). Falls back to a live fetch
    # otherwise (e.g. running against a cell/date the cache doesn't have).
    if not use_sample:
        cache_path = GENERATED_DATA_DIR / "weather_history_cache.json.gz"
        cached = load_history_cache(cache_path)
        entry = cached.get(cell.cell_id)
        if entry is not None:
            try:
                first = datetime.fromisoformat(entry.times[0]).replace(tzinfo=timezone.utc)
                last = datetime.fromisoformat(entry.times[-1]).replace(tzinfo=timezone.utc)
                if first <= target <= last:
                    print(f"(using cached weather history for {cell.cell_id}: {entry.times[0]}..{entry.times[-1]})")
                    return entry
            except (ValueError, IndexError):
                pass

    if use_sample:
        provider = SyntheticWeatherProvider(today=target)
        result = provider.fetch_combined([cell], past_days=past_days, forecast_days=2)
    else:
        provider = OpenMeteoProvider()
        result = provider.fetch_combined([cell], past_days=past_days, forecast_days=2)
    return result[cell.cell_id]


def _print_diagnostics(
    label: str,
    cell: GridCell,
    target: datetime,
    features: FeatureSet,
    score: ScoreResult,
) -> None:
    category_key, category_label = risk_category(score.final_risk)
    print(f"\n=== {label} ===")
    print(f"cell: {cell.cell_id} ({cell.latitude:.4f}, {cell.longitude:.4f}), target: {target.isoformat()}")
    print("-- wind --")
    print(f"  forecast wind (current, m/s):  {features.wind_speed_current_ms}")
    print(f"  effective (shelter-adj) wind:  {features.wind_speed_effective_ms}")
    print(f"  wind 1h ago:                   {features.wind_speed_1h_ago_ms}")
    print(f"  wind 3h ago:                   {features.wind_speed_3h_ago_ms}")
    print(f"  wind change over 1h:           {features.wind_change_1h_ms}")
    print(f"  wind change over 3h:           {features.wind_change_3h_ms}")
    print(f"  wind min over trailing 3h:     {features.wind_min_3h_ms}")
    print(f"  consecutive calm hours:        {features.calm_hours_streak}")
    print("-- other inputs --")
    print(f"  temperature (C):               {features.current_temperature_c}")
    print(f"  humidity (%):                  {features.humidity_current_pct}")
    print(f"  daypart activity term:         {round(score.activity_terms.get('daypart_activity', 0.0), 4)}")
    print("-- scores --")
    print(f"  population potential:          {score.population_potential}")
    print(f"  raw biting activity:           {score.biting_activity}")
    print(f"  calm-wind uplift multiplier:   {score.activity_terms.get('calm_wind_uplift')}")
    print(f"    calm gate:                   {score.activity_terms.get('calm_calm_gate')}")
    print(f"    population gate:             {score.activity_terms.get('calm_population_gate')}")
    print(f"    comfort gate:                {score.activity_terms.get('calm_comfort_gate')}")
    print(f"    daypart gate:                {score.activity_terms.get('calm_daypart_gate')}")
    print(f"    release (wind-drop) gate:    {score.activity_terms.get('calm_release_gate')}")
    print(f"  activity modifier:             {score.activity_modifier}")
    print(f"  exposure:                      {score.exposure}")
    print(f"  exposure modifier:             {score.exposure_modifier}")
    print(f"  FINAL RISK:                    {score.final_risk}  ({category_label} / {category_key})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--timestamp", type=str, required=True, help="ISO8601, e.g. 2026-08-05T20:00:00Z")
    parser.add_argument("--activity", type=str, default="general")
    parser.add_argument("--sample", action="store_true", help="Use the sample grid + synthetic weather (offline, deterministic)")
    parser.add_argument("--past-days", type=int, default=10, help="How many days of history to fetch before --timestamp")
    parser.add_argument(
        "--candidate-config", type=str, default=None,
        help="Path to an alternate model.yaml; scores are printed side by side with the current one",
    )
    parser.add_argument(
        "--observed-wind-ms", type=float, default=None,
        help="Override the forecast's own current-wind reading with this value (what-if / 'the forecast wind looked wrong' check)",
    )
    parser.add_argument("--notes", type=str, default=None, help="Free-text notes about the reported observation (echoed only, not fed into the model)")
    args = parser.parse_args()

    target = _parse_timestamp(args.timestamp)
    if args.notes:
        print(f"Notes: {args.notes}")

    cells, static_map = _load_cells_and_static(args.sample)
    cell = _nearest_cell(cells, args.lat, args.lon)
    static = static_map[cell.cell_id]
    dist_km = math.hypot(
        (cell.latitude - args.lat) * 111.32,
        (cell.longitude - args.lon) * 111.32 * math.cos(math.radians(args.lat)),
    )
    print(f"Nearest cell: {cell.cell_id} at ({cell.latitude:.4f}, {cell.longitude:.4f}), {dist_km:.2f} km from the requested point.")
    print(
        f"Static shelter inputs: forest={static.forest_fraction}, urban={static.urban_fraction}, "
        f"slope={static.slope_deg} deg, coastal_exposure={static.coastal_exposure}"
        + (" [PLACEHOLDER, not real GIS data]" if static.is_placeholder else "")
    )

    weather = _fetch_weather(cell, target, args.sample, args.past_days)
    if args.observed_wind_ms is not None:
        # Overwrite the single hour nearest `target` with the observed
        # value so every downstream feature (current wind, effective wind,
        # the calm/release gates) reacts to it consistently -- a naive
        # override of just features.wind_speed_current_ms after the fact
        # would leave wind_speed_effective_ms stale (see feature_engineering
        # tests for why that matters).
        from feature_engineering import _nearest_index, _parse_times

        parsed = _parse_times(weather.times)
        idx = _nearest_index(parsed, target)
        weather.wind_speed_10m[idx] = args.observed_wind_ms
        print(f"Overriding forecast wind at {weather.times[idx]} with observed value: {args.observed_wind_ms} m/s")

    def run(config: ModelConfig, label: str) -> None:
        rolling = precompute_rolling_windows(weather, config.development_base_temperature_c)
        features = compute_features(
            static, weather, target, config.development_base_temperature_c,
            rolling=rolling,
            calm_threshold_ms=config.wind_dynamics_params.get("calm_threshold_ms", 1.8),
            wind_shelter_params=config.wind_shelter_params,
        )
        score = compute_score(features, config, args.activity)
        _print_diagnostics(label, cell, target, features, score)

    baseline_config = load_model_config()
    run(baseline_config, f"CURRENT model.yaml (v{baseline_config.version})")

    if args.candidate_config:
        candidate_config = load_model_config(Path(args.candidate_config))
        run(candidate_config, f"CANDIDATE {args.candidate_config} (v{candidate_config.version})")


if __name__ == "__main__":
    main()
