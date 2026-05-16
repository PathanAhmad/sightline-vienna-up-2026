"""Public UI API for the Streamlit dashboard.

Loading order matters — tokens first (CSS variables others reference),
then base (chrome / typography), then the layout grid, then components.

Typical usage in `app.py`:

    from src.ui import inject_all_css, layout
    from src.ui.components import (
        topbar, hero, demo_tour, map_view,
        catches, download, segment_panel,
    )

    inject_all_css()
    topbar.render(...)
    hero.render(stats)
    layout.begin_dash_row()
    map_col, rail_col = st.columns([2, 1])
    ...

The upload surface (`?view=upload`) lives in `src/ui/upload_view.py`
and pulls scoring helpers from `src/ui/components/live_score.py`
directly — no re-export needed here.
"""
from __future__ import annotations

import streamlit as st

from . import base, layout, tokens
from .components import (
    catches,
    chat,
    demo_tour,
    download,
    hero,
    map_view,
    segment_panel,
    topbar,
    upload_panel,
)


def inject_all_css() -> None:
    """Inject all CSS in the correct cascade order.

    Tokens define variables; base styles use them; layout uses them;
    components use them. Later rules can override earlier ones but in
    practice we keep each layer's selectors disjoint.
    """
    chunks = [
        tokens.TOKENS_CSS,
        base.BASE_CSS,
        layout.LAYOUT_CSS,
        topbar.CSS,
        hero.CSS,
        demo_tour.CSS,
        map_view.CSS,
        catches.CSS,
        download.CSS,
        segment_panel.CSS,
        chat.CSS,
        upload_panel.CSS,
    ]
    st.markdown("\n".join(chunks), unsafe_allow_html=True)


__all__ = [
    "inject_all_css",
    "layout",
    "topbar",
    "hero",
    "demo_tour",
    "map_view",
    "catches",
    "download",
    "segment_panel",
    "chat",
    "upload_panel",
]
