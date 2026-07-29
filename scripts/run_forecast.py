#!/usr/bin/env python
"""Run the forecast pipeline and write generated output assets.

Usage:
    python scripts/run_forecast.py --sample          # fast, no network, 5 cells
    python scripts/run_forecast.py                   # full grid, live Open-Meteo data
"""
from __future__ import annotations

import argparse
import logging
import sys

import _pathsetup  # noqa: F401
from pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="Use the small sample grid + synthetic weather")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        result = run_pipeline(sample=args.sample)
    except Exception:
        logging.getLogger("mosquito_forecast").exception("Forecast pipeline failed")
        sys.exit(1)

    print(f"OK: {result['cell_count']} cells, {len(result['daily_files'])} daily files, "
          f"{len(result['hourly_files'])} hourly files")
    if result["warnings"]:
        print("Warnings:")
        for w in result["warnings"]:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
