"""Unit tests for upload_map's cache-lookup + pin-decision logic.

Standalone runner (no pytest) because this project doesn't use a test
framework. Run with:

    .venv/Scripts/python.exe scripts/test_upload_map_geocode.py

Exit code 0 = all pass. Any assertion error or non-zero exit = failure.

We monkey-patch the module's `_NOMINATIM_CACHE` Path so the test doesn't
touch the real cache file. Streamlit cache decorators are sidestepped by
calling the inner function via `.__wrapped__` or by clearing cache
between tests.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

# Make the repo root importable when run from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ui.components import upload_map as um  # noqa: E402


def _set_cache_file(tmp_dir: Path, content: dict | None) -> Path:
    """Point upload_map at a fresh cache file inside tmp_dir."""
    cache_path = tmp_dir / "nominatim_cache.json"
    if content is not None:
        cache_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    um._NOMINATIM_CACHE = cache_path
    # Streamlit's @st.cache_data caches by argument value. Our `mtime_key`
    # changes when we touch the file, so a fresh write invalidates the
    # cache. But we also explicitly clear to be safe across tests.
    um._load_geocode_cache.clear()
    return cache_path


def _fake_qc(*, latlon: str | None = None, address: str = "",
             paper: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        overlay_latlon=latlon,
        overlay_address=address,
        paper_label_code=paper,
    )


def test_lookup_hit_returns_floats() -> None:
    with tempfile.TemporaryDirectory() as td:
        _set_cache_file(Path(td), {
            "1 Fasanstraße, Maria Rain": {
                "lat": 46.5651314, "lon": 14.2880093,
                "road": "Fasanstraße", "display_name": "...",
            }
        })
        got = um.lookup_cached_geocode("1 Fasanstraße, Maria Rain")
        assert got is not None, "expected a hit"
        lat, lon = got
        assert abs(lat - 46.5651314) < 1e-9, lat
        assert abs(lon - 14.2880093) < 1e-9, lon


def test_lookup_miss_returns_none() -> None:
    with tempfile.TemporaryDirectory() as td:
        _set_cache_file(Path(td), {"some other address": {"lat": 0, "lon": 0}})
        assert um.lookup_cached_geocode("Unbekannte Straße 99") is None


def test_lookup_strips_whitespace() -> None:
    with tempfile.TemporaryDirectory() as td:
        _set_cache_file(Path(td), {
            "Pirolweg 2, 9161 Maria Rain": {"lat": 46.5, "lon": 14.3},
        })
        got = um.lookup_cached_geocode("   Pirolweg 2, 9161 Maria Rain   ")
        assert got == (46.5, 14.3), got


def test_lookup_empty_returns_none() -> None:
    with tempfile.TemporaryDirectory() as td:
        _set_cache_file(Path(td), {})
        assert um.lookup_cached_geocode("") is None
        assert um.lookup_cached_geocode("   ") is None


def test_lookup_missing_file_returns_none() -> None:
    with tempfile.TemporaryDirectory() as td:
        # Don't write anything -- file doesn't exist
        _set_cache_file(Path(td), None)
        assert um.lookup_cached_geocode("anything") is None


def test_lookup_null_entry_returns_none() -> None:
    """Geocoder caches null results too -- we shouldn't pin those."""
    with tempfile.TemporaryDirectory() as td:
        _set_cache_file(Path(td), {"unknown addr": {}})
        assert um.lookup_cached_geocode("unknown addr") is None


def test_lookup_malformed_lat_returns_none() -> None:
    with tempfile.TemporaryDirectory() as td:
        _set_cache_file(Path(td), {"x": {"lat": "not a number", "lon": 14.0}})
        assert um.lookup_cached_geocode("x") is None


def test_pin_decision_overlay_latlon() -> None:
    r = {
        "qc": _fake_qc(
            latlon="46.56527988N 14.28760966E",
            address="1 Fasanstraße, Maria Rain",
            paper="F170-R084-11-or",
        ),
        "name": "photo1.jpg",
        "label": "PASS",
    }
    pin, status = um._pin_from_result(r)
    assert pin is not None
    assert status == "overlay_latlon", status
    assert pin["coord_source"] == "overlay_latlon"
    assert abs(pin["lat"] - 46.56527988) < 1e-6, pin["lat"]
    assert abs(pin["lon"] - 14.28760966) < 1e-6, pin["lon"]
    assert pin["verdict"] == "PASS"
    assert pin["paper_label_code"] == "F170-R084-11-or"
    # Address still carried for tooltip
    assert pin["address"] == "1 Fasanstraße, Maria Rain"


def test_pin_decision_geocoded_address() -> None:
    with tempfile.TemporaryDirectory() as td:
        _set_cache_file(Path(td), {
            "Pirolweg 2, 9161 Maria Rain": {"lat": 46.55, "lon": 14.29},
        })
        r = {
            "qc": _fake_qc(
                latlon=None,
                address="Pirolweg 2, 9161 Maria Rain",
                paper=None,
            ),
            "name": "photo2.jpg",
            "label": "WARN",
        }
        pin, status = um._pin_from_result(r)
        assert pin is not None
        assert status == "geocoded_address", status
        assert pin["coord_source"] == "geocoded_address"
        assert pin["lat"] == 46.55
        assert pin["lon"] == 14.29
        assert pin["verdict"] == "WARN"
        assert pin["paper_label_code"] is None


def test_pin_decision_uncached_address() -> None:
    with tempfile.TemporaryDirectory() as td:
        _set_cache_file(Path(td), {})  # empty cache
        r = {
            "qc": _fake_qc(latlon=None, address="Some uncached street 42"),
            "name": "photo3.jpg",
            "label": "FAIL",
        }
        pin, status = um._pin_from_result(r)
        assert pin is None
        assert status == "uncached_address", status


def test_pin_decision_no_address() -> None:
    r = {
        "qc": _fake_qc(latlon=None, address=""),
        "name": "photo4.jpg",
        "label": "DROP",
    }
    pin, status = um._pin_from_result(r)
    assert pin is None
    assert status == "no_address", status


def test_pin_decision_unparseable_latlon_falls_through_to_address() -> None:
    """If the overlay_latlon string is garbage, we should still try
    geocoding the address before giving up."""
    with tempfile.TemporaryDirectory() as td:
        _set_cache_file(Path(td), {
            "Hauptstraße 1, Klagenfurt": {"lat": 46.62, "lon": 14.31},
        })
        r = {
            "qc": _fake_qc(
                latlon="GPS unavailable",   # unparseable
                address="Hauptstraße 1, Klagenfurt",
            ),
            "name": "photo5.jpg",
            "label": "PASS",
        }
        pin, status = um._pin_from_result(r)
        assert pin is not None, "should have fallen through to geocode"
        assert status == "geocoded_address"
        assert pin["coord_source"] == "geocoded_address"


def test_legend_html_contains_all_swatches() -> None:
    html = um._legend_html()
    for label in ("Pass", "Warn", "Fail", "Withheld", "Address-only"):
        assert label in html, f"legend missing {label!r}"
    # Purple ring color must appear (verifies our swatch was actually rendered)
    assert um.GEOCODED_RING_COLOR.lower() in html.lower()


def test_tooltip_html_escapes_dangerous_input() -> None:
    """Filenames or OCR'd addresses could contain `<` or `&`."""
    p = {
        "name": "evil<script>.jpg",
        "verdict": "PASS",
        "coord_source": "overlay_latlon",
        "address": "Fake & Co",
        "paper_label_code": "F<bad>",
    }
    out = um._pin_tooltip_html(p)
    assert "<script>" not in out, "raw <script> leaked into tooltip"
    assert "&lt;script&gt;" in out
    assert "&amp;" in out
    assert "&lt;bad&gt;" in out


def test_tooltip_html_includes_geocoded_marker() -> None:
    p = {
        "name": "p.jpg",
        "verdict": "PASS",
        "coord_source": "geocoded_address",
        "address": "Pirolweg 2",
        "paper_label_code": "F170-R084",
    }
    out = um._pin_tooltip_html(p)
    assert "approximate" in out.lower()
    assert "Pirolweg 2" in out
    assert "F170-R084" in out


def test_tooltip_html_omits_missing_fields() -> None:
    p = {
        "name": "p.jpg",
        "verdict": "DROP",
        "coord_source": "overlay_latlon",
    }
    out = um._pin_tooltip_html(p)
    # No address row, no paper-label row
    assert "Address:" not in out
    assert "Paper label:" not in out
    assert "overlay GPS" in out


# -----------------------------------------------------------------------------

def main() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERR   {t.__name__}: {type(e).__name__}: {e}")
    total = len(tests)
    print(f"\n{total - failed}/{total} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
