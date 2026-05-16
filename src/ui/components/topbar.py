"""Topbar — slim single row at the top.

    APG · TRENCH QC    Project · Location              [• live data]

One row. Wraps on mobile. Bottom border separates it from the hero.
"""
from __future__ import annotations

import streamlit as st


CSS = """
<style>
.topbar {
    display: flex;
    align-items: center;
    gap: clamp(8px, 1vw, 16px);
    padding: clamp(4px, 0.4vw, 8px) 0 clamp(6px, 0.6vw, 10px) 0;
    margin-bottom: clamp(6px, 0.6vw, 10px);
    border-bottom: 1px solid var(--c-border-soft);
    flex-wrap: wrap;
}
.topbar-brand {
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--c-accent);
    white-space: nowrap;
}
.topbar-project {
    font-size: 14px;
    color: var(--c-text-2);
    line-height: 1.3;
    min-width: 0;
    flex: 1;
}
.topbar-project b { color: var(--c-text); font-weight: 600; }
.topbar-project .loc { color: var(--c-muted); font-size: 12px; }
.topbar-status {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    padding: 3px 10px;
    border-radius: var(--r-pill);
    border: 1px solid var(--c-border);
    background: var(--c-bg);
    color: var(--c-text-2);
    white-space: nowrap;
}
.topbar-status.live {
    background: var(--c-green-soft);
    border-color: #bbf7d0;
    color: #166534;
}
.topbar-status .dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: currentColor;
    margin-right: 5px;
    vertical-align: 1px;
}
</style>
"""


_STATUS_PRESETS = {
    "live": ("live", "live data"),
    "fixtures": ("", "demo fixtures"),
    "upload": ("", "operator submission"),
}


def render(
    project_name: str,
    project_location: str,
    source: str,
    status_text: str | None = None,
    status_cls: str | None = None,
) -> None:
    """Render the topbar.

    `source` is one of {'live', 'fixtures', 'upload'} — a shorthand that
    picks a preset status pill. `status_text` / `status_cls` override the
    preset when set (e.g. a future 'review' surface)."""
    preset_cls, preset_text = _STATUS_PRESETS.get(source, ("", source))
    cls = status_cls if status_cls is not None else preset_cls
    text = status_text if status_text is not None else preset_text
    st.markdown(
        f"""
        <div class="topbar">
          <span class="topbar-brand">APG · TRENCH QC</span>
          <span class="topbar-project">
            <b>{project_name}</b>
            <span class="loc"> · {project_location}</span>
          </span>
          <span class="topbar-status {cls}">
            <span class="dot"></span>{text}
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
