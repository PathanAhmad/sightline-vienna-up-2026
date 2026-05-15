"""Streamlit entrypoint — the live demo surface.

Run: `uv run streamlit run app.py`

What it does: loads pipeline outputs from disk (no live Claude calls)
and renders a folium map of the trench network colored by verdict.
Click a segment → side panel with the photo grid, the per-photo checks,
and the human-readable reasons for the verdict.

Data sources (preferred → fallback):
    data/processed/  (the real pipeline outputs, gitignored)
    demo_fixtures/   (synthetic stand-ins, committed)

Files consumed:
    verdicts.csv         per-segment GREEN/YELLOW/RED + reasons
    geomatch.csv         photo → segment + position
    readqc.jsonl         per-photo Claude vision output (1 line/photo)
    forensics.jsonl      per-photo phash + ELA
    manifest.sqlite      photo_id → rel_path
    geo/Trenches.geojson
    geo/FCP_Polygons.geojson
    geo/SiteCluster_Polygons.geojson

Demo-day rule (CLAUDE.md): no live Claude calls during the pitch.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

# --- Paths ---------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent
REAL_PROCESSED = REPO_ROOT / "data" / "processed"
REAL_GEO = REPO_ROOT / "data" / "geo"
REAL_PHOTOS_DIR = REPO_ROOT / "data" / "Fotos" / "Fotos"
FIXTURE_DIR = REPO_ROOT / "demo_fixtures"
FIXTURE_GEO = FIXTURE_DIR / "geo"
RESOURCES_PHOTOS_DIR = REPO_ROOT / "Resources" / "all"
EXEMPLARS_FALLBACK_DIR = REPO_ROOT / "Resources" / "examples"

VERDICT_COLORS = {
    "GREEN": "#22c55e",   # tailwind green-500
    "YELLOW": "#eab308",  # tailwind yellow-500
    "RED": "#ef4444",     # tailwind red-500
}


# --- Loaders -------------------------------------------------------------

@dataclass
class DataPaths:
    """Resolved file paths for the dataset we're going to display."""
    source: str  # "live" or "fixtures"
    verdicts_csv: Path
    geomatch_csv: Path
    readqc_jsonl: Path
    forensics_jsonl: Path
    manifest_sqlite: Path
    trenches_geojson: Path
    fcps_geojson: Path
    cluster_geojson: Path
    photos_root: Path


def resolve_paths() -> DataPaths:
    """Prefer live pipeline outputs; fall back to committed fixtures.

    All-or-nothing: we only switch to live mode if every required
    artifact is present. A partial live state (e.g. verdicts.csv landed
    but manifest.sqlite hasn't yet) would crash a downstream loader, so
    we stay on fixtures until the pipeline finishes a full run.
    """
    live_candidates = {
        "verdicts_csv": REAL_PROCESSED / "verdicts.csv",
        "geomatch_csv": REAL_PROCESSED / "geomatch.csv",
        "readqc_jsonl": REAL_PROCESSED / "readqc.jsonl",
        "forensics_jsonl": REAL_PROCESSED / "forensics.jsonl",
        "manifest_sqlite": REAL_PROCESSED / "manifest.sqlite",
        "trenches_geojson":
            REAL_GEO / "CLP20417A-P1-B00_Trenches.geojson",
        "fcps_geojson":
            REAL_GEO / "CLP20417A-P1-B00_FCP_Polygons.geojson",
        "cluster_geojson":
            REAL_GEO / "CLP20417A-P1-B00_SiteCluster_Polygons.geojson",
    }
    if all(p.exists() for p in live_candidates.values()):
        return DataPaths(
            source="live", photos_root=REAL_PHOTOS_DIR, **live_candidates
        )
    return DataPaths(
        source="fixtures",
        verdicts_csv=FIXTURE_DIR / "verdicts.csv",
        geomatch_csv=FIXTURE_DIR / "geomatch.csv",
        readqc_jsonl=FIXTURE_DIR / "readqc.jsonl",
        forensics_jsonl=FIXTURE_DIR / "forensics.jsonl",
        manifest_sqlite=FIXTURE_DIR / "manifest.sqlite",
        trenches_geojson=FIXTURE_GEO / "Trenches.geojson",
        fcps_geojson=FIXTURE_GEO / "FCP_Polygons.geojson",
        cluster_geojson=FIXTURE_GEO / "SiteCluster_Polygons.geojson",
        photos_root=RESOURCES_PHOTOS_DIR,
    )


@st.cache_data(show_spinner=False)
def load_verdicts(path_str: str) -> pd.DataFrame:
    # keep_default_na=False: empty CSV cells stay as "" (not NaN). Otherwise
    # rows like GREEN segments (no `reasons`) leak NaN floats out of the
    # loader and crash the renderer with `'float' has no attribute 'split'`.
    # Numeric columns are coerced to NaN by pd.to_numeric below regardless.
    return pd.read_csv(path_str, dtype=str, keep_default_na=False).assign(
        length_m=lambda d: pd.to_numeric(d["length_m"], errors="coerce"),
        photo_count=lambda d: pd.to_numeric(d["photo_count"], errors="coerce")
        .fillna(0)
        .astype(int),
        compliant_photo_count=lambda d: pd.to_numeric(
            d["compliant_photo_count"], errors="coerce"
        )
        .fillna(0)
        .astype(int),
        max_gap_m=lambda d: pd.to_numeric(d["max_gap_m"], errors="coerce"),
        density_photos_per_5m=lambda d: pd.to_numeric(
            d["density_photos_per_5m"], errors="coerce"
        ),
    )


@st.cache_data(show_spinner=False)
def load_geomatch(path_str: str) -> pd.DataFrame:
    # Same NaN-avoidance pattern as load_verdicts above. Empty segment_id /
    # fcp_name / paper_label_code cells become "" instead of NaN floats.
    return pd.read_csv(path_str, dtype=str, keep_default_na=False).assign(
        lat=lambda d: pd.to_numeric(d["lat"], errors="coerce"),
        lon=lambda d: pd.to_numeric(d["lon"], errors="coerce"),
        segment_t=lambda d: pd.to_numeric(d["segment_t"], errors="coerce"),
        snap_distance_m=lambda d: pd.to_numeric(
            d["snap_distance_m"], errors="coerce"
        ),
        latlon_vs_address_flag=lambda d: d["latlon_vs_address_flag"]
        .str.lower()
        .map({"true": True, "false": False})
        .fillna(False),
    )


@st.cache_data(show_spinner=False)
def load_jsonl(path_str: str) -> list[dict]:
    rows: list[dict] = []
    with open(path_str, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


@st.cache_data(show_spinner=False)
def load_manifest(path_str: str) -> dict[str, str]:
    """Return {photo_id: rel_path}."""
    conn = sqlite3.connect(path_str)
    try:
        rows = conn.execute("SELECT photo_id, rel_path FROM photos").fetchall()
    finally:
        conn.close()
    return {pid: rp for pid, rp in rows}


@st.cache_data(show_spinner=False)
def load_geojson(path_str: str) -> dict:
    with open(path_str, encoding="utf-8") as f:
        return json.load(f)


# --- Map rendering -------------------------------------------------------

def style_for_segment(verdict: str) -> dict:
    return {
        "color": VERDICT_COLORS.get(verdict, "#888"),
        "weight": 6,
        "opacity": 0.9,
    }


def build_map(
    trenches: dict,
    fcps: dict,
    cluster: dict,
    verdicts_by_segment: dict[str, dict],
    photo_points: list[dict],
) -> folium.Map:
    """Build the folium map. Each trench feature carries its verdict in
    properties so the click handler can read it back without a roundtrip."""
    feature_collection = {
        "type": "FeatureCollection",
        "features": [],
    }
    for feat in trenches["features"]:
        # Real Trenches.geojson uses `externalID` (verified 2026-05-15);
        # `globalID` and `segment_id` are kept as fallbacks for the demo
        # fixtures, which were authored against the original PLAN naming.
        props = feat["properties"]
        seg_id = (
            props.get("externalID")
            or props.get("globalID")
            or props.get("segment_id")
        )
        v_row = verdicts_by_segment.get(seg_id, {})
        verdict = v_row.get("verdict", "RED")
        enriched = {
            **feat,
            "properties": {
                **feat["properties"],
                "segment_id": seg_id,
                "verdict": verdict,
                "fcp_name": v_row.get("fcp_name", ""),
                "length_m": v_row.get("length_m", ""),
                "reasons": v_row.get("reasons", ""),
            },
        }
        feature_collection["features"].append(enriched)

    # Map center: cluster centroid (rough)
    try:
        c_coords = cluster["features"][0]["geometry"]["coordinates"][0]
        lats = [pt[1] for pt in c_coords]
        lons = [pt[0] for pt in c_coords]
        center = [sum(lats) / len(lats), sum(lons) / len(lons)]
    except Exception:
        center = [46.555, 14.290]

    m = folium.Map(
        location=center,
        zoom_start=17,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    # Cluster outline (gray, dashed-ish)
    folium.GeoJson(
        cluster,
        name="Site cluster",
        style_function=lambda _f: {
            "color": "#475569",
            "weight": 1.5,
            "fill": False,
            "dashArray": "4,4",
        },
        interactive=False,
    ).add_to(m)

    # FCP polygons (very light fill)
    folium.GeoJson(
        fcps,
        name="FCP zones",
        style_function=lambda _f: {
            "color": "#0ea5e9",
            "weight": 1,
            "fillColor": "#bae6fd",
            "fillOpacity": 0.10,
        },
        interactive=False,
    ).add_to(m)

    # Trench segments, colored by verdict.
    folium.GeoJson(
        feature_collection,
        name="Trench segments",
        style_function=lambda f: style_for_segment(
            f["properties"].get("verdict", "RED")
        ),
        highlight_function=lambda _f: {"weight": 10, "color": "#1e293b"},
        tooltip=folium.GeoJsonTooltip(
            fields=["segment_id", "fcp_name", "verdict", "length_m"],
            aliases=["Segment", "FCP", "Verdict", "Length (m)"],
            sticky=True,
        ),
    ).add_to(m)

    # Photo markers — small circles per photo for visual density.
    for pt in photo_points:
        folium.CircleMarker(
            location=[pt["lat"], pt["lon"]],
            radius=3,
            color="#1e293b",
            weight=0.5,
            fillColor="#1e293b",
            fillOpacity=0.7,
        ).add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)
    return m


# --- Side panel ---------------------------------------------------------

PHOTO_CHECK_FIELDS = [
    ("warning_tape_visible", "Warning tape"),
    ("sand_bedding_visible", "Sand bedding"),
    ("side_view_present", "Side view"),
    ("depth_reference_visible", "Depth ref"),
    ("duct_visible", "Duct"),
    ("pipe_ends_sealed", "Pipe ends sealed"),
    # NOTE: `personal_data_visible` intentionally NOT in this list. It is
    # the redaction trigger (see render_personal_data_redaction below), not
    # a check that the reviewer needs to see displayed.
]


def render_personal_data_redaction(pid: str, qc: dict, segment_t: float) -> None:
    """Render a GDPR notice card in place of a photo flagged with personal
    data. Replaces both the image bytes AND the per-photo check chips so
    nothing about the original photo's contents bleeds into the demo screen.

    Policy reversal documented in DECISIONS.md (2026-05-15 Saturday): the
    original 'flag, don't redact' approach was correct for compliance
    bookkeeping, but a screen-recorded demo of a tool that talks about
    NIS2 / GDPR while displaying a worker's face is a bad look. We now
    withhold the image at display time, surface the withholding visibly,
    and route the photo to the retake bucket the same way as before.
    """
    st.markdown(
        "<div class='gdpr-card'>"
        "<div class='gdpr-icon'>&#x1F6AB;</div>"
        "<div class='gdpr-title'>Image withheld</div>"
        "<div class='gdpr-body'>Personal data detected "
        "(face / licence plate). Withheld per GDPR / NIS2.</div>"
        "<div class='gdpr-foot'>Routed to contractor retake bucket.</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='font-size:11.5px;color:var(--c-text-2);margin-top:6px;'>"
        f"phase <b style='color:var(--c-text);'>{qc.get('phase','?')}</b> · "
        f"pos <b style='color:var(--c-text);'>{segment_t:.0%}</b> · "
        f"id <code style='font-size:10px;background:var(--c-bg);"
        f"padding:1px 4px;border-radius:3px;'>{pid[:10]}…</code></div>",
        unsafe_allow_html=True,
    )


def photo_path_for(photo_id: str, manifest: dict, photos_root: Path) -> Path | None:
    rel = manifest.get(photo_id)
    if not rel:
        return None
    p = photos_root / rel
    if p.exists():
        return p
    # Fall back to Resources/all/ if the live photos dir is empty.
    alt = RESOURCES_PHOTOS_DIR / rel
    if alt.exists():
        return alt
    return None


def _fmt_meters(value: Any) -> str:
    """Render a length-in-meters value tolerantly. NaN / None → '?'."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "?"
    if f != f:  # NaN
        return "?"
    return f"{f:g} m"


def resolve_qc(
    photo_id: str,
    readqc_by_id: dict[str, dict],
    forensics_by_id: dict[str, dict],
    rep_by_cluster: dict[Any, str],
) -> tuple[dict, str | None]:
    """Return (qc_row, duplicate_of_photo_id).

    Direct hit on readqc → use it. Otherwise resolve via the photo's
    phash_cluster_id to its cluster representative and inherit that row.
    The duplicate_of_photo_id is non-None only when we inherited.
    """
    direct = readqc_by_id.get(photo_id)
    if direct:
        return direct, None
    fo = forensics_by_id.get(photo_id) or {}
    cluster_id = fo.get("phash_cluster_id")
    rep_id = rep_by_cluster.get(cluster_id) if cluster_id is not None else None
    if rep_id and rep_id != photo_id:
        return readqc_by_id.get(rep_id, {}), rep_id
    return {}, None


def render_check_chip_v2(field_label: str, value: str) -> str:
    """A single inline check chip with the new design tokens."""
    val_class = {
        "yes": "yes", "no": "no",
        "occluded": "occluded", "not_applicable": "na",
    }.get(value, "na")
    return (
        f"<span class='check-chip'>"
        f"<span class='lbl'>{field_label}</span>"
        f"<span class='val {val_class}'>{value}</span>"
        f"</span>"
    )


def render_segment_panel(
    seg_id: str,
    verdicts_by_segment: dict[str, dict],
    geomatch_df: pd.DataFrame,
    readqc_by_id: dict[str, dict],
    forensics_by_id: dict[str, dict],
    rep_by_cluster: dict[Any, str],
    manifest: dict,
    photos_root: Path,
) -> None:
    """Render the side panel for a clicked segment."""
    v = verdicts_by_segment.get(seg_id)
    if v is None:
        st.warning(f"Segment {seg_id} not found in verdicts.")
        return

    verdict = v.get("verdict", "?")
    pill_class = verdict.lower() if verdict in VERDICT_COLORS else ""

    # Header block — verdict pill, FCP / length / photo counts, "Why",
    # rendered as one panel-card. Reasons are split on ';' and surfaced as
    # a styled list with a yellow accent stripe.
    # NB: coerce to str — pandas can hand us a NaN float for empty cells if
    # the loader didn't strip them (see load_verdicts), and `nan.split(';')`
    # explodes.
    reasons_raw = v.get("reasons", "")
    reasons = reasons_raw if isinstance(reasons_raw, str) else ""
    reasons_html = ""
    if reasons:
        items = "".join(
            f"<li>{r.strip()}</li>"
            for r in reasons.split(";")
            if r.strip()
        )
        reasons_html = (
            f"<div style='font-weight:600;font-size:12px;"
            f"color:var(--c-text-2);margin-bottom:2px;'>Why this verdict</div>"
            f"<ul class='reason-list'>{items}</ul>"
        )

    st.markdown(
        f"<div class='panel-card'>"
        f"<div class='panel-title'>"
        f"<span>Segment <code style='font-family:ui-monospace,monospace;"
        f"font-size:13px;background:var(--c-bg);padding:2px 6px;"
        f"border-radius:4px'>{seg_id}</code></span>"
        f"<span class='verdict-pill {pill_class}'>{verdict}</span>"
        f"</div>"
        f"<div class='panel-meta'>"
        f"FCP <b>{v.get('fcp_name','?')}</b> · "
        f"length <b>{_fmt_meters(v.get('length_m'))}</b> · "
        f"<b>{v.get('photo_count', 0)}</b> photos snapped · "
        f"<b>{v.get('compliant_photo_count', 0)}</b> compliant"
        f"</div>"
        f"{reasons_html}"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Photo grid (photos snapped to this segment)
    seg_photos = geomatch_df[geomatch_df["segment_id"] == seg_id]
    if seg_photos.empty:
        st.markdown(
            "<div class='panel-card' style='margin-top:10px;color:var(--c-muted);"
            "font-size:13px;text-align:center;'>"
            "No photos snapped to this segment.</div>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        "<div class='section-head'>Photos on this segment</div>",
        unsafe_allow_html=True,
    )

    # Show in rows of 2 (the side panel is narrow).
    photos = seg_photos.sort_values("segment_t").to_dict("records")
    for i in range(0, len(photos), 2):
        cols = st.columns(2)
        for col, row in zip(cols, photos[i:i + 2]):
            pid = row["photo_id"]
            with col:
                qc, dup_of = resolve_qc(
                    pid, readqc_by_id, forensics_by_id, rep_by_cluster
                )
                # GDPR / NIS2 redaction. Photos flagged personal_data_visible
                # NEVER show their image bytes in the demo surface; the rest
                # of the per-photo card (chips, ELA, geo flag) is also
                # suppressed since it would reveal what's in the frame.
                if qc and qc.get("personal_data_visible") == "yes":
                    render_personal_data_redaction(
                        pid, qc, float(row.get("segment_t") or 0.0)
                    )
                    continue

                img_path = photo_path_for(pid, manifest, photos_root)
                if img_path:
                    st.image(str(img_path), width="stretch")
                else:
                    st.markdown(
                        f"<div style='background:var(--c-bg);"
                        f"border:1px solid var(--c-border);padding:30px;"
                        f"text-align:center;border-radius:var(--r-sm);"
                        f"color:var(--c-text-2);font-size:12px;'>"
                        f"image unavailable<br>"
                        f"<small style='color:var(--c-muted)'>"
                        f"{pid[:24]}…</small></div>",
                        unsafe_allow_html=True,
                    )
                fo = forensics_by_id.get(pid, {})
                if qc:
                    st.markdown(
                        f"<div style='font-size:11.5px;color:var(--c-text-2);"
                        f"margin-top:6px;'>"
                        f"phase <b style='color:var(--c-text);'>"
                        f"{qc.get('phase','?')}</b> · "
                        f"pos <b style='color:var(--c-text);'>"
                        f"{float(row['segment_t']):.0%}</b></div>",
                        unsafe_allow_html=True,
                    )
                    if dup_of:
                        st.markdown(
                            f"<div style='font-size:11px;color:var(--c-purple);"
                            f"margin-top:2px;'>"
                            f"⟲ duplicate of "
                            f"<code style='background:var(--c-purple-soft);"
                            f"padding:1px 4px;border-radius:3px;font-size:10px;'>"
                            f"{dup_of[:18]}…</code></div>",
                            unsafe_allow_html=True,
                        )
                    chips = "".join(
                        render_check_chip_v2(label, qc.get(field, "?"))
                        for field, label in PHOTO_CHECK_FIELDS
                    )
                    st.markdown(
                        f"<div style='margin-top:6px;line-height:1.9;'>"
                        f"{chips}</div>",
                        unsafe_allow_html=True,
                    )
                    if qc.get("note"):
                        st.markdown(
                            f"<div style='font-size:11px;color:var(--c-muted);"
                            f"font-style:italic;margin-top:6px;line-height:1.4;'>"
                            f"{qc['note']}</div>",
                            unsafe_allow_html=True,
                        )
                if fo.get("ela_flag"):
                    st.markdown(
                        "<div style='font-size:11px;color:var(--c-amber);"
                        "margin-top:4px;font-weight:500;'>"
                        "⚠ ELA tamper hint</div>",
                        unsafe_allow_html=True,
                    )
                if row.get("latlon_vs_address_flag"):
                    st.markdown(
                        "<div style='font-size:11px;color:var(--c-red);"
                        "margin-top:4px;font-weight:500;'>"
                        "⚠ lat/lon ↔ address mismatch</div>",
                        unsafe_allow_html=True,
                    )


# --- Header (hero + summary cards + catches) ----------------------------

@dataclass
class HeaderStats:
    """Pre-computed counts the hero, summary cards, and catch row all share.
    Computed once per render and passed down to avoid recomputing."""
    n_segments: int
    n_green: int
    n_yellow: int
    n_red: int
    pct_green: float
    n_photos_scored: int
    n_not_classified: int
    n_personal_data: int
    n_duplicate_photos: int
    n_ela: int
    n_geo_mismatch: int
    total_cost: float


def _compute_header_stats(
    verdicts: pd.DataFrame,
    readqc: list[dict],
    forensics: list[dict],
    geomatch: pd.DataFrame,
) -> HeaderStats:
    n_segments = len(verdicts)
    counts = verdicts["verdict"].value_counts().to_dict()
    n_green = counts.get("GREEN", 0)
    n_yellow = counts.get("YELLOW", 0)
    n_red = counts.get("RED", 0)
    return HeaderStats(
        n_segments=n_segments,
        n_green=n_green,
        n_yellow=n_yellow,
        n_red=n_red,
        pct_green=(n_green / n_segments * 100) if n_segments else 0.0,
        n_photos_scored=len(readqc),
        n_not_classified=sum(
            1 for r in readqc if r.get("relevance") != "scorable"
        ),
        n_personal_data=sum(
            1 for r in readqc if r.get("personal_data_visible") == "yes"
        ),
        n_duplicate_photos=max(0, len(forensics) - sum(
            1 for r in forensics if r.get("is_phash_representative")
        )),
        n_ela=sum(1 for r in forensics if r.get("ela_flag")),
        n_geo_mismatch=int(geomatch["latlon_vs_address_flag"].sum()),
        total_cost=sum(r.get("cost_usd", 0.0) for r in readqc),
    )


def render_topbar(source: str) -> None:
    """Slim status banner — live data vs fixtures."""
    if source == "live":
        st.markdown(
            "<div class='source-banner live'>"
            "● Live pipeline data — <code>data/processed/</code></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div class='source-banner'>"
            "● Showing demo fixtures (synthetic). Real pipeline outputs at "
            "<code>data/processed/</code> will shadow automatically.</div>",
            unsafe_allow_html=True,
        )


def render_hero(s: HeaderStats) -> None:
    """The headline. The one thing a judge skimming for 3 seconds should
    catch: what we do, on what scale, and how cheap/fast vs manual."""
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-left">
            <div class="hero-eyebrow">APG · Austrian Power Grid</div>
            <div class="hero-title">
              Trench-photo QC — every meter, every segment.
            </div>
            <div class="hero-sub">
              Each colored line on the map is a trench segment. We grade
              every one <b>green / yellow / red</b> from the photos that
              document it. Manual review: 3–5 days per section.
              Ours: minutes, ~$0.005 per photo.
            </div>
          </div>
          <div class="hero-stats">
            <div class="hero-stat">
              <div class="hero-stat-label">Photos audited</div>
              <div class="hero-stat-value">{s.n_photos_scored:,}</div>
            </div>
            <div class="hero-stat">
              <div class="hero-stat-label">Segments scored</div>
              <div class="hero-stat-value">{s.n_segments:,}</div>
            </div>
            <div class="hero-stat">
              <div class="hero-stat-label">Compliant</div>
              <div class="hero-stat-value">{s.pct_green:.0f}%</div>
            </div>
            <div class="hero-stat">
              <div class="hero-stat-label">Run cost</div>
              <div class="hero-stat-value">${s.total_cost:.2f}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_summary_cards(s: HeaderStats) -> None:
    """The 4-card row. Each card is a single, easy-to-grasp number."""
    st.markdown(
        f"""
        <div class="summary-row">
          <div class="summary-card green">
            <div class="summary-label">Coverage</div>
            <div class="summary-value">{s.pct_green:.0f}%</div>
            <div class="summary-sub">
              {s.n_green:,} of {s.n_segments:,} segments fully compliant
            </div>
          </div>
          <div class="summary-card yellow">
            <div class="summary-label">Verdict mix</div>
            <div class="summary-traffic">
              <span class="g">{s.n_green:,}</span>
              <span class="sep">·</span>
              <span class="y">{s.n_yellow:,}</span>
              <span class="sep">·</span>
              <span class="r">{s.n_red:,}</span>
            </div>
            <div class="summary-sub">green · yellow · red</div>
          </div>
          <div class="summary-card">
            <div class="summary-label">Photos scored</div>
            <div class="summary-value">{s.n_photos_scored:,}</div>
            <div class="summary-sub">
              {s.n_not_classified:,} dropped at relevance gate
            </div>
          </div>
          <div class="summary-card purple">
            <div class="summary-label">Run cost</div>
            <div class="summary-value">${s.total_cost:.2f}</div>
            <div class="summary-sub">
              Claude Sonnet 4.6 vision, full corpus
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_catches_row(s: HeaderStats) -> None:
    """The obvious-error catches — duplicates, geo, GDPR, tamper. Each is
    its own card with a count + plain-English explanation. Empty cards are
    skipped (only show what we actually found)."""
    cards: list[str] = []
    if s.n_duplicate_photos:
        plural = "s" if s.n_duplicate_photos != 1 else ""
        cards.append(
            f"<div class='catch-card dup'>"
            f"<div class='catch-count'>{s.n_duplicate_photos:,}</div>"
            f"<div class='catch-text'><b>Duplicate photo{plural}</b><br>"
            f"re-submitted across jobs</div></div>"
        )
    if s.n_geo_mismatch:
        plural = "es" if s.n_geo_mismatch != 1 else ""
        cards.append(
            f"<div class='catch-card geo'>"
            f"<div class='catch-count'>{s.n_geo_mismatch:,}</div>"
            f"<div class='catch-text'><b>Geo-mismatch{plural}</b><br>"
            f"lat/lon ↔ printed address &gt;150 m apart</div></div>"
        )
    if s.n_personal_data:
        plural = "s" if s.n_personal_data != 1 else ""
        cards.append(
            f"<div class='catch-card gdpr'>"
            f"<div class='catch-count'>{s.n_personal_data:,}</div>"
            f"<div class='catch-text'><b>Withheld photo{plural}</b><br>"
            f"GDPR / NIS2 — face or licence plate</div></div>"
        )
    if s.n_ela:
        plural = "s" if s.n_ela != 1 else ""
        cards.append(
            f"<div class='catch-card tamper'>"
            f"<div class='catch-count'>{s.n_ela:,}</div>"
            f"<div class='catch-text'><b>Tamper hint{plural}</b><br>"
            f"re-save suspected (ELA)</div></div>"
        )
    if not cards:
        return
    st.markdown("<div class='section-head'>Obvious catches</div>",
                unsafe_allow_html=True)
    st.markdown(
        "<div class='catches-row'>" + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


# --- Demo tour ----------------------------------------------------------

def _find_demo_segments(
    verdicts_by_segment: dict[str, dict],
    geomatch_df: pd.DataFrame,
    readqc: list[dict],
    forensics: list[dict],
) -> dict[str, str | None]:
    """For each demo-tour button, pick one segment in the loaded data that
    showcases the scenario. Returns None per slot when nothing matches —
    the button is then disabled rather than guessing."""
    red_gap: str | None = None
    red_segs = [
        s for s in verdicts_by_segment.values()
        if s.get("verdict") == "RED"
    ]
    if red_segs:
        red_gap = max(
            red_segs,
            key=lambda s: float(s.get("length_m") or 0),
        )["segment_id"]

    gdpr: str | None = None
    pd_photos = {
        r["photo_id"] for r in readqc
        if r.get("personal_data_visible") == "yes"
    }
    if pd_photos and not geomatch_df.empty:
        match = geomatch_df[geomatch_df["photo_id"].isin(pd_photos)]
        match = match[match["segment_id"].notna() & (match["segment_id"] != "")]
        if not match.empty:
            gdpr = str(match.iloc[0]["segment_id"])

    duplicate: str | None = None
    non_rep = {
        r["photo_id"] for r in forensics
        if not r.get("is_phash_representative")
    }
    if non_rep and not geomatch_df.empty:
        match = geomatch_df[geomatch_df["photo_id"].isin(non_rep)]
        match = match[match["segment_id"].notna() & (match["segment_id"] != "")]
        if not match.empty:
            duplicate = str(match.iloc[0]["segment_id"])

    return {"red_gap": red_gap, "duplicate": duplicate, "gdpr": gdpr}


def render_demo_tour(
    verdicts_by_segment: dict[str, dict],
    geomatch_df: pd.DataFrame,
    readqc: list[dict],
    forensics: list[dict],
) -> None:
    """Three jump-to buttons. Picks one segment per scenario from the
    loaded data; disables a button if no example exists. Selecting a tour
    target sets session_state['selected_segment'] — the panel reads from
    there. A subsequent map click overrides the tour selection."""
    picks = _find_demo_segments(
        verdicts_by_segment, geomatch_df, readqc, forensics,
    )
    st.markdown(
        "<div class='section-head'>Demo tour — jump to a typical catch</div>",
        unsafe_allow_html=True,
    )
    tour_items = [
        ("red_gap",   "Red segment · coverage gap",
            "missing photos on a long stretch"),
        ("duplicate", "Duplicate caught",
            "same photo across two jobs"),
        ("gdpr",      "GDPR redaction",
            "face / licence plate withheld"),
    ]
    cols = st.columns(3)
    for col, (key, label, sub) in zip(cols, tour_items):
        seg_id = picks.get(key)
        disabled = seg_id is None
        with col:
            clicked = st.button(
                label,
                key=f"tour_{key}",
                disabled=disabled,
                use_container_width=True,
            )
            if clicked and seg_id is not None:
                st.session_state["selected_segment"] = seg_id
            st.caption(
                sub if not disabled else f"{sub} — no example in data"
            )


# --- Live photo scoring (sidebar) ---------------------------------------

LIVE_MODEL_KEY = "sonnet"  # claude-sonnet-4-6


def _resolved_exemplars() -> list[tuple[str, Path, str]]:
    """The 4 readqc exemplars, with a fallback path for boxes that don't
    have the gitignored `data/Beispiele/` tree (e.g. a fresh checkout)."""
    from src.readqc import EXEMPLARS
    out: list[tuple[str, Path, str]] = []
    for name, path, caption in EXEMPLARS:
        if path.exists():
            out.append((name, path, caption))
        else:
            alt = EXEMPLARS_FALLBACK_DIR / path.name
            if alt.exists():
                out.append((name, alt, caption))
    return out


@st.cache_resource(show_spinner=False)
def _live_score_prefix() -> list[dict]:
    """Build the cached 4-exemplar prefix once per Streamlit process.
    Returns an empty list if no exemplars are reachable — the call still
    works, just without few-shot anchors."""
    from src.readqc import b64
    exemplars = _resolved_exemplars()
    if not exemplars:
        return []
    blocks: list[dict] = []
    for i, (name, path, caption) in enumerate(exemplars):
        media, data = b64(path)
        blocks.append({
            "type": "text",
            "text": f"Exemplar {i + 1} -- {name}: {caption}",
        })
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media,
                "data": data,
            },
        })
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _anthropic_client():
    """Build a fresh Anthropic client per call. NOT cached — caching with
    @st.cache_resource bit us hard: if the first call ever happened before
    .env existed, the cache stored None and kept returning None even after
    .env was added mid-session. The client itself is cheap to construct
    (just stores config); the expensive part is the exemplar prefix, which
    IS cached via _live_score_prefix below."""
    from src.readqc import load_env_key
    load_env_key()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    return anthropic.Anthropic()


def _score_uploaded_photo(
    file_bytes: bytes, suffix: str,
) -> tuple[Any, float, str | None]:
    """Run one Claude vision call on the uploaded bytes, with retries on
    transient upstream errors (Cloudflare 502, 429, etc). Returns
    (QCResult|None, cost_usd, error_message|None)."""
    from src.readqc import MODELS, _score_with_retry, cost_of
    client = _anthropic_client()
    if client is None:
        return None, 0.0, (
            "ANTHROPIC_API_KEY not set. Add it to .env or paste it below."
        )
    prefix = _live_score_prefix()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)
    try:
        # _score_with_retry handles 429, 502/503/504, Overloaded,
        # APIConnectionError, etc. Up to 3 attempts with 2/4/8s backoff.
        result, usage, err = _score_with_retry(
            client, MODELS[LIVE_MODEL_KEY], prefix, tmp_path,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    if err:
        return None, 0.0, err
    return result, cost_of(MODELS[LIVE_MODEL_KEY], usage), None


def _verdict_for_live_photo(qc: Any) -> tuple[str, str]:
    """A one-photo flavor of the rubric, just for the live demo card.
    Returns (label, pill_class). The pipeline verdict is per-segment;
    this is a lighter 'would this photo be compliant on its own?' badge."""
    relevance = getattr(qc, "relevance", None)
    if relevance != "scorable":
        return "DROP", "muted"
    if getattr(qc, "personal_data_visible", "no") == "yes":
        return "WITHHELD", "cyan"
    failing = [
        f for f, _ in PHOTO_CHECK_FIELDS
        if getattr(qc, f, "no") == "no"
    ]
    if not failing:
        return "PASS", "green"
    if len(failing) <= 2:
        return "WARN", "yellow"
    return "FAIL", "red"


def _render_live_score_result(
    qc: Any, image_bytes: bytes, cost_usd: float,
) -> None:
    """Result card under the uploader."""
    verdict_label, pill_class = _verdict_for_live_photo(qc)
    st.markdown(
        f"<div style='margin-top:8px;'>"
        f"<span style='font-size:10px;color:var(--c-muted);font-weight:600;"
        f"letter-spacing:0.08em;text-transform:uppercase;margin-right:8px;'>"
        f"Live verdict</span>"
        f"<span class='verdict-pill {pill_class} large'>"
        f"{verdict_label}</span></div>",
        unsafe_allow_html=True,
    )

    # Image preview — withhold if Claude flagged personal data.
    if getattr(qc, "personal_data_visible", "no") == "yes":
        st.markdown(
            "<div class='gdpr-card' style='margin-top:8px;min-height:120px;'>"
            "<div class='gdpr-icon'>&#x1F6AB;</div>"
            "<div class='gdpr-title'>Image withheld</div>"
            "<div class='gdpr-body'>Personal data detected — "
            "withheld per GDPR / NIS2.</div></div>",
            unsafe_allow_html=True,
        )
    else:
        st.image(image_bytes, width="stretch")

    st.markdown(
        f"<div style='font-size:11.5px;color:var(--c-text-2);margin-top:6px;'>"
        f"relevance <b style='color:var(--c-text);'>"
        f"{getattr(qc, 'relevance', '?')}</b> · "
        f"phase <b style='color:var(--c-text);'>"
        f"{getattr(qc, 'phase', '?')}</b> · "
        f"cost <b style='color:var(--c-text);'>${cost_usd:.4f}</b></div>",
        unsafe_allow_html=True,
    )

    # Check chips (uses the same chip style as the segment panel)
    chips = "".join(
        render_check_chip_v2(label, getattr(qc, field, "?"))
        for field, label in PHOTO_CHECK_FIELDS
    )
    st.markdown(
        f"<div style='margin-top:8px;line-height:1.9;'>{chips}</div>",
        unsafe_allow_html=True,
    )

    # Overlay fields (the geomatch signals Claude read off the photo).
    # Address + lat/lon are NDA-redacted on screen so a demoer who drops
    # a Resources/ photo in front of judges doesn't leak the route. The
    # full values still flow through the pipeline; the UI just doesn't
    # render them. Matches the redaction pattern at src/geomatch.py:219.
    overlay_rows = []
    if getattr(qc, "overlay_date", ""):
        overlay_rows.append(("Date", qc.overlay_date))
    if getattr(qc, "overlay_address", ""):
        addr = qc.overlay_address
        redacted = (addr[:3] + "…") if len(addr) > 3 else "…"
        overlay_rows.append(("Address", f"{redacted}  (NDA-redacted)"))
    if getattr(qc, "overlay_latlon", None):
        overlay_rows.append(("Lat/Lon", "✓ present  (NDA-redacted)"))
    if getattr(qc, "paper_label_code", None):
        overlay_rows.append(("Paper label", qc.paper_label_code))
    if overlay_rows:
        st.markdown(
            "<div class='section-head' style='margin:12px 0 4px 0;'>"
            "Overlay fields</div>",
            unsafe_allow_html=True,
        )
        rows_html = "".join(
            f"<div style='font-size:11.5px;margin-bottom:3px;'>"
            f"<span style='color:var(--c-muted);'>{k}:</span> "
            f"<code style='font-size:11px;background:var(--c-bg);"
            f"padding:1px 5px;border-radius:3px;'>{v}</code></div>"
            for k, v in overlay_rows
        )
        st.markdown(rows_html, unsafe_allow_html=True)

    note = getattr(qc, "note", "") or ""
    if note:
        st.markdown(
            f"<div style='margin-top:10px;font-size:11.5px;"
            f"color:var(--c-muted);font-style:italic;line-height:1.4;'>"
            f"{note}</div>",
            unsafe_allow_html=True,
        )


def render_live_score_sidebar() -> None:
    """Sidebar block: drop a photo, get a live Claude QC score."""
    with st.sidebar:
        st.markdown(
            "<div style='font-size:11px;font-weight:600;color:var(--c-accent);"
            "letter-spacing:0.12em;text-transform:uppercase;margin-bottom:2px;'>"
            "Try it live</div>"
            "<div style='font-size:1.1rem;font-weight:700;color:var(--c-text);"
            "margin-bottom:6px;line-height:1.2;'>Score a photo</div>"
            "<div style='font-size:12.5px;color:var(--c-text-2);"
            "line-height:1.45;margin-bottom:14px;'>"
            "Drop a trench photo. We call Claude Sonnet 4.6 with the same "
            "prompt the batch pipeline uses and show the QC verdict here."
            "</div>",
            unsafe_allow_html=True,
        )

        # API key handling. Always show the field — the user might want to
        # paste a different key even when one is already loaded from .env.
        # Precedence: pasted (this session) > .env > shell env > nothing.
        from src.readqc import load_env_key
        load_env_key()
        env_key_present = bool(os.environ.get("ANTHROPIC_API_KEY"))
        if env_key_present:
            st.markdown(
                "<div style='background:var(--c-green-soft);"
                "border:1px solid #bbf7d0;color:#166534;"
                "padding:6px 10px;border-radius:var(--r-sm);"
                "font-size:11.5px;margin-bottom:6px;'>"
                "✓ API key loaded from <code>.env</code>"
                "</div>",
                unsafe_allow_html=True,
            )
            pasted = st.text_input(
                "Override with a different key (optional)",
                type="password",
                placeholder="sk-ant-api03-... (leave empty to use .env)",
                key="api_key_override",
            )
        else:
            pasted = st.text_input(
                "ANTHROPIC_API_KEY",
                type="password",
                placeholder="sk-ant-api03-...",
                help=(
                    "Used only for this session. For batch runs, set it in "
                    ".env at the repo root."
                ),
                key="api_key_input",
            )
        if pasted:
            os.environ["ANTHROPIC_API_KEY"] = pasted.strip()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.markdown(
                "<div style='background:var(--c-amber-soft);"
                "border:1px solid #fcd34d;color:#78350f;"
                "padding:8px 10px;border-radius:var(--r-sm);"
                "font-size:11.5px;'>"
                "No API key set — uploads will not score until you paste "
                "one above or set <code>ANTHROPIC_API_KEY</code> in "
                "<code>.env</code>.</div>",
                unsafe_allow_html=True,
            )

        uploaded_files = st.file_uploader(
            "Photos (JPG / PNG) — drop one or many",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key="live_upload",
        )

        if uploaded_files:
            cache = st.session_state.setdefault("live_score_cache", {})

            # Pending: files we haven't yet scored OR whose cached result
            # was an error (so a transient 502 / stale-key gets re-tried
            # on the next interaction without the user having to remove +
            # re-add the file). A successful score is cached and never
            # rescored.
            pending: list[tuple[Any, bytes, tuple[str, int]]] = []
            for f in uploaded_files:
                file_bytes = f.getvalue()
                key = (f.name, len(file_bytes))
                cached = cache.get(key)
                if cached is None or cached[0] is None:
                    pending.append((f, file_bytes, key))

            if pending:
                n = len(pending)
                # Single progress bar advances as each photo finishes —
                # one-by-one because the sidebar wants visible per-photo
                # feedback during the demo ("watch it score each one").
                progress = st.progress(
                    0.0, text=f"Scoring 0/{n} with Claude Sonnet 4.6 …"
                )
                for i, (f, file_bytes, key) in enumerate(pending, 1):
                    suffix = Path(f.name).suffix or ".jpg"
                    qc, cost, err = _score_uploaded_photo(file_bytes, suffix)
                    cache[key] = (qc, cost, err, file_bytes)
                    if qc is not None:
                        st.session_state["live_total_cost"] = (
                            st.session_state.get("live_total_cost", 0.0)
                            + cost
                        )
                    progress.progress(
                        i / n,
                        text=f"Scoring {i}/{n} with Claude Sonnet 4.6 …",
                    )
                progress.empty()

            # Render results in upload order. Multiple photos stack
            # vertically; each gets a small "Photo N" header so the
            # demoer can point to which result is which. We use an
            # index, not the filename, because Resources/ filenames can
            # carry route hints (camera-app prefixes, FCP codes that
            # someone renamed locally) that we don't want on the
            # projector during the demo.
            for idx, f in enumerate(uploaded_files, 1):
                file_bytes = f.getvalue()
                key = (f.name, len(file_bytes))
                if key not in cache:
                    continue
                qc, cost, err, img_bytes = cache[key]
                if len(uploaded_files) > 1:
                    st.markdown(
                        f"<div class='section-head' "
                        f"style='margin:14px 0 6px 0;'>"
                        f"<code style='font-family:ui-monospace,monospace;"
                        f"font-size:11px;background:var(--c-bg);"
                        f"padding:2px 6px;border-radius:4px;'>"
                        f"Photo {idx}</code></div>",
                        unsafe_allow_html=True,
                    )
                if err:
                    st.error(err)
                    # Per-file retry — clears just this cache entry so the
                    # next rerun re-attempts. Avoids forcing the user to
                    # remove and re-add the file from the uploader.
                    retry_key = (
                        f"retry_{f.name}_{len(file_bytes)}"
                    )
                    if st.button("Retry", key=retry_key,
                                 use_container_width=False):
                        cache.pop(key, None)
                        st.rerun()
                elif qc is not None:
                    _render_live_score_result(qc, img_bytes, cost)

        total = st.session_state.get("live_total_cost", 0.0)
        if total > 0:
            n_photos = len(st.session_state.get("live_score_cache", {}))
            plural = "s" if n_photos != 1 else ""
            st.markdown(
                f"<div style='margin-top:18px;padding:10px 12px;"
                f"background:var(--c-bg);border:1px solid var(--c-border);"
                f"border-radius:var(--r-sm);font-size:11.5px;"
                f"color:var(--c-text-2);'>"
                f"Session live-score spend: "
                f"<b style='color:var(--c-text);'>${total:.4f}</b> "
                f"({n_photos} photo{plural})</div>",
                unsafe_allow_html=True,
            )


def _inject_css() -> None:
    """The design system. CSS variables for tokens (color, spacing, radius)
    + component classes (.card, .pill, .badge, .hero, .summary-card,
    .tour-button, .catch-card, .reason-item). Used by the inline-HTML
    components below. Theme is pinned to light via .streamlit/config.toml
    so these colors are deterministic."""
    st.markdown(
        """
        <style>
        :root {
            --c-bg: #f8fafc;
            --c-surface: #ffffff;
            --c-border: #e2e8f0;
            --c-border-soft: #eef2f7;
            --c-text: #0f172a;
            --c-text-2: #475569;
            --c-muted: #64748b;
            --c-accent: #0ea5e9;
            --c-accent-deep: #0369a1;
            --c-accent-soft: #e0f2fe;
            --c-green: #16a34a;
            --c-green-soft: #dcfce7;
            --c-yellow: #ca8a04;
            --c-yellow-soft: #fef9c3;
            --c-red: #dc2626;
            --c-red-soft: #fee2e2;
            --c-purple: #a855f7;
            --c-purple-soft: #f3e8ff;
            --c-amber: #b45309;
            --c-amber-soft: #fef3c7;
            --c-cyan: #0891b2;
            --c-cyan-soft: #cffafe;
            --r-sm: 6px;
            --r-md: 10px;
            --r-lg: 14px;
            --r-pill: 999px;
            --shadow-card: 0 1px 2px rgba(15,23,42,0.04),
                            0 1px 3px rgba(15,23,42,0.05);
            --shadow-elev: 0 4px 14px rgba(15,23,42,0.08);
            --font-stack: -apple-system, BlinkMacSystemFont, "Segoe UI",
                          Roboto, "Helvetica Neue", Arial, sans-serif;
        }

        /* Page chrome */
        html, body, [class*="css"] {
            font-family: var(--font-stack);
            color: var(--c-text);
        }
        .stApp { background: var(--c-bg); }
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
            max-width: 1500px;
        }
        /* Hide Streamlit's default header/footer for a cleaner canvas */
        header[data-testid="stHeader"] { background: transparent; }
        footer { visibility: hidden; }
        #MainMenu { visibility: hidden; }

        /* Sidebar */
        section[data-testid="stSidebar"] {
            background: var(--c-surface);
            border-right: 1px solid var(--c-border);
        }
        section[data-testid="stSidebar"] .block-container {
            padding-top: 1.25rem;
        }

        /* Typography */
        h1, h2, h3, h4 { color: var(--c-text); letter-spacing: -0.01em; }
        h3 { font-size: 1.05rem; margin-top: 0.5rem !important; }

        /* === Hero card === */
        .hero {
            background: linear-gradient(135deg,
                #0c4a6e 0%, #0369a1 55%, #0ea5e9 100%);
            color: #ffffff;
            border-radius: var(--r-lg);
            padding: 22px 28px;
            margin-bottom: 16px;
            box-shadow: var(--shadow-elev);
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 24px;
            flex-wrap: wrap;
        }
        .hero-left { flex: 1 1 360px; }
        .hero-eyebrow {
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            opacity: 0.85;
            margin-bottom: 6px;
        }
        .hero-title {
            font-size: 1.55rem;
            font-weight: 700;
            line-height: 1.15;
            margin-bottom: 8px;
        }
        .hero-sub {
            font-size: 0.92rem;
            line-height: 1.45;
            opacity: 0.92;
            max-width: 640px;
        }
        .hero-stats {
            display: flex;
            gap: 18px;
            flex-wrap: wrap;
            align-items: stretch;
        }
        .hero-stat {
            background: rgba(255,255,255,0.13);
            backdrop-filter: blur(2px);
            border: 1px solid rgba(255,255,255,0.18);
            padding: 10px 14px;
            border-radius: var(--r-md);
            min-width: 110px;
        }
        .hero-stat-label {
            font-size: 10px;
            font-weight: 600;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            opacity: 0.85;
        }
        .hero-stat-value {
            font-size: 1.4rem;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            margin-top: 2px;
        }

        /* === Summary cards === */
        .summary-row {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin-bottom: 14px;
        }
        @media (max-width: 1000px) {
            .summary-row { grid-template-columns: repeat(2, 1fr); }
        }
        .summary-card {
            background: var(--c-surface);
            border: 1px solid var(--c-border);
            border-radius: var(--r-md);
            padding: 14px 16px;
            box-shadow: var(--shadow-card);
            position: relative;
            overflow: hidden;
        }
        .summary-card::before {
            content: "";
            position: absolute;
            left: 0; top: 0; bottom: 0;
            width: 3px;
            background: var(--c-accent);
        }
        .summary-card.green::before { background: var(--c-green); }
        .summary-card.yellow::before { background: var(--c-yellow); }
        .summary-card.red::before { background: var(--c-red); }
        .summary-card.purple::before { background: var(--c-purple); }
        .summary-label {
            color: var(--c-muted);
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .summary-value {
            color: var(--c-text);
            font-size: 1.55rem;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            margin-top: 4px;
            line-height: 1.1;
        }
        .summary-sub {
            color: var(--c-text-2);
            font-size: 12px;
            margin-top: 4px;
        }
        .summary-traffic {
            display: flex;
            gap: 8px;
            margin-top: 4px;
            align-items: baseline;
        }
        .summary-traffic span {
            font-size: 1.1rem;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
        }
        .summary-traffic .g { color: var(--c-green); }
        .summary-traffic .y { color: var(--c-yellow); }
        .summary-traffic .r { color: var(--c-red); }
        .summary-traffic .sep { color: var(--c-border); font-weight: 400; }

        /* === Catches row === */
        .catches-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 10px;
            margin-bottom: 14px;
        }
        .catch-card {
            background: var(--c-surface);
            border: 1px solid var(--c-border);
            border-left: 3px solid var(--c-muted);
            border-radius: var(--r-sm);
            padding: 10px 12px;
            display: flex;
            align-items: center;
            gap: 10px;
            box-shadow: var(--shadow-card);
        }
        .catch-card.dup    { border-left-color: var(--c-purple); }
        .catch-card.geo    { border-left-color: var(--c-red); }
        .catch-card.gdpr   { border-left-color: var(--c-cyan); }
        .catch-card.tamper { border-left-color: var(--c-amber); }
        .catch-count {
            font-size: 1.4rem;
            font-weight: 700;
            font-variant-numeric: tabular-nums;
            line-height: 1;
        }
        .catch-card.dup    .catch-count { color: var(--c-purple); }
        .catch-card.geo    .catch-count { color: var(--c-red); }
        .catch-card.gdpr   .catch-count { color: var(--c-cyan); }
        .catch-card.tamper .catch-count { color: var(--c-amber); }
        .catch-text {
            font-size: 12px;
            line-height: 1.35;
            color: var(--c-text-2);
        }
        .catch-text b { color: var(--c-text); }

        /* === Section heading === */
        .section-head {
            font-size: 13px;
            font-weight: 600;
            color: var(--c-text-2);
            letter-spacing: 0.06em;
            text-transform: uppercase;
            margin: 14px 0 8px 0;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .section-head::after {
            content: "";
            flex: 1;
            height: 1px;
            background: var(--c-border);
        }

        /* === Demo tour buttons (styled st.button) === */
        .stButton > button {
            border-radius: var(--r-md);
            border: 1px solid var(--c-border);
            background: var(--c-surface);
            color: var(--c-text);
            font-weight: 500;
            padding: 8px 14px;
            transition: all 120ms ease;
            box-shadow: var(--shadow-card);
        }
        .stButton > button:hover {
            border-color: var(--c-accent);
            color: var(--c-accent-deep);
            transform: translateY(-1px);
        }
        .stButton > button:focus {
            box-shadow: 0 0 0 3px var(--c-accent-soft);
            border-color: var(--c-accent);
        }

        /* === Verdict pills === */
        .verdict-pill {
            display: inline-block;
            padding: 3px 10px;
            border-radius: var(--r-pill);
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: white;
            vertical-align: middle;
        }
        .verdict-pill.green  { background: var(--c-green); }
        .verdict-pill.yellow { background: var(--c-yellow); }
        .verdict-pill.red    { background: var(--c-red); }
        .verdict-pill.cyan   { background: var(--c-cyan); }
        .verdict-pill.muted  { background: var(--c-muted); }
        .verdict-pill.large {
            font-size: 12px;
            padding: 5px 14px;
        }

        /* === Panel === */
        .panel-card {
            background: var(--c-surface);
            border: 1px solid var(--c-border);
            border-radius: var(--r-md);
            padding: 16px 18px;
            box-shadow: var(--shadow-card);
        }
        .panel-title {
            font-size: 1.05rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 4px;
        }
        .panel-meta {
            color: var(--c-muted);
            font-size: 12px;
            margin-bottom: 12px;
        }
        .panel-meta code {
            background: var(--c-bg);
            padding: 1px 5px;
            border-radius: 4px;
            font-size: 11px;
        }
        .reason-list {
            margin: 6px 0 12px 0;
            padding: 0;
            list-style: none;
        }
        .reason-list li {
            background: var(--c-bg);
            border-left: 3px solid var(--c-yellow);
            padding: 6px 10px;
            margin-bottom: 4px;
            border-radius: 4px;
            font-size: 12.5px;
            color: var(--c-text-2);
        }

        /* === Check chips inside panel === */
        .check-chip {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            font-size: 10px;
            padding: 2px 6px;
            border-radius: var(--r-pill);
            font-weight: 500;
            margin: 1px 2px 1px 0;
            white-space: nowrap;
        }
        .check-chip .lbl { color: var(--c-text-2); }
        .check-chip .val {
            color: white;
            padding: 0 5px;
            border-radius: var(--r-pill);
            font-weight: 600;
        }
        .check-chip .val.yes      { background: var(--c-green); }
        .check-chip .val.no       { background: var(--c-red); }
        .check-chip .val.occluded { background: var(--c-amber); }
        .check-chip .val.na       { background: var(--c-muted); }

        /* === Worst-segments preview === */
        .worst-row {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 10px;
            border-radius: var(--r-sm);
            border: 1px solid var(--c-border-soft);
            background: var(--c-surface);
            margin-bottom: 6px;
        }
        .worst-row .id {
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 11px;
            background: var(--c-bg);
            padding: 2px 6px;
            border-radius: 4px;
            color: var(--c-text);
            white-space: nowrap;
        }
        .worst-row .why {
            color: var(--c-text-2);
            font-size: 12px;
            line-height: 1.35;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        /* === GDPR redaction card === */
        .gdpr-card {
            background: var(--c-amber-soft);
            border: 1.5px solid #f59e0b;
            border-radius: var(--r-sm);
            padding: 14px;
            text-align: center;
            color: #78350f;
            min-height: 160px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 4px;
        }
        .gdpr-card .gdpr-icon { font-size: 26px; line-height: 1; }
        .gdpr-card .gdpr-title { font-weight: 700; }
        .gdpr-card .gdpr-body  { font-size: 11.5px; }
        .gdpr-card .gdpr-foot  { font-size: 10.5px; color: #92400e; }

        /* === Source banner === */
        .source-banner {
            background: var(--c-accent-soft);
            border: 1px solid #bae6fd;
            color: var(--c-accent-deep);
            padding: 6px 12px;
            font-size: 12px;
            border-radius: var(--r-sm);
            margin-bottom: 10px;
            display: inline-block;
        }
        .source-banner.live {
            background: var(--c-green-soft);
            border-color: #bbf7d0;
            color: #166534;
        }

        /* === Download button polish === */
        .stDownloadButton > button {
            background: var(--c-accent);
            color: white;
            border: 1px solid var(--c-accent-deep);
            border-radius: var(--r-md);
            padding: 10px 16px;
            font-weight: 600;
        }
        .stDownloadButton > button:hover {
            background: var(--c-accent-deep);
            border-color: var(--c-accent-deep);
        }

        /* === File uploader polish === */
        [data-testid="stFileUploader"] section {
            border: 1.5px dashed var(--c-border) !important;
            border-radius: var(--r-md) !important;
            background: var(--c-bg) !important;
        }
        [data-testid="stFileUploader"] section:hover {
            border-color: var(--c-accent) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# --- Main ----------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="APG photo-QC",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_css()
    render_live_score_sidebar()

    paths = resolve_paths()

    verdicts = load_verdicts(str(paths.verdicts_csv))
    geomatch = load_geomatch(str(paths.geomatch_csv))
    readqc = load_jsonl(str(paths.readqc_jsonl))
    forensics = load_jsonl(str(paths.forensics_jsonl))
    manifest = load_manifest(str(paths.manifest_sqlite))
    trenches = load_geojson(str(paths.trenches_geojson))
    fcps = load_geojson(str(paths.fcps_geojson))
    cluster = load_geojson(str(paths.cluster_geojson))

    readqc_by_id = {r["photo_id"]: r for r in readqc}
    forensics_by_id = {r["photo_id"]: r for r in forensics}
    rep_by_cluster: dict[Any, str] = {
        r["phash_cluster_id"]: r["photo_id"]
        for r in forensics
        if r.get("is_phash_representative")
    }
    verdicts_by_segment: dict[str, dict] = {
        r["segment_id"]: r for r in verdicts.to_dict("records")
    }

    # Top of page: status banner → hero → summary cards → catches
    stats = _compute_header_stats(verdicts, readqc, forensics, geomatch)
    render_topbar(paths.source)
    render_hero(stats)
    render_summary_cards(stats)
    render_catches_row(stats)

    # Demo tour — three jump-to scenarios for the live pitch
    render_demo_tour(verdicts_by_segment, geomatch, readqc, forensics)

    photo_points = (
        geomatch[geomatch["lat"].notna() & geomatch["lon"].notna()][
            ["lat", "lon"]
        ].to_dict("records")
    )

    st.markdown(
        "<div class='section-head'>Compliance map · click a segment</div>",
        unsafe_allow_html=True,
    )
    map_col, panel_col = st.columns([3, 2], gap="medium")

    with map_col:
        m = build_map(
            trenches, fcps, cluster, verdicts_by_segment, photo_points
        )
        click = st_folium(
            m,
            width=None,
            height=620,
            returned_objects=[
                "last_active_drawing",
                "last_object_clicked_tooltip",
                "last_object_clicked",
            ],
            key="map",
        )

    # Selected-segment plumbing: map clicks update session_state, demo-tour
    # buttons set it directly. Most recent action wins. We track the last
    # observed click value so a stale st_folium-cached click doesn't
    # overwrite a fresh tour selection.
    click_seg = _segment_id_from_click(click, list(verdicts_by_segment))
    if click_seg and click_seg != st.session_state.get("_last_map_click_seg"):
        st.session_state["selected_segment"] = click_seg
        st.session_state["_last_map_click_seg"] = click_seg
    selected = st.session_state.get("selected_segment")
    if selected is not None and selected not in verdicts_by_segment:
        selected = None
        st.session_state.pop("selected_segment", None)

    with panel_col:
        if selected is None:
            _render_panel_placeholder()
            _render_top_issues(verdicts)
        else:
            render_segment_panel(
                selected,
                verdicts_by_segment,
                geomatch,
                readqc_by_id,
                forensics_by_id,
                rep_by_cluster,
                manifest,
                paths.photos_root,
            )

    _render_deficiency_download(verdicts)


def _render_panel_placeholder() -> None:
    st.markdown(
        "<div class='panel-card'>"
        "<div class='panel-title'>Click a segment</div>"
        "<div class='panel-meta'>"
        "Each colored line on the map is a trench segment. Click one to "
        "see the photos snapped to it, the per-photo compliance checks, "
        "and the reasons for the verdict."
        "</div></div>",
        unsafe_allow_html=True,
    )


def _segment_id_from_click(
    click: dict[str, Any] | None, known_ids: list[str]
) -> str | None:
    """Pull segment_id out of st_folium's returned click dict.

    streamlit-folium returns several click-related keys; we try them in
    priority order. last_active_drawing carries the full feature for a
    folium.GeoJson click; tooltip is a textual fallback we parse for the
    leading 'Segment <id>' from the GeoJsonTooltip.
    """
    if not click:
        return None
    drawing = click.get("last_active_drawing")
    if drawing:
        props = drawing.get("properties") or {}
        sid = props.get("segment_id")
        if sid and sid in known_ids:
            return sid
    tip = click.get("last_object_clicked_tooltip")
    if isinstance(tip, str):
        # Tooltip text like 'Segment S004 FCP F001 Verdict YELLOW Length …'.
        # The GeoJsonTooltip emits fields in declared order, so segment_id
        # is the FIRST cell. Pick the first token that matches a known id,
        # not just any token — avoids accidental matches against FCP names
        # or other tooltip fields if a future feature shares a segment_id
        # value (e.g. globalIDs with curly braces).
        known_set = set(known_ids)
        for token in tip.replace("\n", " ").split():
            token = token.strip().strip(":,")
            if token in known_set:
                return token
    return None


def _render_top_issues(verdicts: pd.DataFrame) -> None:
    """Compact preview of worst segments when no segment is selected."""
    bad = (
        verdicts[verdicts["verdict"] != "GREEN"]
        .sort_values(["verdict", "length_m"], ascending=[True, False])
        .head(8)
    )
    if bad.empty:
        st.markdown(
            "<div class='panel-card' style='margin-top:10px;text-align:center;"
            "color:var(--c-green);font-weight:600;'>"
            "All segments GREEN — nothing to flag.</div>",
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        "<div class='section-head'>Worst segments · preview</div>",
        unsafe_allow_html=True,
    )
    rows_html = ""
    for r in bad.to_dict("records"):
        pill_class = r["verdict"].lower()
        # Same NaN-defence as render_segment_panel — pandas may hand us a
        # float NaN for empty reasons cells.
        reasons_raw = r.get("reasons", "")
        reasons_str = reasons_raw if isinstance(reasons_raw, str) else ""
        why = reasons_str.replace("<", "&lt;").replace(">", "&gt;")
        rows_html += (
            f"<div class='worst-row'>"
            f"<span class='verdict-pill {pill_class}'>{r['verdict']}</span>"
            f"<span class='id'>{r['segment_id']}</span>"
            f"<span class='why'>{why}</span>"
            f"</div>"
        )
    st.markdown(rows_html, unsafe_allow_html=True)


def _render_deficiency_download(verdicts: pd.DataFrame) -> None:
    """A one-click CSV download. Same shape as src/report.py's
    deficiency.csv so a reviewer gets identical artifacts whether they
    download from the UI or fetch from the report directory."""
    from src.report import DEFICIENCY_FIELDS
    bad = (
        verdicts[verdicts["verdict"] != "GREEN"][list(DEFICIENCY_FIELDS)]
        .sort_values(["fcp_name", "length_m"], ascending=[True, False])
    )
    st.markdown(
        "<div class='section-head'>Hand off to the partner</div>",
        unsafe_allow_html=True,
    )
    n_bad = len(bad)
    plural = "s" if n_bad != 1 else ""
    download_col, info_col = st.columns([1, 2], gap="medium")
    with download_col:
        st.download_button(
            f"Download deficiency CSV ({n_bad} segment{plural})",
            data=bad.to_csv(index=False).encode("utf-8"),
            file_name="deficiency.csv",
            mime="text/csv",
            width="stretch",
        )
    with info_col:
        st.markdown(
            "<div style='font-size:12.5px;color:var(--c-text-2);"
            "line-height:1.5;padding-top:4px;'>"
            "One row per RED or YELLOW segment with the reasons that "
            "drove the verdict — drops straight into a contractor "
            "retake ticket. Same shape as the pipeline's own "
            "<code style='font-size:11px;background:var(--c-bg);"
            "padding:1px 5px;border-radius:3px;'>deficiency.csv</code>."
            "</div>",
            unsafe_allow_html=True,
        )


if __name__ == "__main__":
    main()
