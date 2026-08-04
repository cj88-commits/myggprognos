#!/usr/bin/env python
"""Benchmark report over a fixed set of representative Swedish locations.

Item 22: a version-controlled set of 30+ locations spanning cities, dense
forest, floodplain, wetland, exposed coast, archipelago, farmland, lake
shore, Gotland/Oland, northern coast, mountains, and the far north
(forecast/benchmarks/locations.json). For each forecast run, reports
Myggläge / Myggrisk idag / Myggrisk just nu, component values, peak time,
category, top explanation factors, and data quality per location -- read
directly from the currently published data/generated/latest, no pipeline
re-run needed.

Purpose: catch implausible behaviour and regressions by eye ("does Kiruna
in December look like Kiruna in December should?"), not to assert exact
expected scores -- there is no ground truth to assert against yet (see
the final report's "remaining scientific limitations").

Usage:
    python scripts/run_benchmarks.py
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from pathlib import Path
from typing import Any

import _pathsetup  # noqa: F401
from config import GENERATED_DATA_DIR

BENCHMARKS_DIR = Path(__file__).resolve().parents[1] / "forecast" / "benchmarks"


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_gz(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _nearest_cell(cells: list[dict], lat: float, lon: float) -> dict:
    """Mirrors frontend/src/lib/api.ts::nearestCell -- same flat-projection
    squared-distance approximation, good enough at Sweden's scale/latitude
    range for "which ~5km grid cell is this" and kept consistent with what
    the frontend actually shows for the same coordinates."""
    best = cells[0]
    best_dist = math.inf
    cos_lat = math.cos(math.radians(lat))
    for cell in cells:
        d_lat = cell["latitude"] - lat
        d_lon = (cell["longitude"] - lon) * cos_lat
        dist = d_lat * d_lat + d_lon * d_lon
        if dist < best_dist:
            best_dist = dist
            best = cell
    return best


def build_report(data_dir: Path, locations_path: Path) -> dict[str, Any]:
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    cells = _load_gz(data_dir / "cells.json.gz")
    locations = _load_json(locations_path)

    today_daily = _load_gz(data_dir / manifest["daily_files"][0])
    daily_by_cell = {r["cell_id"]: r for r in today_daily}

    hourly_slots = []
    for rel in manifest["hourly_files"]:
        hour_label = Path(rel).stem.replace(".json", "")
        if hour_label[-2:] in ("12", "21"):  # representative midday + evening hours
            hourly_slots.append((hour_label, _load_gz(data_dir / rel)))
        if len(hourly_slots) >= 2:
            break

    entries = []
    for loc in locations:
        cell = _nearest_cell(cells, loc["latitude"], loc["longitude"])
        cell_id = cell["cell_id"]
        daily = daily_by_cell.get(cell_id)

        entry: dict[str, Any] = {
            "name": loc["name"],
            "category": loc["category"],
            "latitude": loc["latitude"],
            "longitude": loc["longitude"],
            "matched_cell_id": cell_id,
            "matched_cell_region": cell.get("region"),
        }
        if daily is None:
            entry["error"] = "no daily record found for matched cell"
            entries.append(entry)
            continue

        entry.update(
            {
                "mosquito_abundance": daily.get("mosquito_abundance", daily["population_potential"]),
                "daily_peak_risk": daily.get("daily_peak_risk", daily["risk"]),
                "daily_peak_local_time": daily.get("daily_peak_local_time"),
                "peak_period": daily.get("peak_period"),
                "biting_activity_at_peak": daily["biting_activity"],
                "exposure_modifier_at_peak": daily.get("exposure_modifier"),
                "activity_modifier_at_peak": daily.get("activity_modifier"),
                "confidence": daily["confidence"],
                "top_positive_factors": [f["label"] for f in daily["explanation"]["positive_factors"][:3]],
                "top_negative_factors": [f["label"] for f in daily["explanation"]["negative_factors"][:2]],
            }
        )
        for hour_label, records in hourly_slots:
            by_cell = {r["cell_id"]: r for r in records}
            record = by_cell.get(cell_id)
            entry[f"current_risk_at_{hour_label[-2:]}h_utc"] = record["risk"] if record else None

        entries.append(entry)

    return {"generated_at": manifest["generated_at"], "cell_count": manifest["cell_count"], "locations": entries}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Benchmark location report",
        "",
        f"Generated from forecast run `{report['generated_at']}`, {report['cell_count']} cells, "
        f"{len(report['locations'])} benchmark locations.",
        "",
        "No expected/ground-truth scores are encoded here yet -- this is for eyeballing plausibility "
        "and spotting regressions between runs, not automated pass/fail assertions.",
        "",
        "| Location | Category | Myggläge | Myggrisk idag | Peak | Data quality | Top factors |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in report["locations"]:
        if "error" in e:
            lines.append(f"| {e['name']} | {e['category']} | - | - | - | - | ERROR: {e['error']} |")
            continue
        peak = f"{e.get('peak_period', '?')} (~{e.get('daily_peak_local_time', '?')})"
        factors = ", ".join(e["top_positive_factors"][:2]) or "-"
        lines.append(
            f"| {e['name']} | {e['category']} | {e['mosquito_abundance']:.0f} | "
            f"{e['daily_peak_risk']:.0f} | {peak} | {e['confidence']:.0f} | {factors} |"
        )

    lines += ["", "## Full detail per location", ""]
    for e in report["locations"]:
        lines.append(f"### {e['name']} ({e['category']})")
        lines.append(f"- Coordinates: {e['latitude']}, {e['longitude']} -> matched cell `{e['matched_cell_id']}` ({e.get('matched_cell_region')})")
        if "error" in e:
            lines.append(f"- ERROR: {e['error']}")
            lines.append("")
            continue
        lines.append(f"- Myggläge (abundance): {e['mosquito_abundance']:.1f}")
        lines.append(f"- Myggrisk idag (daily peak): {e['daily_peak_risk']:.1f}, peak {e['peak_period']} (~{e['daily_peak_local_time']})")
        for k, v in e.items():
            if k.startswith("current_risk_at_"):
                lines.append(f"- {k}: {v if v is not None else 'n/a'}")
        lines.append(f"- Biting activity at peak: {e['biting_activity_at_peak']:.1f}")
        lines.append(f"- Activity modifier / exposure modifier at peak: {e['activity_modifier_at_peak']} / {e['exposure_modifier_at_peak']}")
        lines.append(f"- Data quality (confidence): {e['confidence']:.1f}")
        lines.append(f"- Top positive factors: {', '.join(e['top_positive_factors']) or '-'}")
        lines.append(f"- Top negative factors: {', '.join(e['top_negative_factors']) or '-'}")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=GENERATED_DATA_DIR / "latest")
    parser.add_argument("--locations", type=Path, default=BENCHMARKS_DIR / "locations.json")
    parser.add_argument("--out", type=Path, default=GENERATED_DATA_DIR / "diagnostics")
    args = parser.parse_args()

    report = build_report(args.data_dir, args.locations)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "benchmark-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = render_markdown(report)
    (args.out / "benchmark-report.md").write_text(markdown, encoding="utf-8")

    print(markdown[:4000])
    print(f"\n... full report written to {args.out / 'benchmark-report.md'}")


if __name__ == "__main__":
    main()
