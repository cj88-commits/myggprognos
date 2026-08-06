#!/usr/bin/env python
"""Full-Sweden distributional diagnostics for the wind-calm model change.

Runs the CURRENT model.yaml, and optionally one or more CANDIDATE configs,
against a representative random sample of the real full-Sweden grid (real
static forest/wetland/urban/slope/coastal features from
data/static/cell_features.json), under four controlled wind scenarios
evaluated at the same evening hour:

    baseline    the weather provider's own (unmodified) synthetic wind
    calm        wind forced to ~1 m/s for the preceding ~6h, steady
    windy       wind forced to ~6 m/s for the preceding ~6h, steady
    wind_drop   wind forced to ~5 m/s, then drops to ~1 m/s for the last ~2h

Uses SyntheticWeatherProvider rather than live weather, specifically so
temperature/humidity/population diversity stays realistic and season-
appropriate while wind is deliberately controlled per scenario -- a live
full-Sweden fetch (~18k cells) is impractical to run repeatedly for this
kind of A/B comparison, and controlled scenarios are what the specific
comparisons below actually need.

Usage:
    python scripts/diagnose_wind_distribution.py --sample-size 3000
    python scripts/diagnose_wind_distribution.py --sample-size 3000 \\
        --candidate-configs forecast/model_candidate_a.yaml forecast/model_candidate_b.yaml
"""
from __future__ import annotations

import argparse
import random
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import _pathsetup  # noqa: F401
from config import STATIC_DATA_DIR, ModelConfig, load_model_config
from feature_engineering import _nearest_index, _parse_times, compute_features, precompute_rolling_windows
from grid import GridCell, load_grid
from model import compute_score, risk_category
from static_features import generate_placeholder_static_features, load_static_features
from weather import HourlyWeather, SyntheticWeatherProvider

BENCHMARKS = [
    ("Stockholm (urban)", 59.3293, 18.0686),
    ("Kolmarden (wetland-adjacent)", 58.6900, 16.1200),
    ("Gothenburg (coastal)", 57.7089, 11.9746),
    ("Lulea (north)", 65.5848, 22.1567),
]

EVENING_HOUR_UTC = 18  # ~20:00 local (CEST) in Swedish summer -- dusk-ish
SCENARIOS = ["baseline", "calm", "windy", "wind_drop"]
CATEGORY_ORDER = ["very_low", "low", "moderate", "high", "very_high"]


def _nearest_cell(cells: list[GridCell], lat: float, lon: float) -> GridCell:
    import math

    def dist2(c: GridCell) -> float:
        lon_scale = math.cos(math.radians(lat))
        return (c.latitude - lat) ** 2 + ((c.longitude - lon) * lon_scale) ** 2

    return min(cells, key=dist2)


def _sample_cells(cells: list[GridCell], sample_size: int, seed: int = 42) -> list[GridCell]:
    if sample_size >= len(cells):
        return cells
    rng = random.Random(seed)
    return rng.sample(cells, sample_size)


def _scenario_weather(base: HourlyWeather, eval_idx: int, scenario: str) -> HourlyWeather:
    if scenario == "baseline":
        return base
    wind = list(base.wind_speed_10m)
    n = len(wind)
    if scenario == "calm":
        for i in range(max(0, eval_idx - 6), min(n, eval_idx + 1)):
            wind[i] = 1.0
    elif scenario == "windy":
        for i in range(max(0, eval_idx - 6), min(n, eval_idx + 1)):
            wind[i] = 6.0
    elif scenario == "wind_drop":
        for i in range(max(0, eval_idx - 6), min(n, max(0, eval_idx - 1))):
            wind[i] = 5.0
        for i in range(max(0, eval_idx - 1), min(n, eval_idx + 1)):
            wind[i] = 1.0
    else:
        raise ValueError(scenario)
    return HourlyWeather(
        cell_id=base.cell_id, latitude=base.latitude, longitude=base.longitude, times=base.times,
        temperature_2m=base.temperature_2m, relative_humidity_2m=base.relative_humidity_2m,
        precipitation=base.precipitation, wind_speed_10m=wind, wind_gusts_10m=base.wind_gusts_10m,
        cloud_cover=base.cloud_cover, soil_moisture=base.soil_moisture, used_fallback=base.used_fallback,
    )


def _score(static, weather: HourlyWeather, target: datetime, config: ModelConfig) -> tuple[float, str]:
    rolling = precompute_rolling_windows(weather, config.development_base_temperature_c)
    features = compute_features(
        static, weather, target, config.development_base_temperature_c, rolling=rolling,
        calm_threshold_ms=config.wind_dynamics_params.get("calm_threshold_ms", 1.8),
        wind_shelter_params=config.wind_shelter_params,
    )
    score = compute_score(features, config, "general")
    key, _label = risk_category(score.final_risk)
    return score.final_risk, key


def _pct_table(counter: Counter, total: int) -> str:
    return "  ".join(f"{k}={100 * counter.get(k, 0) / total:.1f}%" for k in CATEGORY_ORDER)


def run(sample_size: int, candidate_paths: list[str], date_str: str) -> None:
    cells = load_grid(STATIC_DATA_DIR / "grid.json")
    static_map = load_static_features(STATIC_DATA_DIR / "cell_features.json")
    for c in cells:
        if c.cell_id not in static_map:
            static_map[c.cell_id] = generate_placeholder_static_features(c)

    sample = _sample_cells(cells, sample_size)
    benchmark_cells = [(name, _nearest_cell(cells, lat, lon)) for name, lat, lon in BENCHMARKS]
    for name, cell in benchmark_cells:
        if cell.cell_id not in {c.cell_id for c in sample}:
            sample.append(cell)
    print(f"Sample: {len(sample)} real grid cells (of {len(cells)} total), evaluated {date_str} ~evening (UTC hour {EVENING_HOUR_UTC}).")

    target_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
    target = target_date.replace(hour=EVENING_HOUR_UTC)

    provider = SyntheticWeatherProvider(today=target_date)
    weather_by_cell = provider.fetch_combined(sample, past_days=10, forecast_days=1)

    configs: dict[str, ModelConfig] = {"current": load_model_config()}
    for path in candidate_paths:
        configs[Path(path).stem] = load_model_config(Path(path))

    # results[config][scenario][cell_id] = (risk, category)
    results: dict[str, dict[str, dict[str, tuple[float, str]]]] = {
        cfg: {s: {} for s in SCENARIOS} for cfg in configs
    }

    for i, cell in enumerate(sample):
        base_weather = weather_by_cell[cell.cell_id]
        parsed = _parse_times(base_weather.times)
        eval_idx = _nearest_index(parsed, target)
        static = static_map[cell.cell_id]

        for scenario in SCENARIOS:
            weather = _scenario_weather(base_weather, eval_idx, scenario)
            for cfg_name, cfg in configs.items():
                results[cfg_name][scenario][cell.cell_id] = _score(static, weather, target, cfg)

        if (i + 1) % 1000 == 0:
            print(f"  ...{i + 1}/{len(sample)} cells scored")

    n = len(sample)

    print("\n" + "=" * 70)
    print("1) CATEGORY DISTRIBUTION per scenario, per config")
    print("=" * 70)
    for cfg_name in configs:
        print(f"\n-- config: {cfg_name} --")
        for scenario in SCENARIOS:
            counts = Counter(cat for _r, cat in results[cfg_name][scenario].values())
            print(f"  {scenario:10s}  {_pct_table(counts, n)}")

    print("\n" + "=" * 70)
    print("2) EXTREME-SCORE FREQUENCY (final_risk >= 90) per scenario, per config")
    print("   (safety check: calm weather alone must not saturate the map)")
    print("=" * 70)
    for cfg_name in configs:
        for scenario in SCENARIOS:
            extreme = sum(1 for r, _ in results[cfg_name][scenario].values() if r >= 90.0)
            print(f"  {cfg_name:10s} / {scenario:10s}: {100 * extreme / n:.2f}% of cells >= 90")

    print("\n" + "=" * 70)
    print("3) CELLS CHANGING CATEGORY: windy -> calm (current config)")
    print("=" * 70)
    windy = results["current"]["windy"]
    calm = results["current"]["calm"]
    changed = sum(1 for cid in windy if windy[cid][1] != calm[cid][1])
    print(f"  {changed}/{n} cells ({100 * changed / n:.1f}%) change category between windy (6 m/s) and calm (1 m/s).")

    print("\n" + "=" * 70)
    print("4) SCORE CHANGE AFTER A RAPID WIND DROP (windy -> wind_drop), per config")
    print("=" * 70)
    for cfg_name in configs:
        windy_r = results[cfg_name]["windy"]
        drop_r = results[cfg_name]["wind_drop"]
        deltas = [drop_r[cid][0] - windy_r[cid][0] for cid in windy_r]
        print(
            f"  {cfg_name:10s}: mean +{statistics.mean(deltas):.1f}, median +{statistics.median(deltas):.1f}, "
            f"p90 +{sorted(deltas)[int(0.9 * len(deltas))]:.1f}, max +{max(deltas):.1f}"
        )

    if len(configs) > 1:
        print("\n" + "=" * 70)
        print("5) IMPACT OF THE MODEL CHANGE ITSELF (candidate vs current, same scenario)")
        print("   proportion of sampled cells shifted by >10/20/30 points")
        print("=" * 70)
        for cfg_name in configs:
            if cfg_name == "current":
                continue
            for scenario in SCENARIOS:
                cur = results["current"][scenario]
                cand = results[cfg_name][scenario]
                deltas = [abs(cand[cid][0] - cur[cid][0]) for cid in cur]
                over10 = sum(1 for d in deltas if d > 10) / n
                over20 = sum(1 for d in deltas if d > 20) / n
                over30 = sum(1 for d in deltas if d > 30) / n
                print(
                    f"  {cfg_name:10s} / {scenario:10s}: >10pt {100*over10:.1f}%  >20pt {100*over20:.1f}%  >30pt {100*over30:.1f}%"
                )

    print("\n" + "=" * 70)
    print("6) BENCHMARK LOCATIONS")
    print("=" * 70)
    for name, cell in benchmark_cells:
        print(f"\n-- {name} ({cell.cell_id}) --")
        for cfg_name in configs:
            row = "  ".join(f"{s}={results[cfg_name][s][cell.cell_id][0]:.1f}({results[cfg_name][s][cell.cell_id][1]})" for s in SCENARIOS)
            print(f"  {cfg_name:10s}: {row}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample-size", type=int, default=3000)
    parser.add_argument("--candidate-configs", nargs="*", default=[])
    parser.add_argument("--date", type=str, default="2026-07-20")
    args = parser.parse_args()
    run(args.sample_size, args.candidate_configs, args.date)


if __name__ == "__main__":
    main()
