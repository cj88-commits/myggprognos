#!/usr/bin/env python
"""Geographic diagnostic benchmark (Phase 2/9 of the geography redesign).

Unlike scripts/run_benchmarks.py (which reads already-published daily/hourly
JSON and only exposes the handful of fields written there), this script
computes every location fresh, directly from the real static features
(data/static/cell_features.json) and a real live weather fetch for exactly
the benchmark cells -- so it can expose every raw/derived feature the model
actually computes (habitat/water/terrain statics, emergence/standing-water,
population/activity/exposure/risk sub-scores), not just what happens to be
serialized to the public output files.

Every location uses the SAME "now" instant, so any remaining difference
between e.g. Stockholm and a Dalarna forest cell is attributable to geography
and slow-moving weather history, not to different points in time.

Usage:
    python scripts/geographic_benchmark.py --label before
    python scripts/geographic_benchmark.py --label after
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import _pathsetup  # noqa: F401
from config import STATIC_DATA_DIR, GENERATED_DATA_DIR, load_model_config
from feature_engineering import compute_features, precompute_rolling_windows
from grid import GridCell, load_grid
from model import compute_score
from static_features import compute_static_features_from_rasters, load_static_features
from weather import OpenMeteoProvider

BENCHMARKS_DIR = Path(__file__).resolve().parents[1] / "forecast" / "benchmarks"
DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"

HISTORY_DAYS_BACK = 21
FORECAST_DAYS = 7

# Contrast pairs of interest for the write-up (Phase 9): (label, location
# name that should score HIGHER, location name that should score LOWER).
# Names must match forecast/benchmarks/locations.json exactly.
CONTRAST_PAIRS = [
    ("Dalarna skog / Stockholm centrum", "Dalarna skog (Alvdalen)", "Stockholm centrum"),
    ("Siljan strand / Stockholm centrum", "Siljan strand (Rattvik)", "Stockholm centrum"),
    ("Osterfarnebo (Lower Dalalven) / Stockholm centrum", "Osterfarnebo", "Stockholm centrum"),
    ("Norrbotten vat barrskog / Stockholm centrum", "Norrbotten vat barrskog (Jokkmokk)", "Stockholm centrum"),
    ("Norrbotten vatmark / Harjedalen fjall", "Norrbotten vatmark (Muddus/Sjaunja)", "Harjedalen fjall (Funasdalen)"),
    ("Vanern strand / Vanern oppet vatten", "Vanern strand (Lidkoping)", "Vanern oppet vatten"),
    ("Store Mosse (wetland) / Malardalen jordbruksbygd (farmland)", "Store Mosse nationalpark", "Malardalen jordbruksbygd (Enkoping)"),
    ("Vasterbottens inland (forest) / Stockholm centrum", "Vasterbottens inland (Lycksele)", "Stockholm centrum"),
    ("Bohuslan (exposed coast) / Varmland skog och sjo (sheltered lake)", "Varmland skog och sjo (Sunne, Frykensjoarna)", "Bohuslan (Fjallbacka)"),
]


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _nearest_cell(cells: list[GridCell], lat: float, lon: float) -> GridCell:
    """Mirrors scripts/run_benchmarks.py::_nearest_cell / frontend nearestCell."""
    best = cells[0]
    best_dist = math.inf
    cos_lat = math.cos(math.radians(lat))
    for cell in cells:
        d_lat = cell.latitude - lat
        d_lon = (cell.longitude - lon) * cos_lat
        dist = d_lat * d_lat + d_lon * d_lon
        if dist < best_dist:
            best_dist = dist
            best = cell
    return best


ROW_FIELDS = [
    "name", "category", "latitude", "longitude", "matched_cell_id", "matched_region",
    "forest_fraction", "wetland_fraction", "water_fraction", "water_body_density",
    "urban_fraction", "distance_to_water_km", "slope_deg", "elevation_m",
    "coastal_exposure", "is_placeholder",
    "current_temperature_c", "mean_temperature_14d_c",
    "precipitation_14d_mm", "precipitation_21d_mm", "days_since_meaningful_rain",
    "soil_moisture_7d_mean", "standing_water_persistence", "emergence_potential",
    "seasonal_suitability", "wind_speed_effective_ms",
    "population_potential", "biting_activity", "exposure", "final_risk",
    "pop_term_temperature", "pop_term_rainfall", "pop_term_moisture", "pop_term_wetland",
    "pop_term_forest", "pop_term_season", "pop_term_snowmelt", "pop_term_standing_water",
]


def build_rows(
    locations: list[dict], cells: list[GridCell], static_map: dict, run_time: datetime, live_static: bool = True
) -> list[dict]:
    config = load_model_config()

    matched: dict[str, GridCell] = {}
    for loc in locations:
        matched[loc["name"]] = _nearest_cell(cells, loc["latitude"], loc["longitude"])

    fetch_cells = list({c.cell_id: c for c in matched.values()}.values())

    if live_static:
        # Compute static features fresh, directly from the real raster
        # tiles, for exactly the matched cells -- avoids depending on
        # data/static/cell_features.json being up to date (a full-grid
        # regeneration is a ~18.6k-cell, multi-minute-to-hours batch job;
        # this benchmark only needs the handful of cells the 55 locations
        # actually match to, so it's both faster and always current).
        print(f"Computing static features live for {len(fetch_cells)} distinct matched cells...")
        live_features = compute_static_features_from_rasters(fetch_cells, STATIC_DATA_DIR)
        static_map = {f.cell_id: f for f in live_features}

    print(f"Fetching real weather for {len(fetch_cells)} distinct matched cells ({len(locations)} locations)...")
    provider = OpenMeteoProvider()
    weather_by_cell = provider.fetch_combined(fetch_cells, HISTORY_DAYS_BACK, FORECAST_DAYS)

    rows = []
    for loc in locations:
        cell = matched[loc["name"]]
        weather = weather_by_cell.get(cell.cell_id)
        static = static_map.get(cell.cell_id)
        row: dict[str, Any] = {
            "name": loc["name"], "category": loc["category"],
            "latitude": loc["latitude"], "longitude": loc["longitude"],
            "matched_cell_id": cell.cell_id, "matched_region": cell.region,
        }
        if weather is None or static is None:
            row["error"] = "missing weather or static features for matched cell"
            rows.append(row)
            continue

        rolling = precompute_rolling_windows(weather, config.development_base_temperature_c)
        features = compute_features(
            static, weather, run_time, config.development_base_temperature_c,
            rolling=rolling,
            calm_threshold_ms=config.wind_dynamics_params.get("calm_threshold_ms", 1.8),
            wind_shelter_params=config.wind_shelter_params,
        )
        score = compute_score(features, config, "general")

        row.update({
            "forest_fraction": static.forest_fraction,
            "wetland_fraction": static.wetland_fraction,
            "water_fraction": static.water_fraction,
            "water_body_density": static.water_body_density,
            "urban_fraction": static.urban_fraction,
            "distance_to_water_km": static.distance_to_water_km,
            "slope_deg": static.slope_deg,
            "elevation_m": static.elevation_m,
            "coastal_exposure": static.coastal_exposure,
            "is_placeholder": static.is_placeholder,
            "current_temperature_c": features.current_temperature_c,
            "mean_temperature_14d_c": features.mean_temperature_14d_c,
            "precipitation_14d_mm": features.precipitation_14d_mm,
            "precipitation_21d_mm": features.precipitation_21d_mm,
            "days_since_meaningful_rain": features.days_since_meaningful_rain,
            "soil_moisture_7d_mean": features.soil_moisture_7d_mean,
            "standing_water_persistence": features.standing_water_persistence,
            "emergence_potential": features.emergence_potential,
            "seasonal_suitability": features.seasonal_suitability,
            "wind_speed_effective_ms": features.wind_speed_effective_ms,
            "population_potential": score.population_potential,
            "biting_activity": score.biting_activity,
            "exposure": score.exposure,
            "final_risk": score.final_risk,
        })
        for k, v in score.population_terms.items():
            row[f"pop_term_{k}"] = v
        rows.append(row)

    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    fields = list(ROW_FIELDS)
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _by_name(rows: list[dict]) -> dict[str, dict]:
    return {r["name"]: r for r in rows}


def render_markdown(rows: list[dict], run_time: datetime, label: str) -> str:
    by_name = _by_name(rows)
    lines = [
        f"# Geographic benchmark — {label}",
        "",
        f"Computed fresh at `{run_time.isoformat()}` from real static features "
        f"(`data/static/cell_features.json`) and a live weather fetch for {len(rows)} benchmark "
        "locations (`forecast/benchmarks/locations.json`), all evaluated at the same instant so "
        "differences are attributable to geography/weather-history, not time-of-day. Full data: "
        f"`data/generated/diagnostics/geographic-benchmark-{label}.csv`.",
        "",
        "## Contrast pairs",
        "",
        "No target ratios are hard-coded here (per spec) -- these numbers are reported as evidence, "
        "not asserted against a threshold.",
        "",
        "| Contrast | Higher-expected location | population_potential | Lower-expected location | population_potential | ratio | final_risk ratio |",
        "|---|---|---|---|---|---|---|",
    ]
    for label_txt, hi_name, lo_name in CONTRAST_PAIRS:
        hi = by_name.get(hi_name)
        lo = by_name.get(lo_name)
        if not hi or not lo or "error" in hi or "error" in lo:
            lines.append(f"| {label_txt} | {hi_name} | ERROR | {lo_name} | ERROR | - | - |")
            continue
        pop_ratio = hi["population_potential"] / lo["population_potential"] if lo["population_potential"] else float("inf")
        risk_ratio = hi["final_risk"] / lo["final_risk"] if lo["final_risk"] else float("inf")
        lines.append(
            f"| {label_txt} | {hi_name} | {hi['population_potential']:.1f} | {lo_name} | "
            f"{lo['population_potential']:.1f} | {pop_ratio:.2f}x | {risk_ratio:.2f}x |"
        )

    pop_values = [r["population_potential"] for r in rows if "error" not in r]
    risk_values = [r["final_risk"] for r in rows if "error" not in r]

    def _stats(values: list[float]) -> str:
        if not values:
            return "n/a"
        s = sorted(values)
        n = len(s)
        return (
            f"min {s[0]:.1f}, p25 {s[n // 4]:.1f}, median {s[n // 2]:.1f}, "
            f"p75 {s[3 * n // 4]:.1f}, max {s[-1]:.1f}, mean {sum(s) / n:.1f}"
        )

    lines += [
        "",
        "## Distribution across all benchmark locations",
        "",
        f"- `population_potential` (Myggläge): {_stats(pop_values)}",
        f"- `final_risk` (Myggrisk, this instant): {_stats(risk_values)}",
        "",
        "## Full table",
        "",
        "| Location | Category | forest | wetland | water | urban | dist_water_km | elevation_m | "
        "pop_potential | activity | exposure | final_risk |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['name']} | {r['category']} | ERROR: {r['error']} |")
            continue
        lines.append(
            f"| {r['name']} | {r['category']} | {r['forest_fraction']:.2f} | {r['wetland_fraction']:.2f} | "
            f"{r['water_fraction']:.2f} | {r['urban_fraction']:.2f} | {r['distance_to_water_km']:.1f} | "
            f"{r['elevation_m']:.0f} | {r['population_potential']:.1f} | {r['biting_activity']:.1f} | "
            f"{r['exposure']:.1f} | {r['final_risk']:.1f} |"
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="before", help="'before' or 'after' -- controls output filenames")
    parser.add_argument("--locations", type=Path, default=BENCHMARKS_DIR / "locations.json")
    parser.add_argument("--out-dir", type=Path, default=GENERATED_DATA_DIR / "diagnostics")
    parser.add_argument("--docs-dir", type=Path, default=DOCS_DIR)
    parser.add_argument(
        "--use-cached-static", action="store_true",
        help="Use data/static/cell_features.json as-is instead of recomputing static features live "
        "from raster tiles for the matched cells (faster, but only correct if the cache is current).",
    )
    args = parser.parse_args()

    locations = _load_json(args.locations)
    cells = load_grid(STATIC_DATA_DIR / "grid.json")
    static_map = load_static_features(STATIC_DATA_DIR / "cell_features.json") if args.use_cached_static else {}
    run_time = datetime.now(timezone.utc)

    rows = build_rows(locations, cells, static_map, run_time, live_static=not args.use_cached_static)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / f"geographic-benchmark-{args.label}.csv"
    write_csv(rows, csv_path)

    markdown = render_markdown(rows, run_time, args.label)
    doc_path = args.docs_dir / f"geographic-benchmark-{args.label}.md"
    doc_path.write_text(markdown, encoding="utf-8")

    print(markdown[:6000])
    print(f"\n... CSV written to {csv_path}")
    print(f"... full report written to {doc_path}")


if __name__ == "__main__":
    main()
