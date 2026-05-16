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
)
from src.ui.components.hero import HeroStats


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

    stats = compute_hero_stats(verdicts, readqc, forensics, geomatch)

    # ---- Page assembly -------------------------------------------------
    topbar.render(
        project_name="Maria Rain",
        project_location="Carinthia · L101 Goltschacher Straße",
        source=paths.source,
    )
    hero.render(stats)

    layout.begin_dash_row()
    map_col, rail_col = st.columns([2, 1], gap="small")

    photo_points = (
        geomatch[geomatch["lat"].notna() & geomatch["lon"].notna()]
        [["lat", "lon"]].to_dict("records")
    )
    m = map_view.build_map(
        trenches, fcps, cluster, verdicts_by_segment, photo_points,
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
            catches.render(stats)
            # Download + Ask sit on one 50/50 row -- two primary actions
            # framed as a pair instead of stacking the chat under the CTA.
            cta_l, cta_r = st.columns(2, gap="small")
            with cta_l:
                download.render(verdicts)
            with cta_r:
                chat.render_inline()
        else:
            if st.button("← Back to overview",
                         key="back_to_rail",
                         use_container_width=True):
                st.session_state.pop("selected_segment", None)
                st.session_state.pop("_last_map_click_seg", None)
                st.rerun()
            segment_panel.render(
                selected,
                verdicts_by_segment,
                geomatch,
                readqc_by_id,
                forensics_by_id,
                rep_by_cluster,
                manifest,
                paths.photos_root,
            )


if __name__ == "__main__":
    main()
