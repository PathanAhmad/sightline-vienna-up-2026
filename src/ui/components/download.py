"""Download CTA — popover menu offering CSV or print-ready PDF.

The visible trigger on the rail is a primary (accent) button styled to
match the adjacent "Ask QC bot" CTA. Clicking it opens a small popover
with two options:

  * Raw CSV    — full field set, for the reviewer's spreadsheet.
  * Field PDF  — a designed deficiency report (cover + per-section
                 cards + legend) the foreman can print and bring to
                 the trench. Built in src/pdf_report.py.
"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from src import paths
from src.pdf_report import (
    PhotoIntake,
    build_pdf,
    compute_photo_intake,
    compute_segment_addresses,
)
from src.report import DEFICIENCY_FIELDS


CSS = """
<style>
/* ---- Popover trigger -- match the original accent CTA --------------- */
[data-testid="stHorizontalBlock"]:has(.st-key-chat_inline)
    [data-testid="stPopover"] button {
    background: var(--c-accent) !important;
    color: white !important;
    border: 1px solid var(--c-accent) !important;
    border-radius: var(--r-md) !important;
    padding: var(--s-2) var(--s-4) !important;
    min-height: 44px !important;
    height: 44px !important;
    font-weight: 600 !important;
    font-size: 13.5px !important;
    width: 100% !important;
    box-shadow: var(--shadow-card) !important;
}
[data-testid="stHorizontalBlock"]:has(.st-key-chat_inline)
    [data-testid="stPopover"] button:hover {
    background: #075985 !important;
    border-color: #075985 !important;
}

/* ---- Inside the popover panel: stacked, subtler download buttons.
   The panel is rendered in a portal at body level, so the chat-row
   `:has()` overrides don't reach it. --------------------------------- */
[data-testid="stPopoverBody"] .stDownloadButton,
div[data-baseweb="popover"] .stDownloadButton {
    width: 100%;
    display: block;
    margin-top: 6px;
}
[data-testid="stPopoverBody"] .stDownloadButton > button,
div[data-baseweb="popover"] .stDownloadButton > button {
    background: var(--c-surface);
    color: var(--c-text) !important;
    border: 1px solid var(--c-border-soft);
    border-radius: var(--r-sm);
    padding: 10px 12px;
    min-height: 44px;
    width: 100%;
    font-weight: 600;
    font-size: 13px;
    text-align: left;
    box-shadow: none;
}
[data-testid="stPopoverBody"] .stDownloadButton > button:hover,
div[data-baseweb="popover"] .stDownloadButton > button:hover {
    background: var(--c-bg);
    border-color: var(--c-accent);
}
.download-popover-hint {
    color: var(--c-muted);
    font-size: 11.5px;
    margin: 0 0 6px 0;
    line-height: 1.4;
}
.download-popover-sub {
    color: var(--c-muted);
    font-size: 11px;
    margin: -2px 0 6px 2px;
    line-height: 1.4;
}
</style>
"""


@st.cache_data(show_spinner=False)
def _build_pdf_cached(
    verdicts: pd.DataFrame,
    source: str,
    intake: PhotoIntake | None,
    segment_addresses_items: tuple[tuple[str, str], ...] | None,
    readqc_payload: str | None,
    forensics_payload: str | None,
    geomatch_payload: str | None,
) -> bytes:
    """st.download_button needs bytes at render time, and the popover
    body evaluates on every rerun whether it's open or not. Cache so the
    full pipeline only pays the build cost once per unique input.

    `segment_addresses_items` is the dict flattened into sorted tuples
    so it hashes cleanly as a cache key (raw dicts aren't hashable).

    `readqc_payload` / `forensics_payload` / `geomatch_payload` are
    JSON strings so they hash cleanly. We parse back to lists of dicts
    inside the cached call. Each is independently optional — if any one
    of the three is missing, the PDF skips the audit-trail appendices
    that need them.
    """
    addresses = (
        dict(segment_addresses_items)
        if segment_addresses_items is not None
        else None
    )
    readqc = json.loads(readqc_payload) if readqc_payload else None
    forensics = json.loads(forensics_payload) if forensics_payload else None
    geomatch_recs = (
        json.loads(geomatch_payload) if geomatch_payload else None
    )
    # readqc / forensics / geomatch are decoded above so the cache key
    # changes when their content changes, but build_pdf only consumes
    # the derived `intake` + `segment_addresses` -- the raw artifacts
    # aren't part of its current signature.
    _ = readqc, forensics, geomatch_recs
    return build_pdf(
        verdicts,
        source=source,
        intake=intake,
        segment_addresses=addresses,
    )


def render(
    verdicts: pd.DataFrame,
    readqc: list[dict] | None = None,
    forensics: list[dict] | None = None,
    geomatch: pd.DataFrame | None = None,
) -> None:
    """Render the rail CTA: popover with CSV and PDF download options.

    The intake artifacts are optional — the PDF still builds without
    them, just without the photo-intake table on the cover.
    """
    bad = (
        verdicts[verdicts["verdict"] != "GREEN"][list(DEFICIENCY_FIELDS)]
        .sort_values(
            ["fcp_name", "length_m"], ascending=[True, False]
        )
    )
    source = "live" if paths.VERDICTS_CSV.exists() else "fixtures"
    intake = None
    address_items: tuple[tuple[str, str], ...] | None = None
    readqc_payload: str | None = None
    forensics_payload: str | None = None
    geomatch_payload: str | None = None
    if readqc is not None and forensics is not None and geomatch is not None:
        geo_records = geomatch.to_dict("records")
        intake = compute_photo_intake(readqc, forensics, geo_records)
        addresses = compute_segment_addresses(geo_records, readqc)
        address_items = tuple(sorted(addresses.items()))
        # JSON-encode for the cache key. Sort keys so identical payloads
        # hash identically across reruns.
        readqc_payload = json.dumps(
            readqc, sort_keys=True, default=str,
        )
        forensics_payload = json.dumps(
            forensics, sort_keys=True, default=str,
        )
        geomatch_payload = json.dumps(
            geo_records, sort_keys=True, default=str,
        )

    with st.popover(
        "Download deficiency report",
        use_container_width=True,
    ):
        st.markdown(
            "<div class='download-popover-hint'>"
            "Pick a format for the deficiency list."
            "</div>",
            unsafe_allow_html=True,
        )
        st.download_button(
            "Raw CSV data",
            data=bad.to_csv(index=False).encode("utf-8"),
            file_name="deficiency.csv",
            mime="text/csv",
            key="download_deficiency_csv",
            use_container_width=True,
        )
        st.markdown(
            "<div class='download-popover-sub'>"
            "Full field set for the reviewer's spreadsheet."
            "</div>",
            unsafe_allow_html=True,
        )
        st.download_button(
            "Field report (PDF)",
            data=_build_pdf_cached(
                verdicts, source, intake, address_items,
                readqc_payload, forensics_payload, geomatch_payload,
            ),
            file_name="deficiency-report.pdf",
            mime="application/pdf",
            key="download_deficiency_pdf",
            use_container_width=True,
        )
        st.markdown(
            "<div class='download-popover-sub'>"
            "Designed PDF — cover summary, per-section evidence cards, "
            "and an audit-trail appendix (every photo, every check, "
            "every threshold). Print and bring it to the trench."
            "</div>",
            unsafe_allow_html=True,
        )
