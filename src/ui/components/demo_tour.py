"""Demo tour — three pill buttons at the top of the rail.

Picks one segment per scenario from the loaded data; disables a button
if no example exists. Clicking sets `st.session_state['selected_segment']`.

Like other components in this package, the CSS targets the actual
Streamlit buttons that render AFTER the marker (Streamlit widgets
don't nest inside markdown wrappers, so the marker-sibling pattern is
how we reach them).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st


CSS = """
<style>
[data-testid="stElementContainer"]:has(.demo-tour-marker)
    ~ [data-testid="stLayoutWrapper"]:first-of-type
    .stButton > button,
[data-testid="stElementContainer"]:has(.demo-tour-marker)
    ~ [data-testid="stHorizontalBlock"]:first-of-type
    .stButton > button {
    width: 100%;
    border-radius: var(--r-sm);
    border: 1px solid var(--c-border);
    background: var(--c-surface);
    color: var(--c-text);
    font-weight: 500;
    font-size: 11.5px;
    letter-spacing: -0.005em;
    padding: 6px var(--s-3);
    min-height: 34px;
    text-align: center;
    line-height: 1.2;
    transition: border-color 120ms ease, color 120ms ease,
                background 120ms ease;
}
[data-testid="stElementContainer"]:has(.demo-tour-marker)
    ~ [data-testid="stLayoutWrapper"]:first-of-type
    .stButton > button:hover,
[data-testid="stElementContainer"]:has(.demo-tour-marker)
    ~ [data-testid="stHorizontalBlock"]:first-of-type
    .stButton > button:hover {
    border-color: var(--c-accent);
    color: var(--c-accent);
    background: var(--c-accent-soft);
}
[data-testid="stElementContainer"]:has(.demo-tour-marker)
    ~ [data-testid="stLayoutWrapper"]:first-of-type
    .stButton > button:disabled,
[data-testid="stElementContainer"]:has(.demo-tour-marker)
    ~ [data-testid="stHorizontalBlock"]:first-of-type
    .stButton > button:disabled {
    color: var(--c-muted);
    background: var(--c-bg);
    border-color: var(--c-border-soft);
    cursor: not-allowed;
}
.demo-tour-marker { display: none; }
</style>
"""


def _find_demo_segments(
    verdicts_by_segment: dict[str, dict],
    geomatch_df: pd.DataFrame,
    readqc: list[dict],
    forensics: list[dict],
) -> dict[str, str | None]:
    """For each demo-tour scenario, pick one segment in the loaded data
    that showcases it. Returns None per slot when nothing matches — the
    button is disabled rather than guessing.
    """
    red_gap: str | None = None
    red_segs = [
        s for s in verdicts_by_segment.values() if s.get("verdict") == "RED"
    ]
    if red_segs:
        red_gap = max(
            red_segs, key=lambda s: float(s.get("length_m") or 0),
        )["segment_id"]

    # Pick the segment with the MOST matching photos -- bigger visible
    # payoff than iloc[0] (which was undefined-ordering, often landed on
    # an unremarkable single-photo segment with only 4 non-reps in data).
    def _top_segment_by_count(photo_ids: set[str]) -> str | None:
        if not photo_ids or geomatch_df.empty:
            return None
        match = geomatch_df[geomatch_df["photo_id"].isin(photo_ids)]
        match = match[match["segment_id"].notna() & (match["segment_id"] != "")]
        if match.empty:
            return None
        return str(match["segment_id"].value_counts().idxmax())

    pd_photos = {
        r["photo_id"] for r in readqc
        if r.get("personal_data_visible") == "yes"
    }
    gdpr = _top_segment_by_count(pd_photos)

    non_rep = {
        r["photo_id"] for r in forensics
        if not r.get("is_phash_representative")
    }
    duplicate = _top_segment_by_count(non_rep)

    return {"red_gap": red_gap, "duplicate": duplicate, "gdpr": gdpr}


def render(
    verdicts_by_segment: dict[str, dict],
    geomatch_df: pd.DataFrame,
    readqc: list[dict],
    forensics: list[dict],
) -> None:
    """Render the three tour pill buttons. The marker primes the CSS
    selector that pill-styles the buttons rendered after it."""
    picks = _find_demo_segments(
        verdicts_by_segment, geomatch_df, readqc, forensics,
    )
    st.markdown(
        "<div class='demo-tour-marker'></div>"
        "<div class='section-head'>Jump to a typical catch</div>",
        unsafe_allow_html=True,
    )
    # "Coverage gap" is special: it toggles a map-wide filter that
    # hides every segment with photos, leaving only the un-documented
    # gaps. The other two pills still jump to a single example segment.
    coverage_filter_on = bool(
        st.session_state.get("map_filter_coverage_gap", False)
    )

    items = [
        ("red_gap",   "Coverage gap"),
        ("duplicate", "Duplicate"),
        ("gdpr",      "GDPR redaction"),
    ]
    cols = st.columns(3)
    for col, (key, label) in zip(cols, items):
        seg_id = picks.get(key)
        with col:
            if key == "red_gap":
                # Filter toggle: button label flips to "Show all" when
                # the filter is active. Never disabled — the filter
                # mode is always meaningful even if no RED segment
                # qualifies as a single-pick "example."
                btn_label = "Show all" if coverage_filter_on else label
                clicked = st.button(
                    btn_label,
                    key=f"tour_{key}",
                    use_container_width=True,
                )
                if clicked:
                    st.session_state["map_filter_coverage_gap"] = (
                        not coverage_filter_on
                    )
                    # Drop any open segment selection so the filtered
                    # map doesn't keep an out-of-view panel pinned open.
                    st.session_state.pop("selected_segment", None)
                    st.rerun()
                continue
            clicked = st.button(
                label,
                key=f"tour_{key}",
                disabled=seg_id is None,
                use_container_width=True,
            )
            if clicked and seg_id is not None:
                st.session_state["selected_segment"] = seg_id
                # Pan the map to the picked segment for the same frame.
                # Without this, only the rail panel changes -- the map
                # looks identical and the click feels broken. Consumed
                # once by app.py's focus_bounds path.
                st.session_state["_fly_to_segment"] = seg_id
                # Also reset the click-handler's "last seen click" so a
                # later real map click on the same segment still opens
                # the panel (st_folium replays its last click payload).
                st.session_state["_last_map_click_seg"] = seg_id
                st.rerun()
