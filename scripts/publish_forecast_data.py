#!/usr/bin/env python
"""Upload data/generated/latest/ to the Cloudflare R2 forecast-data bucket.

Publishes exactly what prune_stale_output already kept on local disk (the
active-window daily/hourly files, current series shards, cells.json.gz,
locations/index.json.gz, and manifest.json). Skips files whose R2 object
already carries a matching content-hash (see r2_sync.build_upload_plan), and
deletes remote objects that have fallen outside the current window -- the
same rolling-window pruning applied to the bucket, so it never re-grows the
unbounded-storage problem this migration exists to fix.

Requires (see README "Forecast data hosting" for how to obtain these):
    CLOUDFLARE_ACCOUNT_ID
    R2_ACCESS_KEY_ID
    R2_SECRET_ACCESS_KEY
    R2_DATA_BUCKET

Exits non-zero on ANY upload/delete failure or missing config -- a forecast
that was generated locally but not fully published must never be reported
as a successful run (the caller, forecast.yml, must not proceed to treat
this run as published if this script fails).

Usage:
    python scripts/publish_forecast_data.py [--output-dir PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import _pathsetup  # noqa: F401
from r2_client import R2ConfigError, build_r2_client
from r2_sync import (
    CONTENT_HASH_METADATA_KEY,
    R2_PREFIX,
    build_upload_plan,
    cache_control_for,
    collect_local_files,
    content_type_for,
    r2_key,
)

logger = logging.getLogger("publish_forecast_data")


def fetch_remote_hashes(client, bucket: str) -> dict[str, str]:
    """Content-hash metadata for every object currently under R2_PREFIX.

    Requires a HEAD per object (S3 ListObjects doesn't return custom
    metadata) -- acceptable here since the delivery set is small (roughly
    daily + hourly + 128-256 series files + a handful of top-level files,
    a few hundred objects at most).
    """
    hashes: dict[str, str] = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{R2_PREFIX}/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            head = client.head_object(Bucket=bucket, Key=key)
            hashes[key] = head.get("Metadata", {}).get(CONTENT_HASH_METADATA_KEY, "")
    return hashes


def publish(output_dir: Path, dry_run: bool = False) -> int:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        logger.error("No manifest.json found under %s -- nothing to publish", output_dir)
        return 1

    bucket = os.environ.get("R2_DATA_BUCKET")
    if not bucket:
        logger.error("R2_DATA_BUCKET env var is not set")
        return 1

    local_files = collect_local_files(output_dir)
    total_bytes = sum(f.abs_path.stat().st_size for f in local_files)
    logger.info(
        "Found %d local file(s) to consider publishing (%.1f MB total)",
        len(local_files), total_bytes / 1_000_000,
    )

    try:
        client = build_r2_client()
    except R2ConfigError as exc:
        logger.error("R2 not configured: %s", exc)
        return 1

    try:
        remote_hashes = fetch_remote_hashes(client, bucket)
    except Exception:
        logger.exception("Failed to list/inspect existing R2 objects -- aborting publish")
        return 1
    plan = build_upload_plan(local_files, remote_hashes)

    logger.info(
        "Publish plan: %d to upload, %d unchanged, %d stale remote object(s) to delete",
        len(plan.to_upload), plan.unchanged_count, len(plan.to_delete),
    )

    if dry_run:
        for f in plan.to_upload:
            logger.info("[dry-run] would upload %s", f.rel_path)
        for key in plan.to_delete:
            logger.info("[dry-run] would delete %s", key)
        return 0

    uploaded = 0
    for f in plan.to_upload:
        content_type, content_encoding = content_type_for(f.rel_path)
        extra_args = {
            "ContentType": content_type,
            "CacheControl": cache_control_for(f.rel_path),
            "Metadata": {CONTENT_HASH_METADATA_KEY: f.content_hash},
        }
        if content_encoding:
            extra_args["ContentEncoding"] = content_encoding
        try:
            client.upload_file(str(f.abs_path), bucket, r2_key(f.rel_path), ExtraArgs=extra_args)
            uploaded += 1
        except Exception:
            logger.exception("Failed to upload %s -- aborting publish", f.rel_path)
            return 1

    deleted = 0
    for key in plan.to_delete:
        try:
            client.delete_object(Bucket=bucket, Key=key)
            deleted += 1
        except Exception:
            logger.exception("Failed to delete stale object %s -- aborting publish", key)
            return 1

    logger.info(
        "Publish complete: %d uploaded, %d unchanged, %d deleted, %.1f MB total local size",
        uploaded, plan.unchanged_count, deleted, total_bytes / 1_000_000,
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None, help="Defaults to data/generated/latest")
    parser.add_argument("--dry-run", action="store_true", help="Log the plan without uploading/deleting anything")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from config import GENERATED_DATA_DIR

    output_dir = args.output_dir or (GENERATED_DATA_DIR / "latest")
    sys.exit(publish(output_dir, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
