"""Per-photo scoring helpers — one Claude vision call, one verdict card.

Helpers for the upload view (`src/ui/upload_view.py`). Public surface:

    score_uploaded_photo(file_bytes, suffix)  -> (qc, cost_usd, err)
    verdict_for_photo(qc)                     -> (label, pill_class)
    render_result_card(qc, image_bytes, cost) -> renders into the
        current Streamlit block

Caches the 4-exemplar prefix once per Streamlit process (cheap reads
on every subsequent call). Address and lat/lon are NDA-redacted at
display time even though the underlying values flow through to the
pipeline.

History: this module previously also rendered a sidebar widget
(`render()` for the dashboard's "Try it live" sidebar). That widget
was retired on 2026-05-16 when the upload flow moved to its own
top-level surface (`?view=upload`). The helpers stayed; the sidebar
render and its file-uploader CSS were dropped.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import streamlit as st

from src.ui.components.segment_panel import (
    PHOTO_CHECK_FIELDS,
    check_chip_html,
)


_LIVE_MODEL_KEY = "sonnet"  # claude-sonnet-4-6
_EXEMPLARS_FALLBACK = Path(__file__).resolve().parents[3] / "Resources" / "examples"


def _resolved_exemplars() -> list[tuple[str, Path, str]]:
    """The 4 readqc exemplars, with a fallback path for boxes that don't
    have the gitignored `data/Beispiele/` tree (e.g. a fresh checkout)."""
    from src.readqc import EXEMPLARS
    out: list[tuple[str, Path, str]] = []
    for name, path, caption in EXEMPLARS:
        if path.exists():
            out.append((name, path, caption))
        else:
            alt = _EXEMPLARS_FALLBACK / path.name
            if alt.exists():
                out.append((name, alt, caption))
    return out


@st.cache_resource(show_spinner=False)
def _live_score_prefix() -> list[dict]:
    """Build the cached 4-exemplar prefix once per Streamlit process."""
    from src.readqc import b64
    exemplars = _resolved_exemplars()
    if not exemplars:
        return []
    blocks: list[dict] = []
    for i, (name, path, caption) in enumerate(exemplars):
        media, data = b64(path)
        blocks.append({
            "type": "text",
            "text": f"Exemplar {i + 1} -- {name}: {caption}",
        })
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media,
                "data": data,
            },
        })
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _anthropic_client():
    """Build a fresh Anthropic client per call (NOT cached — caching with
    @st.cache_resource bit us if the first call ever happened before
    .env existed)."""
    from src.readqc import load_env_key
    load_env_key()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    return anthropic.Anthropic()


def score_uploaded_photo(
    file_bytes: bytes, suffix: str,
) -> tuple[Any, float, str | None]:
    """Run one Claude vision call on the uploaded bytes, with retries
    on transient upstream errors."""
    from src.readqc import MODELS, _score_with_retry, cost_of
    client = _anthropic_client()
    if client is None:
        return None, 0.0, (
            "ANTHROPIC_API_KEY not set. Add it to .env or paste it below."
        )
    prefix = _live_score_prefix()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)
    try:
        result, usage, err = _score_with_retry(
            client, MODELS[_LIVE_MODEL_KEY], prefix, tmp_path,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    if err:
        return None, 0.0, err
    return result, cost_of(MODELS[_LIVE_MODEL_KEY], usage), None


def verdict_for_photo(qc: Any) -> tuple[str, str]:
    """Per-photo verdict label (the pipeline verdict is per-segment;
    this is 'would this photo be compliant on its own?').

    Used by the live-score sidebar AND the batch upload page.
    """
    relevance = getattr(qc, "relevance", None)
    if relevance != "scorable":
        return "DROP", "muted"
    if getattr(qc, "personal_data_visible", "no") == "yes":
        return "WITHHELD", "muted"
    failing = [
        f for f, _ in PHOTO_CHECK_FIELDS
        if getattr(qc, f, "no") == "no"
    ]
    if not failing:
        return "PASS", "green"
    if len(failing) <= 2:
        return "WARN", "yellow"
    return "FAIL", "red"


def render_result_card(qc: Any, image_bytes: bytes, cost_usd: float) -> None:
    """Render the result card for one scored photo."""
    verdict_label, pill_class = verdict_for_photo(qc)
    st.markdown(
        f"<div style='margin-top:8px;'>"
        f"<span style='font-size:10px;color:var(--c-muted);font-weight:600;"
        f"letter-spacing:0.08em;text-transform:uppercase;margin-right:8px;'>"
        f"Verdict</span>"
        f"<span class='verdict-pill {pill_class} large'>"
        f"{verdict_label}</span></div>",
        unsafe_allow_html=True,
    )

    if getattr(qc, "personal_data_visible", "no") == "yes":
        st.markdown(
            "<div class='gdpr-card' style='margin-top:8px;min-height:120px;'>"
            "<div class='gdpr-icon'>&#x1F6AB;</div>"
            "<div class='gdpr-title'>Image withheld</div>"
            "<div class='gdpr-body'>Personal data detected — "
            "withheld per GDPR / NIS2.</div></div>",
            unsafe_allow_html=True,
        )
    else:
        st.image(image_bytes, width="stretch")

    st.markdown(
        f"<div style='font-size:11.5px;color:var(--c-text-2);"
        f"margin-top:6px;'>"
        f"relevance <b style='color:var(--c-text);'>"
        f"{getattr(qc, 'relevance', '?')}</b> · "
        f"phase <b style='color:var(--c-text);'>"
        f"{getattr(qc, 'phase', '?')}</b> · "
        f"cost <b style='color:var(--c-text);'>${cost_usd:.4f}</b></div>",
        unsafe_allow_html=True,
    )

    chips = "".join(
        check_chip_html(label, getattr(qc, field, "?"))
        for field, label in PHOTO_CHECK_FIELDS
    )
    st.markdown(
        f"<div style='margin-top:8px;line-height:1.9;'>{chips}</div>",
        unsafe_allow_html=True,
    )

    # Overlay fields — address + lat/lon are NDA-redacted on screen.
    overlay_rows = []
    if getattr(qc, "overlay_date", ""):
        overlay_rows.append(("Date", qc.overlay_date))
    if getattr(qc, "overlay_address", ""):
        addr = qc.overlay_address
        redacted = (addr[:3] + "…") if len(addr) > 3 else "…"
        overlay_rows.append(("Address", f"{redacted}  (NDA-redacted)"))
    if getattr(qc, "overlay_latlon", None):
        overlay_rows.append(("Lat/Lon", "✓ present  (NDA-redacted)"))
    if getattr(qc, "paper_label_code", None):
        overlay_rows.append(("Paper label", qc.paper_label_code))
    if overlay_rows:
        st.markdown(
            "<div class='section-head' style='margin:12px 0 4px 0;'>"
            "Overlay fields</div>",
            unsafe_allow_html=True,
        )
        rows_html = "".join(
            f"<div style='font-size:11.5px;margin-bottom:3px;'>"
            f"<span style='color:var(--c-muted);'>{k}:</span> "
            f"<code style='font-size:11px;background:var(--c-bg);"
            f"padding:1px 5px;border-radius:3px;'>{v}</code></div>"
            for k, v in overlay_rows
        )
        st.markdown(rows_html, unsafe_allow_html=True)

    note = getattr(qc, "note", "") or ""
    if note:
        st.markdown(
            f"<div style='margin-top:10px;font-size:11.5px;"
            f"color:var(--c-muted);font-style:italic;line-height:1.4;'>"
            f"{note}</div>",
            unsafe_allow_html=True,
        )


