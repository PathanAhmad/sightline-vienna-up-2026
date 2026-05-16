"""UI components. Each module owns one piece of the surface and exports:
    CSS         the component's scoped CSS string (concatenated by
                src.ui.inject_all_css)
    render(…)   renders the component into the current Streamlit context
"""
from __future__ import annotations
