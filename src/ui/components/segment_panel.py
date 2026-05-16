"""Segment detail panel — replaces the rail when a segment is selected.

Renders:
    - Header (segment id, verdict pill, FCP / length / counts)
    - "Why this verdict" reason list
    - Photo grid (2-up) with per-photo check chips
    - GDPR redaction card in place of personal-data photos

Photos flagged `personal_data_visible == "yes"` NEVER show their image
bytes; the GDPR card replaces them and the rest of the per-photo card
(chips, ELA, geo flag) is suppressed since it would reveal frame
content.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


CSS = """
<style>
.panel-card {
    background: var(--c-surface);
    border: 1px solid var(--c-border);
    border-radius: var(--r-md);
    padding: var(--s-4);
    box-shadow: var(--shadow-card);
    margin-bottom: var(--s-3);
}
@media (min-width: 48rem) {
    .panel-card { padding: var(--s-4) var(--s-6); }
}
.panel-title {
    font-size: 16px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: var(--s-3);
    margin-bottom: var(--s-2);
    flex-wrap: wrap;
}
.panel-meta {
    color: var(--c-muted);
    font-size: 12px;
    margin-bottom: var(--s-3);
    line-height: 1.5;
}
.panel-meta b { color: var(--c-text); font-weight: 600; }
.panel-meta code {
    background: var(--c-bg);
    padding: 1px 5px;
    border-radius: var(--r-sm);
    font-size: 11px;
}
.reason-list {
    margin: var(--s-2) 0 0 0;
    padding: 0;
    list-style: none;
}
.reason-list li {
    background: var(--c-bg);
    border-left: 3px solid var(--c-yellow);
    padding: var(--s-2) var(--s-3);
    margin-bottom: var(--s-1);
    border-radius: var(--r-sm);
    font-size: 13px;
    color: var(--c-text-2);
    line-height: 1.45;
}

.check-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    padding: 2px 4px 2px 6px;
    border-radius: var(--r-pill);
    background: var(--c-bg);
    border: 1px solid var(--c-border-soft);
    font-weight: 500;
    margin: 2px 4px 2px 0;
    white-space: nowrap;
}
.check-chip .lbl { color: var(--c-text-2); }
.check-chip .val {
    color: white;
    padding: 0 6px;
    border-radius: var(--r-pill);
    font-weight: 600;
}
.check-chip .val.yes      { background: var(--c-green); }
.check-chip .val.no       { background: var(--c-red); }
.check-chip .val.occluded { background: var(--c-yellow); }
.check-chip .val.na       { background: var(--c-muted); }

.gdpr-card {
    background: var(--c-yellow-soft);
    border: 1.5px solid #f59e0b;
    border-radius: var(--r-sm);
    padding: var(--s-4);
    text-align: center;
    color: #78350f;
    min-height: 160px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: var(--s-1);
}
.gdpr-card .gdpr-icon { font-size: 24px; line-height: 1; }
.gdpr-card .gdpr-title { font-weight: 700; font-size: 13px; }
.gdpr-card .gdpr-body  { font-size: 11px; }
.gdpr-card .gdpr-foot  { font-size: 10px; color: #92400e; }
</style>
"""


PHOTO_CHECK_FIELDS = [
    ("warning_tape_visible", "Warning tape"),
    ("sand_bedding_visible", "Sand bedding"),
    ("side_view_present", "Side view"),
    ("depth_reference_visible", "Depth ref"),
    ("duct_visible", "Duct"),
    ("pipe_ends_sealed", "Pipe ends sealed"),
    # NOTE: `personal_data_visible` intentionally NOT in this list. It is
    # the redaction trigger (see _render_personal_data_redaction), not a
    # check that the reviewer needs to see displayed.
]


# Fallback dir for photos when the live photo tree isn't mounted.
_RESOURCES_PHOTOS_DIR = Path(__file__).resolve().parents[3] / "Resources" / "all"


def _fmt_meters(value: Any) -> str:
    """Render a length-in-meters value tolerantly. NaN / None → '?'."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "?"
    if f != f:  # NaN
        return "?"
    return f"{f:g} m"


def _photo_path_for(
    photo_id: str, manifest: dict, photos_root: Path,
) -> Path | None:
    rel = manifest.get(photo_id)
    if not rel:
        return None
    p = photos_root / rel
    if p.exists():
        return p
    alt = _RESOURCES_PHOTOS_DIR / rel
    if alt.exists():
        return alt
    return None


def _resolve_qc(
    photo_id: str,
    readqc_by_id: dict[str, dict],
    forensics_by_id: dict[str, dict],
    rep_by_cluster: dict[Any, str],
) -> tuple[dict, str | None]:
    """Return (qc_row, duplicate_of_photo_id).

    Direct hit on readqc → use it. Otherwise resolve via the photo's
    phash_cluster_id to its cluster representative and inherit that row.
    The duplicate_of_photo_id is non-None only when we inherited.
    """
    direct = readqc_by_id.get(photo_id)
    if direct:
        return direct, None
    fo = forensics_by_id.get(photo_id) or {}
    cluster_id = fo.get("phash_cluster_id")
    rep_id = rep_by_cluster.get(cluster_id) if cluster_id is not None else None
    if rep_id and rep_id != photo_id:
        return readqc_by_id.get(rep_id, {}), rep_id
    return {}, None


def check_chip_html(field_label: str, value: str) -> str:
    val_class = {
        "yes": "yes", "no": "no",
        "occluded": "occluded", "not_applicable": "na",
    }.get(value, "na")
    return (
        f"<span class='check-chip'>"
        f"<span class='lbl'>{field_label}</span>"
        f"<span class='val {val_class}'>{value}</span>"
        f"</span>"
    )


def _render_personal_data_redaction(
    pid: str, qc: dict, segment_t: float,
) -> None:
    """GDPR notice card in place of a personal-data photo.

    Policy: don't display image bytes for photos flagged
    `personal_data_visible == "yes"`. Show the withholding visibly, route
    the photo to the retake bucket. See DECISIONS.md 2026-05-15.
    """
    st.markdown(
        "<div class='gdpr-card'>"
        "<div class='gdpr-icon'>&#x1F6AB;</div>"
        "<div class='gdpr-title'>Image withheld</div>"
        "<div class='gdpr-body'>Personal data detected "
        "(face / licence plate). Withheld per GDPR / NIS2.</div>"
        "<div class='gdpr-foot'>Routed to contractor retake bucket.</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='font-size:11.5px;color:var(--c-text-2);"
        f"margin-top:6px;'>"
        f"phase <b style='color:var(--c-text);'>{qc.get('phase','?')}</b> · "
        f"pos <b style='color:var(--c-text);'>{segment_t:.0%}</b> · "
        f"id <code style='font-size:10px;background:var(--c-bg);"
        f"padding:1px 4px;border-radius:3px;'>{pid[:10]}…</code></div>",
        unsafe_allow_html=True,
    )


def render(
    seg_id: str,
    verdicts_by_segment: dict[str, dict],
    geomatch_df: pd.DataFrame,
    readqc_by_id: dict[str, dict],
    forensics_by_id: dict[str, dict],
    rep_by_cluster: dict[Any, str],
    manifest: dict,
    photos_root: Path,
) -> None:
    """Render the segment detail panel for the given segment_id."""
    v = verdicts_by_segment.get(seg_id)
    if v is None:
        st.warning(f"Segment {seg_id} not found in verdicts.")
        return

    verdict = v.get("verdict", "?")
    pill_class = verdict.lower() if verdict in ("GREEN", "YELLOW", "RED") else ""

    reasons_raw = v.get("reasons", "")
    reasons = reasons_raw if isinstance(reasons_raw, str) else ""
    reasons_html = ""
    if reasons:
        items = "".join(
            f"<li>{r.strip()}</li>"
            for r in reasons.split(";")
            if r.strip()
        )
        reasons_html = (
            f"<div style='font-weight:600;font-size:12px;"
            f"color:var(--c-text-2);margin-bottom:2px;'>Why this verdict</div>"
            f"<ul class='reason-list'>{items}</ul>"
        )

    st.markdown(
        f"<div class='panel-card'>"
        f"<div class='panel-title'>"
        f"<span>Segment <code style='font-family:ui-monospace,monospace;"
        f"font-size:13px;background:var(--c-bg);padding:2px 6px;"
        f"border-radius:4px'>{seg_id}</code></span>"
        f"<span class='verdict-pill {pill_class}'>{verdict}</span>"
        f"</div>"
        f"<div class='panel-meta'>"
        f"FCP <b>{v.get('fcp_name','?')}</b> · "
        f"length <b>{_fmt_meters(v.get('length_m'))}</b> · "
        f"<b>{v.get('photo_count', 0)}</b> photos snapped · "
        f"<b>{v.get('compliant_photo_count', 0)}</b> compliant"
        f"</div>"
        f"{reasons_html}"
        f"</div>",
        unsafe_allow_html=True,
    )

    seg_photos = geomatch_df[geomatch_df["segment_id"] == seg_id]
    if seg_photos.empty:
        st.markdown(
            "<div class='panel-card' style='text-align:center;"
            "color:var(--c-muted);font-size:13px;'>"
            "No photos snapped to this segment.</div>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        "<div class='section-head'>Photos on this segment</div>",
        unsafe_allow_html=True,
    )

    photos = seg_photos.sort_values("segment_t").to_dict("records")
    for i in range(0, len(photos), 2):
        cols = st.columns(2)
        for col, row in zip(cols, photos[i:i + 2]):
            pid = row["photo_id"]
            with col:
                qc, dup_of = _resolve_qc(
                    pid, readqc_by_id, forensics_by_id, rep_by_cluster,
                )
                if qc and qc.get("personal_data_visible") == "yes":
                    _render_personal_data_redaction(
                        pid, qc, float(row.get("segment_t") or 0.0),
                    )
                    continue

                img_path = _photo_path_for(pid, manifest, photos_root)
                if img_path:
                    st.image(str(img_path), width="stretch")
                else:
                    st.markdown(
                        f"<div style='background:var(--c-bg);"
                        f"border:1px solid var(--c-border);padding:30px;"
                        f"text-align:center;border-radius:var(--r-sm);"
                        f"color:var(--c-text-2);font-size:12px;'>"
                        f"image unavailable<br>"
                        f"<small style='color:var(--c-muted)'>"
                        f"{pid[:24]}…</small></div>",
                        unsafe_allow_html=True,
                    )
                fo = forensics_by_id.get(pid, {})
                if qc:
                    st.markdown(
                        f"<div style='font-size:11.5px;color:var(--c-text-2);"
                        f"margin-top:6px;'>"
                        f"phase <b style='color:var(--c-text);'>"
                        f"{qc.get('phase','?')}</b> · "
                        f"pos <b style='color:var(--c-text);'>"
                        f"{float(row['segment_t']):.0%}</b></div>",
                        unsafe_allow_html=True,
                    )
                    if dup_of:
                        st.markdown(
                            f"<div style='font-size:11px;"
                            f"color:var(--c-text-2);margin-top:2px;'>"
                            f"⟲ duplicate of "
                            f"<code style='background:var(--c-bg);"
                            f"padding:1px 4px;border-radius:3px;"
                            f"font-size:10px;'>{dup_of[:18]}…</code></div>",
                            unsafe_allow_html=True,
                        )
                    chips = "".join(
                        check_chip_html(label, qc.get(field, "?"))
                        for field, label in PHOTO_CHECK_FIELDS
                    )
                    st.markdown(
                        f"<div style='margin-top:6px;line-height:1.9;'>"
                        f"{chips}</div>",
                        unsafe_allow_html=True,
                    )
                    if qc.get("note"):
                        st.markdown(
                            f"<div style='font-size:11px;color:var(--c-muted);"
                            f"font-style:italic;margin-top:6px;"
                            f"line-height:1.4;'>{qc['note']}</div>",
                            unsafe_allow_html=True,
                        )
                if fo.get("ela_flag"):
                    st.markdown(
                        "<div style='font-size:11px;color:var(--c-yellow);"
                        "margin-top:4px;font-weight:500;'>"
                        "⚠ ELA tamper hint</div>",
                        unsafe_allow_html=True,
                    )
                if row.get("latlon_vs_address_flag"):
                    st.markdown(
                        "<div style='font-size:11px;color:var(--c-red);"
                        "margin-top:4px;font-weight:500;'>"
                        "⚠ lat/lon ↔ address mismatch</div>",
                        unsafe_allow_html=True,
                    )
