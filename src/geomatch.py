"""Stage 4 -- Geomatch (photo -> LineString segment).

For every representative photo we have a QC row for, figure out which
trench LineString it documents and where along that segment it sits.
Non-representative duplicates inherit their representative's row.

Reads:
    - data/processed/readqc.jsonl     (overlay_latlon, overlay_address, paper_label_code)
    - data/processed/forensics.jsonl  (phash_cluster_id, is_phash_representative)
    - data/geo/*.geojson              (trenches, FCPs, site cluster) via ingest.load_geo()

Writes:
    - data/processed/geomatch.csv     (one row per photo, columns per PLAN)
    - data/processed/nominatim_cache.json  (persistent address -> latlon cache)

Snap order:
    1. Lat/lon parsed -> snap to nearest LineString.
    2. Address only -> Nominatim forward-geocode (cached) -> nearest
       LineString restricted to the FCP polygon containing the point.
    3. Neither -> coord_source = "none", segment_id empty.

Cross-checks (don't block):
    latlon_vs_address_flag: lat/lon AND address present, geocode address,
        haversine > 150m AND road-name fuzzy-different -> flag.
    label_match: parse paper code F###-R###..., compare to snapped
        trench's fcp_name + ductMainShort.

Internal CRS:
    Trenches/FCPs are stored in WGS84 (EPSG:4326). We reproject ONCE to
    UTM 33N (EPSG:32633, the right zone for Carinthia) for distance &
    interpolate math. All output lat/lon is back in WGS84.

Nominatim contract:
    User-Agent: "ViennaUP2026/0.1 (pathanahmad2334@gmail.com)"
    Rate limit: 1 req/sec (sleep 1.1s between *uncached* calls).
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.ingest import load_geo
from src.paths import (
    FORENSICS_JSONL,
    GEOMATCH_CSV,
    PROCESSED_DIR,
    READQC_JSONL,
    ensure_dirs,
)

UTM_EPSG = 32633   # WGS84 / UTM zone 33N -- correct for Carinthia, Austria
LATLON_VS_ADDRESS_DIST_M = 150.0
PAPER_LABEL_RE = re.compile(r"\bF(\d{3})\b.*?\bR(\d{3})\b", re.IGNORECASE)
NOMINATIM_USER_AGENT = "ViennaUP2026/0.1 (pathanahmad2334@gmail.com)"
NOMINATIM_THROTTLE_S = 1.1
NOMINATIM_CACHE = PROCESSED_DIR / "nominatim_cache.json"


# ---------------------------------------------------------------------------
# Lat/lon parsers
# ---------------------------------------------------------------------------

# DMS pattern: 46°33'56.226"N -- with either period or comma for decimal.
# `°` is REQUIRED so we don't accidentally match a pure decimal like 46.56153856.
_DMS_RE = re.compile(
    r"""
    (?P<deg>\d{1,3}) \s* [°º] \s*
    (?P<min>\d{1,2}) \s* ['’ʼ]? \s*
    (?P<sec>\d{1,3}(?:[.,]\d+)?) \s* ["”ʺ]? \s*
    (?P<hemi>[NSEW])
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Decimal pattern: 46.56153856N or 46.56°N or "Lat 46.55, Long 14.29".
# Either a trailing hemisphere letter OR a leading Lat/Long label must be present.
_DEC_LABELED_RE = re.compile(
    r"\b(?P<label>Lat(?:itude)?|Long(?:itude)?)\b\s*[:=]?\s*"
    r"(?P<num>-?\d{1,3}[.,]\d+)",
    re.IGNORECASE,
)
_DEC_HEMI_RE = re.compile(
    r"(?P<num>\d{1,3}[.,]\d+)\s*[°º]?\s*(?P<hemi>[NSEW])",
    re.IGNORECASE,
)


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


def parse_overlay_latlon(s: str | None) -> tuple[float, float] | None:
    """Return (lat, lon) decimal degrees, or None if unparseable.

    Tries: DMS-period, DMS-comma, decimal-no-separators, labeled-decimal.
    """
    if not s:
        return None
    text = s.strip()
    # Normalise weird unicode quotes
    text = text.replace("´", "'").replace("′", "'").replace("″", '"')

    # DMS first (greedier pattern; if it matches we trust it)
    dms_matches = list(_DMS_RE.finditer(text))
    if len(dms_matches) >= 2:
        coords: dict[str, float] = {}
        for m in dms_matches[:2]:
            deg = float(m.group("deg"))
            mn  = float(m.group("min"))
            sc  = _to_float(m.group("sec"))
            val = deg + mn / 60 + sc / 3600
            h = m.group("hemi").upper()
            if h in {"S", "W"}:
                val = -val
            coords["lat" if h in {"N", "S"} else "lon"] = val
        if "lat" in coords and "lon" in coords:
            return (coords["lat"], coords["lon"])

    # Decimal-with-hemisphere first: 46.56153856N 14.28786228E
    dec_h = list(_DEC_HEMI_RE.finditer(text))
    if len(dec_h) >= 2:
        coords = {}
        for m in dec_h[:2]:
            val = _to_float(m.group("num"))
            h = m.group("hemi").upper()
            if h in {"S", "W"}:
                val = -val
            coords["lat" if h in {"N", "S"} else "lon"] = val
        if "lat" in coords and "lon" in coords:
            return (coords["lat"], coords["lon"])

    # Labeled decimal: "Lat 46.55, Long 14.29" -- hemisphere inferred from label.
    dec_l = list(_DEC_LABELED_RE.finditer(text))
    if len(dec_l) >= 2:
        coords = {}
        for m in dec_l[:2]:
            val = _to_float(m.group("num"))
            key = "lat" if m.group("label").lower().startswith("lat") else "lon"
            coords[key] = val
        if "lat" in coords and "lon" in coords:
            return (coords["lat"], coords["lon"])

    return None


# ---------------------------------------------------------------------------
# Nominatim with persistent cache
# ---------------------------------------------------------------------------

def _load_cache() -> dict[str, dict]:
    if NOMINATIM_CACHE.exists():
        try:
            return json.loads(NOMINATIM_CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict[str, dict]) -> None:
    ensure_dirs()
    NOMINATIM_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _nominatim_call(q: str) -> dict | None:
    url = "https://nominatim.openstreetmap.org/search?" + urlencode({
        "q": q,
        "format": "json",
        "limit": 1,
        "countrycodes": "at",
        "addressdetails": 1,
    })
    req = Request(url, headers={"User-Agent": NOMINATIM_USER_AGENT, "Accept-Language": "de,en"})
    with urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    if not data:
        return None
    r = data[0]
    return {
        "lat": float(r["lat"]),
        "lon": float(r["lon"]),
        "road": r.get("address", {}).get("road", ""),
        "display_name": r.get("display_name", ""),
    }


class Geocoder:
    """Cached forward-geocoder. Throttles uncached calls to 1.1s."""

    def __init__(self) -> None:
        self.cache = _load_cache()
        self._last_call = 0.0

    def __call__(self, address: str) -> dict | None:
        if not address:
            return None
        key = address.strip()
        if key in self.cache:
            return self.cache[key] or None
        # Throttle. Sleep relative to last network call only.
        wait = NOMINATIM_THROTTLE_S - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            result = _nominatim_call(key)
        except Exception as e:
            # NDA: don't echo full address to stdout/stderr (the terminal can
            # end up in screenshots, demo recordings, or pasted bug reports).
            redacted = (key[:3] + "...") if len(key) > 3 else "..."
            print(f"[geomatch] Nominatim error on addr={redacted!r}: {type(e).__name__}", file=sys.stderr)
            return None
        self._last_call = time.time()
        # Cache even null results so we don't retry every run
        self.cache[key] = result or {}
        return result

    def save(self) -> None:
        _save_cache(self.cache)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _norm_street(s: str) -> set[str]:
    """Lower, strip diacritics, split into word tokens. Useful for fuzzy compare."""
    if not s:
        return set()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    # Drop common umlaut transliteration artefacts and house numbers
    return {w for w in re.split(r"[^a-z]+", s) if w and not w.isdigit() and len(w) > 2}


def streets_disagree(addr_a: str, addr_b: str) -> bool:
    """True if the two address strings share NO meaningful street tokens."""
    a, b = _norm_street(addr_a), _norm_street(addr_b)
    if not a or not b:
        return False
    # Tolerate "strasse"/"strae"/"strae" residues
    a |= {w.replace("strasse", "") for w in a if "strasse" in w}
    b |= {w.replace("strasse", "") for w in b if "strasse" in w}
    return not (a & b)


def parse_paper_label(code: str | None) -> tuple[str, str] | None:
    """Extract (F-code, R-code) from "F170-R084-11-or" -> ("F170", "R084")."""
    if not code:
        return None
    m = PAPER_LABEL_RE.search(code)
    if not m:
        return None
    return (f"F{m.group(1)}", f"R{m.group(2)}")


# ---------------------------------------------------------------------------
# Geomatch core
# ---------------------------------------------------------------------------

def _project_to_utm(gdf):
    return gdf.to_crs(epsg=UTM_EPSG)


def _snap_one(point_utm, candidate_trenches_utm) -> tuple[int, float, float]:
    """Return (row_index_in_gdf, segment_t in [0,1], snap_distance_m).
    candidate_trenches_utm is a GeoDataFrame in UTM. Brute-force over candidates.
    """
    best_idx = -1
    best_dist = math.inf
    best_t = 0.0
    for idx, geom in candidate_trenches_utm.geometry.items():
        d = geom.distance(point_utm)
        if d < best_dist:
            best_dist = d
            best_idx = idx
            # Position along this LineString
            t_dist = geom.project(point_utm)  # meters in UTM
            length = geom.length  # meters
            best_t = (t_dist / length) if length > 0 else 0.0
    return best_idx, max(0.0, min(1.0, best_t)), best_dist


def _assign_fcp(point_utm, fcps_utm, cluster_utm) -> tuple[str, str]:
    """Return (fcp_name, mode). mode in {inside_polygon, nearest_fallback, off_cluster}."""
    # Off-cluster gate first
    if not cluster_utm.geometry.iloc[0].contains(point_utm):
        # Still attach the nearest FCP -- useful for the report -- but flag off_cluster
        dists = [g.distance(point_utm) for g in fcps_utm.geometry]
        return fcps_utm["fcp_name"].iloc[dists.index(min(dists))], "off_cluster"
    for fn, geom in zip(fcps_utm["fcp_name"], fcps_utm.geometry):
        if geom.contains(point_utm):
            return fn, "inside_polygon"
    # Inside the cluster but in an FCP gap
    dists = [g.distance(point_utm) for g in fcps_utm.geometry]
    return fcps_utm["fcp_name"].iloc[dists.index(min(dists))], "nearest_fallback"


def main() -> int:
    import geopandas as gpd
    from shapely.geometry import Point

    ensure_dirs()

    if not READQC_JSONL.exists():
        print(f"[geomatch] {READQC_JSONL.name} missing -- run readqc first", file=sys.stderr)
        return 1

    print("[geomatch] loading geo + readqc rows ...")
    trenches, fcps, cluster = load_geo()
    trenches_utm = _project_to_utm(trenches)
    fcps_utm     = _project_to_utm(fcps)
    cluster_utm  = _project_to_utm(cluster)

    # Build a per-FCP candidate index: dict[fcp_name -> GeoDataFrame]
    trenches_by_fcp: dict[str, "gpd.GeoDataFrame"] = {
        fn: trenches_utm[trenches_utm["fcp_name"] == fn] for fn in fcps_utm["fcp_name"]
    }

    # Load readqc rows
    readqc_rows = [json.loads(l) for l in READQC_JSONL.open(encoding="utf-8")]

    # Load forensics so we can copy the representative's row out to its duplicates
    forensics_rows = [json.loads(l) for l in FORENSICS_JSONL.open(encoding="utf-8")]
    cluster_of_photo = {r["photo_id"]: r["phash_cluster_id"] for r in forensics_rows}
    photos_in_cluster: dict[int, list[str]] = {}
    for pid, cid in cluster_of_photo.items():
        photos_in_cluster.setdefault(cid, []).append(pid)

    geocoder = Geocoder()
    rep_rows: list[dict] = []  # geomatch rows for representatives only

    n_overlay = n_geocoded = n_none = n_off_cluster = n_flag = 0

    for i, qc in enumerate(readqc_rows, 1):
        photo_id = qc["photo_id"]
        latlon_parsed = parse_overlay_latlon(qc.get("overlay_latlon"))
        address = (qc.get("overlay_address") or "").strip()
        geocoded = None
        coord_source = "none"
        lat: float | None = None
        lon: float | None = None

        if latlon_parsed is not None:
            lat, lon = latlon_parsed
            coord_source = "overlay_latlon"
            n_overlay += 1
        elif address:
            geocoded = geocoder(address)
            if geocoded:
                lat, lon = geocoded["lat"], geocoded["lon"]
                coord_source = "geocoded_address"
                n_geocoded += 1

        if lat is None:
            rep_rows.append({
                "photo_id": photo_id, "lat": "", "lon": "",
                "coord_source": "none", "segment_id": "", "segment_t": "",
                "snap_distance_m": "", "fcp_name": "", "fcp_assignment": "",
                "label_match": "no_label", "latlon_vs_address_flag": False,
            })
            n_none += 1
            continue

        # Project to UTM for the snap math
        point_wgs = Point(lon, lat)
        point_utm = gpd.GeoSeries([point_wgs], crs=4326).to_crs(epsg=UTM_EPSG).iloc[0]

        # FCP assignment + candidate trench pool
        fcp_name, fcp_mode = _assign_fcp(point_utm, fcps_utm, cluster_utm)
        if fcp_mode == "off_cluster":
            n_off_cluster += 1
        candidates = trenches_by_fcp.get(fcp_name, trenches_utm)
        if candidates.empty:
            candidates = trenches_utm

        idx, seg_t, snap_d = _snap_one(point_utm, candidates)
        seg_id = trenches_utm.loc[idx, "externalID"]
        snapped_fcp = trenches_utm.loc[idx, "fcp_name"]
        snapped_r   = trenches_utm.loc[idx, "ductMainShort"] or ""

        # latlon vs address sanity flag (only when both signals exist)
        flag = False
        if coord_source == "overlay_latlon" and address:
            # Geocode the address purely for the cross-check
            geocoded_x = geocoder(address)
            if geocoded_x is not None:
                d = haversine_m(lat, lon, geocoded_x["lat"], geocoded_x["lon"])
                if d > LATLON_VS_ADDRESS_DIST_M and streets_disagree(address, geocoded_x.get("road", "")):
                    flag = True
                    n_flag += 1

        # Paper label consistency
        pl = parse_paper_label(qc.get("paper_label_code"))
        if pl is None:
            label_match = "no_label"
        else:
            f_code, r_code = pl
            if f_code != snapped_fcp:
                label_match = "fcp_mismatch"
            elif r_code and snapped_r and r_code.upper() != snapped_r.upper():
                label_match = "r_mismatch"
            else:
                label_match = "ok"

        rep_rows.append({
            "photo_id": photo_id,
            "lat": round(lat, 7),
            "lon": round(lon, 7),
            "coord_source": coord_source,
            "segment_id": seg_id,
            "segment_t": round(seg_t, 4),
            "snap_distance_m": round(snap_d, 2),
            "fcp_name": fcp_name,
            "fcp_assignment": fcp_mode,
            "label_match": label_match,
            "latlon_vs_address_flag": flag,
        })

        if i % 200 == 0:
            print(f"[geomatch]   {i}/{len(readqc_rows)} (overlay={n_overlay}, geocoded={n_geocoded}, none={n_none})")
            geocoder.save()

    geocoder.save()

    # Inherit rows to non-representative duplicates
    rep_by_id = {r["photo_id"]: r for r in rep_rows}
    all_rows: list[dict] = []
    for rep_id, rep_row in rep_by_id.items():
        cid = cluster_of_photo.get(rep_id)
        if cid is None:
            all_rows.append(rep_row)
            continue
        for member_id in photos_in_cluster.get(cid, [rep_id]):
            if member_id == rep_id:
                all_rows.append(rep_row)
            else:
                inherited = dict(rep_row)
                inherited["photo_id"] = member_id
                all_rows.append(inherited)

    # Write CSV
    fields = [
        "photo_id", "lat", "lon", "coord_source",
        "segment_id", "segment_t", "snap_distance_m",
        "fcp_name", "fcp_assignment", "label_match", "latlon_vs_address_flag",
    ]
    with GEOMATCH_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)

    print(
        f"[geomatch] {len(all_rows)} rows ({len(rep_rows)} representatives, "
        f"{len(all_rows) - len(rep_rows)} inherited duplicates) -> {GEOMATCH_CSV.name}"
    )
    print(
        f"[geomatch] overlay_latlon={n_overlay}, geocoded={n_geocoded}, "
        f"none={n_none}, off_cluster={n_off_cluster}, mismatch_flag={n_flag}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
