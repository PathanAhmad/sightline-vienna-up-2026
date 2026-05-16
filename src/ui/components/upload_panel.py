"""Rail upload panel — drop photos on the dashboard, watch the map recolor.

Replaces the catches grid in the right rail when no segment is selected.
Mirrors the standalone /?view=upload page (`src/ui/upload_view.py`) but
sized for the narrow rail column: smaller card, no project metadata
form, vertical 1-up result list instead of 3-up grid.

Mutates `st.session_state["dashboard_uploads"]` -- a list of dicts:
    {
        "photo_id":   "live_001",
        "name":       "IMG-...jpg",
        "image":      bytes,
        "qc":         QCResult | None,
        "err":        str | None,
        "cost":       float,
        "lat":        float | None,
        "lon":        float | None,
        "snap":       {segment_id, segment_t, ...} | None,
    }

The dashboard reads this list, builds extra readqc/geomatch rows from it
via `live_geomatch.qc_to_*_row`, merges them into the on-disk data, and
calls `live_geomatch.recompute_verdicts` -- which recolors any segment
the uploads snapped to.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import streamlit as st

from src.ui.components import archive_expand, lot_bundle
from src.ui.components.live_geomatch import (
    qc_to_geomatch_row,
    qc_to_readqc_row,
    snap_to_segment,
)
from src.ui.components.live_score import (
    score_uploaded_photo,
    verdict_for_photo,
)
from src.geomatch import parse_overlay_latlon


CSS = """
<style>
/* Rail-scoped upload card. The right rail is ~360px wide on a 1440px
   monitor, so everything in here is sized one notch smaller than the
   standalone upload page. */
.upload-rail-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--s-2);
    margin: var(--s-3) 0 var(--s-2) 0;
}
.upload-rail-head .title {
    font-size: 13px;
    font-weight: 600;
    color: var(--c-text);
    letter-spacing: -0.005em;
}
.upload-rail-head .hint {
    font-size: 10.5px;
    color: var(--c-muted);
}

/* Style the rail's file uploader. The `key="card_rail_upload"` lands on
   the st.container(border=True) so we can scope to it. */
.st-key-card_rail_upload {
    background: var(--c-surface) !important;
    border-radius: var(--r-md) !important;
    border: 1px solid var(--c-border) !important;
    box-shadow: var(--shadow-card);
    padding: 12px !important;
    margin-bottom: var(--s-3) !important;
}
.st-key-card_rail_upload [data-testid="stFileUploader"] section {
    border: 2px dashed var(--c-border) !important;
    border-radius: var(--r-sm) !important;
    background: var(--c-bg) !important;
    padding: 14px !important;
    min-height: 70px !important;
    transition: border-color 120ms ease, background 120ms ease;
}
.st-key-card_rail_upload [data-testid="stFileUploader"] section:hover {
    border-color: var(--c-accent) !important;
    background: var(--c-accent-soft) !important;
}
.st-key-card_rail_upload [data-testid="stFileUploaderDropzoneInstructions"] {
    font-size: 11.5px !important;
}

.upload-rail-help {
    font-size: 11px;
    color: var(--c-muted);
    line-height: 1.45;
    margin: 0 0 10px 0;
}

/* Summary row -- one line of pass/warn/fail tallies + spend. */
.rail-summary {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
    padding: 8px 12px;
    background: var(--c-green-soft);
    border: 1px solid #bbf7d0;
    border-radius: var(--r-sm);
    margin: 10px 0 8px 0;
    font-size: 11.5px;
}
.rail-summary .num {
    font-size: 15px;
    font-weight: 700;
    color: #14532d;
    font-variant-numeric: tabular-nums;
    line-height: 1;
}
.rail-summary .lbl {
    font-size: 10px;
    color: #166534;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin-left: 4px;
}
.rail-summary .spend {
    margin-left: auto;
    color: #166534;
    font-size: 11px;
}
.rail-summary .spend b { color: #14532d; font-variant-numeric: tabular-nums; }

/* Compact one-line result rows in the rail (image thumb left, verdict
   pill + filename right). Each row links back to its segment if we
   snapped it. */
.rail-result {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 0;
    border-top: 1px solid var(--c-border);
    font-size: 11.5px;
}
.rail-result:first-of-type { border-top: none; }
.rail-result .thumb {
    flex: 0 0 44px;
    width: 44px;
    height: 44px;
    border-radius: var(--r-sm);
    background: var(--c-bg);
    object-fit: cover;
    border: 1px solid var(--c-border);
}
.rail-result .thumb.gdpr {
    display: flex; align-items: center; justify-content: center;
    font-size: 16px; color: #92400e; background: #fef3c7;
}
.rail-result .meta { min-width: 0; flex: 1 1 auto; }
.rail-result .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--c-text);
    font-weight: 500;
}
.rail-result .seg {
    font-size: 10.5px;
    color: var(--c-muted);
    margin-top: 2px;
}
.rail-result .seg b { color: var(--c-text); }
.rail-result .right { margin-left: auto; }

/* Δ-this-batch panel -- shows verdict transitions caused by the upload
   so the operator sees "your photos moved 3 segments" instead of having
   to hunt for tiny colour changes in a sea of red trenches. */
.rail-delta {
    background: var(--c-bg);
    border: 1px solid var(--c-border);
    border-left: 3px solid var(--c-accent);
    border-radius: var(--r-sm);
    padding: 8px 10px 6px 12px;
    margin: 6px 0 8px 0;
    font-size: 11.5px;
    line-height: 1.45;
}
.rail-delta .head {
    font-size: 9.5px;
    font-weight: 700;
    color: var(--c-muted);
    letter-spacing: 0.10em;
    text-transform: uppercase;
    margin-bottom: 4px;
}
.rail-delta .row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 2px;
}
.rail-delta .pair {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-variant-numeric: tabular-nums;
}
.rail-delta .swatch {
    display: inline-block;
    width: 10px; height: 10px;
    border-radius: 2px;
    vertical-align: middle;
}
.rail-delta .swatch.green  { background: var(--c-green); }
.rail-delta .swatch.yellow { background: var(--c-yellow); }
.rail-delta .swatch.red    { background: var(--c-red); }
.rail-delta .arrow {
    color: var(--c-muted);
    margin: 0 2px;
}
.rail-delta .none {
    color: var(--c-muted);
    font-style: italic;
}

/* Fly-to-changes button -- accent-colored, full-width. */
.st-key-rail_fly_btn .stButton > button {
    background: var(--c-accent) !important;
    color: white !important;
    border: 1px solid var(--c-accent) !important;
    min-height: 28px !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    margin-top: 2px;
}
.st-key-rail_fly_btn .stButton > button:hover {
    background: #075985 !important;
    color: white !important;
    border-color: #075985 !important;
}

/* Loaded-lot banner (only shown when a contractor bundle is active). */
.loaded-lot-banner {
    background: var(--c-accent-soft);
    border: 1px solid var(--c-accent);
    border-radius: var(--r-sm);
    padding: 8px 12px;
    margin-bottom: 8px;
    font-size: 11.5px;
    line-height: 1.4;
}
.loaded-lot-banner .banner-eyebrow {
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    color: var(--c-accent);
}
.loaded-lot-banner .banner-id {
    font-family: ui-monospace, monospace;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--c-text);
    margin: 2px 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.loaded-lot-banner .banner-sub {
    color: var(--c-text-2);
    font-size: 11px;
}

/* Unload-lot button -- secondary, sits beside the banner. */
.st-key-rail_unload_lot_btn .stButton > button {
    min-height: 56px !important;
    font-size: 11px !important;
}

/* "Clear uploads" button -- understated link-style. */
.st-key-rail_clear_btn .stButton > button {
    background: transparent !important;
    border: none !important;
    color: var(--c-muted) !important;
    font-size: 11px !important;
    font-weight: 500 !important;
    min-height: 24px !important;
    padding: 2px 6px !important;
    text-decoration: underline;
    text-underline-offset: 2px;
}
.st-key-rail_clear_btn .stButton > button:hover {
    color: var(--c-accent) !important;
    background: transparent !important;
    border: none !important;
}
</style>
"""


def _ensure_state() -> list[dict]:
    return st.session_state.setdefault("dashboard_uploads", [])


def _score_cache() -> dict[tuple[str, int], dict]:
    return st.session_state.setdefault("dashboard_score_cache", {})


def _summary_bar_html(uploads: list[dict]) -> str:
    counts: dict[str, int] = {}
    spend = 0.0
    for u in uploads:
        if u.get("err") or u.get("qc") is None:
            continue
        label, _ = verdict_for_photo(u["qc"])
        counts[label] = counts.get(label, 0) + 1
        spend += float(u.get("cost", 0.0))
    if not counts:
        return ""
    parts = []
    for label in ("PASS", "WARN", "FAIL", "WITHHELD", "DROP"):
        n = counts.get(label, 0)
        if n:
            parts.append(
                f"<div><span class='num'>{n}</span>"
                f"<span class='lbl'>{label.lower()}</span></div>"
            )
    return (
        f"<div class='rail-summary'>{''.join(parts)}"
        f"<div class='spend'>Spend <b>${spend:.4f}</b></div></div>"
    )


def _process_pending(uploaded_files: list[Any]) -> None:
    """Expand any archives, score every image we haven't scored yet, snap
    to a segment, store results in session state for the dashboard merge.

    `uploaded_files` is a list of Streamlit UploadedFile objects. Each is
    one of:
      * a direct image (.jpg / .jpeg / .png)
      * a plain archive (.zip / .tar / .tgz / ...) of images
      * a CONTRACTOR LOT BUNDLE -- a zip that also carries the lot's
        Trenches / FCP_Polygons / SiteCluster_Polygons geojsons. We
        detect this first, swap the dashboard to that lot for the rest
        of the session, then add the bundle's photos to the scoring
        queue alongside any plain uploads.
    """
    if not uploaded_files:
        return
    state = _ensure_state()
    cache = _score_cache()
    geom_for_snap = st.session_state.get("_dash_geom_handle")

    # Drop session entries whose SOURCE upload is no longer in the
    # uploader (Streamlit lets the user remove individual files). We
    # match against `_source`, not `name`, so all members of a removed
    # archive disappear together.
    keep_sources = {f.name for f in uploaded_files}
    state[:] = [u for u in state if u.get("_source") in keep_sources]

    # First pass: detect lot bundles. If multiple are uploaded, the LAST
    # one wins (most recent intent). We cache extracted bundles per
    # source filename -- `extract_lot_bundle` calls `tempfile.mkdtemp()`
    # which returns a *new* path every call, so without this cache the
    # `prior != new` change-detector below would fire on every rerun,
    # wiping the upload state and leaking a fresh /tmp dir each time.
    # Bundle messages are (source_name, message, level) where level is
    # "info" (lot loaded) or "error" (extraction failed).
    bundle_cache: dict[str, lot_bundle.LotBundle] = (
        st.session_state.setdefault("_extracted_lot_cache", {})
    )
    bundle_msgs: list[tuple[str, str, str]] = []
    bundle_photos: list[tuple[str, bytes, str]] = []
    lot_sources: set[str] = set()
    new_session_lot: dict | None = None
    for f in uploaded_files:
        raw = f.getvalue()
        if not lot_bundle.is_lot_bundle(f.name, raw):
            continue
        bundle = bundle_cache.get(f.name)
        if bundle is None:
            bundle = lot_bundle.extract_lot_bundle(f.name, raw)
            if bundle is None:
                bundle_msgs.append((
                    f.name,
                    "bundle looked valid but failed to extract",
                    "error",
                ))
                continue
            bundle_cache[f.name] = bundle
        new_session_lot = {
            "lot_id": bundle.lot_id,
            "trenches_path": str(bundle.trenches_path),
            "fcps_path": str(bundle.fcps_path),
            "cluster_path": str(bundle.cluster_path),
            "source_name": f.name,
        }
        lot_sources.add(f.name)
        # Mark the bundle's photos so they can be scored as normal uploads.
        for display, payload in bundle.photos:
            bundle_photos.append((display, payload, f.name))
        if bundle.skipped:
            bundle_msgs.append((
                f.name,
                "loaded lot " + bundle.lot_id
                + " (skipped: " + ", ".join(bundle.skipped[:3]) + ")",
                "info",
            ))
        else:
            bundle_msgs.append((
                f.name,
                f"loaded lot {bundle.lot_id} ({len(bundle.photos)} photo(s))",
                "info",
            ))

    if new_session_lot is not None:
        prior = st.session_state.get("session_lot")
        prior_source = prior.get("source_name") if prior else None
        if prior_source != new_session_lot["source_name"]:
            # Lot changed -- prior uploads / scores belong to a different
            # trench set. Wipe them and force a fresh rerun so app.py
            # rebuilds geom_handle against the new lot BEFORE we try to
            # snap any photos. Without the rerun, geom_for_snap below is
            # the old lot's handle and bundle photos enter `state` with
            # snap=None, then the dedup guard prevents them from being
            # re-snapped on the next rerun -- they'd stay forever as
            # "no GPS" rows even though we have their coords.
            st.session_state["session_lot"] = new_session_lot
            st.session_state["dashboard_uploads"] = []
            st.session_state["dashboard_score_cache"] = {}
            st.rerun()

    # Expand each upload into (display_name, bytes, source_name) tuples.
    # Lot bundles are handled separately above -- skip them in this loop.
    members: list[tuple[str, bytes, str]] = list(bundle_photos)
    archive_msgs: list[tuple[str, str, str]] = list(bundle_msgs)
    for f in uploaded_files:
        if f.name in lot_sources:
            continue
        raw = f.getvalue()
        if archive_expand.is_archive(f.name):
            try:
                pairs = archive_expand.expand(f.name, raw)
            except ValueError as e:
                archive_msgs.append((f.name, str(e), "error"))
                continue
            if not pairs:
                archive_msgs.append((
                    f.name,
                    "no .jpg / .jpeg / .png images found inside",
                    "error",
                ))
                continue
            for display, payload in pairs:
                members.append((display, payload, f.name))
        else:
            members.append((f.name, raw, f.name))

    # Surface archive / lot-bundle messages as upload entries so the
    # user sees them in the result list (info or error, depending on
    # level). De-duplicated on (source, level) so re-runs don't pile up.
    for src, msg, level in archive_msgs:
        key = (f"{src}::{level}", 0)
        if any(u.get("_key") == key for u in state):
            continue
        entry: dict[str, Any] = {
            "_key": key,
            "_source": src,
            "photo_id": f"live_msg_{abs(hash(key)) % 10**9:09d}",
            "name": src,
            "image": b"",
            "qc": None,
            "cost": 0.0,
            "lat": None, "lon": None, "snap": None,
        }
        if level == "error":
            entry["err"] = msg
        else:
            entry["info"] = msg
        state.append(entry)

    pending: list[tuple[str, bytes, str, tuple[str, int]]] = []
    for display, payload, source in members:
        key = (display, len(payload))
        if any(u.get("_key") == key for u in state):
            continue
        if key in cache:
            state.append(
                _build_entry(display, payload, source, key, cache[key], geom_for_snap)
            )
            continue
        pending.append((display, payload, source, key))

    if not pending:
        return

    n = len(pending)
    progress = st.progress(0.0, text=f"Scoring 0 / {n} …")
    for i, (display, payload, source, key) in enumerate(pending, 1):
        suffix = Path(display).suffix or ".jpg"
        qc, cost, err = score_uploaded_photo(payload, suffix)
        cached = {"qc": qc, "cost": cost, "err": err}
        cache[key] = cached
        state.append(
            _build_entry(display, payload, source, key, cached, geom_for_snap)
        )
        progress.progress(i / n, text=f"Scoring {i} / {n} …")
    progress.empty()
    # Force a rerun so app.py picks up the newly-scored uploads, merges
    # them into the verdicts/photo_points lists, and the map redraws
    # with the new orange dots + recolored segments. Without this the
    # script ends here and the map keeps the *pre-scoring* snapshot --
    # the user only sees the recolor after some other interaction
    # triggers a rerun.
    st.rerun()


def _build_entry(
    name: str, file_bytes: bytes, source: str, key: tuple[str, int],
    scored: dict, geom: dict | None,
) -> dict:
    """Combine score + snap into one session-state row.

    `name` is the display name (e.g. "archive.zip/IMG-001.jpg" for an
    archive member, or just the original filename). `source` is the name
    of the file the operator dropped on the uploader -- used for cleanup
    so removing an archive removes all its expanded members.
    """
    qc = scored.get("qc")
    lat = lon = None
    snap = None
    if qc is not None and geom is not None:
        parsed = parse_overlay_latlon(getattr(qc, "overlay_latlon", None))
        if parsed is not None:
            lat, lon = parsed
            try:
                snap = snap_to_segment(lat, lon, geom)
            except Exception:
                snap = None
    photo_id = f"live_{abs(hash(key)) % 10**9:09d}"
    return {
        "_key": key,
        "_source": source,
        "photo_id": photo_id,
        "name": name,
        "image": file_bytes,
        "qc": qc,
        "err": scored.get("err"),
        "cost": float(scored.get("cost", 0.0)),
        "lat": lat,
        "lon": lon,
        "snap": snap,
    }


_VERDICT_CSS = {"GREEN": "green", "YELLOW": "yellow", "RED": "red"}


def _render_delta_panel() -> None:
    """Verdict-transition summary + 'Fly to changes' button.

    Reads `_dashboard_delta_counts` / `_dashboard_changed_segments` from
    session_state (populated by app.py after the in-memory recompute).
    Renders nothing when there are no uploads or no changes -- the
    operator doesn't need to see an empty panel.
    """
    delta: dict[str, int] = st.session_state.get(
        "_dashboard_delta_counts", {}
    )
    changed: list[str] = st.session_state.get(
        "_dashboard_changed_segments", []
    )
    has_uploads = bool(st.session_state.get("dashboard_uploads", []))
    if not has_uploads:
        return

    # Group transitions by direction. The dict keys look like "RED→YELLOW".
    if delta:
        pair_html: list[str] = []
        for label, n in sorted(delta.items(), key=lambda kv: -kv[1]):
            before, after = label.split("→")
            pair_html.append(
                f"<span class='pair'><b>{n}</b>"
                f"<span class='swatch {_VERDICT_CSS.get(before,'')}'></span>"
                f"<span class='arrow'>→</span>"
                f"<span class='swatch {_VERDICT_CSS.get(after,'')}'></span>"
                f"</span>"
            )
        body_html = "<div class='row'>" + " ".join(pair_html) + "</div>"
    else:
        body_html = (
            "<div class='none'>"
            "Photos scored, no segment crossed a threshold yet."
            "</div>"
        )

    st.markdown(
        f"<div class='rail-delta'>"
        f"<div class='head'>&Delta; this batch &middot; "
        f"{len(changed)} segment(s) changed</div>"
        f"{body_html}"
        f"</div>",
        unsafe_allow_html=True,
    )

    if st.button(
        "Fly to changes",
        key="rail_fly_btn",
        use_container_width=True,
        disabled=not bool(changed) and not has_uploads,
        help="Pan and zoom the map to fit your batch's footprint.",
    ):
        st.session_state["_fly_to_uploads"] = True
        st.rerun()


def _render_result_rows(uploads: list[dict]) -> None:
    """One compact row per uploaded photo (thumb + name + verdict pill)."""
    if not uploads:
        return
    for u in reversed(uploads):  # newest first
        if u.get("err"):
            st.error(f"{u['name']} — {u['err']}", icon="⚠️")
            continue
        if u.get("info"):
            st.success(u["info"], icon="✅")
            continue
        qc = u.get("qc")
        if qc is None:
            continue
        label, pill = verdict_for_photo(qc)
        gdpr = getattr(qc, "personal_data_visible", "no") == "yes"

        seg_text = "no GPS in photo overlay"
        if u.get("snap"):
            seg_id = u["snap"]["segment_id"]
            dist = u["snap"]["snap_distance_m"]
            short = seg_id.split("_")[-1] if "_" in seg_id else seg_id
            seg_text = f"snapped to <b>{short}</b> · {dist:.0f}m"
        elif u.get("lat") is None and qc is not None:
            seg_text = "no GPS in photo overlay"

        if gdpr:
            thumb_html = "<div class='thumb gdpr'>&#x1F6AB;</div>"
        else:
            import base64
            b64 = base64.b64encode(u["image"]).decode("ascii")
            thumb_html = (
                f"<img class='thumb' src='data:image/jpeg;base64,{b64}'/>"
            )

        st.markdown(
            f"<div class='rail-result'>"
            f"{thumb_html}"
            f"<div class='meta'>"
            f"<div class='name'>{u['name']}</div>"
            f"<div class='seg'>{seg_text}</div>"
            f"</div>"
            f"<div class='right'>"
            f"<span class='verdict-pill {pill}'>{label}</span>"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


def render(geom_handle: dict | None) -> None:
    """Render the rail upload panel.

    `geom_handle` is the live_geomatch geometry bundle (or None when
    geopandas isn't available / load failed). When None, photos are
    still scored but they don't snap to a segment.
    """
    # Stash so _process_pending can reach it without changing signatures.
    st.session_state["_dash_geom_handle"] = geom_handle

    from src.readqc import load_env_key
    load_env_key()
    api_ready = bool(os.environ.get("ANTHROPIC_API_KEY"))

    st.markdown(
        "<div class='upload-rail-head'>"
        "<div class='title'>Drop photos</div>"
        "<div class='hint'>scored live · map recolors</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    session_lot = st.session_state.get("session_lot")
    if session_lot:
        n_uploads = len(st.session_state.get("dashboard_uploads", []))
        photo_word = "photo" if n_uploads == 1 else "photos"
        sl_l, sl_r = st.columns([3, 1], gap="small")
        with sl_l:
            st.markdown(
                "<div class='loaded-lot-banner'>"
                "<div class='banner-eyebrow'>Loaded lot</div>"
                f"<div class='banner-id'>{session_lot.get('lot_id','uploaded-lot')}"
                f"</div>"
                f"<div class='banner-sub'>{n_uploads} {photo_word} scored "
                f"against this lot &middot; map shows its trenches</div>"
                "</div>",
                unsafe_allow_html=True,
            )
        with sl_r:
            if st.button(
                "Unload",
                key="rail_unload_lot_btn",
                use_container_width=True,
                help="Drop the uploaded lot and reload the default dashboard.",
            ):
                st.session_state.pop("session_lot", None)
                st.session_state["dashboard_uploads"] = []
                st.session_state["dashboard_score_cache"] = {}
                st.session_state.pop("dashboard_batch_upload", None)
                st.rerun()

    with st.container(border=True, key="card_rail_upload"):
        st.markdown(
            "<div class='upload-rail-help'>"
            "Photos (JPG / JPEG / PNG) or an archive "
            "(.zip / .tar / .tgz / .tar.gz / .tar.bz2). Each photo runs "
            "the seven APG checks &mdash; usually 6 s per photo. Segments "
            "the photos snap to recolor on the map."
            "</div>",
            unsafe_allow_html=True,
        )
        if not api_ready:
            st.warning(
                "ANTHROPIC_API_KEY not set in .env. Add it and reload "
                "to score uploads.",
                icon="⚠️",
            )
        uploaded_files = st.file_uploader(
            "Drop photos or an archive",
            type=["jpg", "jpeg", "png",
                  "zip", "tar", "tgz", "gz", "bz2", "tbz", "tbz2",
                  "xz", "txz"],
            accept_multiple_files=True,
            key="dashboard_batch_upload",
            label_visibility="collapsed",
            disabled=not api_ready,
        )

        if uploaded_files and api_ready:
            _process_pending(uploaded_files)

        uploads = _ensure_state()
        if uploads:
            html = _summary_bar_html(uploads)
            if html:
                st.markdown(html, unsafe_allow_html=True)
            _render_delta_panel()
            _render_result_rows(uploads)
            # Clear-button row -- right-aligned via a tiny column trick.
            _, clear_col = st.columns([3, 1])
            with clear_col:
                if st.button(
                    "Clear all",
                    key="rail_clear_btn",
                    use_container_width=True,
                ):
                    st.session_state["dashboard_uploads"] = []
                    st.session_state["dashboard_score_cache"] = {}
                    # Reset the file_uploader widget too so the file
                    # chips disappear.
                    st.session_state.pop("dashboard_batch_upload", None)
                    st.rerun()
