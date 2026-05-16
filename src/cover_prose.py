"""Generate human-readable cover prose for the deficiency PDF.

Called once by the pipeline (`src/report.py`) and baked to a JSON file
the PDF reader picks up at download time. Keeps live Claude calls off
the dashboard render path (per CLAUDE.md demo-day rule) while still
letting the cover prose adapt naturally to whatever shape the run took.

Public surface:
    PROSE_FIELDS = ("intro", "situation", "closing")
    generate_cover_prose(verdicts, intake) -> dict | None
    write_cover_prose(verdicts, intake, out_path) -> bool
    load_cover_prose(*candidates) -> dict | None

If the API call fails (no key, network down, malformed response),
returns None — the PDF then falls back to templated prose so the
download never breaks.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import anthropic

from src.pdf_report import PhotoIntake


PROSE_FIELDS: tuple[str, ...] = ("intro", "situation", "closing")

_MODEL = "claude-sonnet-4-6"

_PROMPT_TEMPLATE = """You are writing the opening paragraphs of a printed \
PDF deficiency report for a fiber-trench construction project. The reader \
is a construction foreman who reads this on paper, then takes it to the \
site to re-shoot missing photos.

Write THREE short paragraphs in plain English. Each 2-4 sentences. \
No engineering jargon. Address the reader directly ("you", "the crew"). \
Don't repeat numbers across paragraphs.

PARAGRAPH "intro": What this report is and how to use it. Two or three \
sentences. Do not include numbers — those come later.

PARAGRAPH "situation": What the data shows for THIS run. Be specific \
about the shape of the result (everyone failing for the same reason vs. \
a mix vs. everyone passing, etc.) and end with what the foreman should \
do next. Use the verdict numbers and the top reasons to ground the prose.

PARAGRAPH "closing": One or two sentences orienting the reader to how the \
rest of the document is organized: sections grouped by FCP route, "no \
photos yet" sections collapsed into a single block per route, full cards \
for sections with unique issues, appendix at the back with passing \
sections and the eight checks.

Use only the data below. Do not invent extra context.

DATA:
{stats_json}

Return ONLY a single JSON object with keys "intro", "situation", \
"closing". No code fences, no commentary."""


def _build_stats(
    verdicts: list[dict],
    intake: PhotoIntake | None,
) -> dict[str, Any]:
    """Compact stats summary that Claude reads — verdict counts, top
    reasons, and the per-photo intake roll-up. Top 6 reasons is enough
    to capture the shape without leaking 2,983 rows of identical text."""
    n_total = len(verdicts)
    counts = Counter(str(r.get("verdict") or "").upper() for r in verdicts)
    reason_counts: Counter[str] = Counter()
    for r in verdicts:
        if str(r.get("verdict") or "").upper() == "GREEN":
            continue
        reason_counts[str(r.get("reasons") or "")] += 1
    top_reasons = [
        {"count": c, "reason": r}
        for r, c in reason_counts.most_common(6)
    ]
    return {
        "total_sections": n_total,
        "green": counts.get("GREEN", 0),
        "yellow": counts.get("YELLOW", 0),
        "red": counts.get("RED", 0),
        "top_reasons_for_non_green_sections": top_reasons,
        "photo_intake": (asdict(intake) if intake is not None else None),
    }


def _strip_code_fence(text: str) -> str:
    """Claude sometimes wraps JSON in a ```json … ``` fence despite the
    prompt asking it not to. Strip it so json.loads doesn't choke."""
    t = text.strip()
    if not t.startswith("```"):
        return t
    # Drop the opening fence (and optional language tag).
    first_newline = t.find("\n")
    if first_newline == -1:
        return t
    t = t[first_newline + 1:]
    # Drop the closing fence.
    closing = t.rfind("```")
    if closing != -1:
        t = t[:closing]
    return t.strip()


def _load_env_key() -> None:
    """Same pattern src/readqc.py uses — pick up the key from .env if
    the process didn't get it from the shell."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = (
                line.split("=", 1)[1].strip().strip('"').strip("'")
            )
            return


def generate_cover_prose(
    verdicts: list[dict],
    intake: PhotoIntake | None,
) -> dict[str, str] | None:
    """Ask Claude to write the three cover paragraphs. Returns None if
    the call can't complete or the response isn't usable — the PDF
    falls back to templated prose in that case."""
    _load_env_key()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    stats = _build_stats(verdicts, intake)
    prompt = _PROMPT_TEMPLATE.format(stats_json=json.dumps(stats, indent=2))
    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _strip_code_fence(msg.content[0].text)
        parsed = json.loads(text)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    if not all(k in parsed and isinstance(parsed[k], str) for k in PROSE_FIELDS):
        return None
    return {k: parsed[k].strip() for k in PROSE_FIELDS}


def write_cover_prose(
    verdicts: list[dict],
    intake: PhotoIntake | None,
    out_path: Path,
) -> bool:
    """Generate + write to disk. Returns True on success, False if the
    Claude call failed (caller can log and continue — the PDF still
    works without baked prose)."""
    prose = generate_cover_prose(verdicts, intake)
    if prose is None:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(prose, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return True


def load_cover_prose(*candidates: Path) -> dict[str, str] | None:
    """Read the first candidate file that exists and parses. Used by
    the PDF builder to pick up the baked artifact at download time."""
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and all(
            isinstance(data.get(k), str) for k in PROSE_FIELDS
        ):
            return {k: data[k] for k in PROSE_FIELDS}
    return None
