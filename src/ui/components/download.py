"""Download CTA — popover menu offering CSV or print-friendly HTML.

The visible trigger on the rail is a primary (accent) button styled to
match the adjacent "Ask QC bot" CTA. Clicking it opens a small popover
with two options:

  * Raw CSV       — full field set, for the reviewer's spreadsheet.
  * Field report  — plain-language HTML, designed for a foreman to open
                    in a browser and "Print → Save as PDF" for the crew.
"""
from __future__ import annotations

import html
import re

import pandas as pd
import streamlit as st


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


def render(verdicts: pd.DataFrame) -> None:
    """Render the rail CTA: popover with CSV and HTML download options."""
    from src.report import DEFICIENCY_FIELDS

    bad = (
        verdicts[verdicts["verdict"] != "GREEN"][list(DEFICIENCY_FIELDS)]
        .sort_values(
            ["fcp_name", "length_m"], ascending=[True, False]
        )
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
            "Field report (HTML — print to PDF)",
            data=_render_field_html(bad).encode("utf-8"),
            file_name="deficiency-report.html",
            mime="text/html",
            key="download_deficiency_html",
            use_container_width=True,
        )
        st.markdown(
            "<div class='download-popover-sub'>"
            "Plain-language punch list. Open in a browser, then "
            "File → Print → Save as PDF."
            "</div>",
            unsafe_allow_html=True,
        )


# ---- Field-friendly HTML rendering -------------------------------------

_VERDICT_LABEL: dict[str, str] = {
    "RED": "Needs review",
    "YELLOW": "Warning",
    "GREEN": "Passing",
}


# Fixed-string reasons emitted verbatim by src/classify.py.
_FIXED_SUBS: dict[str, str] = {
    "personal_data_visible":
        "personal data visible in a photo — must be re-shot",
    "latlon_vs_address_disagree":
        "photo GPS does not match the printed address",
    "off_cluster":
        "photo location is far from other photos of this section",
    "no compliant photos snapped":
        "no usable photos for this section",
}


# Templated reasons emitted by src/classify.py. Order matters: more
# specific patterns first so they preempt the catch-all variants.
_REGEX_SUBS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"relevance=portrait"),
     "photo is mostly a person, not the trench"),
    (re.compile(r"relevance=off_topic"),
     "photo is not of the trench"),
    (re.compile(r"relevance=unreadable"),
     "photo is too blurry or dark to read"),
    (re.compile(r"relevance=(\w+)"),
     r"photo flagged as \1 — not a usable trench photo"),
    (re.compile(r"snap_distance=(\d+)m"),
     r"photo is \1 m off the trench centreline"),
    (re.compile(r"phase=paper_label"),
     "photo shows only the paper label — no trench evidence"),
    (re.compile(r"phase=staging"),
     "photo shows staging only — no trench evidence"),
    (re.compile(r"phase=other"),
     "photo does not show a recognised trench stage"),
    (re.compile(r"phase=(\w+)"),
     r"photo at phase \1 — no trench evidence"),
    (re.compile(r"warning_tape_visible=no"),
     "no warning tape visible"),
    (re.compile(r"sand_bedding_visible=no"),
     "no sand bedding visible"),
    (re.compile(r"duct_visible=no"),
     "no duct visible"),
    (re.compile(r"density \d+/(\d+)m below 1/10m"),
     r"too few photos for the section length (\1 m)"),
    (re.compile(
        r"first compliant photo at meter (\d+) "
        r"\(>(\d+)m from start\)"),
     r"first usable photo is \1 m in — "
     r"no coverage in the first \2 m"),
    (re.compile(
        r"last compliant photo at meter (\d+) "
        r"\(>(\d+)m from end of (\d+)m\)"),
     r"last usable photo is at \1 m — last "
     r"\2 m of the \3 m section uncovered"),
    (re.compile(
        r"max gap (\d+)m > (\d+)m between meter "
        r"(\d+) and meter (\d+)"),
     r"\1 m gap between meter \3 and meter \4 "
     r"(allowed maximum: \2 m)"),
    (re.compile(r"(\d+) personal-data photo\(s\)"),
     r"\1 photo(s) contain visible personal data"),
    (re.compile(r"(\d+)x (.+)"),
     r"\1 photos: \2"),
]


def _humanize_reason(reason: str) -> str:
    """Translate one reason string into plain English for the crew.

    Two passes: fixed-string lookup first, then regex substitutions
    (more specific patterns earlier in the list). Anything we don't
    recognise passes through verbatim — silent omission would hide
    info the inspector might need.
    """
    r = reason.strip()
    if not r:
        return r
    if r in _FIXED_SUBS:
        return _FIXED_SUBS[r]
    for pattern, repl in _REGEX_SUBS:
        new_r, n = pattern.subn(repl, r)
        if n:
            r = new_r
    return r


def _humanize_reasons(reasons_field: str) -> str:
    """Split the semicolon-joined reasons and humanize each."""
    if not reasons_field:
        return "No specific issue recorded — please re-check on site."
    parts = [p for p in (s.strip() for s in reasons_field.split(";")) if p]
    return "; ".join(_humanize_reason(p) for p in parts)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Deficiency report — on-site punch list</title>
<style>
  @page {{ size: A4; margin: 18mm 14mm; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #111;
    margin: 0;
    line-height: 1.45;
    font-size: 14px;
  }}
  h1 {{ font-size: 22px; margin: 0 0 4px 0; }}
  .sub {{ color: #555; font-size: 13px; margin-bottom: 18px; }}
  .row {{
    border: 1px solid #ccc;
    border-radius: 6px;
    padding: 12px 14px;
    margin-bottom: 10px;
    page-break-inside: avoid;
  }}
  .head {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 6px;
  }}
  .ref {{ font-weight: 700; font-size: 15px; }}
  .pill {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    color: #fff;
    white-space: nowrap;
  }}
  .pill.red {{ background: #b91c1c; }}
  .pill.yellow {{ background: #b45309; }}
  .meta {{
    color: #444;
    font-size: 12.5px;
    margin-bottom: 6px;
  }}
  .meta strong {{ color: #111; }}
  .why {{
    background: #f5f3ef;
    border-left: 3px solid #444;
    padding: 6px 10px;
    font-size: 13px;
    border-radius: 0 4px 4px 0;
  }}
  .empty {{
    color: #15803d;
    font-weight: 600;
    padding: 16px;
    border: 1px solid #bbf7d0;
    border-radius: 6px;
    background: #f0fdf4;
  }}
  .legend {{
    font-size: 12px;
    color: #555;
    margin-top: 16px;
    line-height: 1.7;
  }}
  @media print {{
    .row {{ border-color: #888; }}
  }}
</style>
</head>
<body>
<h1>Deficiency report</h1>
<div class="sub">Sections that did not pass automated photo checks.
Bring this to the trench; tick each entry as you re-do or re-shoot.</div>
{rows_html}
<div class="legend">
  <strong>Severity:</strong>
  <span class="pill red">Needs review</span>
  — not enough good photos to confirm the work is OK.
  &nbsp;
  <span class="pill yellow">Warning</span>
  — some checks missed but section is mostly covered.
</div>
</body>
</html>
"""


def _render_field_html(bad: pd.DataFrame) -> str:
    """Build the print-friendly HTML document for the crew."""
    if bad.empty:
        rows_html = (
            "<div class='empty'>"
            "All sections passed — nothing to flag."
            "</div>"
        )
        return _HTML_TEMPLATE.format(rows_html=rows_html)

    cards: list[str] = []
    for r in bad.to_dict("records"):
        verdict_raw = str(r.get("verdict") or "").upper()
        pill_class = verdict_raw.lower()
        label = _VERDICT_LABEL.get(verdict_raw, verdict_raw.title())

        seg_id = str(r.get("segment_id") or "")
        short = seg_id.rsplit("_", 1)[-1] if "_" in seg_id else seg_id
        fcp = html.escape(str(r.get("fcp_name") or "—"))

        length_raw = r.get("length_m")
        try:
            length_str = f"{float(length_raw):.0f} m"
        except (TypeError, ValueError):
            length_str = "—"

        photos = r.get("photo_count") or 0
        ok_photos = r.get("compliant_photo_count") or 0

        reasons_raw = r.get("reasons") or ""
        why = html.escape(_humanize_reasons(str(reasons_raw)))

        cards.append(
            "<div class='row'>"
            "<div class='head'>"
            f"<span class='ref'>Section {html.escape(short)} "
            f"&middot; {fcp}</span>"
            f"<span class='pill {pill_class}'>"
            f"{html.escape(label)}</span>"
            "</div>"
            "<div class='meta'>"
            f"Length <strong>{length_str}</strong> &middot; "
            f"Photos <strong>{ok_photos}/{photos}</strong> "
            "passing checks"
            "</div>"
            f"<div class='why'>{why}</div>"
            "</div>"
        )

    return _HTML_TEMPLATE.format(rows_html="\n".join(cards))
