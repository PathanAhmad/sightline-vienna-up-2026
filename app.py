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
import sqlite3
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
    return pd.read_csv(path_str, dtype=str).assign(
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
    return pd.read_csv(path_str, dtype=str).assign(
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
        f"<div style='background:#fef3c7;border:1.5px solid #f59e0b;"
        f"padding:18px;border-radius:6px;text-align:center;color:#78350f;"
        f"min-height:160px;display:flex;flex-direction:column;"
        f"justify-content:center;'>"
        f"<div style='font-size:28px;line-height:1;'>&#x1F6AB;</div>"
        f"<div style='font-weight:600;margin-top:6px;'>Image withheld</div>"
        f"<div style='font-size:12px;margin-top:4px;'>"
        f"Personal data detected (face / licence plate). "
        f"Withheld per GDPR / NIS2.</div>"
        f"<div style='font-size:11px;margin-top:6px;color:#92400e;'>"
        f"Routed to contractor retake bucket.</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"phase: **{qc.get('phase','?')}** · pos {segment_t:.0%} "
        f"· id `{pid[:10]}…`"
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


def render_check_pill(value: str) -> str:
    """Tiny inline HTML pill for a yes/no/occluded check value."""
    color = {
        "yes": "#16a34a",
        "no": "#dc2626",
        "occluded": "#a16207",
        "not_applicable": "#64748b",
    }.get(value, "#64748b")
    return (
        f"<span style='background:{color};color:white;padding:1px 6px;"
        f"border-radius:4px;font-size:11px'>{value}</span>"
    )


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
    color = VERDICT_COLORS.get(verdict, "#64748b")

    st.markdown(
        f"### Segment `{seg_id}` "
        f"<span style='background:{color};color:white;padding:2px 8px;"
        f"border-radius:6px;font-size:14px'>{verdict}</span>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"FCP {v.get('fcp_name','?')} · length "
        f"{_fmt_meters(v.get('length_m'))} · "
        f"{v.get('photo_count',0)} photos snapped · "
        f"{v.get('compliant_photo_count',0)} compliant"
    )

    reasons = v.get("reasons", "") or ""
    if reasons:
        st.markdown("**Why this verdict**")
        for r in reasons.split(";"):
            r = r.strip()
            if r:
                st.markdown(f"- {r}")

    # Photo grid (photos snapped to this segment)
    seg_photos = geomatch_df[geomatch_df["segment_id"] == seg_id]
    if seg_photos.empty:
        st.info("No photos snapped to this segment.")
        return

    st.markdown("**Photos on this segment**")
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
                        f"<div style='background:#e2e8f0;padding:30px;"
                        f"text-align:center;border-radius:6px;color:#475569;'>"
                        f"image unavailable<br><small>{pid[:24]}…</small></div>",
                        unsafe_allow_html=True,
                    )
                fo = forensics_by_id.get(pid, {})
                if qc:
                    st.caption(f"phase: **{qc.get('phase','?')}** · pos "
                               f"{float(row['segment_t']):.0%}")
                    if dup_of:
                        st.markdown(
                            "<small style='color:#7e22ce'>"
                            f"⟲ duplicate of <code>{dup_of[:24]}…</code>"
                            "</small>",
                            unsafe_allow_html=True,
                        )
                    chips = " ".join(
                        f"<span style='font-size:10px;color:#475569'>"
                        f"{label}:</span> {render_check_pill(qc.get(field,'?'))}"
                        for field, label in PHOTO_CHECK_FIELDS
                    )
                    st.markdown(chips, unsafe_allow_html=True)
                    if qc.get("note"):
                        st.caption(f"_{qc['note']}_")
                if fo.get("ela_flag"):
                    st.markdown(
                        "<small style='color:#b45309'>"
                        "⚠ ELA tamper hint</small>",
                        unsafe_allow_html=True,
                    )
                if row.get("latlon_vs_address_flag"):
                    st.markdown(
                        "<small style='color:#b91c1c'>"
                        "⚠ lat/lon ↔ address mismatch</small>",
                        unsafe_allow_html=True,
                    )


# --- Header KPIs ---------------------------------------------------------

def render_header(
    verdicts: pd.DataFrame,
    readqc: list[dict],
    forensics: list[dict],
    geomatch: pd.DataFrame,
    source: str,
) -> None:
    """Top-of-page summary: 4 KPIs + obvious-error chips."""
    st.title("APG photo-QC — segment compliance map")
    if source == "fixtures":
        st.caption(
            "⚙ Showing **demo fixtures** (synthetic). Real pipeline outputs "
            "at `data/processed/` will shadow these automatically."
        )

    n_segments = len(verdicts)
    counts = verdicts["verdict"].value_counts().to_dict()
    n_green = counts.get("GREEN", 0)
    n_yellow = counts.get("YELLOW", 0)
    n_red = counts.get("RED", 0)
    pct_green = (n_green / n_segments * 100) if n_segments else 0

    n_photos_scored = len(readqc)
    n_not_classified = sum(
        1 for r in readqc if r.get("relevance") != "scorable"
    )
    n_personal_data = sum(
        1 for r in readqc if r.get("personal_data_visible") == "yes"
    )
    n_duplicate_photos = max(0, len(forensics) - sum(
        1 for r in forensics if r.get("is_phash_representative")
    ))
    n_ela = sum(1 for r in forensics if r.get("ela_flag"))
    n_geo_mismatch = int(geomatch["latlon_vs_address_flag"].sum())
    total_cost = sum(r.get("cost_usd", 0.0) for r in readqc)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Segments", f"{n_segments}",
              delta=f"{pct_green:.0f}% green", delta_color="off")
    c2.metric(
        "GREEN / YELLOW / RED",
        f"{n_green} / {n_yellow} / {n_red}",
    )
    c3.metric("Photos scored", f"{n_photos_scored}",
              delta=f"-{n_not_classified} dropped", delta_color="off")
    c4.metric("Run cost", f"${total_cost:.2f}")

    chips = []
    if n_duplicate_photos:
        chips.append(
            (f"{n_duplicate_photos} duplicate photo"
             f"{'s' if n_duplicate_photos != 1 else ''} (re-submitted across jobs)",
             "#a855f7"))
    if n_geo_mismatch:
        chips.append(
            (f"{n_geo_mismatch} geo-mismatch"
             f"{'es' if n_geo_mismatch != 1 else ''} "
             f"(lat/lon ↔ printed address >150 m apart)",
             "#dc2626"))
    if n_personal_data:
        chips.append(
            (f"{n_personal_data} photo"
             f"{'s' if n_personal_data != 1 else ''} withheld "
             f"(GDPR / NIS2 — face or licence plate)",
             "#0891b2"))
    if n_ela:
        chips.append(
            (f"{n_ela} ELA tamper hint"
             f"{'s' if n_ela != 1 else ''} (re-save suspected)",
             "#b45309"))

    if chips:
        st.markdown("**Obvious-error catches**")
        cols = st.columns(len(chips))
        for col, (text, color) in zip(cols, chips):
            col.markdown(
                f"<div style='background:{color};color:white;padding:8px 12px;"
                f"border-radius:8px;font-size:13px'>{text}</div>",
                unsafe_allow_html=True,
            )


# --- Main ----------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="APG photo-QC",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

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

    render_header(verdicts, readqc, forensics, geomatch, paths.source)

    photo_points = (
        geomatch[geomatch["lat"].notna() & geomatch["lon"].notna()][
            ["lat", "lon"]
        ].to_dict("records")
    )

    map_col, panel_col = st.columns([2, 1], gap="medium")

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

    with panel_col:
        seg_id = _segment_id_from_click(click, list(verdicts_by_segment))
        if seg_id is None:
            st.markdown("### Click a segment on the map")
            st.caption(
                "Each colored line is a trench segment. Click one to see "
                "the photos snapped to it, the per-photo compliance "
                "checks, and the reasons for the verdict."
            )
            # Show a quick deficiency summary as a fallback.
            _render_top_issues(verdicts)
        else:
            render_segment_panel(
                seg_id,
                verdicts_by_segment,
                geomatch,
                readqc_by_id,
                forensics_by_id,
                rep_by_cluster,
                manifest,
                paths.photos_root,
            )

    st.divider()
    _render_deficiency_download(verdicts)


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
        st.success("All segments GREEN — nothing to flag.")
        return
    st.markdown("**Worst segments (preview)**")
    for r in bad.to_dict("records"):
        color = VERDICT_COLORS[r["verdict"]]
        st.markdown(
            f"<div style='border-left:4px solid {color};padding:4px 8px;"
            f"margin:4px 0;font-size:13px'>"
            f"<b>{r['segment_id']}</b> ({r['verdict']}) — "
            f"{r['reasons']}</div>",
            unsafe_allow_html=True,
        )


def _render_deficiency_download(verdicts: pd.DataFrame) -> None:
    """A one-click CSV download. Same shape as src/report.py's
    deficiency.csv so a reviewer gets identical artifacts whether they
    download from the UI or fetch from the report directory."""
    # Import here to avoid a top-level src dependency in the demo path.
    from src.report import DEFICIENCY_FIELDS
    bad = (
        verdicts[verdicts["verdict"] != "GREEN"][list(DEFICIENCY_FIELDS)]
        .sort_values(["fcp_name", "length_m"], ascending=[True, False])
    )
    st.download_button(
        "Download deficiency CSV (RED + YELLOW segments)",
        data=bad.to_csv(index=False).encode("utf-8"),
        file_name="deficiency.csv",
        mime="text/csv",
        width="stretch",
    )


if __name__ == "__main__":
    main()
