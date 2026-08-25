#!/usr/bin/env python
"""Persist forecast/src/history_cache.py's weather-history cache to
Cloudflare R2 instead of committing it to git.

weather_history_cache.json.gz is pipeline STATE (a rolling window of
already-fetched observed weather, self-bounded by history_cache.py's own
keep_days trimming -- see that module's docstring), not frontend delivery
data. It never needs to be publicly reachable, so it lives in a separate,
private R2 bucket from publish_forecast_data.py's delivery bucket.

Two subcommands, both single-object operations (no diffing needed -- this
is one file, always fully overwritten):

    download   Fetch the cache from R2 to a local path (run before the
               pipeline). Missing object is NOT an error -- same as today's
               "cache file doesn't exist yet" cold-start behaviour;
               history_cache.load_history_cache already handles a missing
               local file the same way.
    upload     Push a local path to R2 (run after the pipeline, and
               optionally as a periodic mid-run checkpoint replacing the
               git-commit-every-10-minutes loop in forecast.yml).

Requires: CLOUDFLARE_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
R2_STATE_BUCKET.

Usage:
    python scripts/weather_cache_r2.py download --path data/generated/weather_history_cache.json.gz
    python scripts/weather_cache_r2.py upload --path data/generated/weather_history_cache.json.gz
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import _pathsetup  # noqa: F401
from r2_client import R2ConfigError, build_r2_client

logger = logging.getLogger("weather_cache_r2")

STATE_KEY = "state/weather_history_cache.json.gz"


def download(path: Path, bucket: str, client) -> int:
    try:
        client.head_object(Bucket=bucket, Key=STATE_KEY)
    except client.exceptions.ClientError:
        logger.info("No weather-history cache in R2 yet (key %s) -- starting cold, same as a missing local file", STATE_KEY)
        return 0
    except Exception:
        logger.exception("Failed to check for existing weather-history cache in R2")
        return 1

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(bucket, STATE_KEY, str(path))
    except Exception:
        logger.exception("Failed to download weather-history cache from R2")
        return 1

    logger.info("Downloaded weather-history cache from R2 (%.1f MB) to %s", path.stat().st_size / 1_000_000, path)
    return 0


def upload(path: Path, bucket: str, client) -> int:
    if not path.exists():
        logger.info("No local weather-history cache at %s to upload (nothing fetched yet this run)", path)
        return 0

    try:
        client.upload_file(str(path), bucket, STATE_KEY, ExtraArgs={"ContentType": "application/gzip"})
    except Exception:
        logger.exception("Failed to upload weather-history cache to R2 -- checkpoint NOT saved")
        return 1

    logger.info("Uploaded weather-history cache to R2 (%.1f MB)", path.stat().st_size / 1_000_000)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["download", "upload"])
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bucket = os.environ.get("R2_STATE_BUCKET")
    if not bucket:
        logger.error("R2_STATE_BUCKET env var is not set")
        sys.exit(1)

    try:
        client = build_r2_client()
    except R2ConfigError as exc:
        logger.error("R2 not configured: %s", exc)
        sys.exit(1)

    if args.command == "download":
        sys.exit(download(args.path, bucket, client))
    else:
        sys.exit(upload(args.path, bucket, client))


if __name__ == "__main__":
    main()
