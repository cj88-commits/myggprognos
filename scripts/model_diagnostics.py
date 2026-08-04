#!/usr/bin/env python
"""Read-only diagnostics over the currently published forecast output.

Item 9 of the public-beta polish pass: before touching any model weights,
understand what the model is actually producing across all of Sweden --
how risk is distributed across the five categories, whether that
distribution looks plausible, how much it varies hour-to-hour and
day-to-day, and whether any region stands out. This script makes NO model
changes; it only reads data/generated/latest (the same assets the frontend
serves) and reports on them.

Usage:
    python scripts/model_diagnostics.py
    python scripts/model_diagnostics.py --out data/generated/diagnostics
"""
from __future__ import annotations

import argparse
import gzip
import json
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import _pathsetup  # noqa: F401
from config import GENERATED_DATA_DIR, RISK_CATEGORIES, load_model_config

# Suspicion thresholds -- deliberately conservative/simple (percentages and
# point-deltas on the existing 0-100 risk scale), not statistical tests.
# The goal is "flag things a human should look at", not a rigorous model
# audit.
CONCENTRATION_THRESHOLD_PCT = 80.0  # one category holding this much of Sweden
DAY_JUMP_THRESHOLD_POINTS = 25.0  # national mean risk change between consecutive days
FLAT_DAY_VARIATION_POINTS = 3.0  # national mean risk range across all 7 days
FLAT_HOURLY_VARIATION_POINTS = 5.0  # national mean risk range across the 48h hourly series

CATEGORY_KEYS = ("very_low", "low", "moderate", "high", "very_high")


def _read_gz_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _category_key(risk: float) -> str:
    key = RISK_CATEGORIES[0][2]
    for lo, _hi, cat_key, _label in RISK_CATEGORIES:
        if risk >= lo:
            key = cat_key
    return key


def _abundance_category_key(value: float, edges: list[float]) -> str:
    """Mirrors frontend/src/lib/riskModel.ts::abundanceCategory -- same 4
    edges (read from the same model.yaml `thresholds.abundance` config, via
    the manifest) define the same 5 bands, so this script's category shares
    always agree with what the map/legend actually show."""
    mins = [0.0, *edges]
    key_index = 0
    for i, lo in enumerate(mins):
        if value >= lo:
            key_index = i
    return CATEGORY_KEYS[key_index]


def _pct_distribution(values: list[str]) -> dict[str, float]:
    n = len(values)
    counts = Counter(values)
    return {key: round(100.0 * counts.get(key, 0) / n, 1) for key in CATEGORY_KEYS} if n else {}


def _empty_band_warnings(category_pct: dict[str, float], product_label: str, date_str: str) -> list[str]:
    empty = [key for key, pct in category_pct.items() if pct == 0.0]
    if not empty:
        return []
    return [
        f"{date_str} ({product_label}): {', '.join(empty)} {'is' if len(empty) == 1 else 'are'} completely empty "
        f"(0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating "
        f"against real output (see docs/model-audit-after.md)."
    ]


@dataclass
class DailySummary:
    date: str
    n_cells: int
    mean_risk: float
    median_risk: float
    category_pct: dict[str, float]
    region_mean_risk: dict[str, float]
    abundance_category_pct: dict[str, float] = field(default_factory=dict)
    mean_abundance: float = 0.0


@dataclass
class Report:
    generated_at: str
    cell_count: int
    daily: list[DailySummary] = field(default_factory=list)
    hourly_mean_by_hour: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    six_hour_change: dict[str, float] = field(default_factory=dict)
    cell_to_cell_discontinuity: dict[str, float] = field(default_factory=dict)


DISCONTINUITY_WARN_POINTS = 60.0  # a single 5km-neighbour jump this large is suspicious
SIX_HOUR_CHANGE_WARN_POINTS = 70.0  # a single cell swinging this much in 6h is suspicious


def _cell_row_col(cell_id: str) -> tuple[int, int] | None:
    """Parses grid.py's f"SE_{row:04d}_{col:04d}" scheme. Returns None for
    anything else (e.g. the separate SE_ISLE_... scheme for split island
    pieces) rather than guessing -- those aren't on the same regular grid
    so "adjacent" doesn't mean the same thing for them."""
    parts = cell_id.split("_")
    if len(parts) != 3 or parts[0] != "SE":
        return None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


def _cell_to_cell_discontinuity(records: list[dict]) -> dict[str, float]:
    """|risk difference| between each main-grid cell and its immediate
    right-hand (col+1) neighbour -- real mosquito risk should vary
    smoothly across a 5km grid; a large jump between adjacent cells more
    often indicates a data/indexing bug than real terrain-driven variation."""
    risk_by_rc: dict[tuple[int, int], float] = {}
    for r in records:
        rc = _cell_row_col(r["cell_id"])
        if rc is not None:
            risk_by_rc[rc] = r["risk"]

    diffs = []
    for (row, col), risk in risk_by_rc.items():
        neighbor = risk_by_rc.get((row, col + 1))
        if neighbor is not None:
            diffs.append(abs(neighbor - risk))

    if not diffs:
        return {}
    diffs.sort()
    n = len(diffs)
    return {
        "pairs_checked": n,
        "mean": round(statistics.mean(diffs), 2),
        "p95": round(diffs[int(n * 0.95)], 2),
        "max": round(diffs[-1], 2),
    }


def _six_hour_change(hourly_files: list[str], data_dir: Path) -> dict[str, float]:
    series: dict[str, dict[str, float]] = {}
    for rel_path in hourly_files:
        hour_label = Path(rel_path).stem.replace(".json", "")
        records = _read_gz_json(data_dir / rel_path)
        series[hour_label] = {r["cell_id"]: r["risk"] for r in records}

    labels = list(series.keys())
    diffs = []
    for i in range(len(labels) - 6):
        earlier, later = series[labels[i]], series[labels[i + 6]]
        for cell_id, risk_earlier in earlier.items():
            risk_later = later.get(cell_id)
            if risk_later is not None:
                diffs.append(abs(risk_later - risk_earlier))

    if not diffs:
        return {}
    diffs.sort()
    n = len(diffs)
    return {
        "samples": n,
        "mean": round(statistics.mean(diffs), 2),
        "p95": round(diffs[int(n * 0.95)], 2),
        "max": round(diffs[-1], 2),
    }


def build_report(data_dir: Path) -> Report:
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    cells = _read_gz_json(data_dir / "cells.json.gz")
    region_by_cell = {c["cell_id"]: c.get("region", "unknown") for c in cells}

    # Same source the frontend reads (manifest.thresholds.abundance) --
    # falls back to the model config directly if this run's manifest
    # predates that field, never to an independently-hand-copied constant.
    abundance_edges = manifest.get("thresholds", {}).get("abundance") or load_model_config().abundance_thresholds

    report = Report(generated_at=manifest["generated_at"], cell_count=manifest["cell_count"])

    # --- Daily: category distribution, median, regional breakdown ---
    daily_means: list[tuple[str, float]] = []
    for rel_path in manifest["daily_files"]:
        date_str = Path(rel_path).stem.replace(".json", "")
        records = _read_gz_json(data_dir / rel_path)
        risks = [r["risk"] for r in records]
        cats = [_category_key(r) for r in risks]
        abundances = [r.get("mosquito_abundance", r["population_potential"]) for r in records]
        abundance_cats = [_abundance_category_key(v, abundance_edges) for v in abundances]

        region_risks: dict[str, list[float]] = defaultdict(list)
        for r in records:
            region_risks[region_by_cell.get(r["cell_id"], "unknown")].append(r["risk"])

        summary = DailySummary(
            date=date_str,
            n_cells=len(records),
            mean_risk=round(statistics.mean(risks), 1),
            median_risk=round(statistics.median(risks), 1),
            category_pct=_pct_distribution(cats),
            region_mean_risk={region: round(statistics.mean(vals), 1) for region, vals in region_risks.items()},
            abundance_category_pct=_pct_distribution(abundance_cats),
            mean_abundance=round(statistics.mean(abundances), 1),
        )
        report.daily.append(summary)
        daily_means.append((date_str, summary.mean_risk))

        top_category, top_pct = max(summary.category_pct.items(), key=lambda kv: kv[1])
        if top_pct >= CONCENTRATION_THRESHOLD_PCT:
            report.warnings.append(
                f"{date_str}: {top_pct:.0f}% of Sweden is in a single risk category ('{top_category}') -- "
                f"check for a model component saturating (e.g. exposure or population term pinned near 0 or 1)."
            )
        report.warnings.extend(_empty_band_warnings(summary.category_pct, "Myggrisk idag", date_str))
        report.warnings.extend(_empty_band_warnings(summary.abundance_category_pct, "Myggläge", date_str))

        if rel_path == manifest["daily_files"][0]:
            report.cell_to_cell_discontinuity = _cell_to_cell_discontinuity(records)
            if report.cell_to_cell_discontinuity.get("max", 0) >= DISCONTINUITY_WARN_POINTS:
                report.warnings.append(
                    f"Largest adjacent-cell risk jump today is {report.cell_to_cell_discontinuity['max']:.0f} "
                    f"points -- check for a data or indexing bug rather than assuming real terrain variation."
                )

    if len(daily_means) >= 2:
        day_range = max(m for _, m in daily_means) - min(m for _, m in daily_means)
        if day_range < FLAT_DAY_VARIATION_POINTS:
            report.warnings.append(
                f"National mean risk barely moves across the {len(daily_means)}-day forecast "
                f"(range {day_range:.1f} points) -- check whether the weather forecast inputs actually "
                f"differ day to day, or the model is under-weighting them."
            )
        for (d1, m1), (d2, m2) in zip(daily_means, daily_means[1:]):
            jump = abs(m2 - m1)
            if jump >= DAY_JUMP_THRESHOLD_POINTS:
                report.warnings.append(
                    f"National mean risk jumps {jump:.1f} points between {d1} ({m1:.1f}) and {d2} ({m2:.1f}) -- "
                    f"larger than a day of weather alone would typically explain; check for a data/unit bug on the boundary."
                )

    # --- Hourly: diurnal variation across the ~48h hourly horizon ---
    hourly_means: list[tuple[str, float]] = []
    for rel_path in manifest["hourly_files"]:
        hour_label = Path(rel_path).stem.replace(".json", "")
        records = _read_gz_json(data_dir / rel_path)
        if not records:
            continue
        mean_risk = round(statistics.mean(r["risk"] for r in records), 1)
        hourly_means.append((hour_label, mean_risk))
        report.hourly_mean_by_hour.append({"hour": hour_label, "mean_risk": mean_risk})

    if len(hourly_means) >= 2:
        hour_range = max(m for _, m in hourly_means) - min(m for _, m in hourly_means)
        if hour_range < FLAT_HOURLY_VARIATION_POINTS:
            report.warnings.append(
                f"National mean risk barely varies across the {len(hourly_means)}-hour hourly series "
                f"(range {hour_range:.1f} points) -- a real diurnal mosquito-activity cycle should show more "
                f"movement between e.g. midday and dusk; check daypart_activity weighting in model.py."
            )

    report.six_hour_change = _six_hour_change(manifest["hourly_files"], data_dir)
    if report.six_hour_change.get("max", 0) >= SIX_HOUR_CHANGE_WARN_POINTS:
        report.warnings.append(
            f"Largest single-cell 6-hour risk change is {report.six_hour_change['max']:.0f} points -- "
            f"check for a discontinuity at a daypart/data boundary rather than assuming real weather swing."
        )

    return report


def render_markdown(report: Report) -> str:
    lines = [
        "# Model output diagnostics",
        "",
        f"Generated from forecast run `{report.generated_at}`, {report.cell_count} cells.",
        "",
        "## Suspicious patterns" if report.warnings else "## Suspicious patterns: none found",
    ]
    for w in report.warnings:
        lines.append(f"- ⚠ {w}")
    if not report.warnings:
        lines.append("- No configured threshold was tripped (see script header for what's checked).")

    if report.cell_to_cell_discontinuity:
        d = report.cell_to_cell_discontinuity
        lines += [
            "", "## Cell-to-cell spatial discontinuity (today, adjacent 5km cells)", "",
            f"Pairs checked: {d['pairs_checked']} -- mean {d['mean']}, p95 {d['p95']}, max {d['max']} points.",
        ]
    if report.six_hour_change:
        h = report.six_hour_change
        lines += [
            "", "## Six-hour change distribution (single-cell risk swing)", "",
            f"Samples: {h['samples']} -- mean {h['mean']}, p95 {h['p95']}, max {h['max']} points.",
        ]

    lines += ["", "## Daily peak risk (Myggrisk idag) distribution (% of Sweden per category)", ""]
    cat_keys = [c[2] for c in RISK_CATEGORIES]
    lines.append("| Date | Mean | Median | " + " | ".join(cat_keys) + " |")
    lines.append("|---|---|---|" + "---|" * len(cat_keys))
    for d in report.daily:
        row = [d.date, f"{d.mean_risk}", f"{d.median_risk}"] + [f"{d.category_pct.get(k, 0)}%" for k in cat_keys]
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## Abundance (Myggläge) distribution (% of Sweden per category)", ""]
    lines.append("| Date | Mean | " + " | ".join(CATEGORY_KEYS) + " |")
    lines.append("|---|---|" + "---|" * len(CATEGORY_KEYS))
    for d in report.daily:
        row = [d.date, f"{d.mean_abundance}"] + [f"{d.abundance_category_pct.get(k, 0)}%" for k in CATEGORY_KEYS]
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## Regional mean risk by day", ""]
    regions = sorted({r for d in report.daily for r in d.region_mean_risk})
    lines.append("| Date | " + " | ".join(regions) + " |")
    lines.append("|---|" + "---|" * len(regions))
    for d in report.daily:
        row = [d.date] + [f"{d.region_mean_risk.get(r, 0)}" for r in regions]
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## Hourly national mean risk (diurnal variation, next ~48h)", ""]
    lines.append("| Hour (UTC) | Mean risk |")
    lines.append("|---|---|")
    for h in report.hourly_mean_by_hour:
        lines.append(f"| {h['hour']} | {h['mean_risk']} |")

    return "\n".join(lines) + "\n"


def main() -> None:
    # Windows' console defaults to a cp1252-family codepage that can't
    # encode the "⚠" warning marker below -- UTF-8 output (the report.md
    # file was always written as UTF-8; only the console print needed this).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", type=Path, default=GENERATED_DATA_DIR / "latest",
        help="Generated forecast output directory to analyse (default: data/generated/latest)",
    )
    parser.add_argument(
        "--out", type=Path, default=GENERATED_DATA_DIR / "diagnostics",
        help="Directory to write report.json / report.md into",
    )
    args = parser.parse_args()

    report = build_report(args.data_dir)
    args.out.mkdir(parents=True, exist_ok=True)

    (args.out / "report.json").write_text(
        json.dumps(
            {
                "generated_at": report.generated_at,
                "cell_count": report.cell_count,
                "daily": [d.__dict__ for d in report.daily],
                "hourly_mean_by_hour": report.hourly_mean_by_hour,
                "six_hour_change": report.six_hour_change,
                "cell_to_cell_discontinuity": report.cell_to_cell_discontinuity,
                "warnings": report.warnings,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    markdown = render_markdown(report)
    (args.out / "report.md").write_text(markdown, encoding="utf-8")

    print(markdown)
    print(f"\nWritten to {args.out / 'report.json'} and {args.out / 'report.md'}")


if __name__ == "__main__":
    main()
