"""Detect + extract a 'contractor bundle' upload (photos + operator lot package).

A lot bundle is a zip that contains both:
  * The operator's lot geojsons (Trenches, FCP_Polygons, SiteCluster_Polygons), and
  * The contractor's trench photos.

The operator ships its lot package as a zip-of-zips: each geojson is wrapped
in its own per-file `.zip`. Contractors may pack things flat too, so we
handle:

  outer.zip/
    CLP..._Trenches_geojson.zip      <- nested zip wrapping the geojson
    CLP..._FCP_Polygons_geojson.zip
    CLP..._SiteCluster_Polygons_geojson.zip
    IMG-001.jpg
    IMG-002.jpg

or:

  outer.zip/
    CLP..._Trenches.geojson           <- raw geojson, no nested zip
    CLP..._FCP_Polygons.geojson
    CLP..._SiteCluster_Polygons.geojson
    IMG-001.jpg
    ...

or just the operator's lot package alone (no photos), or just photos (no
geojsons -- in which case `extract_lot_bundle` returns None and the caller
falls back to plain-photo handling).

Detection rule: bundle if the zip contains a Trenches geojson somewhere
(raw or inside a `_geojson.zip` nested archive). Other lots are
out-of-scope for this hackathon.

Geojsons get written to a process-scoped temp dir so the rest of the
dashboard (which expects file paths, not bytes) can read them with
geopandas / json.load. Old temp dirs leak; the OS cleans /tmp.
"""
from __future__ import annotations

import io
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from src.ui.components.archive_expand import (
    IMAGE_EXTS,
    MAX_BYTES_PER_MEMBER,
    MAX_MEMBERS,
    _is_metadata,
)


# Geojson filename hints. Order matters for `_classify_geojson`: we test
# the most specific tag first so "FCP_Polygons" wins over "FCPs", and
# "SiteCluster_Polygons" wins over a bare "SiteCluster".
_GEOJSON_HINTS = (
    ("trenches",     "Trenches"),
    ("fcps",         "FCP_Polygons"),
    ("cluster",      "SiteCluster"),
)

# Match the operator lot id at the front of a filename: "CLP20417A-P1-B00".
_LOT_ID_RE = re.compile(r"\b(CLP\d{5}[A-Z]?(?:-P\d+)?(?:-B\d+)?)", re.IGNORECASE)


@dataclass
class LotBundle:
    """Result of unpacking a contractor bundle.

    `trenches_path`, `fcps_path`, `cluster_path` are real on-disk paths
    inside a session temp dir; the dashboard can load them like any
    other geojson. `photos` is the same shape as `archive_expand.expand`
    output -- (display_name, bytes) pairs ready to score.
    """
    lot_id: str
    trenches_path: Path
    fcps_path: Path
    cluster_path: Path
    photos: list[tuple[str, bytes]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def is_lot_bundle(name: str, data: bytes) -> bool:
    """Cheap check: does this look like a contractor bundle?

    Walks the outer zip's central directory only -- no per-file reads --
    so it's safe to call on every upload.
    """
    if not name.lower().endswith(".zip"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if _classify_geojson(info.filename) == "trenches":
                    return True
                if (
                    info.filename.lower().endswith("_geojson.zip")
                    and "trenches" in info.filename.lower()
                ):
                    return True
    except zipfile.BadZipFile:
        return False
    return False


def _classify_geojson(name: str) -> str | None:
    """Return 'trenches' / 'fcps' / 'cluster' for known geojson filenames,
    else None."""
    base = PurePosixPath(name).name.lower()
    if not base.endswith(".geojson"):
        return None
    for tag, hint in _GEOJSON_HINTS:
        if hint.lower() in base:
            return tag
    return None


def extract_lot_bundle(name: str, data: bytes) -> LotBundle | None:
    """Walk the outer zip, pull out trenches/fcps/cluster geojsons +
    photos. Returns None if the zip doesn't have at least a trenches
    geojson (i.e. it isn't really a bundle).
    """
    if not name.lower().endswith(".zip"):
        return None
    try:
        outer = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None

    geojsons: dict[str, tuple[str, bytes]] = {}  # tag -> (member_name, bytes)
    photos: list[tuple[str, bytes]] = []
    skipped: list[str] = []

    with outer:
        for info in outer.infolist():
            if info.is_dir() or _is_metadata(info.filename):
                continue
            lower = info.filename.lower()
            base = PurePosixPath(info.filename).name

            tag = _classify_geojson(info.filename)
            if tag is not None and tag not in geojsons:
                if info.file_size > MAX_BYTES_PER_MEMBER:
                    skipped.append(f"{base} (too large)")
                    continue
                with outer.open(info) as fh:
                    payload = fh.read(MAX_BYTES_PER_MEMBER + 1)
                if len(payload) > MAX_BYTES_PER_MEMBER:
                    skipped.append(f"{base} (too large)")
                    continue
                geojsons[tag] = (base, payload)
                continue

            # Nested per-file lot zip ("..._geojson.zip"): peek inside,
            # take the first geojson member.
            if lower.endswith("_geojson.zip"):
                with outer.open(info) as fh:
                    inner_bytes = fh.read(MAX_BYTES_PER_MEMBER + 1)
                if len(inner_bytes) > MAX_BYTES_PER_MEMBER:
                    skipped.append(f"{base} (too large)")
                    continue
                try:
                    inner = zipfile.ZipFile(io.BytesIO(inner_bytes))
                except zipfile.BadZipFile:
                    skipped.append(f"{base} (corrupt nested zip)")
                    continue
                with inner:
                    for inner_info in inner.infolist():
                        if inner_info.is_dir() or _is_metadata(inner_info.filename):
                            continue
                        inner_tag = _classify_geojson(inner_info.filename)
                        if inner_tag is None or inner_tag in geojsons:
                            continue
                        if inner_info.file_size > MAX_BYTES_PER_MEMBER:
                            skipped.append(
                                f"{inner_info.filename} (too large)")
                            continue
                        with inner.open(inner_info) as gh:
                            gpayload = gh.read(MAX_BYTES_PER_MEMBER + 1)
                        if len(gpayload) > MAX_BYTES_PER_MEMBER:
                            skipped.append(
                                f"{inner_info.filename} (too large)")
                            continue
                        inner_base = PurePosixPath(inner_info.filename).name
                        geojsons[inner_tag] = (inner_base, gpayload)
                        break
                continue

            # Image members.
            if (
                PurePosixPath(info.filename).suffix.lower() in IMAGE_EXTS
                and len(photos) < MAX_MEMBERS
            ):
                if info.file_size > MAX_BYTES_PER_MEMBER:
                    skipped.append(f"{base} (too large)")
                    continue
                with outer.open(info) as fh:
                    pbytes = fh.read(MAX_BYTES_PER_MEMBER + 1)
                if len(pbytes) > MAX_BYTES_PER_MEMBER:
                    skipped.append(f"{base} (too large)")
                    continue
                display = f"{name}/{base}"
                photos.append((display, pbytes))
                continue
            # everything else (POPs.geojson, FCPs lines, READMEs) is ignored

    if "trenches" not in geojsons:
        return None

    # Write the geojsons to a session temp dir. mkdtemp returns a unique
    # path so concurrent sessions don't collide. The dashboard uses these
    # as file paths going forward.
    out_dir = Path(tempfile.mkdtemp(prefix="ahmed_lot_"))
    paths: dict[str, Path] = {}
    for tag, (member_name, payload) in geojsons.items():
        p = out_dir / member_name
        p.write_bytes(payload)
        paths[tag] = p

    # FCPs / cluster fallback: dashboard refuses to start without all
    # three. Synthesize from the trenches' bounding box so the page at
    # least renders -- the snap logic will still work (FCPs are only
    # used to bucket candidates; a single bbox polygon as one FCP gives
    # a coarser but functional snap).
    if "fcps" not in paths or "cluster" not in paths:
        bbox_geo = _bbox_polygon_from_trenches(paths["trenches"])
        if bbox_geo is not None:
            if "fcps" not in paths:
                fpath = out_dir / "fallback_FCP_Polygons.geojson"
                fpath.write_text(bbox_geo)
                paths["fcps"] = fpath
                skipped.append("FCP_Polygons (synthesized from trench bbox)")
            if "cluster" not in paths:
                cpath = out_dir / "fallback_SiteCluster_Polygons.geojson"
                cpath.write_text(bbox_geo)
                paths["cluster"] = cpath
                skipped.append("SiteCluster (synthesized from trench bbox)")

    if {"trenches", "fcps", "cluster"} - set(paths):
        return None  # really can't render without the full set

    lot_id = _guess_lot_id(name) or _guess_lot_id(
        geojsons["trenches"][0]
    ) or "uploaded-lot"

    return LotBundle(
        lot_id=lot_id,
        trenches_path=paths["trenches"],
        fcps_path=paths["fcps"],
        cluster_path=paths["cluster"],
        photos=photos,
        skipped=skipped,
    )


def _guess_lot_id(text: str) -> str | None:
    m = _LOT_ID_RE.search(text)
    return m.group(1) if m else None


def _bbox_polygon_from_trenches(geojson_path: Path) -> str | None:
    """Build a single-polygon FeatureCollection covering all trench
    coordinates -- used as a last-resort FCP/cluster fallback so the
    dashboard can still render a lot whose package was incomplete.
    """
    import json

    try:
        gj = json.loads(geojson_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    lons: list[float] = []
    lats: list[float] = []

    def _walk(coords: object) -> None:
        if isinstance(coords, (list, tuple)):
            if (
                len(coords) >= 2
                and isinstance(coords[0], (int, float))
                and isinstance(coords[1], (int, float))
            ):
                lons.append(float(coords[0]))
                lats.append(float(coords[1]))
            else:
                for c in coords:
                    _walk(c)

    for feat in gj.get("features", []):
        _walk(feat.get("geometry", {}).get("coordinates"))
    if not lons or not lats:
        return None
    pad = 0.0005  # ~50m -- keeps the polygon from skimming the trenches
    min_lon, max_lon = min(lons) - pad, max(lons) + pad
    min_lat, max_lat = min(lats) - pad, max(lats) + pad
    ring = [
        [min_lon, min_lat], [max_lon, min_lat],
        [max_lon, max_lat], [min_lon, max_lat],
        [min_lon, min_lat],
    ]
    return json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "fcp_name": "F000",
                "kmlDescriptionSimple": "F000 [bbox]",
            },
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        }],
    })
