#!/usr/bin/env python
"""Download the NMD2023 v2.x base layer raster used by static_features.py's
NMD override path (see forecast/src/static_features.py's module docstring).

Source: Naturvardsverket's national land cover product, CC0, no login
required. https://geodata.naturvardsverket.se/nedladdning/marktacke/NMD2023/

The published archive is a single ~2.5GB zip containing one national
GeoTIFF (~10.85GB uncompressed) plus a large ESRI/GeoPackage metadata
geodatabase we don't need (~2.7GB uncompressed, roughly half the zip's
compressed bytes). Rather than downloading the whole zip, this script:

  1. Fetches just the zip's end-of-central-directory + central directory
     (the last couple MB) via an HTTP Range request, to locate the main
     .tif entry's exact byte offset and compressed size without a full
     download.
  2. Range-downloads only those compressed bytes.
  3. Decompresses them as a raw DEFLATE stream (zip's compression method 8,
     no zlib/gzip wrapper) directly to data/static/nmd/, streaming so peak
     memory stays small even though the output is ~10.85GB.

Skips entirely if the output file already exists (re-run is a no-op unless
you delete it first, e.g. after a new NMD version is published).

Usage:
    python scripts/download_nmd_data.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import httpx

import _pathsetup  # noqa: F401
from config import STATIC_DATA_DIR

NMD_ZIP_URL = (
    "https://geodata.naturvardsverket.se/nedladdning/marktacke/"
    "NMD2023/Basskikt_v2_x/NMD2023_basskikt_v2_1.zip"
)
OUTPUT_FILENAME = "NMD2023bas_v2_1.tif"
TAIL_FETCH_SIZE = 2 * 1024 * 1024  # comfortably bigger than the central directory itself
REQUEST_TIMEOUT_S = 120.0
DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024


def _find_tif_entry(client: httpx.Client) -> tuple[int, int]:
    """(compressed_data_start_offset, compressed_size) for the main .tif
    entry inside the remote zip, found via its central directory rather
    than downloading the archive."""
    head = client.head(NMD_ZIP_URL)
    head.raise_for_status()
    total = int(head.headers["content-length"])

    tail_resp = client.get(
        NMD_ZIP_URL, headers={"Range": f"bytes={total - TAIL_FETCH_SIZE}-{total - 1}"}
    )
    tail_resp.raise_for_status()

    import io
    import zipfile

    zf = zipfile.ZipFile(io.BytesIO(tail_resp.content))
    # zipfile rebases header_offset against the start of the buffer we gave
    # it (which is only the tail of the real file), not the true file
    # offset -- undo that rebasing to recover real offsets into the full
    # remote zip.
    correction = total - TAIL_FETCH_SIZE

    tif_info = next(i for i in zf.infolist() if i.filename.endswith(".tif"))
    local_header_offset = tif_info.header_offset + correction

    header_resp = client.get(
        NMD_ZIP_URL, headers={"Range": f"bytes={local_header_offset}-{local_header_offset + 300}"}
    )
    header_resp.raise_for_status()
    h = header_resp.content
    if h[0:4] != b"PK\x03\x04":
        raise RuntimeError("Local file header signature mismatch -- zip layout may have changed")
    fname_len = struct.unpack("<H", h[26:28])[0]
    extra_len = struct.unpack("<H", h[28:30])[0]
    data_start = local_header_offset + 30 + fname_len + extra_len

    if tif_info.compress_type != zipfile.ZIP_DEFLATED:
        raise RuntimeError(f"Unexpected compression type {tif_info.compress_type}, expected DEFLATE")

    return data_start, tif_info.compress_size


def _download_and_inflate(client: httpx.Client, data_start: int, compress_size: int, out_path: Path) -> None:
    data_end = data_start + compress_size - 1
    decompressor = zlib.decompressobj(wbits=-15)  # raw deflate, no header
    written = 0
    with client.stream(
        "GET", NMD_ZIP_URL, headers={"Range": f"bytes={data_start}-{data_end}"}
    ) as resp:
        resp.raise_for_status()
        with open(out_path, "wb") as out:
            for chunk in resp.iter_bytes(DOWNLOAD_CHUNK_SIZE):
                out.write(decompressor.decompress(chunk))
                written += len(chunk)
                print(f"\r  {written / 1e6:.0f} / {compress_size / 1e6:.0f} MB compressed", end="", flush=True)
            out.write(decompressor.flush())
    print()


def main() -> None:
    nmd_dir = STATIC_DATA_DIR / "nmd"
    nmd_dir.mkdir(parents=True, exist_ok=True)
    out_path = nmd_dir / OUTPUT_FILENAME

    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"{out_path} already present, skipping. Delete it first to re-download.")
        return

    with httpx.Client(timeout=REQUEST_TIMEOUT_S, follow_redirects=True) as client:
        print("Locating main .tif entry in remote NMD2023 zip...")
        data_start, compress_size = _find_tif_entry(client)
        print(f"Found: {compress_size / 1e6:.0f} MB compressed, downloading and inflating...")

        tmp_path = out_path.with_suffix(".tif.partial")
        _download_and_inflate(client, data_start, compress_size, tmp_path)
        tmp_path.rename(out_path)

    print(f"Done: {out_path} ({out_path.stat().st_size / 1e9:.2f} GB)")


if __name__ == "__main__":
    main()
