"""Download CTA — the single primary action on the rail.

Streamlit's `st.download_button` is the only on-screen primary
(filled accent) button. Other Streamlit buttons are styled as
secondary in base.py.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st


CSS = """
<style>
/* Force the download container itself to fill the column width. Without
   this, .stDownloadButton sizes to button content (~328px) and leaves a
   visible gap to the right of the CTA inside the rail. */
.stDownloadButton {
    width: 100%;
    display: block;
}
.stDownloadButton > button {
    background: var(--c-accent);
    color: white !important;
    border: 1px solid var(--c-accent);
    border-radius: var(--r-sm);
    padding: var(--s-3) var(--s-4);
    min-height: 48px;
    font-weight: 600;
    font-size: 14px;
    width: 100%;
    box-shadow: none;
}
.stDownloadButton > button:hover {
    background: #075985;
    border-color: #075985;
}
</style>
"""


def render(verdicts: pd.DataFrame) -> None:
    """Download a deficiency CSV containing all non-GREEN segments."""
    from src.report import DEFICIENCY_FIELDS

    bad = (
        verdicts[verdicts["verdict"] != "GREEN"][list(DEFICIENCY_FIELDS)]
        .sort_values(["fcp_name", "length_m"], ascending=[True, False])
    )
    n_bad = len(bad)
    plural = "s" if n_bad != 1 else ""
    st.download_button(
        f"Download deficiency report  ·  {n_bad} segment{plural}",
        data=bad.to_csv(index=False).encode("utf-8"),
        file_name="deficiency.csv",
        mime="text/csv",
        key="download_deficiency",
        use_container_width=True,
    )
