"""Map view — folium map of the trench network + click-to-select.

Builds a folium map colored by segment verdict, snaps photos as small
dots, and parses st_folium's click payload back to a segment_id that
the segment panel can pick up.

The iframe CSS in src.ui.layout already makes the map fill 100% of
its column (height-wise). This module only owns the map's *appearance*
(the leaflet styling, photo dot color) and the click-parsing logic.
"""
from __future__ import annotations

from typing import Any

import folium


CSS = ""  # iframe sizing/styling is owned by src.ui.layout
         # (targets iframe[title="streamlit_folium.st_folium"] directly).


VERDICT_COLORS = {
    "GREEN": "#22c55e",
    "YELLOW": "#eab308",
    "RED": "#ef4444",
}


def _style_for_segment(verdict: str) -> dict:
    return {
        "color": VERDICT_COLORS.get(verdict, "#888"),
        "weight": 6,
        "opacity": 0.9,
    }


def build_map(
    trenches: dict,
    fcps: dict,
    cluster: dict,
    verdicts_by_segment: dict[str, dict],
    photo_points: list[dict],
    upload_points: list[dict] | None = None,
    focus_bounds: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> folium.Map:
    """Build the folium map. Each trench feature carries its verdict in
    properties so the click handler can read it back without a roundtrip.
    """
    feature_collection = {"type": "FeatureCollection", "features": []}
    for feat in trenches["features"]:
        # Real Trenches.geojson uses `externalID` (verified 2026-05-15);
        # `globalID` and `segment_id` are kept as fallbacks for the demo
        # fixtures, which were authored against the original PLAN naming.
        props = feat["properties"]
        seg_id = (
            props.get("externalID")
            or props.get("globalID")
            or props.get("segment_id")
        )
        v_row = verdicts_by_segment.get(seg_id, {})
        verdict = v_row.get("verdict", "RED")
        enriched = {
            **feat,
            "properties": {
                **feat["properties"],
                "segment_id": seg_id,
                "verdict": verdict,
                "fcp_name": v_row.get("fcp_name", ""),
                "length_m": v_row.get("length_m", ""),
                "reasons": v_row.get("reasons", ""),
            },
        }
        feature_collection["features"].append(enriched)

    # Map center: cluster centroid (rough)
    try:
        c_coords = cluster["features"][0]["geometry"]["coordinates"][0]
        lats = [pt[1] for pt in c_coords]
        lons = [pt[0] for pt in c_coords]
        center = [sum(lats) / len(lats), sum(lons) / len(lons)]
    except Exception:
        center = [46.555, 14.290]

    m = folium.Map(
        location=center,
        zoom_start=17,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    folium.GeoJson(
        cluster,
        name="Site cluster",
        style_function=lambda _f: {
            "color": "#475569",
            "weight": 1.5,
            "fill": False,
            "dashArray": "4,4",
        },
        interactive=False,
    ).add_to(m)

    folium.GeoJson(
        fcps,
        name="FCP zones",
        style_function=lambda _f: {
            "color": "#0ea5e9",
            "weight": 1,
            "fillColor": "#bae6fd",
            "fillOpacity": 0.10,
        },
        interactive=False,
    ).add_to(m)

    folium.GeoJson(
        feature_collection,
        name="Trench segments",
        style_function=lambda f: _style_for_segment(
            f["properties"].get("verdict", "RED")
        ),
        highlight_function=lambda _f: {"weight": 10, "color": "#1e293b"},
        tooltip=folium.GeoJsonTooltip(
            fields=["segment_id", "fcp_name", "verdict", "length_m"],
            aliases=["Segment", "FCP", "Verdict", "Length (m)"],
            sticky=True,
        ),
    ).add_to(m)

    for pt in photo_points:
        folium.CircleMarker(
            location=[pt["lat"], pt["lon"]],
            radius=3,
            color="#1e293b",
            weight=0.5,
            fillColor="#1e293b",
            fillOpacity=0.7,
        ).add_to(m)

    # Live uploads -- bigger, brighter, on top so the operator sees
    # exactly where their drop landed.
    upload_layer = folium.FeatureGroup(name="Your uploads", show=True)
    for pt in (upload_points or []):
        tooltip = pt.get("tooltip") or "uploaded photo"
        folium.CircleMarker(
            location=[pt["lat"], pt["lon"]],
            radius=7,
            color="#1e293b",
            weight=2,
            fillColor="#f97316",
            fillOpacity=0.95,
            tooltip=tooltip,
        ).add_to(upload_layer)
    upload_layer.add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)

    # One-shot fit_bounds — used by the rail's "Fly to changes" button.
    # The caller pops the session flag before passing this in, so the
    # auto-fit only happens on the rerun triggered by the click.
    if focus_bounds is not None:
        (s_lat, s_lon), (n_lat, n_lon) = focus_bounds
        # Pad a touch so the markers don't sit flush against the edge.
        pad_lat = max((n_lat - s_lat) * 0.25, 0.0005)
        pad_lon = max((n_lon - s_lon) * 0.25, 0.0005)
        m.fit_bounds([
            [s_lat - pad_lat, s_lon - pad_lon],
            [n_lat + pad_lat, n_lon + pad_lon],
        ])

    return m


def segment_id_from_click(
    click: dict[str, Any] | None, known_ids: list[str],
) -> str | None:
    """Pull segment_id out of st_folium's returned click dict.

    streamlit-folium returns several click-related keys; we try them in
    priority order. last_active_drawing carries the full feature for a
    folium.GeoJson click; tooltip is a textual fallback we parse for the
    leading 'Segment <id>' from the GeoJsonTooltip.
    """
    if not click:
        return None
    drawing = click.get("last_active_drawing")
    if drawing:
        props = drawing.get("properties") or {}
        sid = props.get("segment_id")
        if sid and sid in known_ids:
            return sid
    tip = click.get("last_object_clicked_tooltip")
    if isinstance(tip, str):
        # Tooltip text like 'Segment S004 FCP F001 Verdict YELLOW …'. The
        # GeoJsonTooltip emits fields in declared order, so segment_id is
        # first. Pick the first token that matches a known id — avoids
        # accidental matches against FCP names or other tooltip fields.
        known_set = set(known_ids)
        for token in tip.replace("\n", " ").split():
            token = token.strip().strip(":,")
            if token in known_set:
                return token
    return None
