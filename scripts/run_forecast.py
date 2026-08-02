#!/usr/bin/env python
"""Run the forecast pipeline and write generated output assets.

Usage:
    python scripts/run_forecast.py --sample          # fast, no network, 5 cells
    python scripts/run_forecast.py                   # full grid, live Open-Meteo data
    python scripts/run_forecast.py --provider smhi   # full grid, live SMHI data (parallel
                                                       # evaluation -- writes to a separate
                                                       # output_dir/cache, never touches the
                                                       # production Open-Meteo-driven output)
"""
from __future__ import annotations

import argparse
import logging
import sys

import _pathsetup  # noqa: F401
from config import GENERATED_DATA_DIR
from pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="Use the small sample grid + synthetic weather")
    parser.add_argument(
        "--provider", choices=["open-meteo", "smhi"], default="open-meteo",
        help="Weather data source. 'smhi' is under parallel evaluation (see README) and "
             "always writes to a separate output_dir/history cache, regardless of --sample.",
    )
    parser.add_argument("--verbose", action="store_true")
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

    weather_provider = None
    output_dir = None
    history_cache_path = None
    cache_checkpoint_chunk_cells = None
    if args.provider == "smhi":
        from smhi_weather import SMHIProvider

        weather_provider = SMHIProvider()
        output_dir = GENERATED_DATA_DIR / "latest_smhi"
        history_cache_path = GENERATED_DATA_DIR / "weather_history_cache_smhi.json.gz"
        # SMHIProvider's request cost is independent of how many cells are
        # asked for (unlike Open-Meteo's per-cell batching) -- chunking
        # into groups of 1000 like the Open-Meteo default would repeat its
        # whole-domain fetch ~19x for nothing (confirmed live). One big
        # chunk covering the whole grid instead.
        cache_checkpoint_chunk_cells = 100_000

    try:
        result = run_pipeline(
            sample=args.sample,
            weather_provider=weather_provider,
            output_dir=output_dir,
            history_cache_path=history_cache_path,
            cache_checkpoint_chunk_cells=cache_checkpoint_chunk_cells,
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
