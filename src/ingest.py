"""Stage 1 — Ingest.

Walks `data/Fotos/Fotos/`, records every photo, and loads the three GeoJSONs
(trenches, FCP polygons, site cluster) into geopandas.

Reads:
    - data/Fotos/Fotos/**/*.{jpg,jpeg,png,heic}
    - data/geo/*.geojson

Writes:
    - data/processed/manifest.sqlite  (table `photos`)

In-memory only (no persistence): trenches_gdf, fcps_gdf, cluster_gdf — all
WGS84 / EPSG:4326. `load_geo()` also tags each trench LineString with the
`fcp_name` of the FCP polygon that contains its midpoint (with a
nearest-FCP fallback for trenches whose midpoint lands in an interior gap).

Notes:
- photo_id is sha1 of file BYTES, not the path — survives renames.
- No EXIF parsing. 0/50 sampled WhatsApp photos have any EXIF GPS.
- segment_id everywhere downstream = `externalID` from Trenches.geojson.
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
import time
import warnings
from pathlib import Path
from typing import Iterator

from src.paths import (
    CLUSTER_GEOJSON,
    FCPS_GEOJSON,
    MANIFEST_DB,
    PHOTOS_DIR,
    TRENCHES_GEOJSON,
    ensure_dirs,
)

PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic"}


def iter_photo_files() -> Iterator[Path]:
    """Yield every photo file under PHOTOS_DIR. Sorted by name for determinism."""
    for p in sorted(PHOTOS_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in PHOTO_SUFFIXES:
            yield p


def sha1_bytes(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def build_manifest() -> int:
    """Walk PHOTOS_DIR, write rows to manifest.sqlite. Return row count."""
    ensure_dirs()
    if MANIFEST_DB.exists():
        MANIFEST_DB.unlink()
    conn = sqlite3.connect(MANIFEST_DB)
    conn.execute("""
        CREATE TABLE photos (
            photo_id TEXT PRIMARY KEY,
            rel_path TEXT NOT NULL,
            filename TEXT NOT NULL,
            bytes    INTEGER NOT NULL,
            mtime    REAL    NOT NULL
        )
    """)
    n = 0
    collisions = 0
    with conn:
        for p in iter_photo_files():
            pid = sha1_bytes(p)
            rel = p.relative_to(PHOTOS_DIR).as_posix()
            st = p.stat()
            try:
                conn.execute(
                    "INSERT INTO photos (photo_id, rel_path, filename, bytes, mtime) VALUES (?,?,?,?,?)",
                    (pid, rel, p.name, st.st_size, st.st_mtime),
                )
                n += 1
            except sqlite3.IntegrityError:
                # Byte-identical duplicate. Rare but possible (file copied twice in dataset).
                collisions += 1
    conn.execute("CREATE INDEX idx_photos_filename ON photos(filename)")
    conn.close()
    if collisions:
        print(f"[ingest] {collisions} byte-identical duplicates skipped (kept first occurrence)")
    return n


def load_geo():
    """Return (trenches_gdf, fcps_gdf, cluster_gdf), all WGS84.

    Trenches get an extra `fcp_name` column derived spatially: the FCP polygon
    containing the LineString's midpoint, or the nearest FCP polygon by
    centroid distance if no polygon contains the midpoint (handles the 18.7%
    interior-gap problem from the data audit).
    """
    import geopandas as gpd  # imported lazily so other stages don't pay the cost

    trenches = gpd.read_file(TRENCHES_GEOJSON)
    fcps = gpd.read_file(FCPS_GEOJSON)
    cluster = gpd.read_file(CLUSTER_GEOJSON)

    for name, gdf in [("trenches", trenches), ("fcps", fcps), ("cluster", cluster)]:
        if gdf.crs is None:
            gdf.set_crs(epsg=4326, inplace=True)
        elif gdf.crs.to_epsg() != 4326:
            # OGC:CRS84 is equivalent to EPSG:4326 with swapped lon/lat ordering;
            # geopandas reads CRS84 GeoJSONs as 4326 in practice, but be defensive.
            gdf.to_crs(epsg=4326, inplace=True)

    # FCP polygons store the F-code in `kmlDescriptionSimple` as "F012 [81]" — strip the suffix.
    fcps["fcp_name"] = fcps["kmlDescriptionSimple"].str.split(" [", n=1, regex=False).str[0]

    # Tag each trench with its FCP. Midpoint-in-polygon, fallback to nearest centroid.
    # We're working in WGS84 (lat/lon). Containment is correct regardless of CRS.
    # Distance ordering inside the SiteCluster (~5km wide) is also fine in degrees —
    # the small lat/lon vs metric distortion doesn't change which centroid is nearest.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Geometry is in a geographic CRS")
        mids = trenches.geometry.interpolate(0.5, normalized=True)
        fcp_centroids = fcps.geometry.centroid
    fcp_polys = fcps.geometry
    fcp_names = fcps["fcp_name"].tolist()

    assigned: list[str] = []
    for mid in mids:
        found = None
        for poly, fn in zip(fcp_polys, fcp_names):
            if poly.contains(mid):
                found = fn
                break
        if found is None:
            # Nearest by centroid (fast; trench midpoints are within a few hundred meters of an FCP)
            dists = [mid.distance(c) for c in fcp_centroids]
            found = fcp_names[dists.index(min(dists))]
        assigned.append(found)
    trenches["fcp_name"] = assigned

    return trenches, fcps, cluster


def main() -> int:
    t0 = time.time()
    print(f"[ingest] walking {PHOTOS_DIR} ...")
    n_photos = build_manifest()
    dt_m = time.time() - t0

    t1 = time.time()
    trenches, fcps, cluster = load_geo()
    dt_g = time.time() - t1

    fcp_counts = trenches["fcp_name"].value_counts().to_dict()
    print(
        f"[ingest] {n_photos} photos -> {MANIFEST_DB.name} ({dt_m:.1f}s) | "
        f"{len(trenches)} trench segments, {len(fcps)} FCPs, "
        f"{len(cluster)} cluster polygon ({dt_g:.1f}s)"
    )
    print(f"[ingest] trenches by FCP: {fcp_counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
