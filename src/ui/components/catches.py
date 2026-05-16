"""Catches grid — 2x2 grid showing all four catch categories.

We always render all four cells (even with count 0) so the layout is
predictable and never looks like a single-card afterthought. Zero
counts get a softer treatment.
"""
from __future__ import annotations

import streamlit as st

from src.ui.components.hero import HeroStats


CSS = """
<style>
.catches {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: var(--s-2);
}
.catch-card {
    background: var(--c-surface);
    border-radius: var(--r-md);
    box-shadow: var(--shadow-card);
    padding: 10px var(--s-3);
    min-height: 60px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 1px;
    position: relative;
    overflow: hidden;
}
.catch-card::before {
    content: "";
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 2px;
    background: var(--c-border);
}
.catch-card.has-data::before { background: var(--c-accent); }
.catch-num {
    font-size: 20px;
    font-weight: 700;
    color: var(--c-text);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
    line-height: 1;
}
.catch-card.zero .catch-num { color: var(--c-muted); font-weight: 600; }
.catch-label {
    font-size: 10.5px;
    color: var(--c-text-2);
    line-height: 1.3;
    margin-top: 2px;
}
.catch-label b {
    color: var(--c-text);
    font-weight: 600;
    font-size: 11px;
    letter-spacing: -0.005em;
}
.catch-card.zero .catch-label b { color: var(--c-text-2); }
</style>
"""


def _card(n: int, name: str, sub: str) -> str:
    cls = "catch-card has-data" if n else "catch-card zero"
    return (
        f"<div class='{cls}'>"
        f"<div class='catch-num'>{n:,}</div>"
        f"<div class='catch-label'><b>{name}</b> · {sub}</div>"
        f"</div>"
    )


def render(s: HeroStats) -> None:
    dup_plural = "s" if s.n_duplicate_photos != 1 else ""
    geo_plural = "es" if s.n_geo_mismatch != 1 else ""
    wh_plural = "s" if s.n_personal_data != 1 else ""
    el_plural = "s" if s.n_ela != 1 else ""
    cards = "".join([
        _card(s.n_duplicate_photos, f"Duplicate{dup_plural}",
              "re-submitted"),
        _card(s.n_geo_mismatch, f"Geo-mismatch{geo_plural}",
              "lat/lon ↔ address"),
        _card(s.n_personal_data, f"Withheld{wh_plural}",
              "GDPR / NIS2"),
        _card(s.n_ela, f"Tamper hint{el_plural}",
              "ELA re-save"),
    ])
    st.markdown(
        "<div class='section-head'>Catches</div>"
        f"<div class='catches'>{cards}</div>",
        unsafe_allow_html=True,
    )
