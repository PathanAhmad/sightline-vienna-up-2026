"""In-memory geomatch + classify for live dashboard uploads.

The batch pipeline (src/geomatch.py + src/classify.py) reads/writes CSVs
and JSONLs on disk. When the operator drops a photo onto the dashboard
upload panel, we don't want to mutate those on-disk artifacts -- the
batch run is the source of truth, uploads are session-scoped.

This module bridges the two:

  * `trenches_utm(path)`     -- cached GeoDataFrame in UTM 33N (snap math)
  * `snap_to_segment(...)`   -- one photo lat/lon -> (segment_id, t, dist, fcp)
  * `qc_to_readqc_row(...)`  -- QCResult -> readqc.jsonl dict shape
  * `qc_to_geomatch_row(...)` -- snap result -> geomatch.csv dict shape
  * `recompute_verdicts(...)` -- merged readqc+geomatch -> verdicts_by_segment

The classify logic itself (is_photo_compliant, segment_verdict) is
imported straight from src.classify -- no duplication, same rules the
batch pipeline applies.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from src.classify import (
    PHASE_CHECKS,
    is_photo_compliant,
    segment_verdict,
)
from src.geomatch import (
    UTM_EPSG,
    _assign_fcp,
    _snap_one,
    parse_overlay_latlon,
)


# ---- Geometry cache -----------------------------------------------------

@st.cache_resource(show_spinner=False)
def _load_geom_utm(
    trenches_path: str, fcps_path: str, cluster_path: str,
) -> dict[str, Any]:
    """Load trenches/fcps/cluster as UTM-projected GeoDataFrames, once.

    Cached on the path strings -- the dashboard resolves either live or
    fixture paths, so the cache key tracks that. Computed once per
    Streamlit session, then reused across reruns.
    """
    import geopandas as gpd

    trenches = gpd.read_file(trenches_path)
    fcps = gpd.read_file(fcps_path)
    cluster = gpd.read_file(cluster_path)

    for gdf in (trenches, fcps, cluster):
        if gdf.crs is None:
            gdf.set_crs(epsg=4326, inplace=True)
        elif gdf.crs.to_epsg() != 4326:
            gdf.to_crs(epsg=4326, inplace=True)

    # FCP name from the kml description string -- same parse as ingest.load_geo
    if "fcp_name" not in fcps.columns:
        fcps["fcp_name"] = (
            fcps["kmlDescriptionSimple"].str.split(" [", n=1, regex=False).str[0]
        )

    # Trenches need an fcp_name column for _assign_fcp's candidate pool.
    # Real Trenches.geojson has its own; fixtures may not. Spatial join by
    # midpoint-in-polygon, fallback to nearest centroid (same as
    # ingest.load_geo -- copied here so we don't drag the full ingest import
    # into the dashboard hot path).
    if "fcp_name" not in trenches.columns:
        import warnings as _w
        with _w.catch_warnings():
            _w.filterwarnings("ignore", message="Geometry is in a geographic CRS")
            mids = trenches.geometry.interpolate(0.5, normalized=True)
            fcp_centroids = fcps.geometry.centroid
        polys = list(fcps.geometry)
        names = list(fcps["fcp_name"])
        assigned: list[str] = []
        for mid in mids:
            hit = next(
                (fn for poly, fn in zip(polys, names) if poly.contains(mid)),
                None,
            )
            if hit is None:
                dists = [c.distance(mid) for c in fcp_centroids]
                hit = names[dists.index(min(dists))]
            assigned.append(hit)
        trenches["fcp_name"] = assigned

    # Real data uses externalID; fixtures use globalID or segment_id. Normalize
    # so downstream code can always read row["externalID"].
    if "externalID" not in trenches.columns:
        trenches["externalID"] = (
            trenches.get("globalID")
            if "globalID" in trenches.columns
            else trenches.get("segment_id")
        )

    trenches_utm = trenches.to_crs(epsg=UTM_EPSG)
    fcps_utm = fcps.to_crs(epsg=UTM_EPSG)
    cluster_utm = cluster.to_crs(epsg=UTM_EPSG)

    seg_length_m = {
        row["externalID"]: row.geometry.length
        for _, row in trenches_utm.iterrows()
    }
    seg_fcp = {
        row["externalID"]: row["fcp_name"]
        for _, row in trenches_utm.iterrows()
    }
    trenches_by_fcp = {
        fn: trenches_utm[trenches_utm["fcp_name"] == fn]
        for fn in fcps_utm["fcp_name"]
    }

    return {
        "trenches_utm": trenches_utm,
        "fcps_utm": fcps_utm,
        "cluster_utm": cluster_utm,
        "trenches_by_fcp": trenches_by_fcp,
        "seg_length_m": seg_length_m,
        "seg_fcp": seg_fcp,
    }


def snap_to_segment(
    lat: float, lon: float, geom: dict[str, Any],
) -> dict[str, Any]:
    """Snap a single WGS84 point to the nearest trench segment.

    Returns a geomatch-row-shaped dict: segment_id, segment_t,
    snap_distance_m, fcp_name, fcp_assignment. Empty segment_id if
    the snap fails (shouldn't happen -- we always snap to *something*).
    """
    import geopandas as gpd
    from shapely.geometry import Point

    point_wgs = Point(lon, lat)
    point_utm = gpd.GeoSeries([point_wgs], crs=4326).to_crs(epsg=UTM_EPSG).iloc[0]
    fcp_name, fcp_mode = _assign_fcp(
        point_utm, geom["fcps_utm"], geom["cluster_utm"],
    )
    candidates = geom["trenches_by_fcp"].get(fcp_name, geom["trenches_utm"])
    if candidates.empty:
        candidates = geom["trenches_utm"]
    idx, seg_t, snap_d = _snap_one(point_utm, candidates)
    seg_id = geom["trenches_utm"].loc[idx, "externalID"]
    return {
        "segment_id": seg_id,
        "segment_t": float(seg_t),
        "snap_distance_m": float(snap_d),
        "fcp_name": fcp_name,
        "fcp_assignment": fcp_mode,
    }


# ---- QC -> jsonl/csv row shapes ----------------------------------------

_READQC_FIELDS = (
    "relevance", "phase",
    "warning_tape_visible", "sand_bedding_visible",
    "side_view_present", "depth_reference_visible", "depth_value_cm",
    "duct_visible", "pipe_ends_sealed", "personal_data_visible",
    "overlay_date", "overlay_address", "overlay_latlon", "paper_label_code",
    "note",
)


def qc_to_readqc_row(qc: Any, photo_id: str) -> dict[str, Any]:
    """Flatten a QCResult pydantic into a readqc.jsonl-shaped dict.

    classify.is_photo_compliant reads from a dict, so we shape the live
    QC result the same way the batch run does.
    """
    row: dict[str, Any] = {"photo_id": photo_id}
    for f in _READQC_FIELDS:
        row[f] = getattr(qc, f, None)
    return row


def qc_to_geomatch_row(
    photo_id: str, lat: float | None, lon: float | None,
    snap: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a geomatch.csv-shaped dict. Uploads have no lat/lon vs
    address cross-check (Nominatim throttle would block the page) -- so
    `latlon_vs_address_flag` is always False for live uploads.

    Numeric columns (lat/lon/segment_t/snap_distance_m) use float('nan')
    for missing values, not '' -- the dashboard filters photo_points
    with `.notna()`, and empty strings would slip through that filter
    and crash the map render with bad coords."""
    if snap is None:
        return {
            "photo_id": photo_id,
            "lat": float("nan"), "lon": float("nan"),
            "coord_source": "none",
            "segment_id": "",
            "segment_t": float("nan"),
            "snap_distance_m": float("nan"),
            "fcp_name": "",
            "fcp_assignment": "", "label_match": "no_label",
            "latlon_vs_address_flag": False,
        }
    return {
        "photo_id": photo_id,
        "lat": lat,
        "lon": lon,
        "coord_source": "overlay_latlon",
        "segment_id": snap["segment_id"],
        "segment_t": snap["segment_t"],
        "snap_distance_m": snap["snap_distance_m"],
        "fcp_name": snap["fcp_name"],
        "fcp_assignment": snap["fcp_assignment"],
        "label_match": "no_label",
        "latlon_vs_address_flag": False,
    }


# ---- Recompute per-segment verdicts on merged in-memory data -----------

def recompute_verdicts(
    base_verdicts: pd.DataFrame,
    base_geomatch: pd.DataFrame,
    base_readqc: list[dict],
    base_forensics: list[dict],
    upload_geomatch: list[dict],
    upload_readqc: list[dict],
    geom: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict], list[dict]]:
    """Merge live uploads into the on-disk data and recompute verdicts
    for the affected segments only.

    Only segments that an upload snapped to get recomputed -- everything
    else keeps its batch verdict. That's both faster and preserves the
    `reasons` strings the batch run produced.

    Returns (merged_verdicts_df, merged_geomatch_df, merged_readqc,
    merged_forensics). The dashboard then renders from these.
    """
    if not upload_geomatch:
        return base_verdicts, base_geomatch, base_readqc, base_forensics

    # Append uploads to readqc / geomatch / forensics. Each upload is its
    # own pHash cluster (we don't dedupe across uploads -- the batch's
    # forensics didn't see these images).
    merged_readqc = list(base_readqc) + list(upload_readqc)
    merged_geomatch_df = pd.concat(
        [base_geomatch, pd.DataFrame(upload_geomatch)],
        ignore_index=True,
    )
    next_cluster_id = (
        max((r.get("phash_cluster_id", 0) for r in base_forensics), default=0) + 1
    )
    merged_forensics = list(base_forensics)
    for i, ug in enumerate(upload_geomatch):
        merged_forensics.append({
            "photo_id": ug["photo_id"],
            "phash_cluster_id": next_cluster_id + i,
            "is_phash_representative": True,
            "ela_flag": False,
        })

    # Which segments need recomputing?
    affected_segments: set[str] = {
        ug["segment_id"] for ug in upload_geomatch
        if ug.get("segment_id")
    }
    if not affected_segments:
        return base_verdicts, merged_geomatch_df, merged_readqc, merged_forensics

    # Build lookups for the recompute.
    readqc_by_id = {r["photo_id"]: r for r in merged_readqc}
    geomatch_by_id = {
        r["photo_id"]: r for r in merged_geomatch_df.to_dict("records")
    }
    forensics_by_id = {r["photo_id"]: r for r in merged_forensics}
    cluster_to_rep = {
        r["phash_cluster_id"]: r["photo_id"]
        for r in merged_forensics
        if r.get("is_phash_representative")
    }

    def _readqc_for(pid: str) -> dict | None:
        if pid in readqc_by_id:
            return readqc_by_id[pid]
        cid = forensics_by_id.get(pid, {}).get("phash_cluster_id")
        if cid is None:
            return None
        rep = cluster_to_rep.get(cid)
        return readqc_by_id.get(rep) if rep else None

    # Group photos that snap to affected segments, then dedup by cluster
    # (same logic as classify.main).
    photos_by_segment: dict[str, dict[int, dict]] = defaultdict(dict)
    for pid, geo in geomatch_by_id.items():
        seg_id = geo.get("segment_id") or ""
        if seg_id not in affected_segments:
            continue
        qc = _readqc_for(pid)
        if qc is None:
            continue
        cid = forensics_by_id.get(pid, {}).get("phash_cluster_id", -1)
        compliant, reasons = is_photo_compliant(qc, geo)
        rep_id = cluster_to_rep.get(cid)
        existing = photos_by_segment[seg_id].get(cid)

        def _score(entry: dict, rid: str | None = rep_id) -> tuple:
            return (
                0 if entry["compliant"] else 1,
                0 if entry["photo_id"] == rid else 1,
                entry["photo_id"],
            )

        candidate = {
            "photo_id": pid,
            "t": float(geo.get("segment_t") or 0.0),
            "compliant": compliant,
            "reasons": reasons,
        }
        if existing is None or _score(candidate) < _score(existing):
            photos_by_segment[seg_id][cid] = candidate

    # Recompute the affected verdicts.
    verdicts_by_segment = {r["segment_id"]: dict(r) for r in base_verdicts.to_dict("records")}
    for seg_id in affected_segments:
        length_m = geom["seg_length_m"].get(seg_id, 0.0)
        entries = list(photos_by_segment.get(seg_id, {}).values())
        photo_count = len(entries)
        compliant_entries = [e for e in entries if e["compliant"]]
        compliant_count = len(compliant_entries)
        positions_m = [e["t"] * length_m for e in compliant_entries]
        verdict, max_gap, gap_reasons = segment_verdict(length_m, positions_m)

        seg_reasons = list(gap_reasons)
        if photo_count > 0 and compliant_count < photo_count:
            bad_reasons = [
                r for e in entries if not e["compliant"] for r in e["reasons"]
            ]
            from collections import Counter
            for reason, count in Counter(bad_reasons).most_common(3):
                seg_reasons.append(f"{count}x {reason}")
        n_personal = sum(
            1 for e in entries if any("personal_data_visible" == r for r in e["reasons"])
        )
        if n_personal:
            seg_reasons.append(f"{n_personal} personal-data photo(s)")

        density = (compliant_count / (length_m / 5.0)) if length_m > 0 else 0.0
        verdicts_by_segment[seg_id] = {
            "segment_id": seg_id,
            "fcp_name": geom["seg_fcp"].get(seg_id, ""),
            "length_m": round(length_m, 2),
            "photo_count": photo_count,
            "compliant_photo_count": compliant_count,
            "max_gap_m": round(max_gap, 2),
            "density_photos_per_5m": round(density, 3),
            "verdict": verdict,
            "reasons": "; ".join(seg_reasons),
        }

    merged_verdicts_df = pd.DataFrame(list(verdicts_by_segment.values()))
    return merged_verdicts_df, merged_geomatch_df, merged_readqc, merged_forensics
