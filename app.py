"""Streamlit entrypoint — two surfaces behind one `streamlit run`.

Run: `uv run streamlit run app.py`

Two surfaces, switched by `?view=` query param:
    /                  → reviewer dashboard (map + KPI rail + drill-down)
    /?view=upload      → operator submission form (drop photos, get verdicts)

The two-surface split mirrors the brief's two implied roles — contractor
who submits, APG reviewer who triages. Demo: open both URLs in two
browser tabs, narrate the role swap.

Dashboard rendering lives directly in `main()` below; the upload view is
its own module (`src/ui/upload_view.py`). Shared chrome lives in
`src/ui/` — tokens, base, layout, components.

Data sources for the dashboard (preferred → fallback):
    data/processed/   real pipeline outputs (gitignored)
    demo_fixtures/    synthetic stand-ins (committed)

Demo-day rule (CLAUDE.md): no live Claude calls during the dashboard
demo. Upload view does call Claude live (it's the point) — keep that
batch small.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src.ui import (
    catches,
    demo_tour,
    download,
    hero,
    inject_all_css,
    layout,
    map_view,
    segment_panel,
    topbar,
    upload_panel,
)
from src.ui.components.hero import HeroStats
from src.ui.components.live_geomatch import (
    _load_geom_utm,
    qc_to_geomatch_row,
    qc_to_readqc_row,
    recompute_verdicts,
)


# ---- Paths --------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent
REAL_PROCESSED = REPO_ROOT / "data" / "processed"
REAL_GEO = REPO_ROOT / "data" / "geo"
REAL_PHOTOS_DIR = REPO_ROOT / "data" / "Fotos" / "Fotos"
FIXTURE_DIR = REPO_ROOT / "demo_fixtures"
FIXTURE_GEO = FIXTURE_DIR / "geo"
RESOURCES_PHOTOS_DIR = REPO_ROOT / "Resources" / "all"


@dataclass
class DataPaths:
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

    All-or-nothing: only switch to live if every required artifact is
    present, otherwise a partial live state crashes a downstream loader.
    """
    live = {
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
    if all(p.exists() for p in live.values()):
        return DataPaths(source="live", photos_root=REAL_PHOTOS_DIR, **live)
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


# ---- Loaders ------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_verdicts(path_str: str) -> pd.DataFrame:
    # keep_default_na=False: empty CSV cells stay as "" (not NaN).
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


# ---- Stats --------------------------------------------------------------

def compute_hero_stats(
    verdicts: pd.DataFrame,
    readqc: list[dict],
    forensics: list[dict],
    geomatch: pd.DataFrame,
) -> HeroStats:
    n_segments = len(verdicts)
    counts = verdicts["verdict"].value_counts().to_dict()
    n_green = counts.get("GREEN", 0)
    n_yellow = counts.get("YELLOW", 0)
    n_red = counts.get("RED", 0)
    return HeroStats(
        pct_compliant=(n_green / n_segments * 100) if n_segments else 0.0,
        n_green=n_green,
        n_yellow=n_yellow,
        n_red=n_red,
        n_segments=n_segments,
        n_photos_scored=len(readqc),
        total_cost_usd=sum(r.get("cost_usd", 0.0) for r in readqc),
        audit_minutes=28,
        n_duplicate_photos=max(0, len(forensics) - sum(
            1 for r in forensics if r.get("is_phash_representative")
        )),
        n_geo_mismatch=int(geomatch["latlon_vs_address_flag"].sum()),
        n_personal_data=sum(
            1 for r in readqc if r.get("personal_data_visible") == "yes"
        ),
        n_ela=sum(1 for r in forensics if r.get("ela_flag")),
    )


# ---- Lot-bundle helpers -------------------------------------------------

def _seed_lot_verdicts(geom_handle: dict) -> pd.DataFrame:
    """One all-RED row per segment in the loaded lot.

    The dashboard renders the lot's trenches even before any photos have
    been scored. Without a verdict row per segment, the map would
    correctly default-color them red (via `verdicts_by_segment.get`),
    but the hero stats would say "0 segments" -- which contradicts the
    map. Seeding gives both surfaces the same view of the lot's size.
    """
    rows = [
        {
            "segment_id": seg_id,
            "fcp_name": geom_handle["seg_fcp"].get(seg_id, ""),
            "length_m": round(length_m, 2),
            "photo_count": 0,
            "compliant_photo_count": 0,
            "max_gap_m": round(length_m, 2),
            "density_photos_per_5m": 0.0,
            "verdict": "RED",
            "reasons": "no compliant photos snapped",
        }
        for seg_id, length_m in geom_handle["seg_length_m"].items()
    ]
    return pd.DataFrame(rows)


# ---- Main ---------------------------------------------------------------

def main() -> None:
    # Two-surface split (post-2026-05-16): the brief's #1 deliverable is an
    # upload interface (operator view). The map/stats dashboard (reviewer
    # view) is the second surface. We route via `?view=` so both surfaces
    # share one Streamlit process; the user opens two browser tabs:
    #   localhost:8501/?view=upload  →  operator submission
    #   localhost:8501/              →  reviewer dashboard
    view = st.query_params.get("view", "dashboard")

    if view == "upload":
        st.set_page_config(
            page_title="APG photo-QC · Submit batch",
            layout="wide",
            initial_sidebar_state="collapsed",
        )
        inject_all_css()
        from src.ui.components import chat
        from src.ui.upload_view import render as render_upload
        render_upload()
        chat.render_fab()
        return

    # ---- Reviewer dashboard ----
    st.set_page_config(
        page_title="APG photo-QC · Reviewer dashboard",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_all_css()
    # The old live-score sidebar is dropped from the dashboard — its
    # scoring helpers are now imported by the upload view instead.
    st.markdown(
        "<style>"
        "section[data-testid='stSidebar'] { display: none !important; }"
        "[data-testid='stSidebarCollapsedControl'] "
        "{ display: none !important; }"
        "</style>",
        unsafe_allow_html=True,
    )

    paths = resolve_paths()
    session_lot = st.session_state.get("session_lot")

    if session_lot:
        # Operator dropped a contractor bundle: use the bundle's geojsons
        # for the map, and start with an empty data set -- the on-disk
        # verdicts.csv / geomatch.csv / readqc.jsonl all belong to the
        # *previous* lot's trenches, so mixing them in would surface
        # ghost segments that don't exist in this lot.
        trenches_path = Path(session_lot["trenches_path"])
        fcps_path = Path(session_lot["fcps_path"])
        cluster_path = Path(session_lot["cluster_path"])
        trenches = load_geojson(str(trenches_path))
        fcps = load_geojson(str(fcps_path))
        cluster = load_geojson(str(cluster_path))
        geomatch_cols = [
            "photo_id", "lat", "lon", "coord_source",
            "segment_id", "segment_t", "snap_distance_m",
            "fcp_name", "fcp_assignment",
            "label_match", "latlon_vs_address_flag",
        ]
        geomatch = pd.DataFrame(columns=geomatch_cols)
        # lat/lon need numeric dtype so the photo_points filter works.
        geomatch["lat"] = pd.to_numeric(geomatch["lat"], errors="coerce")
        geomatch["lon"] = pd.to_numeric(geomatch["lon"], errors="coerce")
        readqc = []
        forensics = []
        manifest = {}
        # Verdicts start empty; we seed one all-RED row per segment
        # *after* the geom_handle loads (it has the segment lengths).
        # Until then, an empty DF with the right columns keeps any
        # `.value_counts()` / `.to_dict()` calls happy on early returns.
        verdicts = pd.DataFrame(columns=[
            "segment_id", "fcp_name", "length_m", "photo_count",
            "compliant_photo_count", "max_gap_m",
            "density_photos_per_5m", "verdict", "reasons",
        ])
    else:
        trenches_path = paths.trenches_geojson
        fcps_path = paths.fcps_geojson
        cluster_path = paths.cluster_geojson
        verdicts = load_verdicts(str(paths.verdicts_csv))
        geomatch = load_geomatch(str(paths.geomatch_csv))
        readqc = load_jsonl(str(paths.readqc_jsonl))
        forensics = load_jsonl(str(paths.forensics_jsonl))
        manifest = load_manifest(str(paths.manifest_sqlite))
        trenches = load_geojson(str(paths.trenches_geojson))
        fcps = load_geojson(str(paths.fcps_geojson))
        cluster = load_geojson(str(paths.cluster_geojson))

    # ---- Live uploads: merge into the on-disk data ---------------------
    # Geopandas is heavy; only load when we actually have uploads (or are
    # about to render the upload panel, which is always on the dash view).
    # `_load_geom_utm` is @st.cache_resource so the cost is paid once per
    # session, not per rerun (cache is keyed on the path triple, so a
    # newly loaded lot bundle keys a fresh entry without invalidating
    # the default lot's cached geom).
    try:
        geom_handle = _load_geom_utm(
            str(trenches_path),
            str(fcps_path),
            str(cluster_path),
        )
    except Exception as e:
        # If geopandas / shapely isn't installed or a geojson fails to
        # parse, fall back to a no-snap upload experience -- the photos
        # still score, they just don't recolor segments.
        geom_handle = None
        st.session_state["_dash_geom_error"] = repr(e)

    # If the dashboard is in session-lot mode, seed verdicts AFTER we've
    # built the geom_handle so we can iterate the lot's real segments.
    if session_lot and geom_handle is not None and verdicts.empty:
        verdicts = _seed_lot_verdicts(geom_handle)

    upload_state: list[dict] = st.session_state.get("dashboard_uploads", [])
    upload_readqc: list[dict] = []
    upload_geomatch: list[dict] = []
    for u in upload_state:
        if u.get("err") or u.get("qc") is None:
            continue
        upload_readqc.append(qc_to_readqc_row(u["qc"], u["photo_id"]))
        upload_geomatch.append(
            qc_to_geomatch_row(u["photo_id"], u.get("lat"), u.get("lon"), u.get("snap"))
        )

    # Snapshot baseline verdicts BEFORE the merge so we can diff and tell
    # the operator exactly which segments their batch moved -- the rail's
    # "Δ this batch" summary reads from this.
    baseline_verdict_by_seg: dict[str, str] = {
        r["segment_id"]: r["verdict"]
        for r in verdicts.to_dict("records")
    }

    if upload_readqc and geom_handle is not None:
        verdicts, geomatch, readqc, forensics = recompute_verdicts(
            verdicts, geomatch, readqc, forensics,
            upload_geomatch, upload_readqc, geom_handle,
        )

    # Compute the post-merge transitions for affected segments. Only
    # segments whose uploads snapped to them can change verdict.
    affected_segments = {
        ug["segment_id"] for ug in upload_geomatch if ug.get("segment_id")
    }
    verdict_after_by_seg = {
        r["segment_id"]: r["verdict"] for r in verdicts.to_dict("records")
    }
    delta_counts: dict[str, int] = {}
    changed_segment_ids: list[str] = []
    for seg_id in affected_segments:
        before = baseline_verdict_by_seg.get(seg_id, "RED")
        after = verdict_after_by_seg.get(seg_id, before)
        if before != after:
            delta_counts[f"{before}→{after}"] = (
                delta_counts.get(f"{before}→{after}", 0) + 1
            )
            changed_segment_ids.append(seg_id)

    # Stash for the rail's Δ-summary panel + the "fly to changes" button.
    # Upload panel reads from session_state so we don't have to thread two
    # more parameters through render().
    st.session_state["_dashboard_delta_counts"] = delta_counts
    st.session_state["_dashboard_changed_segments"] = changed_segment_ids

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

    stats = compute_hero_stats(verdicts, readqc, forensics, geomatch)

    # ---- Page assembly -------------------------------------------------
    if session_lot:
        topbar.render(
            project_name=session_lot.get("lot_id", "Uploaded lot"),
            project_location="Loaded from contractor bundle",
            source="uploaded lot",
        )
    else:
        topbar.render(
            project_name="Maria Rain",
            project_location="Carinthia · L101 Goltschacher Straße",
            source=paths.source,
        )
    hero.render(stats)

    layout.begin_dash_row()
    map_col, rail_col = st.columns([2, 1], gap="small")

    # Split base geomatch (dark dots) from live uploads (bright orange).
    # Uploads carry per-row photo_ids prefixed `live_` -- see
    # upload_panel._build_entry.
    upload_pids = {u["photo_id"] for u in upload_state}
    valid_geo = geomatch[geomatch["lat"].notna() & geomatch["lon"].notna()]
    base_geo = valid_geo[~valid_geo["photo_id"].isin(upload_pids)]
    upload_geo = valid_geo[valid_geo["photo_id"].isin(upload_pids)]
    photo_points = base_geo[["lat", "lon"]].to_dict("records")
    name_by_pid = {u["photo_id"]: u["name"] for u in upload_state}
    upload_points = [
        {"lat": r["lat"], "lon": r["lon"],
         "tooltip": name_by_pid.get(r["photo_id"], "uploaded photo")}
        for r in upload_geo[["lat", "lon", "photo_id"]].to_dict("records")
    ]
    # One-shot fly-to: rail's "Fly to changes" button sets a flag, we
    # pop it here and compute a bounding box around the upload photos
    # (and a fallback to the changed segments if no GPS-bearing uploads
    # exist). map_view re-fits the leaflet view to those bounds for
    # exactly one render; user pans / zooms own the view after that.
    focus_bounds = None
    if st.session_state.pop("_fly_to_uploads", False):
        upload_latlons = [
            (u["lat"], u["lon"]) for u in upload_state
            if u.get("lat") is not None and u.get("lon") is not None
        ]
        if upload_latlons:
            lats = [p[0] for p in upload_latlons]
            lons = [p[1] for p in upload_latlons]
            focus_bounds = ((min(lats), min(lons)), (max(lats), max(lons)))

    m = map_view.build_map(
        trenches, fcps, cluster, verdicts_by_segment, photo_points,
        upload_points=upload_points,
        focus_bounds=focus_bounds,
    )
    with map_col:
        click = st_folium(
            m,
            width=None,
            height=600,
            returned_objects=[
                "last_active_drawing",
                "last_object_clicked_tooltip",
                "last_object_clicked",
            ],
            key="map",
        )

    # Map click → segment selection
    click_seg = map_view.segment_id_from_click(click, list(verdicts_by_segment))
    if click_seg and click_seg != st.session_state.get("_last_map_click_seg"):
        st.session_state["selected_segment"] = click_seg
        st.session_state["_last_map_click_seg"] = click_seg
    selected = st.session_state.get("selected_segment")
    if selected is not None and selected not in verdicts_by_segment:
        selected = None
        st.session_state.pop("selected_segment", None)

    from src.ui.components import chat

    with rail_col:
        if selected is None:
            demo_tour.render(
                verdicts_by_segment, geomatch, readqc, forensics,
            )
            # Upload panel sits where the old "Needs attention" list was;
            # drops here score live and recolor any segments they snap to.
            upload_panel.render(geom_handle)
            # Download + Ask sit on one 50/50 row -- two primary actions
            # framed as a pair instead of stacking the chat under the CTA.
            cta_l, cta_r = st.columns(2, gap="small")
            with cta_l:
                download.render(verdicts, readqc, forensics, geomatch)
            with cta_r:
                chat.render_inline()
        else:
            if st.button("← Back to overview",
                         key="back_to_rail",
                         use_container_width=True):
                # Pop selected_segment but KEEP _last_map_click_seg.
                # st_folium replays the last click payload on every
                # rerun -- if we cleared _last_map_click_seg too, the
                # click-handler above would re-select the same segment
                # on the very next rerun and the back button would
                # "do nothing" (panel re-opens instantly). Side effect:
                # to re-open the same segment after dismissing, click a
                # different segment first. Acceptable wart -- the
                # alternative is rebuilding the map iframe (losing
                # pan/zoom state) on every dismiss.
                st.session_state.pop("selected_segment", None)
                st.rerun()
            live_uploads_by_id = {
                u["photo_id"]: u for u in upload_state
                if u.get("qc") is not None and not u.get("err")
            }
            segment_panel.render(
                selected,
                verdicts_by_segment,
                geomatch,
                readqc_by_id,
                forensics_by_id,
                rep_by_cluster,
                manifest,
                paths.photos_root,
                live_uploads_by_id=live_uploads_by_id,
            )


if __name__ == "__main__":
    main()
