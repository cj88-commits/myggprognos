"""Pure planning logic for publishing data/generated/latest/ to Cloudflare R2.

Deliberately separated from any actual boto3/network I/O (see
scripts/publish_forecast_data.py for the CLI that does the I/O) so the
upload/delete decisions can be unit-tested without a real R2 bucket.

R2 layout mirrors the local output directory under a `data/latest/` prefix,
e.g. `data/latest/manifest.json`, `data/latest/daily/2026-08-25.json.gz`.
`.hash` sidecar files (output.py's own local rewrite-skip mechanism) are
never uploaded -- R2 objects carry their content hash as object metadata
instead (see build_upload_plan), so the bucket only ever holds files the
frontend actually fetches.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CONTENT_HASH_METADATA_KEY = "content-hash"
R2_PREFIX = "data/latest"

# manifest.json changes every run and gates whether the frontend sees a new
# forecast -- keep it near-fresh. Everything else can be rewritten in place
# on a later run (a date/hour/shard's content gets refined as the rolling
# forecast updates), so it must revalidate reasonably often too, NOT be
# cached as immutable -- see README "Forecast data hosting" for why the
# obvious-looking "immutable, max-age=1y" choice for dated files would be
# wrong here (their content is genuinely mutable while in the active
# window, only their filename is stable).
MANIFEST_CACHE_CONTROL = "public, max-age=60, no-cache"
DATA_FILE_CACHE_CONTROL = "public, max-age=900, must-revalidate"


@dataclass(frozen=True)
class LocalFile:
    rel_path: str  # e.g. "daily/2026-08-25.json.gz", relative to output_dir
    abs_path: Path
    content_hash: str


@dataclass(frozen=True)
class UploadPlan:
    to_upload: list[LocalFile]
    to_delete: list[str]  # R2 keys (with R2_PREFIX) to remove
    unchanged_count: int


def r2_key(rel_path: str) -> str:
    return f"{R2_PREFIX}/{rel_path}"


def collect_local_files(output_dir: Path) -> list[LocalFile]:
    """Every file that should exist in R2, mirroring exactly what
    prune_stale_output already keeps on local disk -- manifest.json plus
    every non-.hash file under output_dir. Content hash is read from the
    sidecar output.py already maintains where one exists (daily/hourly/
    series/cells files); manifest.json and locations/index.json.gz have no
    sidecar, so their hash is computed directly from file bytes.
    """
    import hashlib

    files: list[LocalFile] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".hash":
            continue
        rel_path = path.relative_to(output_dir).as_posix()
        hash_path = path.with_suffix(path.suffix + ".hash")
        if hash_path.exists():
            content_hash = hash_path.read_text(encoding="utf-8").strip()
        else:
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append(LocalFile(rel_path=rel_path, abs_path=path, content_hash=content_hash))
    return files


def build_upload_plan(local_files: list[LocalFile], remote_hashes: dict[str, str]) -> UploadPlan:
    """Decide what needs uploading/deleting.

    `remote_hashes` maps R2 key -> the content-hash metadata already stored
    on that object (from a prior publish). A file is (re-)uploaded when its
    key is missing remotely or its hash differs; a remote object is deleted
    when its key no longer corresponds to any local file (the same
    window-pruning behaviour prune_stale_output applies locally, applied to
    the bucket).
    """
    local_keys = {r2_key(f.rel_path) for f in local_files}
    to_upload = [f for f in local_files if remote_hashes.get(r2_key(f.rel_path)) != f.content_hash]
    to_delete = sorted(key for key in remote_hashes if key not in local_keys)
    unchanged_count = len(local_files) - len(to_upload)
    return UploadPlan(to_upload=to_upload, to_delete=to_delete, unchanged_count=unchanged_count)


def cache_control_for(rel_path: str) -> str:
    return MANIFEST_CACHE_CONTROL if rel_path == "manifest.json" else DATA_FILE_CACHE_CONTROL


def content_type_for(rel_path: str) -> tuple[str, str | None]:
    """Returns (Content-Type, Content-Encoding or None)."""
    if rel_path.endswith(".json.gz"):
        return "application/json", "gzip"
    if rel_path.endswith(".json"):
        return "application/json", None
    return "application/octet-stream", None
