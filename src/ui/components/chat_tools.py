"""Read-only data tools the chat agent can call.

Every function here returns a small JSON-serialisable dict. The chat
agent (`chat_agent.py`) wraps each result in <photo_data> tags before
showing it to the model and tells the model in the system prompt to
treat anything inside those tags as DATA, not instructions. This file
also defends the *other* layer: it sanitises every string it returns
so a hostile photo note can't close the envelope or smuggle control
characters through.

Three tools, both views see all three:

    current_batch_summary()     -- what the user uploaded this session
    lookup_uploaded_photo(name) -- one uploaded photo's QC, by filename
    dashboard_overview()        -- pipeline-wide stats from verdicts.csv
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# Hard cap on any text field we pass back to the model. Photo notes are
# capped at 500 chars on the scoring side already (see QCResult.note),
# but addresses / paper-label codes have no upstream cap.
_MAX_FIELD_LEN = 300
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _scrub(value: Any) -> Any:
    """Make one value safe to embed in a model-visible data envelope.

    Strings: strip control chars, escape `<`/`>` so a payload can't
    fake a `</photo_data>` close-tag, then cap length. Non-strings
    pass through unchanged (booleans, numbers, None).
    """
    if not isinstance(value, str):
        return value
    cleaned = _CONTROL_CHARS.sub("", value)
    cleaned = cleaned.replace("<", "&lt;").replace(">", "&gt;")
    if len(cleaned) > _MAX_FIELD_LEN:
        cleaned = cleaned[:_MAX_FIELD_LEN] + "…"
    return cleaned


def _scrub_dict(d: dict[str, Any]) -> dict[str, Any]:
    return {k: _scrub(v) for k, v in d.items()}


# ---- Tool 1: current batch summary --------------------------------------

def current_batch_summary() -> dict[str, Any]:
    """Aggregate over the session's uploaded photos.

    Reads `st.session_state["batch_score_cache"]` -- the same dict the
    upload view fills as each photo is scored. Returns counts by verdict,
    total spend, and a list of filenames so the model can offer
    follow-ups like "tell me about photo X".
    """
    from src.ui.components.live_score import verdict_for_photo

    cache: dict = st.session_state.get("batch_score_cache", {})
    if not cache:
        return {
            "status": "empty",
            "message": (
                "No photos have been uploaded in this session yet. "
                "Ask the user to drop photos on the upload page first."
            ),
        }

    counts: dict[str, int] = {}
    names: list[str] = []
    total_cost = 0.0
    n_errors = 0
    for row in cache.values():
        if row.get("err"):
            n_errors += 1
            continue
        qc = row.get("qc")
        if qc is None:
            continue
        label, _ = verdict_for_photo(qc)
        counts[label] = counts.get(label, 0) + 1
        total_cost += float(row.get("cost", 0.0))
        names.append(_scrub(row.get("name", "")))

    return {
        "status": "ok",
        "n_photos_scored": len(names),
        "n_errors": n_errors,
        "verdict_counts": counts,
        "total_cost_usd": round(total_cost, 4),
        "photo_filenames": names,
    }


# ---- Tool 2: one uploaded photo by filename -----------------------------

def lookup_uploaded_photo(name: str) -> dict[str, Any]:
    """Look one uploaded photo up by filename (exact match, case-insensitive).

    Returns the QC fields the model needs to explain *why* a photo
    passed, warned, or failed. Image bytes are never returned -- the
    model only sees the structured verdict.
    """
    from src.ui.components.live_score import verdict_for_photo

    if not isinstance(name, str) or not name.strip():
        return {"status": "error", "message": "name must be a non-empty string"}

    target = name.strip().lower()
    cache: dict = st.session_state.get("batch_score_cache", {})
    match = None
    for (fname, _size), row in cache.items():
        if fname.lower() == target:
            match = row
            break

    if match is None:
        available = [_scrub(k[0]) for k in cache.keys()]
        return {
            "status": "not_found",
            "message": f"No uploaded photo named '{_scrub(name)}'.",
            "available_filenames": available,
        }

    if match.get("err"):
        return {
            "status": "scoring_error",
            "name": _scrub(match.get("name", "")),
            "error": _scrub(match["err"]),
        }

    qc = match.get("qc")
    if qc is None:
        return {"status": "pending", "message": "Scoring not yet complete."}

    label, _ = verdict_for_photo(qc)
    # QCResult is a pydantic model -- dump to a plain dict, then scrub.
    qc_dict = qc.model_dump() if hasattr(qc, "model_dump") else dict(qc)

    return {
        "status": "ok",
        "name": _scrub(match.get("name", "")),
        "verdict": label,
        "cost_usd": round(float(match.get("cost", 0.0)), 4),
        "qc": _scrub_dict(qc_dict),
    }


# ---- Tool 3: dashboard / pipeline overview ------------------------------

# Match the resolve_paths() logic in app.py without importing it (avoids a
# circular import: app.py imports from src.ui, and chat lives under src.ui).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIVE_VERDICTS = _REPO_ROOT / "data" / "processed" / "verdicts.csv"
_FIXTURE_VERDICTS = _REPO_ROOT / "demo_fixtures" / "verdicts.csv"


@st.cache_data(show_spinner=False)
def _load_verdicts_for_chat(path_str: str) -> pd.DataFrame:
    """Cached read of verdicts.csv -- shared across chat turns."""
    df = pd.read_csv(path_str, dtype=str, keep_default_na=False)
    df["length_m"] = pd.to_numeric(df["length_m"], errors="coerce")
    df["photo_count"] = pd.to_numeric(
        df["photo_count"], errors="coerce"
    ).fillna(0).astype(int)
    return df


def dashboard_overview() -> dict[str, Any]:
    """Pipeline-wide stats from verdicts.csv.

    Prefers `data/processed/verdicts.csv` (live pipeline output); falls
    back to `demo_fixtures/verdicts.csv`. Returns counts, %-compliant,
    and the top 5 worst RED + top 5 YELLOW segments by length so the
    model can answer "what's the worst?" in one round-trip.
    """
    path = _LIVE_VERDICTS if _LIVE_VERDICTS.exists() else _FIXTURE_VERDICTS
    if not path.exists():
        return {
            "status": "no_data",
            "message": "No pipeline output available (neither live nor fixtures).",
        }

    df = _load_verdicts_for_chat(str(path))
    n = len(df)
    counts = df["verdict"].value_counts().to_dict()
    n_green = int(counts.get("GREEN", 0))
    n_yellow = int(counts.get("YELLOW", 0))
    n_red = int(counts.get("RED", 0))

    def _top(verdict: str, k: int = 5) -> list[dict]:
        rows = (
            df[df["verdict"] == verdict]
            .sort_values("length_m", ascending=False)
            .head(k)
        )
        return [
            {
                "segment_id": _scrub(r["segment_id"]),
                "fcp_name": _scrub(r.get("fcp_name", "")),
                "length_m": float(r["length_m"]) if pd.notna(r["length_m"]) else None,
                "photo_count": int(r["photo_count"]),
                "reasons": _scrub(r.get("reasons", "")),
            }
            for r in rows.to_dict("records")
        ]

    return {
        "status": "ok",
        "source": "live" if path == _LIVE_VERDICTS else "fixtures",
        "n_segments": n,
        "verdict_counts": {"GREEN": n_green, "YELLOW": n_yellow, "RED": n_red},
        "pct_compliant": round((n_green / n * 100) if n else 0.0, 1),
        "worst_red": _top("RED"),
        "worst_yellow": _top("YELLOW"),
    }


# ---- Anthropic tool schemas ---------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "current_batch_summary",
        "description": (
            "Get a summary of the photos the user has uploaded in THIS "
            "browser session for live QC scoring. Returns verdict counts "
            "(PASS / WARN / FAIL / WITHHELD / DROP), total Claude API "
            "spend so far, and the list of filenames. Use this when the "
            "user asks about 'my uploads', 'the batch I submitted', or "
            "'what did I just score'."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "lookup_uploaded_photo",
        "description": (
            "Look up one uploaded photo by filename. Returns the full "
            "per-photo QC: verdict, the 7 compliance checks (warning "
            "tape, sand bedding, side view, depth reference, duct, pipe "
            "ends sealed, personal data), the burned-in overlay fields "
            "(date, address, lat/lon, paper-label code), and the scorer's "
            "note. Use this when the user asks 'why did X fail?' or "
            "'tell me about photo Y'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The photo filename, e.g. 'IMG-20250612-WA0017.jpg'.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "dashboard_overview",
        "description": (
            "Pipeline-wide stats from the reviewer dashboard's verdicts "
            "table -- one row per trench segment. Returns total segment "
            "count, GREEN/YELLOW/RED counts, % compliant, and the 5 "
            "worst RED + 5 worst YELLOW segments by length (with their "
            "reason strings). Use this when the user asks about overall "
            "compliance, 'which segments are failing', or wants a "
            "project-level picture rather than per-photo."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


TOOL_FUNCTIONS = {
    "current_batch_summary": current_batch_summary,
    "lookup_uploaded_photo": lookup_uploaded_photo,
    "dashboard_overview": dashboard_overview,
}
