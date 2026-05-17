"""Map card for the operator upload view.

Renders a folium map of where the uploaded batch landed (GPS read from
each photo's burned-in overlay) on top of the project's trench / FCP /
cluster geometry.

Two pin shapes signal where the position came from:
    - solid white border   = lat/lon parsed directly from the photo overlay
    - purple ring border   = no overlay GPS, position derived from the
                             street address via the cached Nominatim
                             geocode (less certain — sits at the building
                             centroid, not on the trench line).

Pin **fill** color always carries the QC verdict (PASS/WARN/FAIL/...).
The ring is an orthogonal "how confident is the location" signal, so the
reviewer can read both axes at a glance.

Public surface:
    render_card(results)      -- real card with verdict-colored pins

The card sits between the drop zone and the per-photo verdict grid in
`src/ui/upload_view.py`. Kept in its own module so the upload view stays
about page flow, not folium internals.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import folium
import streamlit as st
from streamlit_folium import st_folium

from src.geomatch import parse_overlay_latlon


# ---- Paths -----------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REAL_GEO = _REPO_ROOT / "data" / "geo"
_FIXTURE_GEO = _REPO_ROOT / "demo_fixtures" / "geo"
_NOMINATIM_CACHE = _REPO_ROOT / "data" / "processed" / "nominatim_cache.json"


def _resolve_geo_paths() -> dict[str, Path]:
    """All-or-nothing: real geometry if every file is present, else fixtures.

    Mirrors `app.py::resolve_paths()` -- a partial live state would crash a
    downstream geojson load.
    """
    live = {
        "trenches": _REAL_GEO / "CLP20417A-P1-B00_Trenches.geojson",
        "fcps":     _REAL_GEO / "CLP20417A-P1-B00_FCP_Polygons.geojson",
        "cluster":  _REAL_GEO / "CLP20417A-P1-B00_SiteCluster_Polygons.geojson",
    }
    if all(p.exists() for p in live.values()):
        return live
    return {
        "trenches": _FIXTURE_GEO / "Trenches.geojson",
        "fcps":     _FIXTURE_GEO / "FCP_Polygons.geojson",
        "cluster":  _FIXTURE_GEO / "SiteCluster_Polygons.geojson",
    }


@st.cache_data(show_spinner=False)
def _load_geojson(path_str: str) -> dict:
    with open(path_str, encoding="utf-8") as f:
        return json.load(f)


# ---- Verdict pin colors ---------------------------------------------------

# Verdict palette matches the dashboard pills so a reviewer reading the
# upload view next to the dashboard doesn't see two different greens.
PIN_COLORS: dict[str, str] = {
    "PASS":     "#22c55e",
    "WARN":     "#eab308",
    "FAIL":     "#ef4444",
    "DROP":     "#64748b",
    "WITHHELD": "#64748b",
}

# Ring (border) color used when a pin's lat/lon came from a geocoded
# address rather than overlay GPS. Sits on the verdict-colored fill.
GEOCODED_RING_COLOR = "#a855f7"   # purple-500


# ---- Nominatim cache lookup (read-only) ------------------------------------

@st.cache_data(show_spinner=False)
def _load_geocode_cache(mtime_key: float) -> dict[str, dict]:
    """Read the persistent Nominatim cache from disk.

    Cached on the file's mtime so a backend pipeline run that refreshes the
    cache is picked up on the next page render without restarting Streamlit.
    The `mtime_key` arg is the cache invalidator — its value is unused
    inside the function.
    """
    del mtime_key  # only here to drive @st.cache_data invalidation
    if not _NOMINATIM_CACHE.exists():
        return {}
    try:
        data = json.loads(_NOMINATIM_CACHE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _cache_mtime() -> float:
    try:
        return _NOMINATIM_CACHE.stat().st_mtime
    except OSError:
        return 0.0


def lookup_cached_geocode(address: str) -> tuple[float, float] | None:
    """Return (lat, lon) for `address` if it's already in the Nominatim cache.

    Pure lookup -- no network call, no throttling, no error path. The full
    geomatch pipeline (`src/geomatch.py`) is the only thing that should
    write to this cache; the upload view reads what's there.

    Cache miss returns None -- the caller then drops the photo into the
    off-grid text strip, same as photos with no address at all.
    """
    if not address:
        return None
    cache = _load_geocode_cache(_cache_mtime())
    entry = cache.get(address.strip())
    if not entry:
        return None
    lat, lon = entry.get("lat"), entry.get("lon")
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


# ---- Map builder ----------------------------------------------------------

def _build_map(pins: list[dict]) -> folium.Map:
    """Folium map: project context (trenches + FCPs + cluster) + pins.

    `pins` -- list of {"lat", "lon", "verdict", "name"}.
    """
    paths = _resolve_geo_paths()
    trenches = _load_geojson(str(paths["trenches"]))
    fcps = _load_geojson(str(paths["fcps"]))
    cluster = _load_geojson(str(paths["cluster"]))

    if pins:
        lats = [p["lat"] for p in pins]
        lons = [p["lon"] for p in pins]
        center = [sum(lats) / len(lats), sum(lons) / len(lons)]
    else:
        try:
            c_coords = cluster["features"][0]["geometry"]["coordinates"][0]
            center = [
                sum(pt[1] for pt in c_coords) / len(c_coords),
                sum(pt[0] for pt in c_coords) / len(c_coords),
            ]
        except Exception:
            center = [46.555, 14.290]

    m = folium.Map(
        location=center, zoom_start=18, tiles="OpenStreetMap",
        control_scale=True,
    )
    folium.GeoJson(
        cluster,
        style_function=lambda _f: {
            "color": "#475569", "weight": 1.5,
            "fill": False, "dashArray": "4,4",
        },
        interactive=False,
    ).add_to(m)
    folium.GeoJson(
        fcps,
        style_function=lambda _f: {
            "color": "#0ea5e9", "weight": 1,
            "fillColor": "#bae6fd", "fillOpacity": 0.10,
        },
        interactive=False,
    ).add_to(m)
    folium.GeoJson(
        trenches,
        style_function=lambda _f: {
            "color": "#94a3b8", "weight": 3, "opacity": 0.7,
        },
        interactive=False,
    ).add_to(m)

    for p in pins:
        fill = PIN_COLORS.get(p["verdict"], "#64748b")
        is_geocoded = p.get("coord_source") == "geocoded_address"
        border = GEOCODED_RING_COLOR if is_geocoded else "white"
        weight = 3 if is_geocoded else 2
        folium.CircleMarker(
            location=[p["lat"], p["lon"]],
            radius=7,
            color=border,
            weight=weight,
            fillColor=fill,
            fillOpacity=0.95,
            tooltip=folium.Tooltip(_pin_tooltip_html(p), sticky=False),
        ).add_to(m)

    if len(pins) >= 2:
        m.fit_bounds(
            [[min(p["lat"] for p in pins), min(p["lon"] for p in pins)],
             [max(p["lat"] for p in pins), max(p["lon"] for p in pins)]],
            padding=(40, 40),
        )
    return m


# ---- Rendering primitives -------------------------------------------------

def _card_head(num_label: str, title: str, hint: str) -> None:
    """Same numbered-card header the upload view uses on its other cards."""
    st.markdown(
        f"<div class='upload-card-head'>"
        f"<div><div class='num'>{num_label}</div>"
        f"<h2>{title}</h2></div>"
        f"<div class='hint'>{hint}</div></div>",
        unsafe_allow_html=True,
    )


def _legend_html() -> str:
    items: list[str] = []
    for label in ("PASS", "WARN", "FAIL", "WITHHELD"):
        items.append(
            f"<span style='display:inline-flex;align-items:center;"
            f"gap:6px;margin-right:14px;font-size:11.5px;"
            f"color:var(--c-text-2);'>"
            f"<span style='width:10px;height:10px;border-radius:50%;"
            f"background:{PIN_COLORS[label]};"
            f"border:2px solid white;"
            f"box-shadow:0 0 0 1px {PIN_COLORS[label]};'></span>"
            f"{label.title()}</span>"
        )
    # Fifth swatch: purple ring = "this pin came from a geocoded address,
    # not from overlay GPS — sits at the building, not on the trench."
    items.append(
        f"<span style='display:inline-flex;align-items:center;"
        f"gap:6px;margin-right:14px;font-size:11.5px;"
        f"color:var(--c-text-2);' "
        f"title='Pin position came from the photo&apos;s street address "
        f"(geocoded), not from a GPS overlay. Address sits at the "
        f"building centroid, not on the trench line, so the pin is "
        f"approximate.'>"
        f"<span style='width:10px;height:10px;border-radius:50%;"
        f"background:#94a3b8;"
        f"border:2px solid {GEOCODED_RING_COLOR};"
        f"box-shadow:0 0 0 1px {GEOCODED_RING_COLOR};'></span>"
        f"Address-only</span>"
    )
    return f"<div class='upload-map-legend'>{''.join(items)}</div>"


def _pin_tooltip_html(p: dict) -> str:
    """Multi-line tooltip: name, verdict, source, address, paper label.

    Folium escapes its `Tooltip` content unless we mark it as HTML; we
    build a small block manually with html.escape() on every interpolated
    string so the tooltip is safe against weird filenames or OCR'd text
    that happens to contain `<`, `>`, `&`, or quotes.
    """
    safe_name = html.escape(p.get("name", ""))
    safe_verdict = html.escape(p.get("verdict", ""))
    rows: list[str] = [
        f"<div style='font-weight:600;margin-bottom:2px;'>{safe_name}</div>",
        f"<div>Verdict: <b>{safe_verdict}</b></div>",
    ]
    src = p.get("coord_source")
    if src == "geocoded_address":
        rows.append(
            "<div style='color:#a855f7;'>Position: from address "
            "(approximate)</div>"
        )
    elif src == "overlay_latlon":
        rows.append("<div>Position: overlay GPS</div>")
    addr = p.get("address")
    if addr:
        rows.append(f"<div>Address: {html.escape(addr)}</div>")
    paper = p.get("paper_label_code")
    if paper:
        rows.append(
            f"<div>Paper label: <code>{html.escape(paper)}</code></div>"
        )
    return (
        "<div style='font-size:12px;line-height:1.45;max-width:260px;'>"
        + "".join(rows)
        + "</div>"
    )


# ---- CSS for the card-internal elements -----------------------------------

# The map card's legend strip and off-grid footer reference these classes.
# Injected once per render via st.markdown; tokens follow upload_view.py's
# CSS-variable palette so the card looks like part of the surrounding page.
_CARD_CSS = """
<style>
.upload-map-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 0;
    margin: 6px 0 12px 0;
    padding-bottom: 4px;
}
.upload-map-offgrid {
    margin-top: 12px;
    padding: 10px 14px;
    background: var(--c-bg, #f8fafc);
    border: 1px solid var(--c-border, #e2e8f0);
    border-radius: 6px;
    color: var(--c-text-2, #475569);
    font-size: 12px;
    line-height: 1.55;
}
.upload-map-offgrid + .upload-map-offgrid {
    margin-top: 6px;
}
.upload-map-offgrid b {
    color: var(--c-text, #0f172a);
    font-weight: 600;
}
.upload-map-offgrid i {
    color: var(--c-muted, #64748b);
    font-style: italic;
}
</style>
"""


# ---- Public API -----------------------------------------------------------

def _pin_from_result(r: dict) -> tuple[dict, str] | tuple[None, str]:
    """Resolve one upload result to a pin dict, or signal why we couldn't.

    Returns either (pin, "overlay_latlon" | "geocoded_address") on success,
    or (None, "no_address" | "uncached_address") on failure -- the failure
    code lets the caller distinguish "no address at all" from "we have an
    address but the geocode isn't cached yet."
    """
    qc = r["qc"]
    name = r["name"]
    verdict = r["label"]
    paper = getattr(qc, "paper_label_code", None)
    address = (getattr(qc, "overlay_address", "") or "").strip()

    latlon = parse_overlay_latlon(getattr(qc, "overlay_latlon", None))
    if latlon is not None:
        return ({
            "lat": latlon[0], "lon": latlon[1],
            "verdict": verdict, "name": name,
            "coord_source": "overlay_latlon",
            "address": address or None,
            "paper_label_code": paper,
        }, "overlay_latlon")

    if not address:
        return (None, "no_address")

    cached = lookup_cached_geocode(address)
    if cached is None:
        return (None, "uncached_address")

    return ({
        "lat": cached[0], "lon": cached[1],
        "verdict": verdict, "name": name,
        "coord_source": "geocoded_address",
        "address": address,
        "paper_label_code": paper,
    }, "geocoded_address")


def render_card(
    results: list[dict],
    *,
    num_label: str = "03 &middot; Photos on the map",
    height_px: int = 420,
) -> None:
    """Real map card: verdict pins on the project geometry.

    `results` items must carry `qc` (with `overlay_latlon` and
    `overlay_address`), `label`, and `name` -- this is the shape
    `upload_view.py` builds in its scoring loop.
    """
    pins: list[dict] = []
    no_address: list[str] = []        # photo had no GPS AND no address
    uncached_address: list[str] = []  # had an address but it's not in the cache yet
    for r in results:
        pin, status = _pin_from_result(r)
        if pin is not None:
            pins.append(pin)
        elif status == "uncached_address":
            uncached_address.append(r["name"])
        else:
            no_address.append(r["name"])

    n_overlay = sum(1 for p in pins if p.get("coord_source") == "overlay_latlon")
    n_geocoded = sum(1 for p in pins if p.get("coord_source") == "geocoded_address")
    # Streamlit silences stdout from script reruns -- emit on stderr so the
    # stage line surfaces in the terminal during a live demo.
    print(
        f"[upload_map] {len(pins)} pinned "
        f"(overlay={n_overlay}, geocoded={n_geocoded}); "
        f"{len(uncached_address)} address-uncached, "
        f"{len(no_address)} no-signal",
        file=sys.stderr, flush=True,
    )

    with st.container(border=True, key="card_map"):
        st.markdown(_CARD_CSS, unsafe_allow_html=True)
        _card_head(
            num_label,
            "Where your batch landed",
            "GPS from the photo overlay, or geocoded from the address",
        )
        st.markdown(_legend_html(), unsafe_allow_html=True)

        m = _build_map(pins)
        st_folium(
            m, width=None, height=height_px,
            returned_objects=[],  # read-only -- no click reactions on this map
            key="upload_batch_map",
        )

        _render_offgrid_strips(no_address, uncached_address)


def _render_offgrid_strips(
    no_address: list[str],
    uncached_address: list[str],
) -> None:
    """Two distinct "couldn't pin this" footer strips.

    Kept separate because they mean different things to the operator:
        no_address       -- nothing we can do; photo has no location signal at all.
        uncached_address -- we have the address, just haven't geocoded it yet;
                            re-running the backend pipeline will pick it up.
    """
    def _names_line(names: list[str]) -> str:
        head = ", ".join(html.escape(n) for n in names[:4])
        more = f" +{len(names) - 4} more" if len(names) > 4 else ""
        return f"<i>{head}{more}</i>"

    if no_address:
        count_label = "photo" if len(no_address) == 1 else "photos"
        st.markdown(
            f"<div class='upload-map-offgrid'>"
            f"<b>{len(no_address)}</b> {count_label} had no GPS overlay "
            f"and no address — can&rsquo;t be mapped: {_names_line(no_address)}. "
            f"They still appear in the per-photo verdicts below."
            f"</div>",
            unsafe_allow_html=True,
        )

    if uncached_address:
        count_label = "photo" if len(uncached_address) == 1 else "photos"
        st.markdown(
            f"<div class='upload-map-offgrid'>"
            f"<b>{len(uncached_address)}</b> {count_label} had only a "
            f"street address (not yet geocoded) and aren&rsquo;t mapped: "
            f"{_names_line(uncached_address)}. They&rsquo;ll be pinned "
            f"as <span style='color:{GEOCODED_RING_COLOR};font-weight:600;'>"
            f"address-only</span> after the next pipeline run."
            f"</div>",
            unsafe_allow_html=True,
        )
