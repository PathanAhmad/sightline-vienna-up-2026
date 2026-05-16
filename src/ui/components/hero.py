"""Hero KPI strip — Linear/Vercel-style.

Layout (desktop): one row, six cells separated by subtle hairlines.
Dominant cell on the left (% Compliant), five secondary cells right.

    [ 0% │ COMPLIANT ] │ Green 0 │ Yellow 0 │ Red 2,983 │ Photos 2 │ 28 min · $0.05

Numbers use `font-feature-settings: "tnum"` (tabular) and tight
negative letter-spacing for that designed-numeric feel.
"""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st


CSS = """
<style>
.hero {
    background: var(--c-surface);
    border-radius: var(--r-md);
    box-shadow: var(--shadow-card);
    padding: clamp(10px, 1vw, 16px) clamp(14px, 1.4vw, 24px);
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: clamp(4px, 0.5vw, 10px) clamp(10px, 1.2vw, 20px);
    align-items: center;
}
@media (min-width: 48rem) {
    .hero {
        grid-template-columns: auto repeat(5, 1fr);
        gap: 0;
        column-gap: clamp(14px, 1.4vw, 28px);
    }
    /* Hairline separators between desktop cells. */
    .hero > * + * {
        position: relative;
    }
    .hero > * + *::before {
        content: "";
        position: absolute;
        left: calc(clamp(14px, 1.4vw, 28px) / -2);
        top: 12%;
        bottom: 12%;
        width: 1px;
        background: var(--c-border-soft);
    }
}

/* Dominant cell: big %, label stacked underneath */
.hero-num {
    display: flex;
    flex-direction: column;
    gap: 2px;
    line-height: 1;
    grid-column: 1 / -1;
}
@media (min-width: 48rem) { .hero-num { grid-column: auto; } }
.hero-num .row {
    display: flex;
    align-items: baseline;
    gap: 4px;
}
.hero-num .pct {
    font-size: clamp(28px, 3vw, 52px);
    font-weight: 700;
    color: var(--c-text);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.03em;
    line-height: 1;
}
.hero-num .pct-unit {
    font-size: clamp(14px, 1.1vw, 18px);
    font-weight: 500;
    color: var(--c-muted);
    letter-spacing: -0.02em;
}
.hero-num .label {
    font-size: clamp(9px, 0.66vw, 10.5px);
    font-weight: 700;
    color: var(--c-muted);
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-top: 2px;
}
.hero-num .sub {
    font-size: clamp(10px, 0.72vw, 11.5px);
    color: var(--c-text-2);
    font-variant-numeric: tabular-nums;
    margin-top: 2px;
}

/* Secondary stat cell — label (small caps + dot) above number */
.hero-stat {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
}
.hero-stat-label {
    font-size: clamp(9px, 0.66vw, 10.5px);
    font-weight: 600;
    color: var(--c-muted);
    text-transform: uppercase;
    letter-spacing: 0.10em;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}
.hero-stat-label .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
}
.hero-stat-label .dot.green  { background: var(--c-green); }
.hero-stat-label .dot.yellow { background: var(--c-yellow); }
.hero-stat-label .dot.red    { background: var(--c-red); }
.hero-stat-num {
    font-size: clamp(16px, 1.4vw, 22px);
    font-weight: 600;
    color: var(--c-text);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
    line-height: 1.1;
}
.hero-stat-sub {
    font-size: clamp(10px, 0.72vw, 11.5px);
    color: var(--c-muted);
    font-variant-numeric: tabular-nums;
    margin-top: -2px;
}
</style>
"""


@dataclass(frozen=True)
class HeroStats:
    """Numbers the hero KPI strip displays."""
    pct_compliant: float
    n_green: int
    n_yellow: int
    n_red: int
    n_segments: int
    n_photos_scored: int
    total_cost_usd: float
    audit_minutes: int
    n_duplicate_photos: int
    n_geo_mismatch: int
    n_personal_data: int
    n_ela: int


def render(s: HeroStats) -> None:
    audit_str = (
        f"{s.audit_minutes} min" if s.audit_minutes < 60
        else f"{s.audit_minutes / 60:.1f} h"
    )
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-num">
            <div class="row">
              <span class="pct">{s.pct_compliant:.0f}</span><span
                class="pct-unit">%</span>
            </div>
            <div class="label">Compliant</div>
            <div class="sub">{s.n_green:,} of {s.n_segments:,} segments</div>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">
              <span class="dot green"></span>Green</span>
            <span class="hero-stat-num">{s.n_green:,}</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">
              <span class="dot yellow"></span>Yellow</span>
            <span class="hero-stat-num">{s.n_yellow:,}</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">
              <span class="dot red"></span>Red</span>
            <span class="hero-stat-num">{s.n_red:,}</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">Photos</span>
            <span class="hero-stat-num">{s.n_photos_scored:,}</span>
          </div>
          <div class="hero-stat">
            <span class="hero-stat-label">Audit · spend</span>
            <span class="hero-stat-num">{audit_str}</span>
            <span class="hero-stat-sub">${s.total_cost_usd:.2f}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
