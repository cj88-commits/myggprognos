from __future__ import annotations

import gzip
import json

from r2_sync import (
    LocalFile,
    build_upload_plan,
    cache_control_for,
    collect_local_files,
    content_type_for,
    r2_key,
)


def _write_gz(path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        fh.write(payload)


def test_collect_local_files_uses_hash_sidecar_when_present(tmp_path):
    _write_gz(tmp_path / "daily" / "2026-08-25.json.gz", b'[{"a":1}]')
    (tmp_path / "daily" / "2026-08-25.json.gz.hash").write_text("deadbeef", encoding="utf-8")

    files = collect_local_files(tmp_path)

    assert len(files) == 1
    assert files[0].rel_path == "daily/2026-08-25.json.gz"
    assert files[0].content_hash == "deadbeef"


def test_collect_local_files_hashes_manifest_directly(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"cell_count": 5}), encoding="utf-8")

    files = collect_local_files(tmp_path)

    assert len(files) == 1
    assert files[0].rel_path == "manifest.json"
    assert len(files[0].content_hash) == 64  # sha256 hex digest


def test_collect_local_files_never_includes_hash_sidecars(tmp_path):
    _write_gz(tmp_path / "cells.json.gz", b"[]")
    (tmp_path / "cells.json.gz.hash").write_text("abc123", encoding="utf-8")

    files = collect_local_files(tmp_path)

    assert [f.rel_path for f in files] == ["cells.json.gz"]


def test_build_upload_plan_uploads_new_and_changed_files():
    local = [
        LocalFile("manifest.json", None, "hash-a"),
        LocalFile("daily/2026-08-25.json.gz", None, "hash-b-new"),
        LocalFile("daily/2026-08-26.json.gz", None, "hash-c"),
    ]
    remote = {
        r2_key("manifest.json"): "hash-a",  # unchanged
        r2_key("daily/2026-08-25.json.gz"): "hash-b-old",  # changed
        # daily/2026-08-26.json.gz missing remotely -> new
    }

    plan = build_upload_plan(local, remote)

    uploaded_paths = {f.rel_path for f in plan.to_upload}
    assert uploaded_paths == {"daily/2026-08-25.json.gz", "daily/2026-08-26.json.gz"}
    assert plan.unchanged_count == 1
    assert plan.to_delete == []


def test_build_upload_plan_deletes_remote_files_outside_local_window():
    local = [LocalFile("daily/2026-08-25.json.gz", None, "hash-a")]
    remote = {
        r2_key("daily/2026-08-25.json.gz"): "hash-a",
        r2_key("daily/2026-07-01.json.gz"): "hash-stale",
        r2_key("hourly/2026-07-01T00.json.gz"): "hash-stale-2",
    }

    plan = build_upload_plan(local, remote)

    assert plan.to_upload == []
    assert plan.unchanged_count == 1
    assert sorted(plan.to_delete) == [
        r2_key("daily/2026-07-01.json.gz"),
        r2_key("hourly/2026-07-01T00.json.gz"),
    ]


def test_build_upload_plan_empty_remote_uploads_everything():
    local = [LocalFile("manifest.json", None, "hash-a"), LocalFile("cells.json.gz", None, "hash-b")]

    plan = build_upload_plan(local, {})

    assert len(plan.to_upload) == 2
    assert plan.unchanged_count == 0
    assert plan.to_delete == []


def test_cache_control_manifest_is_short_and_revalidated():
    assert "no-cache" in cache_control_for("manifest.json")


def test_cache_control_data_files_are_not_marked_immutable():
    # Daily/hourly/series content can be rewritten in place while still
    # within the active forecast window (see r2_sync module docstring) --
    # must never be cached as immutable, or users get stuck on stale data.
    for rel_path in ("daily/2026-08-25.json.gz", "hourly/2026-08-25T06.json.gz", "series/3.json.gz"):
        cache_control = cache_control_for(rel_path)
        assert "immutable" not in cache_control
        assert "max-age=900" in cache_control


def test_content_type_for_gzip_json_sets_encoding():
    content_type, encoding = content_type_for("daily/2026-08-25.json.gz")
    assert content_type == "application/json"
    assert encoding == "gzip"


def test_content_type_for_plain_json_has_no_encoding():
    content_type, encoding = content_type_for("manifest.json")
    assert content_type == "application/json"
    assert encoding is None
