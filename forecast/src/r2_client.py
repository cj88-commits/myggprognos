"""Shared Cloudflare R2 (S3-compatible) client helper.

Used by publish_forecast_data.py (forecast delivery files) and
weather_cache_r2.py (pipeline's persistent weather-history cache). Both
buckets live on the same Cloudflare account but serve different purposes:
one is public delivery data, the other is private pipeline state -- see
README "Forecast data hosting" for the split.

Required env vars (all read lazily, only when a client is actually built,
so importing this module never fails just because secrets aren't set yet):

    CLOUDFLARE_ACCOUNT_ID
    R2_ACCESS_KEY_ID
    R2_SECRET_ACCESS_KEY
"""
from __future__ import annotations

import os


class R2ConfigError(RuntimeError):
    """Raised when required R2 credentials/config are missing."""


REQUIRED_ENV_VARS = ("CLOUDFLARE_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")


def r2_credentials_present() -> bool:
    """True if all env vars needed to build an R2 client are set.

    Callers use this to skip R2 steps gracefully (not as a failure) during
    the migration window before secrets have been provisioned -- see
    forecast.yml's "if: env.R2_CREDENTIALS_PRESENT" steps.
    """
    return all(os.environ.get(var) for var in REQUIRED_ENV_VARS)


def build_r2_client():
    """Construct a boto3 S3 client pointed at this account's R2 endpoint.

    Raises R2ConfigError (not a boto3/botocore error) if credentials are
    missing, so callers get one clear, actionable exception type.
    """
    missing = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
    if missing:
        raise R2ConfigError(f"Missing required R2 env var(s): {', '.join(missing)}")

    import boto3

    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
