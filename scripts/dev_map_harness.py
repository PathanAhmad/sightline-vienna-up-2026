"""Dev-only Streamlit harness that renders upload_map.render_card with
seeded synthetic results, so we can Playwright-test the rendered DOM
without burning Claude API tokens on real uploads.

Run with:
    .venv/Scripts/python.exe -m streamlit run scripts/dev_map_harness.py \
        --server.port 8502 --server.headless true --browser.gatherUsageStats false

This is NOT part of the shipped app -- it's a developer harness only.
The harness primes the Nominatim cache with one synthetic entry before
calling render_card, so the three coord-source code paths
(overlay_latlon / geocoded_address / no_address) all exercise.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from src.ui.components import upload_map  # noqa: E402


# ---- Prime a temp Nominatim cache so the harness is self-contained --------

@st.cache_resource
def _prime_cache() -> Path:
    """Write a one-entry cache to a temp file and point upload_map at it."""
    tmpdir = Path(tempfile.mkdtemp(prefix="dev_map_cache_"))
    cache = tmpdir / "nominatim_cache.json"
    cache.write_text(json.dumps({
        # Pirolweg is in the Maria Rain cluster the fixtures cover
        "Pirolweg 2, 9161 Maria Rain": {
            "lat": 46.5651,
            "lon": 14.2890,
            "road": "Pirolweg",
            "display_name": "Pirolweg 2, 9161 Maria Rain, Austria (synthetic)",
        }
    }), encoding="utf-8")
    upload_map._NOMINATIM_CACHE = cache
    upload_map._load_geocode_cache.clear()
    return cache


# ---- Seeded synthetic results ---------------------------------------------

def _seeded_results() -> list[dict]:
    """Three photos covering the three coord-source code paths."""
    return [
        {
            # 1) Overlay-GPS pin (PASS) -- solid white border
            "name": "001_overlay_gps.jpg",
            "label": "PASS",
            "qc": SimpleNamespace(
                overlay_latlon="46.5651N 14.2880E",
                overlay_address="1 Fasanstraße, Maria Rain",
                paper_label_code="F170-R084-11-or",
            ),
            "image": b"", "cost": 0.0,
        },
        {
            # 2) Address-only pin (WARN) -- purple ring border via cache hit
            "name": "002_addr_only.jpg",
            "label": "WARN",
            "qc": SimpleNamespace(
                overlay_latlon=None,
                overlay_address="Pirolweg 2, 9161 Maria Rain",
                paper_label_code=None,
            ),
            "image": b"", "cost": 0.0,
        },
        {
            # 3) Uncached address (FAIL) -- footer "not yet geocoded" strip
            "name": "003_uncached.jpg",
            "label": "FAIL",
            "qc": SimpleNamespace(
                overlay_latlon=None,
                overlay_address="Unknown Street 99, Klagenfurt",
                paper_label_code="F999-R999-0-xx",
            ),
            "image": b"", "cost": 0.0,
        },
        {
            # 4) No-address-at-all (DROP) -- footer "no GPS / no address" strip
            "name": "004_no_signal.jpg",
            "label": "DROP",
            "qc": SimpleNamespace(
                overlay_latlon=None,
                overlay_address="",
                paper_label_code=None,
            ),
            "image": b"", "cost": 0.0,
        },
    ]


# ---- Streamlit entry ------------------------------------------------------

st.set_page_config(page_title="Dev: upload_map harness", layout="wide")
_prime_cache()

st.markdown("# Dev harness: `upload_map.render_card`")
st.caption(
    "Synthetic results exercising all three coord-source code paths. "
    "Not part of the shipped app -- run via `streamlit run scripts/dev_map_harness.py`."
)

upload_map.render_card(_seeded_results())
