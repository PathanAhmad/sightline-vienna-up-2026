"""Operator-facing upload view — submit a batch of trench photos for QC.

This is the *contractor / foreman* surface from the brief's deliverable #1:
"An upload and ingestion interface — users can upload a batch of photos
with basic metadata: project name, lot ID, GPS coordinates if available."

The reviewer dashboard (rendered by the rest of `app.py`) is the second
surface — the APG-side triage view. Two tabs, two roles, same product.
Demo flow: open `localhost:8501/?view=upload` in one tab and
`localhost:8501/` in another.

Each uploaded photo runs through the same Claude Sonnet 4.6 vision pipeline
the batch run uses — `score_uploaded_photo` in `live_score.py` is the shared
scoring entry point.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import streamlit as st

from src.ui.components import archive_expand, topbar
from src.ui.components.live_score import (
    DEFAULT_LIVE_MODEL_KEY,
    render_result_card,
    score_uploaded_photo,
    verdict_for_photo,
)
from src.ui.components.upload_panel import _render_model_toggle


# ---- Page-specific CSS --------------------------------------------------
# The dashboard's layout.py viewport-locks the body to 100vh. The upload
# page is a vertical scroll flow, so we override that here. Otherwise the
# drop zone + result grid would clip below the fold.
UPLOAD_PAGE_CSS = """
<style>
/* Reset the dashboard's viewport lock for this page.

   The dashboard (layout.py + base.py) locks the whole tree:
     .stApp                      { overflow-y: hidden }
     stAppViewContainer          { height: 100vh; overflow: hidden }
     stMain                      { height: 100vh; overflow: hidden }
     stMainBlockContainer        { height: 100vh; flex column; min-height: 0 }
       > stVerticalBlock         { flex: 1 1 0; min-height: 0 }
       > > stLayoutWrapper       { flex: 1 1 0; min-height: 0 }
   That chain (a) prevents the body from scrolling and (b) collapses
   short-content children to height: 0 via the flex chain. So on the
   upload view we tear it all down back to plain block flow. */
.stApp { overflow-y: auto !important; }
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    height: auto !important;
    min-height: 100vh !important;
    max-height: none !important;
    overflow: visible !important;
}
[data-testid="stMainBlockContainer"] {
    height: auto !important;
    min-height: 0 !important;
    max-height: none !important;
    overflow: visible !important;
    display: block !important;
}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"],
[data-testid="stMainBlockContainer"]
    > [data-testid="stVerticalBlock"]
    > [data-testid="stLayoutWrapper"],
[data-testid="stMainBlockContainer"]
    > [data-testid="stVerticalBlock"]
    > [data-testid="stLayoutWrapper"]
    > [data-testid="stHorizontalBlock"] {
    flex: 0 0 auto !important;
    min-height: 0 !important;
    height: auto !important;
    display: block !important;
}

/* Cap the upload-page main column at a comfortable reading width so the
   drop zone and form aren't 1600px wide on big monitors. */
[data-testid="stMainBlockContainer"] {
    max-width: 1100px !important;
    margin: 0 auto !important;
}

/* Hide Streamlit's auto-generated multi-page nav in the sidebar — we
   want this page to look like a single-purpose surface, not a section
   of a larger app. The user navigates between tabs by URL. */
[data-testid="stSidebarNav"] { display: none !important; }
section[data-testid="stSidebar"] { display: none !important; }
[data-testid="stSidebarCollapsedControl"] { display: none !important; }

/* ---- Page hero ---- */
.upload-hero {
    background: linear-gradient(135deg, var(--c-accent) 0%, #075985 100%);
    color: white;
    border-radius: var(--r-md);
    padding: clamp(20px, 2.4vw, 36px) clamp(20px, 2.4vw, 40px);
    box-shadow: var(--shadow-card);
    margin-bottom: var(--s-4);
}
.upload-hero .eyebrow {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.78);
    margin-bottom: 8px;
}
.upload-hero h1 {
    font-size: clamp(22px, 2.2vw, 32px);
    font-weight: 700;
    letter-spacing: -0.02em;
    line-height: 1.15;
    color: white;
    margin: 0 0 10px 0;
}
.upload-hero p {
    font-size: clamp(13px, 1vw, 15px);
    color: rgba(255,255,255,0.88);
    line-height: 1.5;
    max-width: 62ch;
    margin: 0;
}

/* ---- Card section header (sits inside an st.container(border=True)) ---- */
.upload-card-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--s-3);
    margin-bottom: var(--s-3);
    flex-wrap: wrap;
}
.upload-card-head .num {
    font-size: 11px;
    font-weight: 700;
    color: var(--c-accent);
    letter-spacing: 0.14em;
    text-transform: uppercase;
}
.upload-card-head h2 {
    font-size: 17px;
    font-weight: 600;
    margin: 4px 0 0 0;
    color: var(--c-text);
    letter-spacing: -0.01em;
}
.upload-card-head .hint {
    font-size: 12px;
    color: var(--c-muted);
}

/* Style our upload cards. We tag each `st.container(border=True)` with
   `key="card_<name>"`. In Streamlit 1.57 the `key=` class lands on the
   same stVerticalBlock that gets the `border=True` border — so the
   keyed element IS the card. Style it directly. */
.st-key-card_meta,
.st-key-card_drop,
.st-key-card_results {
    background: var(--c-surface) !important;
    border-radius: var(--r-md) !important;
    border: 1px solid var(--c-border) !important;
    box-shadow: var(--shadow-card);
    padding: clamp(16px, 1.6vw, 24px) !important;
    margin-bottom: var(--s-4) !important;
}

/* The drop zone — bigger and louder than the sidebar version.
   Scoped to the upload page's drop card so we don't restyle file
   uploaders elsewhere. */
.st-key-card_drop [data-testid="stFileUploader"] section {
    border: 2.5px dashed var(--c-border) !important;
    border-radius: var(--r-md) !important;
    background: var(--c-bg) !important;
    padding: clamp(24px, 2.4vw, 36px) !important;
    min-height: 96px !important;
    transition: border-color 120ms ease, background 120ms ease;
}
.st-key-card_drop [data-testid="stFileUploader"] section:hover {
    border-color: var(--c-accent) !important;
    background: var(--c-accent-soft) !important;
}
/* Hide Streamlit's "200MB per file • JPG, PNG" disclaimer — our own
   one-liner below the card head says what's accepted. */
.st-key-card_drop
    [data-testid="stFileUploaderDropzoneInstructions"] {
    display: none !important;
}

/* Small instructional line that sits between the card head and the
   dropzone, telling the user the area is drag-and-drop. */
.drop-help {
    font-size: 12.5px;
    color: var(--c-text-2);
    margin: 4px 0 14px 0;
    line-height: 1.5;
}
.drop-help kbd {
    background: var(--c-bg);
    border: 1px solid var(--c-border);
    border-radius: 4px;
    padding: 1px 6px;
    font-family: ui-monospace, monospace;
    font-size: 11.5px;
    color: var(--c-text);
}

/* Text input chrome inside cards. */
[data-testid="stTextInput"] input {
    border-radius: var(--r-sm) !important;
    border: 1px solid var(--c-border) !important;
    font-size: 13px !important;
    padding: 8px 12px !important;
    min-height: 38px !important;
}
[data-testid="stTextInput"] input:focus {
    border-color: var(--c-accent) !important;
    box-shadow: 0 0 0 3px var(--c-accent-soft) !important;
}
[data-testid="stTextInput"] label {
    font-size: 11px !important;
    font-weight: 600 !important;
    color: var(--c-muted) !important;
    letter-spacing: 0.06em !important;
    text-transform: uppercase !important;
}

/* Summary bar — appears once a batch finishes scoring. */
.summary-bar {
    display: flex;
    flex-wrap: wrap;
    gap: var(--s-4);
    align-items: center;
    padding: var(--s-3) var(--s-4);
    background: var(--c-green-soft);
    border: 1px solid #bbf7d0;
    border-radius: var(--r-sm);
    margin-bottom: var(--s-3);
}
.summary-bar .summary-num {
    font-size: 22px;
    font-weight: 700;
    color: #14532d;
    line-height: 1;
    font-variant-numeric: tabular-nums;
}
.summary-bar .summary-lbl {
    font-size: 11px;
    color: #166534;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-left: 6px;
}
.summary-bar .summary-spend {
    margin-left: auto;
    font-size: 12px;
    color: #166534;
}
.summary-bar .summary-spend b {
    font-variant-numeric: tabular-nums;
    color: #14532d;
}

/* CTA to the reviewer dashboard. Not wrapped in st.container so we can
   keep it as raw HTML with a real anchor (st.link_button doesn't take
   target="_blank"). */
.dashboard-cta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--s-3);
    padding: clamp(16px, 1.6vw, 24px);
    background: var(--c-surface);
    border: 1px solid var(--c-border);
    border-radius: var(--r-md);
    box-shadow: var(--shadow-card);
    margin-bottom: var(--s-4);
}
.dashboard-cta .cta-text { font-size: 13px; color: var(--c-text-2); }
.dashboard-cta .cta-text b { color: var(--c-text); }
.dashboard-cta a.cta-btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: var(--c-accent);
    color: white !important;
    text-decoration: none;
    font-weight: 600;
    font-size: 13px;
    padding: 10px 18px;
    border-radius: var(--r-sm);
    transition: background 120ms ease;
}
.dashboard-cta a.cta-btn:hover { background: #075985; }
.dashboard-cta a.cta-btn .arrow { font-size: 16px; line-height: 1; }
</style>
"""


def _card_head(num_label: str, title: str, hint: str) -> None:
    """Numbered card header rendered at the top of each upload card."""
    st.markdown(
        f"<div class='upload-card-head'>"
        f"<div><div class='num'>{num_label}</div>"
        f"<h2>{title}</h2></div>"
        f"<div class='hint'>{hint}</div></div>",
        unsafe_allow_html=True,
    )


def _render_summary_bar(results: list[dict]) -> None:
    """Tally + spend bar shown above the result grid."""
    if not results:
        return
    counts: dict[str, int] = {}
    spend = 0.0
    for r in results:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
        spend += r["cost"]
    parts = []
    for label in ("PASS", "WARN", "FAIL", "WITHHELD", "DROP"):
        n = counts.get(label, 0)
        if n == 0:
            continue
        parts.append(
            f"<div><span class='summary-num'>{n}</span>"
            f"<span class='summary-lbl'>{label.lower()}</span></div>"
        )
    st.markdown(
        f"<div class='summary-bar'>"
        f"{''.join(parts)}"
        f"<div class='summary-spend'>"
        f"Session spend <b>${spend:.4f}</b></div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_dashboard_cta(n_scored: int) -> None:
    """Bottom CTA — link to the reviewer dashboard in a new tab."""
    photos = "photo" if n_scored == 1 else "photos"
    st.markdown(
        f"<div class='dashboard-cta'>"
        f"<div class='cta-text'>"
        f"<b>Batch submitted.</b> "
        f"{n_scored} {photos} scored and queued for reviewer triage."
        f"</div>"
        f"<a class='cta-btn' href='/' target='_blank' rel='noopener'>"
        f"Open reviewer dashboard "
        f"<span class='arrow'>&#x2192;</span>"
        f"</a></div>",
        unsafe_allow_html=True,
    )


def _render_no_api_key_warning() -> None:
    st.markdown(
        "<div style='background:var(--c-yellow-soft);"
        "border:1px solid #fcd34d;color:#78350f;"
        "padding:12px 16px;border-radius:var(--r-sm);"
        "font-size:13px;line-height:1.5;margin-bottom:12px;'>"
        "<b>Scoring unavailable.</b> "
        "<code>ANTHROPIC_API_KEY</code> is not set in <code>.env</code>. "
        "Add it and reload the page to score uploads."
        "</div>",
        unsafe_allow_html=True,
    )


def render() -> None:
    """Render the upload view. Call from `app.py` after `inject_all_css()`."""
    st.markdown(UPLOAD_PAGE_CSS, unsafe_allow_html=True)

    topbar.render(
        project_name="Operator submission",
        project_location="Drop photos · we route to APG review",
        source="upload",
    )

    # ---- Hero -----------------------------------------------------------
    st.markdown(
        "<div class='upload-hero'>"
        "<div class='eyebrow'>Step 1 of 2 &middot; Operator view</div>"
        "<h1>Submit your batch for compliance review.</h1>"
        "<p>Photos go through the same seven-check QC pipeline APG&rsquo;s "
        "reviewers see &mdash; warning tape, sand bedding, side view, depth "
        "reference, duct, pipe-ends sealed, and personal-data check &mdash; "
        "and land in the reviewer dashboard ready for triage.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ---- Project metadata ----------------------------------------------
    # The brief's #1 deliverable lists three fields: project name, lot ID,
    # "GPS coordinates if available". We keep project + lot (batch-level
    # grouping labels — not in the images) and drop the GPS field because
    # each photo's overlay carries its own per-photo lat/lon, which the
    # vision pipeline extracts directly. A batch-level GPS hint is
    # vestigial under our actual data shape.
    with st.container(border=True, key="card_meta"):
        _card_head(
            "01 · Batch details",
            "Project &amp; lot metadata",
            "Pre-filled for the Maria Rain pilot. Edit if needed.",
        )
        m1, m2 = st.columns([1.4, 1])
        with m1:
            st.text_input(
                "Project name",
                value="Maria Rain — Carinthia pilot",
                key="submit_project",
            )
        with m2:
            st.text_input(
                "Lot ID",
                value="CLP20417A-P1-B00",
                key="submit_lot",
            )
        st.markdown(
            "<div style='margin-top:10px;font-size:11.5px;"
            "color:var(--c-muted);line-height:1.5;'>"
            "Per-photo address and GPS are read directly from each "
            "image&rsquo;s burned-in overlay &mdash; no need to enter "
            "coordinates here."
            "</div>",
            unsafe_allow_html=True,
        )

    # ---- API key check (before showing the drop zone) -------------------
    from src.readqc import load_env_key
    load_env_key()
    api_ready = bool(os.environ.get("ANTHROPIC_API_KEY"))

    # ---- Drop zone ------------------------------------------------------
    with st.container(border=True, key="card_drop"):
        _card_head(
            "02 · Photos",
            "Drop your trench photos",
            "JPG / JPEG / PNG or an archive (.zip / .tar / .tgz / .tar.gz "
            "/ .tar.bz2)",
        )
        st.markdown(
            "<div class='drop-help'>"
            "Drag a batch of photos &mdash; or one archive containing "
            "them &mdash; onto the area below, or press <kbd>Upload</kbd> "
            "to browse. Each photo runs through Claude Sonnet 4.6 vision "
            "and is scored against the seven APG / NIS2 checks &mdash; "
            "usually under six seconds per photo."
            "</div>",
            unsafe_allow_html=True,
        )
        if not api_ready:
            _render_no_api_key_warning()
        _render_model_toggle(key="upload_view_model_toggle")
        uploaded_files = st.file_uploader(
            "Drag and drop or click to browse",
            type=["jpg", "jpeg", "png",
                  "zip", "tar", "tgz", "gz", "bz2", "tbz", "tbz2",
                  "xz", "txz"],
            accept_multiple_files=True,
            key="batch_upload",
            label_visibility="collapsed",
        )

    # ---- Scoring + results ---------------------------------------------
    if uploaded_files and api_ready:
        cache: dict[tuple[str, int], dict] = st.session_state.setdefault(
            "batch_score_cache", {}
        )

        # Expand archives into their image members. Non-archive uploads
        # pass through unchanged. Each entry is (display_name, bytes).
        # Archive errors land in `errors` so the user sees a clear
        # message instead of a silent drop.
        errors: list[tuple[str, str]] = []
        members: list[tuple[str, bytes]] = []
        for f in uploaded_files:
            raw = f.getvalue()
            if archive_expand.is_archive(f.name):
                try:
                    pairs = archive_expand.expand(f.name, raw)
                except ValueError as e:
                    errors.append((f.name, str(e)))
                    continue
                if not pairs:
                    errors.append((
                        f.name,
                        "no .jpg / .jpeg / .png images found inside",
                    ))
                    continue
                members.extend(pairs)
            else:
                members.append((f.name, raw))

        pending: list[tuple[str, bytes, tuple[str, int]]] = []
        for display, payload in members:
            key = (display, len(payload))
            if key not in cache or cache[key].get("qc") is None:
                pending.append((display, payload, key))

        if pending:
            n = len(pending)
            progress = st.progress(0.0, text=f"Scoring 0 / {n} …")
            model_key = st.session_state.get(
                "live_model_key", DEFAULT_LIVE_MODEL_KEY
            )
            for i, (display, payload, key) in enumerate(pending, 1):
                suffix = Path(display).suffix or ".jpg"
                qc, cost, err = score_uploaded_photo(payload, suffix, model_key)
                cache[key] = {
                    "qc": qc, "cost": cost, "err": err,
                    "image": payload, "name": display,
                }
                progress.progress(i / n, text=f"Scoring {i} / {n} …")
            progress.empty()

        # Build the result list for the summary bar.
        results: list[dict] = []
        for display, payload in members:
            key = (display, len(payload))
            row = cache.get(key)
            if row is None:
                continue
            if row.get("err"):
                errors.append((display, row["err"]))
                continue
            if row.get("qc") is None:
                continue
            label, _ = verdict_for_photo(row["qc"])
            results.append({
                "name": display,
                "qc": row["qc"],
                "cost": row["cost"],
                "image": row["image"],
                "label": label,
            })

        # ---- Results card --------------------------------------------
        with st.container(border=True, key="card_results"):
            _card_head(
                "03 · Per-photo verdicts",
                "Results",
                "Each photo scored against the seven APG / NIS2 checks",
            )

            _render_summary_bar(results)

            # 3-up grid of per-photo result cards using real Streamlit
            # columns so st.image bytes render in place.
            per_row = 3
            for i in range(0, len(results), per_row):
                cols = st.columns(per_row, gap="medium")
                for col, r in zip(cols, results[i:i + per_row]):
                    with col:
                        st.markdown(
                            f"<div style='font-size:10.5px;"
                            f"color:var(--c-muted);font-weight:600;"
                            f"letter-spacing:0.06em;"
                            f"text-transform:uppercase;margin-bottom:6px;"
                            f"overflow:hidden;text-overflow:ellipsis;"
                            f"white-space:nowrap;'>"
                            f"{r['name']}</div>",
                            unsafe_allow_html=True,
                        )
                        render_result_card(r["qc"], r["image"], r["cost"])

            if errors:
                st.markdown(
                    "<div class='section-head' style='margin-top:20px;'>"
                    "Photos that failed to score</div>",
                    unsafe_allow_html=True,
                )
                for name, err in errors:
                    st.error(f"{name} — {err}")

        # ---- CTA -----------------------------------------------------
        if results:
            _render_dashboard_cta(len(results))
