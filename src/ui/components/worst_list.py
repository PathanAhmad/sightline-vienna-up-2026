"""Worst-segments list — Linear-style rows, tap-affordable."""
from __future__ import annotations

import pandas as pd
import streamlit as st


CSS = """
<style>
.worst-list {
    background: var(--c-surface);
    border-radius: var(--r-md);
    box-shadow: var(--shadow-card);
    overflow: hidden;
}
.worst-row {
    display: grid;
    grid-template-columns: auto auto 1fr auto;
    gap: var(--s-3);
    align-items: center;
    padding: 10px var(--s-4);
    border-bottom: 1px solid var(--c-border-soft);
    font-size: 13px;
    min-height: 44px;
    transition: background 120ms ease;
}
.worst-row:last-child { border-bottom: none; }
.worst-row:hover { background: var(--c-bg); }
.worst-row .id {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11.5px;
    color: var(--c-text-2);
    letter-spacing: -0.01em;
    font-variant-numeric: tabular-nums;
}
.worst-row .why {
    color: var(--c-text-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 12px;
    line-height: 1.3;
}
.worst-row .chev {
    color: var(--c-muted);
    font-size: 12px;
    opacity: 0;
    transition: opacity 120ms ease;
}
.worst-row:hover .chev { opacity: 1; }
.worst-empty {
    padding: var(--s-4);
    text-align: center;
    color: var(--c-green);
    font-weight: 600;
    font-size: 13px;
}
</style>
"""


def render(verdicts: pd.DataFrame, limit: int = 6) -> None:
    bad = (
        verdicts[verdicts["verdict"] != "GREEN"]
        .sort_values(["verdict", "length_m"], ascending=[True, False])
        .head(limit)
    )
    st.markdown(
        "<div class='section-head section-head-row'>"
        "<span>Needs attention</span>"
        "<span class='hint'>tap a segment on the map</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    if bad.empty:
        st.markdown(
            "<div class='worst-list'><div class='worst-empty'>"
            "All segments green — nothing to flag."
            "</div></div>",
            unsafe_allow_html=True,
        )
        return

    rows_html = ""
    for r in bad.to_dict("records"):
        pill_class = str(r["verdict"]).lower()
        reasons_raw = r.get("reasons", "")
        reasons_str = reasons_raw if isinstance(reasons_raw, str) else ""
        first_reason = reasons_str.split(";")[0].strip() if reasons_str else ""
        why = first_reason.replace("<", "&lt;").replace(">", "&gt;")
        seg_id = str(r["segment_id"])
        short_id = seg_id.rsplit("_", 1)[-1] if "_" in seg_id else seg_id
        rows_html += (
            f"<div class='worst-row'>"
            f"<span class='verdict-pill {pill_class}'>{r['verdict']}</span>"
            f"<span class='id' title='{seg_id}'>{short_id}</span>"
            f"<span class='why'>{why}</span>"
            f"<span class='chev'>›</span>"
            f"</div>"
        )
    st.markdown(
        f"<div class='worst-list'>{rows_html}</div>",
        unsafe_allow_html=True,
    )
