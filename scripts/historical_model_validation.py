#!/usr/bin/env python
"""Historical validation harness (calibration/validation sprint, see
docs/calibration-validation-final.md).

Runs the EXACT SAME production model code (feature_engineering.compute_features,
model.compute_score, pipeline's daypart-peak-selection logic) against REAL
historical weather from Open-Meteo's free Archive API
(weather.py::OpenMeteoArchiveProvider), for a curated set of reference
locations across a full growing season -- not a separate simplified
calibration model, and not just the current week.

Two commands:

    python scripts/historical_model_validation.py reference-series \
        --start 2025-04-01 --end 2025-09-30
        -- daily-resolution (daypart-peak, like production's daily record)
           scoring for ~18 reference cells across the given date range.
           Cheap (~18 archive requests total), used to empirically identify
           representative wet/dry/typical/snowmelt/late-season periods
           (Phase 3), biological time series (Phase 8), matched-location
           geographic contrasts (Phase 9), and contribution decomposition
           through time (Phase 7).

    python scripts/historical_model_validation.py full-grid-snapshot \
        --date 2025-06-20 --label wet_period
        -- full ~23,194-cell scoring for ONE historical date (with the
           model's real 21-day lookback window fetched before it), written
           in the same manifest/cells/daily-record shape production uses,
           so scripts/national_diagnostics.py-style analysis applies
           unchanged. Expensive (~373 archive batches) -- used sparingly,
           for specifically selected representative dates only (Phase 4/11/12/13).

All historical weather is disk-cached (data/cache/historical_weather/) keyed
by (cell_id, start_date, end_date) so repeated threshold experiments never
re-download identical data.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import _pathsetup  # noqa: F401
from config import DATA_DIR, GENERATED_DATA_DIR, STATIC_DATA_DIR, load_model_config
from feature_engineering import compute_features, precompute_rolling_windows
from grid import GridCell, load_grid
from model import compute_score
from pipeline import DAYPART_REPRESENTATIVE_HOUR, _local_daypart_target
from static_features import compute_static_features_from_rasters, load_static_features
from weather import HourlyWeather, OpenMeteoArchiveProvider

HIST_CACHE_DIR = DATA_DIR / "cache" / "historical_weather"
OUT_DIR = GENERATED_DATA_DIR / "diagnostics" / "historical"
LOOKBACK_DAYS = 21  # matches HISTORY_DAYS_BACK in pipeline.py -- the model's real rolling-window need

# --- Reference locations (Phase 8/9) -----------------------------------
# A curated ~18-location subset of forecast/benchmarks/locations.json,
# picked to cover every named example in the new spec's Phase 8/9 plus the
# matched environmental pairs Phase 9 asks for (each "vs" pair shares a
# comparison axis: urban vs. nearby wet habitat, exposed vs. sheltered,
# lowland vs. mountain at the same latitude).
REFERENCE_LOCATIONS = [
    {"name": "Stockholm centrum", "latitude": 59.3293, "longitude": 18.0686, "category": "urban"},
    {"name": "Stockholm forort (Tyreso)", "latitude": 59.2489, "longitude": 18.2286, "category": "urban suburb"},
    {"name": "Dalarna skog (Alvdalen)", "latitude": 61.2333, "longitude": 14.0667, "category": "boreal forest"},
    {"name": "Siljan strand (Rattvik)", "latitude": 60.8994, "longitude": 15.1049, "category": "lake shore"},
    {"name": "Osterfarnebo", "latitude": 60.3372, "longitude": 16.9328, "category": "floodplain (Lower Dalalven)"},
    {"name": "Malardalen jordbruksbygd (Enkoping)", "latitude": 59.6362, "longitude": 17.0777, "category": "dry farmland"},
    {"name": "Smalandsskog (Uppvidinge)", "latitude": 57.0500, "longitude": 15.3167, "category": "wet forest"},
    {"name": "Norrbotten vatmark (Muddus/Sjaunja)", "latitude": 66.9000, "longitude": 20.1000, "category": "northern wetland"},
    {"name": "Vasterbottens inland (Lycksele)", "latitude": 64.6006, "longitude": 18.6700, "category": "northern forest"},
    {"name": "Are (fjallomrade)", "latitude": 63.3989, "longitude": 13.0817, "category": "mountain"},
    {"name": "Sarek nationalpark", "latitude": 67.4500, "longitude": 17.7333, "category": "far north mountain"},
    {"name": "Bohuslan (Fjallbacka)", "latitude": 58.5992, "longitude": 11.2814, "category": "exposed coast"},
    {"name": "Varmland skog och sjo (Sunne)", "latitude": 59.8375, "longitude": 13.1428, "category": "sheltered lake"},
    {"name": "Vanern oppet vatten", "latitude": 58.9000, "longitude": 13.4000, "category": "major open lake"},
    {"name": "Vanern strand (Lidkoping)", "latitude": 58.5039, "longitude": 13.1573, "category": "lake margin"},
    {"name": "Store Mosse nationalpark", "latitude": 57.2500, "longitude": 13.9833, "category": "wetland"},
    {"name": "Kiruna lagland", "latitude": 67.7500, "longitude": 20.5000, "category": "far north lowland"},
    {"name": "Skane jordbruksbygd (Ystad)", "latitude": 55.4295, "longitude": 13.8204, "category": "farmland"},
]


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _nearest_cell(cells: list[GridCell], lat: float, lon: float) -> GridCell:
    import math
    best, best_dist = cells[0], math.inf
    cos_lat = math.cos(math.radians(lat))
    for cell in cells:
        d_lat = cell.latitude - lat
        d_lon = (cell.longitude - lon) * cos_lat
        dist = d_lat * d_lat + d_lon * d_lon
        if dist < best_dist:
            best_dist, best = dist, cell
    return best


def _cache_key(cell_id: str, start: date, end: date) -> str:
    raw = f"{cell_id}:{start.isoformat()}:{end.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _cache_path(cell_id: str, start: date, end: date) -> Path:
    return HIST_CACHE_DIR / f"{_cache_key(cell_id, start, end)}.json.gz"


def _load_cached_weather(cell_id: str, start: date, end: date) -> HourlyWeather | None:
    path = _cache_path(cell_id, start, end)
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            raw = json.load(fh)
        return HourlyWeather(**raw)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _save_cached_weather(cell_id: str, start: date, end: date, weather: HourlyWeather) -> None:
    HIST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cell_id, start, end)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(asdict(weather), fh)


def fetch_with_cache(provider: OpenMeteoArchiveProvider, cells: list[GridCell], start: date, end: date) -> dict[str, HourlyWeather]:
    results: dict[str, HourlyWeather] = {}
    to_fetch: list[GridCell] = []
    for cell in cells:
        cached = _load_cached_weather(cell.cell_id, start, end)
        if cached is not None:
            results[cell.cell_id] = cached
        else:
            to_fetch.append(cell)
    if to_fetch:
        print(f"Fetching {len(to_fetch)}/{len(cells)} cells from Open-Meteo archive "
              f"({start} to {end}); {len(cells) - len(to_fetch)} already cached.")
        fresh = provider.fetch_range(to_fetch, start, end)
        for cell_id, weather in fresh.items():
            results[cell_id] = weather
            _save_cached_weather(cell_id, start, end, weather)
    return results


def _daily_peak_record(static, weather: HourlyWeather, target_date: date, config, rolling) -> dict:
    """Mirrors pipeline.py's daily loop exactly: score every daypart's
    representative local hour, take the peak, return its full feature/score
    breakdown -- the SAME logic production uses to build a daily record."""
    dayparts = {}
    for part, hour in DAYPART_REPRESENTATIVE_HOUR.items():
        target = _local_daypart_target(target_date, hour)
        features = compute_features(
            static, weather, target, config.development_base_temperature_c, rolling=rolling,
            calm_threshold_ms=config.wind_dynamics_params.get("calm_threshold_ms", 1.8),
            wind_shelter_params=config.wind_shelter_params,
            pressure_survival_daily=config.mosquito_pressure_params.get("pressure_survival_daily", 0.90),
            pressure_lookback_days=int(config.mosquito_pressure_params.get("pressure_lookback_days", 21)),
        )
        score = compute_score(features, config, "general")
        dayparts[part] = {"features": features, "score": score}
    peak_part = max(dayparts, key=lambda p: dayparts[p]["score"].final_risk)
    peak = dayparts[peak_part]
    f, s = peak["features"], peak["score"]
    return {
        "date": target_date.isoformat(),
        "peak_period": peak_part,
        "habitat_capacity": f.habitat_capacity,
        "mosquito_pressure": f.mosquito_pressure,
        "population_potential": s.population_potential,
        "biting_activity": s.biting_activity,
        "exposure": s.exposure,
        "final_risk": s.final_risk,
        "current_temperature_c": f.current_temperature_c,
        "mean_temperature_14d_c": f.mean_temperature_14d_c,
        "precipitation_14d_mm": f.precipitation_14d_mm,
        "precipitation_3d_mm": f.precipitation_3d_mm,
        "days_since_meaningful_rain": f.days_since_meaningful_rain,
        "pop_term_pressure": s.population_terms.get("pressure"),
        "pop_term_habitat_capacity": s.population_terms.get("habitat_capacity"),
        "pop_term_temperature": s.population_terms.get("temperature"),
        "pop_term_season": s.population_terms.get("season"),
        "pressure_used_real_snow_data": f.pressure_used_real_snow_data,
    }


def cmd_reference_series(args: argparse.Namespace) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    fetch_start = start - timedelta(days=LOOKBACK_DAYS)

    grid_cells = load_grid(STATIC_DATA_DIR / "grid.json")
    config = load_model_config()

    # --locations lets this reuse the full 55-location national benchmark
    # (forecast/benchmarks/locations.json) instead of the 18-location
    # REFERENCE_LOCATIONS default -- adopted mid-sprint after Open-Meteo's
    # Archive API turned out to rate-limit hard even at a ~2,300-cell
    # spatial subsample of the full grid (see docs/calibration-validation-
    # final.md "Historical periods tested" for the full reasoning). One
    # archive request per LOCATION (not per cell-batch) scales far better:
    # 55 requests total for the whole season, vs. hundreds of batched
    # requests for any full-grid attempt, while still giving real multi-
    # regime, multi-location evidence -- combined with the already-
    # completed real full-grid dry-week snapshot for genuine full-Sweden
    # spatial coverage on at least one regime.
    locations = REFERENCE_LOCATIONS
    if args.locations:
        raw = _load_json(Path(args.locations))
        locations = [{"name": r["name"], "latitude": r["latitude"], "longitude": r["longitude"],
                      "category": r.get("category", "")} for r in raw]

    matched = {loc["name"]: _nearest_cell(grid_cells, loc["latitude"], loc["longitude"]) for loc in locations}
    fetch_cells = list({c.cell_id: c for c in matched.values()}.values())
    # Live-computed static features for just these reference cells (fast)
    # rather than the cached data/static/cell_features.json -- keeps this
    # command always current with the latest static_features.py logic
    # without needing a full ~23k-cell regeneration for every calibration
    # iteration.
    static_map_all = {f.cell_id: f for f in compute_static_features_from_rasters(fetch_cells, STATIC_DATA_DIR)}

    provider = OpenMeteoArchiveProvider(pacing_s=args.pacing)
    weather_by_cell = fetch_with_cache(provider, fetch_cells, fetch_start, end)

    rows = []
    n_days = (end - start).days + 1
    for loc in locations:
        cell = matched[loc["name"]]
        weather = weather_by_cell.get(cell.cell_id)
        static = static_map_all.get(cell.cell_id)
        if weather is None or static is None:
            print(f"SKIP {loc['name']}: missing weather or static features")
            continue
        rolling = precompute_rolling_windows(weather, config.development_base_temperature_c)
        for day_offset in range(n_days):
            target_date = start + timedelta(days=day_offset)
            record = _daily_peak_record(static, weather, target_date, config, rolling)
            record["name"] = loc["name"]
            record["category"] = loc["category"]
            record["latitude"] = loc["latitude"]
            record["longitude"] = loc["longitude"]
            record["cell_id"] = cell.cell_id
            rows.append(record)
        print(f"Scored {loc['name']}: {n_days} days")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "-full55" if args.locations else ""
    out_path = OUT_DIR / f"reference-series{suffix}-{start.isoformat()}-{end.isoformat()}.json"
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=None), encoding="utf-8")
    print(f"\nWrote {len(rows)} location-days to {out_path}")


def cmd_full_grid_snapshot(args: argparse.Namespace) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    target_date = date.fromisoformat(args.date)
    fetch_start = target_date - timedelta(days=LOOKBACK_DAYS)

    all_cells = load_grid(STATIC_DATA_DIR / "grid.json")
    cells = all_cells[:: args.sample_every_nth] if args.sample_every_nth > 1 else all_cells
    static_map = load_static_features(STATIC_DATA_DIR / "cell_features.json")
    config = load_model_config()

    # Open-Meteo's Archive API rate-limits aggressively at literal full-grid
    # (~373-batch) scale (confirmed live: sustained HTTP 429s even with the
    # existing 30s rate-limit backoff -- consistent with the README's
    # documented history of full-grid Open-Meteo scaling problems, which is
    # exactly why SMHI is production's default provider; SMHI has no
    # historical/archive product at all, see smhi_weather.py). Historical
    # full-grid snapshots therefore use BOTH a denser request pacing and (by
    # default, see --sample-every-nth) a systematic spatial subsample rather
    # than literally every cell -- a deliberate, documented sampling
    # decision (see docs/calibration-validation-final.md "Historical
    # periods tested"), not a workaround being silently hidden.
    provider = OpenMeteoArchiveProvider(pacing_s=5.0)
    print(f"Fetching {fetch_start} to {target_date} for {len(cells)}/{len(all_cells)} cells "
          f"(every {args.sample_every_nth} cell(s), label={args.label})...")
    weather_by_cell = fetch_with_cache(provider, cells, fetch_start, target_date)
    print(f"Weather ready for {len(weather_by_cell)}/{len(cells)} cells; scoring...")

    rows = []
    for i, cell in enumerate(cells):
        weather = weather_by_cell.get(cell.cell_id)
        static = static_map.get(cell.cell_id)
        if weather is None or static is None:
            continue
        rolling = precompute_rolling_windows(weather, config.development_base_temperature_c)
        record = _daily_peak_record(static, weather, target_date, config, rolling)
        record["cell_id"] = cell.cell_id
        record["latitude"] = cell.latitude
        record["longitude"] = cell.longitude
        record["region"] = cell.region
        record["urban_fraction"] = static.urban_fraction
        record["wetland_fraction"] = static.wetland_fraction
        record["forest_fraction"] = static.forest_fraction
        record["elevation_m"] = static.elevation_m
        record["small_water_density"] = static.small_water_density
        record["major_lake_interior"] = static.major_lake_interior
        rows.append(record)
        if (i + 1) % 4000 == 0:
            print(f"  scored {i + 1}/{len(cells)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"full-grid-{args.label}-{target_date.isoformat()}.json.gz"
    with gzip.open(out_path, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False)
    print(f"\nWrote {len(rows)} cells to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("reference-series")
    p1.add_argument("--start", required=True)
    p1.add_argument("--end", required=True)
    p1.add_argument("--locations", default=None, help="Path to a locations JSON (name/latitude/longitude/category); default is the built-in 18-location REFERENCE_LOCATIONS")
    p1.add_argument("--pacing", type=float, default=2.0)
    p1.set_defaults(func=cmd_reference_series)

    p2 = sub.add_parser("full-grid-snapshot")
    p2.add_argument("--date", required=True)
    p2.add_argument("--label", required=True)
    p2.add_argument(
        "--sample-every-nth", type=int, default=10,
        help="Use every Nth grid cell (systematic spatial subsample) instead of the literal full "
        "grid, to stay under Open-Meteo Archive API rate limits. Default 10 (~2,319 cells, full "
        "national coverage at ~16km effective spacing). Pass 1 for the literal full grid.",
    )
    p2.set_defaults(func=cmd_full_grid_snapshot)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
