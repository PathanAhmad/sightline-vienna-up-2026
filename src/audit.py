"""Append-only audit log for the pipeline.

One JSON line per noteworthy event. Used to answer "why did photo X
disappear between stages?" after the fact -- stdout-only logging is
gone the moment the terminal closes, and during a long batch you may
miss the line that mattered.

Use:
    from src.audit import log_event, audit_reset, AUDIT_JSONL

    audit_reset()                                  # at the top of ingest only
    log_event("readqc", "api_fail", photo_id=pid, error_class="RateLimit")
    log_event("classify", "drop_no_qc", photo_id=pid)

Conventions:
    - `stage` matches the module name (ingest / forensics / readqc / geomatch / classify).
    - `event` is a short snake_case verb-or-noun naming the situation.
    - `photo_id` (when present) ALWAYS goes through this kwarg, so we
      can grep the file: `grep '"photo_id": "abc..."' audit.jsonl`.
    - Don't write addresses, lat/lon, or full file paths -- the audit log
      is shareable; addresses are NDA. Use the photo_id as the key.

The audit JSONL grows append-only across stages. `audit_reset()` is
called only by ingest (the first stage). If a single stage is re-run,
its old entries stay (with their old timestamps); the new lines are
appended below. The timestamp on each line tells which run it came from.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.paths import PROCESSED_DIR, ensure_dirs

AUDIT_JSONL = PROCESSED_DIR / "audit.jsonl"


def audit_reset() -> None:
    """Truncate the audit log. Only ingest should call this."""
    ensure_dirs()
    AUDIT_JSONL.write_text("", encoding="utf-8")


def log_event(stage: str, event: str, **fields: Any) -> None:
    """Append one event line. Cheap; safe to call in tight loops."""
    ensure_dirs()
    row: dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "stage": stage,
        "event": event,
    }
    row.update(fields)
    with AUDIT_JSONL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def log_stage_start(stage: str, **config: Any) -> None:
    """Banner event. Captures the configuration values a stage was run with
    so we can reproduce or compare runs later."""
    log_event(stage, "stage_start", config=config)


def log_stage_end(stage: str, **counters: Any) -> None:
    """Banner event with summary counts."""
    log_event(stage, "stage_end", counters=counters)
