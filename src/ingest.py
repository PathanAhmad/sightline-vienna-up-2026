"""Stage 1 — Ingest.

What it does: walks `data/Fotos/Fotos/`, records every photo file, and
loads the three GeoJSONs (trenches, FCPs, site cluster) into geopandas.

Reads:
    - data/Fotos/Fotos/**/*.{jpg,jpeg,png,heic}
    - data/geo/*.geojson

Writes:
    - data/processed/manifest.sqlite  (table `photos`)
        photo_id   TEXT  sha1 of file bytes
        rel_path   TEXT  path relative to PHOTOS_DIR
        filename   TEXT  basename only
        bytes      INT
        mtime      REAL

Returns (in-memory, not persisted): three GeoDataFrames in WGS84.

Notes:
- photo_id is the sha1 of the file bytes, not the path — so a rename or
  move doesn't break references in later stages.
- No EXIF parsing here. The dataset has none (WhatsApp strips it).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator


def iter_photo_files() -> Iterator[Path]:
    """Yield every photo file under PHOTOS_DIR. Order is filesystem-defined."""
    raise NotImplementedError("see PLAN.md → Data contracts → ingest")


def build_manifest() -> sqlite3.Connection:
    """Walk PHOTOS_DIR, write rows to manifest.sqlite, return the connection."""
    raise NotImplementedError("see PLAN.md → Data contracts → ingest")


def load_geo() -> tuple[object, object, object]:
    """Return (trenches_gdf, fcps_gdf, cluster_gdf) — all WGS84, EPSG:4326."""
    raise NotImplementedError("see PLAN.md → Data contracts → ingest")


def main() -> int:
    """Entry point for `python -m src.ingest`. Prints a one-line summary."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
