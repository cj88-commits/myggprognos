#!/usr/bin/env python
"""National before/after diagnostics for the geographic-model redesign
(Phase 9/15 follow-up, run against the ACTUAL full ~23,194-cell dataset,
not a location sample).

Compares:
    OLD: data/generated/latest              (pre-redesign, committed production data)
    NEW: data/generated/latest_new_geo_model (post-redesign, freshly generated)

Produces:
    - National distributions (habitat_capacity, mosquito_pressure, Myggläge, Myggrisk)
    - Old vs new spatial variance (std, coefficient of variation)
    - Top/bottom 100 cells by habitat_capacity and by population_potential
    - Top 100 cells by largest old->new population_potential change
    - Region contrasts (Stockholm/Dalarna/Lower Dalälven/Norrland/mountain/urban/lake-margin)
    - Habitat double-counting ablation (direct habitat_capacity term vs its
      indirect amplification through mosquito_pressure)

Usage:
    python scripts/national_diagnostics.py
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from typing import Any

import _pathsetup  # noqa: F401
from config import GENERATED_DATA_DIR, load_model_config

OLD_DIR = GENERATED_DATA_DIR / "latest"
NEW_DIR = GENERATED_DATA_DIR / "latest_new_geo_model"
OUT_DIR = GENERATED_DATA_DIR / "diagnostics"


def _load_gz(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    s = sorted(values)
    n = len(s)
    mean = sum(s) / n
    variance = sum((v - mean) ** 2 for v in s) / n
    std = variance**0.5
    return {
        "min": s[0], "p10": s[int(n * 0.10)], "p25": s[n // 4], "median": s[n // 2],
        "p75": s[3 * n // 4], "p90": s[int(n * 0.90)], "max": s[-1],
        "mean": mean, "std": std, "cv": (std / mean) if mean else 0.0, "n": n,
    }


REGIONS = {
    "Stockholm": (59.20, 59.50, 17.80, 18.30, None),
    "Dalarna": (60.30, 61.50, 13.00, 15.50, None),
    "Lower Dalalven": (60.20, 60.70, 16.50, 17.70, None),
    "Norrland (lat>=63.5)": (63.50, 69.10, 10.90, 24.20, None),
    "Mountain (fjallen)": (62.00, 69.00, 12.00, 16.00, "elevation_gt_600"),
    "Urban (urban_fraction>0.4)": (55.20, 69.10, 10.90, 24.20, "urban_gt_0.4"),
    "Lake margin (small_water top quartile, not major-lake-interior)": (55.20, 69.10, 10.90, 24.20, "lake_margin"),
}


def build_report() -> dict[str, Any]:
    old_manifest = _load_json(OLD_DIR / "manifest.json")
    new_manifest = _load_json(NEW_DIR / "manifest.json")

    old_cells = {c["cell_id"]: c for c in _load_gz(OLD_DIR / "cells.json.gz")}
    new_cells = {c["cell_id"]: c for c in _load_gz(NEW_DIR / "cells.json.gz")}

    old_daily = {r["cell_id"]: r for r in _load_gz(OLD_DIR / old_manifest["daily_files"][0])}
    new_daily = {r["cell_id"]: r for r in _load_gz(NEW_DIR / new_manifest["daily_files"][0])}

    common_ids = sorted(set(old_daily) & set(new_daily) & set(old_cells) & set(new_cells))
    print(f"Common cells: {len(common_ids)} (old {len(old_daily)}, new {len(new_daily)})")

    rows = []
    for cid in common_ids:
        oc, nc = old_cells[cid], new_cells[cid]
        od, nd = old_daily[cid], new_daily[cid]
        rows.append({
            "cell_id": cid,
            "latitude": nc["latitude"], "longitude": nc["longitude"], "region": nc.get("region"),
            "elevation_m": nc.get("elevation_m"),
            "urban_fraction": nc.get("urban_fraction"),
            "habitat_capacity": nc.get("habitat_capacity"),
            "small_water_density": nc.get("small_water_density"),
            "major_lake_interior": nc.get("major_lake_interior"),
            "old_population_potential": od["population_potential"],
            "new_population_potential": nd["population_potential"],
            "old_final_risk": od.get("daily_peak_risk", od["risk"]),
            "new_final_risk": nd.get("daily_peak_risk", nd["risk"]),
            "new_mosquito_pressure": nd.get("mosquito_pressure"),
            "new_habitat_capacity": nd.get("habitat_capacity"),
        })

    # --- Distributions ---
    dist = {
        "habitat_capacity_new": _stats([r["habitat_capacity"] for r in rows if r["habitat_capacity"] is not None]),
        "mosquito_pressure_new": _stats([r["new_mosquito_pressure"] for r in rows if r["new_mosquito_pressure"] is not None]),
        "population_potential_old": _stats([r["old_population_potential"] for r in rows]),
        "population_potential_new": _stats([r["new_population_potential"] for r in rows]),
        "final_risk_old": _stats([r["old_final_risk"] for r in rows]),
        "final_risk_new": _stats([r["new_final_risk"] for r in rows]),
    }

    # --- Spatial variance old vs new ---
    variance_comparison = {
        "population_potential": {
            "old_std": dist["population_potential_old"]["std"], "new_std": dist["population_potential_new"]["std"],
            "old_cv": dist["population_potential_old"]["cv"], "new_cv": dist["population_potential_new"]["cv"],
            "old_range": dist["population_potential_old"]["max"] - dist["population_potential_old"]["min"],
            "new_range": dist["population_potential_new"]["max"] - dist["population_potential_new"]["min"],
        },
        "final_risk": {
            "old_std": dist["final_risk_old"]["std"], "new_std": dist["final_risk_new"]["std"],
            "old_cv": dist["final_risk_old"]["cv"], "new_cv": dist["final_risk_new"]["cv"],
            "old_range": dist["final_risk_old"]["max"] - dist["final_risk_old"]["min"],
            "new_range": dist["final_risk_new"]["max"] - dist["final_risk_new"]["min"],
        },
    }

    # --- Top/bottom 100 ---
    by_habitat = sorted(rows, key=lambda r: r["habitat_capacity"])
    top_habitat = list(reversed(by_habitat[-100:]))
    bottom_habitat = by_habitat[:100]

    by_pop_new = sorted(rows, key=lambda r: r["new_population_potential"])
    top_pop = list(reversed(by_pop_new[-100:]))
    bottom_pop = by_pop_new[:100]

    for r in rows:
        r["pop_change"] = r["new_population_potential"] - r["old_population_potential"]
    by_change = sorted(rows, key=lambda r: abs(r["pop_change"]))
    top_change = list(reversed(by_change[-100:]))

    # --- Region contrasts ---
    def in_region(r: dict, box: tuple, extra: str | None) -> bool:
        lat_lo, lat_hi, lon_lo, lon_hi, _ = box
        if not (lat_lo <= r["latitude"] <= lat_hi and lon_lo <= r["longitude"] <= lon_hi):
            return False
        if extra == "elevation_gt_600":
            return (r["elevation_m"] or 0) > 600
        if extra == "urban_gt_0.4":
            return (r["urban_fraction"] or 0) > 0.4
        if extra == "lake_margin":
            sw_values = sorted(x["small_water_density"] for x in rows if x["small_water_density"] is not None)
            p75 = sw_values[int(len(sw_values) * 0.75)] if sw_values else 0
            return (r["small_water_density"] or 0) >= p75 and not r["major_lake_interior"]
        return True

    region_stats = {}
    for name, box in REGIONS.items():
        matched = [r for r in rows if in_region(r, box, box[4])]
        if not matched:
            region_stats[name] = {"n": 0}
            continue
        region_stats[name] = {
            "n": len(matched),
            "mean_habitat_capacity": sum(r["habitat_capacity"] for r in matched) / len(matched),
            "mean_mosquito_pressure": sum(r["new_mosquito_pressure"] for r in matched) / len(matched),
            "mean_population_potential_new": sum(r["new_population_potential"] for r in matched) / len(matched),
            "mean_population_potential_old": sum(r["old_population_potential"] for r in matched) / len(matched),
            "mean_final_risk_new": sum(r["new_final_risk"] for r in matched) / len(matched),
            "mean_final_risk_old": sum(r["old_final_risk"] for r in matched) / len(matched),
        }

    # --- Habitat double-counting ablation ---
    # mosquito_pressure_fraction = habitat_fraction * raw_signal (by
    # construction, see feature_engineering.py::_mosquito_pressure_fraction)
    # => raw_signal = pressure_fraction / habitat_fraction. Using this,
    # compute what population_potential WOULD be if a cell's habitat_capacity
    # were the national median instead of its real value, in EACH channel
    # separately, holding the other channel at its real value -- isolates
    # how much of population_potential's real sensitivity to habitat comes
    # from the direct (weight 0.35) term vs the indirect pressure-gating
    # channel (weight 0.50 x habitat-scaled raw_signal).
    config = load_model_config()
    weights = config.population_weights or {"pressure": 0.50, "habitat_capacity": 0.35, "temperature": 0.08, "season": 0.07}
    total_weight = sum(weights.values()) or 1.0

    habitat_fractions = [r["habitat_capacity"] / 100.0 for r in rows if r["habitat_capacity"]]
    median_habitat_fraction = sorted(habitat_fractions)[len(habitat_fractions) // 2] if habitat_fractions else 0.0

    ablation_rows = []
    for r in rows:
        hc = r["habitat_capacity"]
        mp = r["new_mosquito_pressure"]
        if hc is None or mp is None or hc <= 0.01:
            continue
        habitat_fraction = hc / 100.0
        pressure_fraction = mp / 100.0
        raw_signal = pressure_fraction / habitat_fraction  # weather-driven-only component

        # Reconstruct the temperature/season contribution implicitly: back
        # out from actual population_potential, since those two terms are
        # unaffected by this ablation.
        actual_pop = r["new_population_potential"]
        pressure_term_actual = pressure_fraction * weights.get("pressure", 0.50) / total_weight * 100
        habitat_term_actual = habitat_fraction * weights.get("habitat_capacity", 0.35) / total_weight * 100
        other_terms = actual_pop - pressure_term_actual - habitat_term_actual  # temperature + season, real values

        # Counterfactual A: only the DIRECT habitat term uses the median;
        # pressure keeps its real (habitat-scaled) value.
        habitat_term_median = median_habitat_fraction * weights.get("habitat_capacity", 0.35) / total_weight * 100
        pop_median_direct_only = other_terms + pressure_term_actual + habitat_term_median

        # Counterfactual B: only the PRESSURE channel's habitat gating uses
        # the median (raw_signal held fixed); direct term keeps its real value.
        pressure_fraction_median_habitat = raw_signal * median_habitat_fraction
        pressure_term_median_habitat = min(pressure_fraction_median_habitat, 1.0) * weights.get("pressure", 0.50) / total_weight * 100
        pop_median_pressure_only = other_terms + pressure_term_median_habitat + habitat_term_actual

        ablation_rows.append({
            "cell_id": r["cell_id"],
            "habitat_capacity": hc,
            "actual_population_potential": actual_pop,
            "swing_from_direct_channel": actual_pop - pop_median_direct_only,
            "swing_from_pressure_channel": actual_pop - pop_median_pressure_only,
            "raw_weather_signal": raw_signal,
        })

    direct_swings = [a["swing_from_direct_channel"] for a in ablation_rows]
    pressure_swings = [a["swing_from_pressure_channel"] for a in ablation_rows]
    ablation_summary = {
        "median_habitat_fraction_used_as_counterfactual": median_habitat_fraction,
        "direct_channel_swing_stats": _stats(direct_swings),
        "pressure_channel_swing_stats": _stats(pressure_swings),
        "n_cells_analyzed": len(ablation_rows),
        "correlation_habitat_vs_pressure": _pearson(
            [r["habitat_capacity"] for r in rows if r["habitat_capacity"] is not None and r["new_mosquito_pressure"] is not None],
            [r["new_mosquito_pressure"] for r in rows if r["habitat_capacity"] is not None and r["new_mosquito_pressure"] is not None],
        ),
    }

    return {
        "common_cell_count": len(common_ids),
        "distributions": dist,
        "variance_comparison": variance_comparison,
        "top_habitat_capacity": top_habitat[:100],
        "bottom_habitat_capacity": bottom_habitat[:100],
        "top_population_potential": top_pop[:100],
        "bottom_population_potential": bottom_pop[:100],
        "top_100_largest_change": top_change[:100],
        "region_stats": region_stats,
        "habitat_double_counting_ablation": ablation_summary,
        "all_rows": rows,
    }


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    denom = (var_x * var_y) ** 0.5
    return cov / denom if denom else 0.0


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = build_report()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    full_rows = report.pop("all_rows")
    (OUT_DIR / "national-diagnostics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    import csv
    with open(OUT_DIR / "national-diagnostics-all-cells.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(full_rows[0].keys()))
        writer.writeheader()
        writer.writerows(full_rows)

    print(json.dumps(report["distributions"], indent=2))
    print("\n=== Variance comparison ===")
    print(json.dumps(report["variance_comparison"], indent=2))
    print("\n=== Region stats ===")
    print(json.dumps(report["region_stats"], indent=2))
    print("\n=== Habitat double-counting ablation ===")
    print(json.dumps(report["habitat_double_counting_ablation"], indent=2))
    print(f"\nFull report: {OUT_DIR / 'national-diagnostics.json'}")
    print(f"All-cells CSV: {OUT_DIR / 'national-diagnostics-all-cells.csv'}")


if __name__ == "__main__":
    main()
