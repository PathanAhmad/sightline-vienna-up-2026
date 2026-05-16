"""Page shell — viewport-locked grid that all components plug into.

Three vertical regions on desktop:
    row 1   topbar          (auto, sized to content)
    row 2   hero KPI strip  (auto)
    row 3   dash row        (1fr — takes ALL remaining vh)
              ├─ map column   (left, iframe fills 100% via the
              │                 streamlit_folium iframe-title rule)
              └─ rail column  (right, scrolls internally; download
                                CTA is bottom-anchored via flex)

Implementation follows the post-Streamlit-1.40 community pattern (see
discuss.streamlit.io thread "Enhancing Streamlit dashboard with CSS"):
target stMainBlockContainer + stVerticalBlock directly, no `:has()`
deep chains. The dash row is identified as the only stLayoutWrapper
at the top level of the page stack.

On mobile (< md), the layout falls back to a normal vertical stack
(columns wrap, no height locking).
"""
from __future__ import annotations

import streamlit as st


LAYOUT_CSS = """
<style>
/* ---- Block container — no max-width, fluid padding ---------------- */
.block-container,
[data-testid="stMainBlockContainer"] {
    padding: clamp(6px, 0.6vw, 12px) clamp(8px, 0.8vw, 14px) !important;
    max-width: 100% !important;
    width: 100% !important;
    margin: 0 !important;
}
[data-testid="stHorizontalBlock"] { gap: clamp(6px, 0.6vw, 10px) !important; }
[data-testid="stVerticalBlock"] { gap: clamp(4px, 0.4vw, 8px) !important; }

/* ---- VIEWPORT GRID — desktop only -------------------------------- */
@media (min-width: 48rem) {
    [data-testid="stAppViewContainer"] {
        height: 100vh;
        overflow: hidden;
    }
    [data-testid="stMain"] {
        height: 100vh;
        overflow: hidden;
    }
    [data-testid="stMainBlockContainer"] {
        height: 100vh;
        display: flex;
        flex-direction: column;
        min-height: 0;
    }
    /* Page stack — flex column. Topbar + hero are auto-height and
       MUST NOT shrink (default flex-shrink:1 was making the hero's
       stElementContainer shorter than its content, causing the hero
       card to bleed into the map below by ~8px). The dash-row
       stLayoutWrapper is the only LayoutWrapper at this level and
       takes flex:1 to fill remaining viewport. */
    [data-testid="stMainBlockContainer"]
        > [data-testid="stVerticalBlock"] {
        flex: 1 1 0;
        min-height: 0;
        display: flex;
        flex-direction: column;
        gap: clamp(4px, 0.4vw, 8px);
    }
    [data-testid="stMainBlockContainer"]
        > [data-testid="stVerticalBlock"]
        > [data-testid="stElementContainer"] {
        flex: 0 0 auto;
    }
    [data-testid="stMainBlockContainer"]
        > [data-testid="stVerticalBlock"]
        > [data-testid="stLayoutWrapper"] {
        flex: 1 1 0;
        min-height: 0;
        display: flex;
        flex-direction: column;
    }
    [data-testid="stMainBlockContainer"]
        > [data-testid="stVerticalBlock"]
        > [data-testid="stLayoutWrapper"]
        > [data-testid="stHorizontalBlock"] {
        flex: 1 1 0;
        min-height: 0;
        height: 100%;
    }
    [data-testid="stMainBlockContainer"]
        > [data-testid="stVerticalBlock"]
        > [data-testid="stLayoutWrapper"]
        > [data-testid="stHorizontalBlock"]
        > [data-testid="stColumn"] {
        height: 100%;
        min-height: 0;
    }

    /* ---- MAP COLUMN — folium iframe fills 100% column height ---- */
    /* streamlit_folium emits its iframe with title="streamlit_folium.
       st_folium" — directly addressable. We also offset the map's top
       so it aligns with the "Jump to a typical catch" section-head in
       the rail (the section-head has its own 12px margin-top; without
       a matching offset the map appears to start higher and visually
       bleeds into the hero card above). */
    iframe[title="streamlit_folium.st_folium"] {
        height: 100% !important;
        width: 100% !important;
        min-height: 320px;
        border-radius: var(--r-md);
        border: 1px solid var(--c-border);
        box-shadow: var(--shadow-card);
        display: block;
    }
    /* The iframe lives inside stCustomComponentV1 → stElementContainer.
       Those need to expand too, otherwise height:100% has no parent
       reference. The margin-top here is what visually aligns the map's
       top edge with the section-head in the rail. */
    [data-testid="stMainBlockContainer"]
        > [data-testid="stVerticalBlock"]
        > [data-testid="stLayoutWrapper"]
        [data-testid="stColumn"]:nth-child(1)
        > [data-testid="stVerticalBlock"]
        > [data-testid="stElementContainer"]:has(iframe) {
        flex: 1 1 0;
        min-height: 0;
        margin-top: 15px;
    }
    [data-testid="stMainBlockContainer"]
        > [data-testid="stVerticalBlock"]
        > [data-testid="stLayoutWrapper"]
        [data-testid="stColumn"]:nth-child(1)
        > [data-testid="stVerticalBlock"]
        > [data-testid="stElementContainer"]:has(iframe)
        > div {
        height: 100%;
    }

    /* ---- RAIL COLUMN — scrolls internally + download anchored ----
       The rail column has overflow-y:auto so tall content (segment
       panel with photo grid) scrolls without breaking the page-level
       viewport lock. The inner stVerticalBlock is a flex column so
       the download CTA can claim margin-top:auto and sit flush at
       the bottom of the rail (matching the map's bottom edge). */
    [data-testid="stMainBlockContainer"]
        > [data-testid="stVerticalBlock"]
        > [data-testid="stLayoutWrapper"]
        [data-testid="stColumn"]:nth-child(2) {
        overflow-y: auto;
        overflow-x: hidden;
        padding-right: 6px;
    }
    [data-testid="stMainBlockContainer"]
        > [data-testid="stVerticalBlock"]
        > [data-testid="stLayoutWrapper"]
        [data-testid="stColumn"]:nth-child(2)::-webkit-scrollbar {
        width: 6px;
    }
    [data-testid="stMainBlockContainer"]
        > [data-testid="stVerticalBlock"]
        > [data-testid="stLayoutWrapper"]
        [data-testid="stColumn"]:nth-child(2)::-webkit-scrollbar-thumb {
        background: var(--c-border);
        border-radius: 3px;
    }
    [data-testid="stMainBlockContainer"]
        > [data-testid="stVerticalBlock"]
        > [data-testid="stLayoutWrapper"]
        [data-testid="stColumn"]:nth-child(2)
        > [data-testid="stVerticalBlock"] {
        display: flex;
        flex-direction: column;
        min-height: 100%;
    }
    /* Anchor the download CTA to the bottom of the rail. */
    [data-testid="stMainBlockContainer"]
        > [data-testid="stVerticalBlock"]
        > [data-testid="stLayoutWrapper"]
        [data-testid="stColumn"]:nth-child(2)
        > [data-testid="stVerticalBlock"]
        > [data-testid="stElementContainer"]:has(.stDownloadButton) {
        margin-top: auto;
    }
}
</style>
"""


def begin_dash_row() -> None:
    """No-op (kept for compatibility / future structural hooks).

    The dash row is identified structurally now (the only top-level
    stLayoutWrapper inside stMainBlockContainer's stVerticalBlock).
    No marker needed.
    """
    return None
