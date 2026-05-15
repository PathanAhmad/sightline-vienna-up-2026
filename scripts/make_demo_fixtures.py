"""Generate synthetic demo fixtures so app.py + src/report.py can run
end-to-end before the real pipeline produces verdicts.csv.

Run: `uv run python scripts/make_demo_fixtures.py`

Why fixtures: the demo surface (app.py, src/report.py) and the pipeline
(ingest/forensics/readqc/geomatch/classify) run in parallel — see the
split in the user message. The fixtures hold the contract shapes so the
UI is testable today; when the real outputs land in data/processed/
they shadow these naturally.

What this writes (all under demo_fixtures/):
  - geo/Trenches.geojson        20 stylized LineStrings near Maria Rain
  - geo/FCP_Polygons.geojson    2 square FCP polygons
  - geo/SiteCluster_Polygons.geojson  1 cluster polygon
  - manifest.sqlite             ~22 photo rows pointing at real filenames
                                under Resources/all/ (which exists locally,
                                gitignored). Filenames carry no PII; the
                                NDA is on geometry + addresses, both of
                                which are synthetic here.
  - forensics.jsonl             one entry per photo, two duplicate pairs
  - readqc.jsonl                one entry per *representative* (post-dedup)
  - geomatch.csv                one row per photo
  - verdicts.csv                one row per segment (mix GREEN/YELLOW/RED)

NDA hygiene:
  All overlay_address / overlay_latlon / segment geometry below are
  fictional. The only real-data reference is filenames in Resources/all/,
  used so the side panel can actually display a photo when run locally.
  No address or lat/lon string in any committed fixture file is taken
  from the real corpus.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "demo_fixtures"
GEO_DIR = FIXTURES_DIR / "geo"

# Stylized cluster center — vaguely Carinthia but the shape is a synthetic grid,
# not the real Maria Rain trench layout (NDA on route geometry).
CENTER_LAT = 46.5550
CENTER_LON = 14.2900

# Meters → degrees at 46.5°N. Good enough for a synthetic demo.
M_PER_DEG_LAT = 111_000
M_PER_DEG_LON = 76_400


def m_to_dlat(m: float) -> float:
    return m / M_PER_DEG_LAT


def m_to_dlon(m: float) -> float:
    return m / M_PER_DEG_LON


def build_trench_geometry() -> list[dict]:
    """20 LineString segments laid out like a small residential block.

    Geometry (waypoints in meters relative to CENTER; the script converts
    to WGS84 lat/lon):
      - Main spine (S001..S008): 8 segments meandering NW → SE
      - NE branch (S009..S013):  5 segments curving NE off the spine's
                                 SE end
      - SW branch (S014..S017):  4 segments going SW off the middle of
                                 the spine
      - Cul-de-sac (S018..S020): 3 segments looping back at the SW end

    Total ~20 segments, ~850 m of trench. FCP F001 covers the main spine
    (the "well-documented main street" in the demo narrative); F002
    covers everything else (the "missed side streets").

    All coordinates are synthetic. No real Maria Rain geometry is encoded
    here — see NDA note at the top of this file.
    """
    import math

    # Each waypoint: (meters_north_of_center, meters_east_of_center).
    spine = [
        (160, -220), (130, -170), (100, -130), (75, -85), (50, -45),
        (15, -10), (-20, 25), (-55, 60), (-90, 95),
    ]
    ne_branch = [
        spine[-1], (-65, 130), (-50, 165), (-30, 195), (-5, 215), (25, 235),
    ]
    sw_branch = [
        spine[5],  # mid-spine junction (the (15, -10) waypoint)
        (-5, -50), (-30, -85), (-65, -110), (-95, -130),
    ]
    cul_de_sac = [
        sw_branch[-1], (-125, -120), (-140, -90), (-115, -75),
    ]

    def to_lonlat(mn: float, me: float) -> list[float]:
        # GeoJSON uses [lon, lat] order.
        return [CENTER_LON + m_to_dlon(me), CENTER_LAT + m_to_dlat(mn)]

    def seg_length_m(a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def emit_chain(
        chain: list[tuple[float, float]],
        start_idx: int,
        fcp: str,
        duct: str,
    ) -> list[dict]:
        out: list[dict] = []
        for i in range(len(chain) - 1):
            a, b = chain[i], chain[i + 1]
            out.append({
                "segment_id": f"S{start_idx + i:03d}",
                "fcp_name": fcp,
                "duct_main_short": duct,
                "length_m": round(seg_length_m(a, b), 1),
                "coords": [to_lonlat(*a), to_lonlat(*b)],
            })
        return out

    segments: list[dict] = []
    segments += emit_chain(spine, 1, "F001", "R001")          # S001..S008
    segments += emit_chain(ne_branch, 9, "F002", "R002")      # S009..S013
    segments += emit_chain(sw_branch, 14, "F002", "R003")     # S014..S017
    segments += emit_chain(cul_de_sac, 18, "F002", "R004")    # S018..S020
    return segments


def _poly_lonlat(
    points_mn_me: list[tuple[float, float]],
) -> list[list[float]]:
    """Convert (north_m, east_m) points to a closed GeoJSON ring of
    [lon, lat]."""
    ring = [
        [CENTER_LON + m_to_dlon(me), CENTER_LAT + m_to_dlat(mn)]
        for mn, me in points_mn_me
    ]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def build_fcps_geojson(segments: list[dict]) -> dict:
    """Two stylized FCP polygons drawn loosely around the trench shapes.

    F001 wraps the main spine (NW → SE meander), F002 wraps everything
    else (the two branches + the cul-de-sac).
    """
    # F001 — irregular hexagon hugging the spine
    f001 = _poly_lonlat([
        (175, -245), (180, -110), (50, 5), (-30, 50),
        (-110, 110), (-120, 25), (-50, -100), (130, -245),
    ])
    # F002 — multi-vertex polygon covering NE branch + SW branch + loop
    f002 = _poly_lonlat([
        (45, 260), (-15, 235), (-55, 175), (-110, 110),
        (-160, 0), (-155, -150), (-100, -160), (-35, -115),
        (10, -50), (35, 5), (15, 110), (35, 195),
    ])
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"fcpName": "F001"},
                "geometry": {"type": "Polygon", "coordinates": [f001]},
            },
            {
                "type": "Feature",
                "properties": {"fcpName": "F002"},
                "geometry": {"type": "Polygon", "coordinates": [f002]},
            },
        ],
    }


def build_cluster_geojson() -> dict:
    """A loose polygon enclosing everything (spine + branches + loop)."""
    coords = _poly_lonlat([
        (200, -260), (60, 270), (-180, 260), (-200, -180), (-110, -240),
    ])
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"clusterName": "CLP_DEMO"},
                "geometry": {"type": "Polygon", "coordinates": [coords]},
            }
        ],
    }


def build_trenches_geojson(segments: list[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "globalID": s["segment_id"],
                    "fcpName": s["fcp_name"],
                    "ductMainShort": s["duct_main_short"],
                    "length_m": s["length_m"],
                },
                "geometry": {"type": "LineString", "coordinates": s["coords"]},
            }
            for s in segments
        ],
    }


# ---------------------------------------------------------------------------
# Photo + QC + geomatch fixtures
# ---------------------------------------------------------------------------

# Hand-picked real filenames from Resources/all/. Used as photo_id sources so
# the side panel can render an actual image when running locally. These
# filenames contain no PII; the NDA is on the trench geometry + addresses,
# both of which are stylized in this file.
PHOTO_FILES = [
    "1_IMG-20240731-WA0029.jpg",          # 0
    "1_IMG-20240731-WA0030.jpg",          # 1
    "1_IMG-20240809-WA0025.jpg",          # 2
    "1_IMG-20240809-WA0038.jpg",          # 3
    "1_IMG-20240812-WA0033.jpg",          # 4
    "1_IMG-20240812-WA0034.jpg",          # 5
    "1_IMG-20240813-WA0028.jpg",          # 6
    "1_IMG-20240813-WA0031.jpg",          # 7
    "1_IMG-20240813-WA0034.jpg",          # 8
    "1_IMG-20240813-WA0036.jpg",          # 9
    "1_IMG-20240814-WA0045.jpg",          # 10
    "1_IMG-20240814-WA0046.jpg",          # 11
    "1_IMG-20240814-WA0048.jpg",          # 12
    "1_IMG-20240816-WA0041.jpg",          # 13
    "1_IMG-20240816-WA0045.jpg",          # 14
    "1_IMG-20240822-WA0010.jpg",          # 15
    "1_IMG-20240822-WA0011.jpg",          # 16
    "1_IMG-20240822-WA0019.jpg",          # 17
    "1_IMG-20240911-WA0030.jpg",          # 18
    "1_IMG-20240911-WA0035.jpg",          # 19
    "1_TimePhoto_20240807_182537.jpg",    # 20
    "IMG-20240723-WA0028 — копия.jpg",    # 21 — duplicate marker file
    "1_IMG-20240911-WA0091.jpg",          # 22 — used for not-classified (off_topic)
    "1_IMG-20240911-WA0092.jpg",          # 23 — used for ela_flag tamper hint
]


# Fake addresses (NOT from the real dataset).
FAKE_ADDRESSES = [
    "12 Demo-Straße, Synthville",
    "14 Demo-Straße, Synthville",
    "1 Mockstrasse, Synthville",
    "3 Mockstrasse, Synthville",
    "5 Mockstrasse, Synthville",
    "22 Beispielweg, Synthville",
]


def photo_id_for(filename: str) -> str:
    """Synthetic photo_id from filename. The real pipeline uses sha1 of bytes;
    for fixtures, a stable slug is fine."""
    return "fx_" + "".join(c if c.isalnum() else "_" for c in filename.lower())[:48]


def build_photo_records(segments: list[dict]) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Return (manifest_rows, forensics_rows, readqc_rows, geomatch_rows).

    Hand-crafted to produce a mix of GREEN/YELLOW/RED segments and to
    surface the killer demo flags (duplicates, geo-mismatch, personal data).
    """

    # Helper to make a readqc row with sensible defaults.
    def qc(
        photo_idx: int,
        relevance: str = "scorable",
        phase: str = "duct_laid",
        warning_tape: str = "yes",
        sand_bedding: str = "yes",
        side_view: str = "yes",
        depth_ref: str = "no",
        depth_cm: float | None = None,
        duct: str = "yes",
        pipe_sealed: str = "yes",
        personal_data: str = "no",
        address: str = FAKE_ADDRESSES[0],
        latlon: str | None = None,
        paper_label: str | None = None,
        note: str = "",
    ) -> dict:
        filename = PHOTO_FILES[photo_idx]
        return {
            "photo_id": photo_id_for(filename),
            "model": "claude-sonnet-4-6",
            "cost_usd": 0.0046,
            "relevance": relevance,
            "phase": phase,
            "warning_tape_visible": warning_tape,
            "sand_bedding_visible": sand_bedding,
            "side_view_present": side_view,
            "depth_reference_visible": depth_ref,
            "depth_value_cm": depth_cm,
            "duct_visible": duct,
            "pipe_ends_sealed": pipe_sealed,
            "personal_data_visible": personal_data,
            "overlay_date": "26.08.2024 14:30",
            "overlay_address": address,
            "overlay_latlon": latlon,
            "paper_label_code": paper_label,
            "note": note,
        }

    # Segment story (drives photo allocation below):
    #   S001/S002/S003 GREEN — 3 compliant photos each (9 files)
    #   S004 YELLOW — 2 photos with a >5m gap (2 files)
    #   S005 YELLOW — 1 personal-data photo + 1 off-topic photo (2 files)
    #   S006 YELLOW — duplicate-reuse demo (1 representative + 1 dup) (2 files)
    #   S007 GREEN — 3 compliant + 1 ELA-flagged (4 files)
    #   S008 YELLOW — 1 photo flagged latlon ↔ address mismatch (1 file)
    #   S011 GREEN — 3 compliant (3 files)
    #   S015 YELLOW — phase tape_laid but warning_tape_visible=no (1 file)
    #   S009/S010/S012-S014/S016-S020 RED — no photos (0 files)
    # Total: 24 photo records (23 distinct files + 1 inherited duplicate).
    photo_specs: list[dict] = []
    file_cursor = 0

    def use_next_file() -> int:
        nonlocal file_cursor
        i = file_cursor
        file_cursor += 1
        return i

    def emit(segment_id, t, **qc_kwargs):
        i = use_next_file()
        photo_specs.append({"photo_idx": i, "segment_id": segment_id, "t": t, "qc": qc_kwargs})

    # GREEN S001
    emit("S001", 0.05, phase="excavation", depth_ref="yes", depth_cm=82,
         warning_tape="no", sand_bedding="no",
         address=FAKE_ADDRESSES[0],
         latlon="46°33'18.0\"N 14°17'19.0\"E",
         paper_label="F001-R001-11-or",
         note="Open trench. Side wall clean. Depth marker visible.")
    emit("S001", 0.45, phase="duct_laid",
         address=FAKE_ADDRESSES[0], paper_label="F001-R001-11-or",
         note="Duct bundle laid; bedding still required.")
    emit("S001", 0.90, phase="sand_bedded",
         address=FAKE_ADDRESSES[0], paper_label="F001-R001-11-or",
         note="Sand evenly distributed.")

    # GREEN S002
    emit("S002", 0.08, phase="duct_laid",
         address=FAKE_ADDRESSES[1], paper_label="F001-R001-12-or")
    emit("S002", 0.50, phase="sand_bedded",
         address=FAKE_ADDRESSES[1], paper_label="F001-R001-12-or")
    emit("S002", 0.92, phase="tape_laid", warning_tape="yes",
         address=FAKE_ADDRESSES[1], paper_label="F001-R001-12-or")

    # GREEN S003
    emit("S003", 0.10, phase="excavation", depth_ref="yes", depth_cm=78,
         warning_tape="no", sand_bedding="no",
         address=FAKE_ADDRESSES[2], paper_label="F001-R001-13-or")
    emit("S003", 0.50, phase="duct_laid",
         address=FAKE_ADDRESSES[2], paper_label="F001-R001-13-or")
    emit("S003", 0.92, phase="sand_bedded",
         address=FAKE_ADDRESSES[2], paper_label="F001-R001-13-or")

    # YELLOW S004 — gap: only 2 photos at t=0.05 and t=0.70 (gap 26m on a 40m seg)
    emit("S004", 0.05, phase="duct_laid",
         address=FAKE_ADDRESSES[3], paper_label="F001-R001-14-or")
    emit("S004", 0.70, phase="sand_bedded",
         address=FAKE_ADDRESSES[3], paper_label="F001-R001-14-or")

    # YELLOW S005 — single photo with personal_data_visible=yes.
    emit("S005", 0.50, phase="paper_label", personal_data="yes",
         warning_tape="no", sand_bedding="no", side_view="no",
         duct="no", pipe_sealed="not_applicable",
         address=FAKE_ADDRESSES[4], paper_label="F001-R001-15-or",
         note="Paper label close-up; worker's face partially visible.")

    # YELLOW S006 — duplicate-reuse demo: representative + 1 inherited dup.
    rep_idx = use_next_file()
    photo_specs.append({
        "photo_idx": rep_idx, "segment_id": "S006", "t": 0.50,
        "qc": dict(phase="duct_laid",
                   address=FAKE_ADDRESSES[5],
                   paper_label="F001-R001-16-or",
                   note="Same image was submitted to job #DEMO-A1 and #DEMO-A2."),
        "is_representative": True,
        "phash_cluster_id": 1,
    })
    # The duplicate: same filename, but distinct photo_id (use копия variant
    # from PHOTO_FILES[21]).
    dup_idx = use_next_file()
    photo_specs.append({
        "photo_idx": dup_idx, "segment_id": "S006", "t": 0.50,
        "qc": None,  # inherits the rep
        "is_representative": False,
        "phash_cluster_id": 1,
        "duplicate_of": photo_id_for(PHOTO_FILES[rep_idx]),
    })

    # GREEN S007
    emit("S007", 0.10, phase="duct_laid",
         address=FAKE_ADDRESSES[0], paper_label="F002-R001-11-or")
    emit("S007", 0.50, phase="sand_bedded",
         address=FAKE_ADDRESSES[0], paper_label="F002-R001-11-or")
    emit("S007", 0.92, phase="tape_laid", warning_tape="yes",
         address=FAKE_ADDRESSES[0], paper_label="F002-R001-11-or")

    # YELLOW S008 — latlon ↔ address mismatch (the geo-mismatch demo).
    emit("S008", 0.50, phase="duct_laid",
         address="78 Wrongtown-Strasse, OffCluster",
         latlon="46°33'18.0\"N 14°17'21.0\"E",
         paper_label="F002-R001-12-or",
         note="Coordinates and printed address disagree by 1.7 km — flagged off-cluster.")

    # S009, S010 RED — no photos.
    # S011 GREEN
    emit("S011", 0.10, phase="duct_laid",
         address=FAKE_ADDRESSES[1], paper_label="F002-R002-11-or")
    emit("S011", 0.50, phase="sand_bedded",
         address=FAKE_ADDRESSES[1], paper_label="F002-R002-11-or")
    emit("S011", 0.92, phase="tape_laid", warning_tape="yes",
         address=FAKE_ADDRESSES[1], paper_label="F002-R002-11-or")

    # S013, S014 RED — no photos.
    # YELLOW S015 — phase tape_laid, but warning_tape_visible=no → quality fail
    emit("S015", 0.50, phase="tape_laid", warning_tape="no",
         address=FAKE_ADDRESSES[2], paper_label="F002-R003-11-or",
         note="Tape phase but no warning tape visible. Likely missed by contractor.")

    # Two additional photos that surface in the report buckets even though
    # they're not on a segment-with-photos: one off_topic (relevance gate
    # drop) and one ELA-flagged (forensics tamper hint). Both attach to
    # S005 nominally for geomatch, but readqc.relevance / forensics.ela_flag
    # excludes them from compliant counting.
    emit("S005", 0.10, relevance="off_topic", phase="other",
         warning_tape="no", sand_bedding="no", side_view="no",
         depth_ref="no", duct="no", pipe_sealed="not_applicable",
         address=FAKE_ADDRESSES[4],
         note="Dumpster / staging area; not a trench photo.")
    # ELA-flagged: pass it through normally but mark in forensics.
    emit("S007", 0.30, phase="duct_laid", _ela_flag=True,
         address=FAKE_ADDRESSES[0], paper_label="F002-R001-11-or",
         note="Visually plausible but ELA suggests re-save / re-compression.")

    # S016 — S020 RED — no photos.

    return photo_specs


# ---------------------------------------------------------------------------
# Compose all artifacts and write them.
# ---------------------------------------------------------------------------

def write_manifest_sqlite(photo_specs: list[dict], path: Path) -> None:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE photos (
            photo_id TEXT PRIMARY KEY,
            rel_path TEXT NOT NULL,
            filename TEXT NOT NULL,
            bytes    INTEGER NOT NULL,
            mtime    REAL NOT NULL
        )
        """
    )
    now = time.time()
    seen = set()
    for spec in photo_specs:
        filename = PHOTO_FILES[spec["photo_idx"]]
        pid = photo_id_for(filename) if spec.get("is_representative", True) else (
            "fx_dup_" + photo_id_for(filename)[3:]
        )
        if pid in seen:
            continue
        seen.add(pid)
        spec["_photo_id"] = pid  # back-fill so other writers see it
        conn.execute(
            "INSERT INTO photos (photo_id, rel_path, filename, bytes, mtime) VALUES (?, ?, ?, ?, ?)",
            (pid, filename, filename, 1_500_000, now),
        )
    conn.commit()
    conn.close()


def _stable_hash(pid: str) -> int:
    """Deterministic across runs — Python's hash() is salted per process,
    which would churn the committed fixtures on every regenerate."""
    return int(hashlib.sha1(pid.encode("utf-8")).hexdigest(), 16)


def write_forensics(photo_specs: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for spec in photo_specs:
            pid = spec["_photo_id"]
            cluster_id = spec.get("phash_cluster_id")
            is_rep = spec.get("is_representative", True)
            if cluster_id is None:
                cluster_id = _stable_hash(pid) % 100000
            qc_kwargs = spec.get("qc") or {}
            ela_flag = bool(qc_kwargs.get("_ela_flag"))
            row = {
                "photo_id": pid,
                "phash": f"{_stable_hash(pid) % (16 ** 16):016x}",
                "phash_cluster_id": cluster_id,
                "is_phash_representative": is_rep,
                "ela_score": 0.18 if ela_flag else 0.02,
                "ela_flag": ela_flag,
            }
            f.write(json.dumps(row) + "\n")


def write_readqc(photo_specs: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for spec in photo_specs:
            if not spec.get("is_representative", True):
                continue  # duplicates inherit; no own readqc row
            qc_kwargs = spec.get("qc") or {}
            pid = spec["_photo_id"]
            # Defaults
            row = {
                "photo_id": pid,
                "model": "claude-sonnet-4-6",
                "cost_usd": 0.0046,
                "relevance": "scorable",
                "phase": "duct_laid",
                "warning_tape_visible": "yes",
                "sand_bedding_visible": "yes",
                "side_view_present": "yes",
                "depth_reference_visible": "no",
                "depth_value_cm": None,
                "duct_visible": "yes",
                "pipe_ends_sealed": "yes",
                "personal_data_visible": "no",
                "overlay_date": "26.08.2024 14:30",
                "overlay_address": FAKE_ADDRESSES[0],
                "overlay_latlon": None,
                "paper_label_code": None,
                "note": "",
            }
            # Apply kwargs aliases.
            alias = {
                "warning_tape": "warning_tape_visible",
                "sand_bedding": "sand_bedding_visible",
                "side_view": "side_view_present",
                "depth_ref": "depth_reference_visible",
                "depth_cm": "depth_value_cm",
                "duct": "duct_visible",
                "pipe_sealed": "pipe_ends_sealed",
                "personal_data": "personal_data_visible",
                "address": "overlay_address",
                "latlon": "overlay_latlon",
                "paper_label": "paper_label_code",
            }
            for k, v in qc_kwargs.items():
                if k.startswith("_"):
                    continue  # fixture-only flag (e.g. _ela_flag)
                key = alias.get(k, k)
                row[key] = v
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_geomatch(photo_specs: list[dict], segments: list[dict], path: Path) -> None:
    seg_by_id = {s["segment_id"]: s for s in segments}
    fields = [
        "photo_id", "lat", "lon", "coord_source", "segment_id", "segment_t",
        "snap_distance_m", "fcp_name", "fcp_assignment",
        "label_match", "latlon_vs_address_flag",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for spec in photo_specs:
            pid = spec["_photo_id"]
            seg_id = spec["segment_id"]
            seg = seg_by_id[seg_id]
            t = spec["t"]
            (lon_a, lat_a), (lon_b, lat_b) = seg["coords"]
            lat = lat_a + (lat_b - lat_a) * t
            lon = lon_a + (lon_b - lon_a) * t
            qc = spec.get("qc") or {}
            mismatch_flag = "true" if seg_id == "S008" else "false"
            coord_source = "overlay_latlon" if qc.get("latlon") else "geocoded_address"
            w.writerow([
                pid,
                f"{lat:.6f}", f"{lon:.6f}",
                coord_source,
                seg_id,
                f"{t:.3f}",
                "1.2",
                seg["fcp_name"],
                "inside_polygon",
                "ok",
                mismatch_flag,
            ])


def write_verdicts(photo_specs: list[dict], segments: list[dict], path: Path) -> None:
    """Roll up per-segment verdict for the fixture. Encoded by hand to
    match the story comments above — not a real Layer A/B rollup."""
    story = {
        "S001": ("GREEN", "all checks ok; 3 compliant photos covering 40m"),
        "S002": ("GREEN", "all checks ok; 3 compliant photos covering 40m"),
        "S003": ("GREEN", "all checks ok; 3 compliant photos covering 40m"),
        "S004": ("YELLOW", "max gap 26m > 5m between meter 2 and meter 28"),
        "S005": ("YELLOW", "1 personal-data photo excluded; 1 off-topic photo excluded; no other photos"),
        "S006": ("YELLOW", "duplicate photo reused on this segment (1 representative, 1 inherited duplicate)"),
        "S007": ("GREEN", "3 compliant photos; 1 photo ELA-flagged (kept; soft warning)"),
        "S008": ("YELLOW", "lat/lon and printed address disagree by 1.7 km (off-cluster)"),
        "S009": ("RED",   "no photos snapped to this segment"),
        "S010": ("RED",   "no photos snapped to this segment"),
        "S011": ("GREEN", "all checks ok; 3 compliant photos"),
        "S012": ("RED",   "no photos snapped to this segment"),
        "S013": ("RED",   "no photos snapped to this segment"),
        "S014": ("RED",   "no photos snapped to this segment"),
        "S015": ("YELLOW", "tape_laid phase but warning tape not visible"),
        "S016": ("RED",   "no photos snapped to this segment"),
        "S017": ("RED",   "no photos snapped to this segment"),
        "S018": ("RED",   "no photos snapped to this segment"),
        "S019": ("RED",   "no photos snapped to this segment"),
        "S020": ("RED",   "no photos snapped to this segment"),
    }
    photo_counts: dict[str, int] = {}
    for spec in photo_specs:
        photo_counts[spec["segment_id"]] = photo_counts.get(spec["segment_id"], 0) + 1

    fields = [
        "segment_id", "fcp_name", "length_m", "photo_count", "compliant_photo_count",
        "max_gap_m", "density_photos_per_5m", "verdict", "reasons",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for s in segments:
            sid = s["segment_id"]
            verdict, reasons = story[sid]
            photos = photo_counts.get(sid, 0)
            compliant = {
                "GREEN": photos,
                "YELLOW": max(photos - 1, 0),
                "RED": 0,
            }[verdict]
            density = compliant / (s["length_m"] / 5) if s["length_m"] else 0.0
            max_gap = {
                "GREEN": 4.0,
                "YELLOW": 26.0 if sid == "S004" else 12.0,
                "RED": float(s["length_m"]),
            }[verdict]
            w.writerow([
                sid, s["fcp_name"], s["length_m"], photos, compliant,
                f"{max_gap:.1f}", f"{density:.2f}", verdict, reasons,
            ])


def main() -> int:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    GEO_DIR.mkdir(parents=True, exist_ok=True)

    segments = build_trench_geometry()
    trenches = build_trenches_geojson(segments)
    fcps = build_fcps_geojson(segments)
    cluster = build_cluster_geojson()

    (GEO_DIR / "Trenches.geojson").write_text(json.dumps(trenches, indent=2))
    (GEO_DIR / "FCP_Polygons.geojson").write_text(json.dumps(fcps, indent=2))
    (GEO_DIR / "SiteCluster_Polygons.geojson").write_text(json.dumps(cluster, indent=2))

    photo_specs = build_photo_records(segments)

    write_manifest_sqlite(photo_specs, FIXTURES_DIR / "manifest.sqlite")
    write_forensics(photo_specs, FIXTURES_DIR / "forensics.jsonl")
    write_readqc(photo_specs, FIXTURES_DIR / "readqc.jsonl")
    write_geomatch(photo_specs, segments, FIXTURES_DIR / "geomatch.csv")
    write_verdicts(photo_specs, segments, FIXTURES_DIR / "verdicts.csv")

    n_segments = len(segments)
    n_photos = len(photo_specs)
    n_reps = sum(1 for s in photo_specs if s.get("is_representative", True))
    print(
        f"[fixtures] wrote {n_segments} segments, {n_photos} photo records "
        f"({n_reps} reps, {n_photos - n_reps} duplicates) → {FIXTURES_DIR.relative_to(REPO_ROOT)}/"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
