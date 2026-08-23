#!/usr/bin/env python
"""Run the forecast pipeline and write generated output assets.

Usage:
    python scripts/run_forecast.py --sample                  # fast, no network, 5 cells
    python scripts/run_forecast.py                           # full grid, live SMHI data (default)
    python scripts/run_forecast.py --provider open-meteo     # full grid, live Open-Meteo data
                                                               # (kept as a fallback -- see README)
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
    parser.add_argument(
        "--provider", choices=["smhi", "open-meteo"], default="smhi",
        help="Weather data source for the real (non-sample) grid. SMHI is the default "
             "production source (see README); open-meteo is kept as a fallback.",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--min-cell-count-ratio", type=float, default=None,
        help="Override run_sanity_checks' default 0.9 floor for one run -- use only when a "
             "grid/boundary change deliberately shrinks the cell count (e.g. removing "
             "erroneously-included foreign land near a border) and the drop has already "
             "been verified by hand; leave unset for routine runs so an accidental cell-count "
             "regression still aborts publishing.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # --verbose is meant to control OUR application-level logging
    # (mosquito_forecast.*), not httpx/httpcore's own wire-protocol
    # tracing -- at DEBUG that library logs ~10 lines per single HTTP
    # request, and a full SMHI or Open-Meteo run makes hundreds of
    # requests. Suspected (not fully confirmed) cause of two live SMHI
    # comparison runs getting silently cancelled ("The operation was
    # canceled.") partway through, well before any timeout-minutes was
    # reached and with no other explanation found -- GitHub Actions log
    # volume is a plausible trigger. Silencing it is a good idea
    # regardless: it's noise, not information we act on.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # --sample always uses the fast, offline SyntheticWeatherProvider
    # (run_pipeline's own default for sample=True) -- --provider only
    # selects between real network sources for the real grid.
    weather_provider = None
    cache_checkpoint_chunk_cells = None
    if not args.sample and args.provider == "smhi":
        from smhi_weather import SMHIProvider

        weather_provider = SMHIProvider()
        # SMHIProvider's request cost is independent of how many cells are
        # asked for (unlike Open-Meteo's per-cell batching) -- chunking
        # into groups of 1000 like the Open-Meteo default would repeat its
        # whole-domain fetch ~19x for nothing (confirmed live). One big
        # chunk covering the whole grid instead.
        cache_checkpoint_chunk_cells = 100_000
    elif not args.sample and args.provider == "open-meteo":
        from weather import OpenMeteoProvider

        weather_provider = OpenMeteoProvider()

    try:
        result = run_pipeline(
            sample=args.sample,
            weather_provider=weather_provider,
            cache_checkpoint_chunk_cells=cache_checkpoint_chunk_cells,
            min_cell_count_ratio=args.min_cell_count_ratio,
        )
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
