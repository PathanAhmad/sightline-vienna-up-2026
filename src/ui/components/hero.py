"""Hero KPI strip — Linear/Vercel-style.

Layout (desktop): one row, five cells separated by subtle hairlines.
Two dominant cells on the left split the headline into the two
questions a reviewer actually asks: how much of the route is
documented, and of that, how much passes. Three secondary cells
break the verdict mix (Green / Yellow / Red).

    [ 9% │ COVERAGE ] [ 31% │ QUALITY ] │ Green │ Yellow │ Red

Per-model accuracy / cost / time used to live in two more cells, but
that comparison is a *pitch* moment, not an operating dashboard
fixture. The numbers still get written to
`data/processed/model_benchmark.json` by `src.audit_groundtruth` for
slide use.

Why two numbers, not one "% compliant": dividing GREEN by all planned
segments collapses coverage (was a photo even taken?) and quality
(does the photo pass spec?) into one ratio. With a hyper-fragmented
route plan and a partial photo batch, that ratio reads ~3% even when
the documented segments are mostly fine. The two-number split keeps
"contractor delivered nothing here" and "contractor's work failed
spec" as separate facts.

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
        grid-template-columns: auto auto repeat(3, 1fr);
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
    font-size: clamp(24px, 2.4vw, 40px);
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
    font-size: clamp(11.5px, 0.88vw, 13px);
    color: var(--c-text);
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    margin-top: 1px;
}
</style>
"""


@dataclass(frozen=True)
class ModelSpend:
    """Cost + wall-time spent on one Claude model variant.

    Production fields (`n_photos`, `cost_usd`, `seconds`) aggregate
    every photo the pipeline scored with this model.

    Benchmark fields (`accuracy_pct`, `accuracy_n_test`, `bench_seconds`,
    `bench_cost_usd`) come from `audit_groundtruth.py` — the model was
    run on the SAME 214 hand-labeled ground-truth photos under
    `data/Resources/examples/{depth,duct}/`, so accuracy and timing are
    apples-to-apples across models. None means we don't have a
    measurement yet for this model.
    """
    n_photos: int
    cost_usd: float
    seconds: float
    accuracy_pct: float | None = None
    accuracy_n_test: int | None = None
    bench_seconds: float | None = None
    bench_cost_usd: float | None = None


@dataclass(frozen=True)
class HeroStats:
    """Numbers the hero KPI strip displays."""
    pct_coverage: float
    pct_quality: float
    n_segments_with_photos: int
    n_green: int
    n_yellow: int
    n_red: int
    n_segments: int
    n_photos_scored: int
    total_cost_usd: float
    audit_minutes: int
    sonnet: ModelSpend
    haiku: ModelSpend
    n_duplicate_photos: int
    n_geo_mismatch: int
    n_personal_data: int
    n_ela: int


def _fmt_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} s"
    if seconds < 3600:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def render(s: HeroStats) -> None:
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-num">
            <div class="row">
              <span class="pct">{s.pct_coverage:.0f}</span><span
                class="pct-unit">%</span>
            </div>
            <div class="label">Coverage</div>
            <div class="sub">{s.n_segments_with_photos:,} of {s.n_segments:,} segments documented</div>
          </div>
          <div class="hero-num">
            <div class="row">
              <span class="pct">{s.pct_quality:.0f}</span><span
                class="pct-unit">%</span>
            </div>
            <div class="label">Quality</div>
            <div class="sub">{s.n_green:,} of {s.n_segments_with_photos:,} pass spec</div>
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
        </div>
        """,
        unsafe_allow_html=True,
    )


def _fmt_accuracy(m: ModelSpend) -> str:
    if m.accuracy_pct is None:
        return "—"
    return f"{m.accuracy_pct:.0f}%"


def _fmt_model_sub(m: ModelSpend) -> str:
    """Single line summarising the apples-to-apples bench run.

    Format: '<N> photos · <time> · $<cost>' — wall time and cost for
    scoring the same N hand-labeled ground-truth photos the accuracy %
    is computed on. Production totals are intentionally NOT shown: the
    point is the comparison between models on the same dataset.
    """
    if m.accuracy_n_test is None or m.accuracy_pct is None:
        return "no benchmark yet"
    bits = [f"{m.accuracy_n_test} photos"]
    if m.bench_seconds is not None and m.bench_seconds > 0:
        bits.append(_fmt_time(m.bench_seconds))
    if m.bench_cost_usd is not None and m.bench_cost_usd > 0:
        bits.append(f"${m.bench_cost_usd:.2f}")
    return " · ".join(bits)
