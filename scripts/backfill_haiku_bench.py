"""Backfill Haiku's GT-bench timing without re-scoring 214 photos.

Haiku has already scored the 214 hand-labeled depth/duct photos as part
of the production readqc batch -- so we can derive its bench timing
without spending another ~$0.75 and 5 minutes.

We extract:
    bench_cost_usd = sum(cost_usd for rows where photo_id in GT and model=haiku)
                     -- exact, per-row from readqc.jsonl
    bench_seconds  = (stage_elapsed_s / stage_n_photos) * n_gt_haiku
                     -- proportional from the production Haiku stage in
                     audit.jsonl. Approximate: same 8-worker pool, same
                     warm exemplar cache, so per-photo wall time is a
                     fair extrapolation.
    bench_n        = count of GT photos Haiku actually scored

If the production Haiku stage is still running (no stage_end yet), the
script falls back to (now - stage_start_ts) / current_haiku_row_count.

Writes data/processed/bench_timings.json's "haiku" entry. Idempotent;
overwrites only the haiku key.

Run:
    uv run python -m scripts.backfill_haiku_bench
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from src.paths import DATA_DIR, PROCESSED_DIR

GT_DIRS = [DATA_DIR / "Resources" / "examples" / "depth",
           DATA_DIR / "Resources" / "examples" / "duct"]
AUDIT_JSONL = PROCESSED_DIR / "audit.jsonl"
READQC_JSONL = PROCESSED_DIR / "readqc.jsonl"
BENCH_TIMINGS = PROCESSED_DIR / "bench_timings.json"

HAIKU_MODEL_ID = "claude-haiku-4-5"


def sha1_bytes(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _gt_ids() -> set[str]:
    out: set[str] = set()
    for d in GT_DIRS:
        for p in sorted(d.iterdir()):
            if p.is_file():
                out.add(sha1_bytes(p))
    return out


def _haiku_stage_seconds_and_n() -> tuple[float, int]:
    """(elapsed_s, n_photos) for the most recent Haiku readqc stage.

    Prefers a clean stage_start→stage_end pair. If the stage is still
    running, returns elapsed-so-far and counts current Haiku rows in
    readqc.jsonl. Returns (0.0, 0) if no Haiku stage is found at all.
    """
    if not AUDIT_JSONL.exists():
        return 0.0, 0
    last_haiku_start_ts: str | None = None
    last_haiku_end: dict | None = None
    with AUDIT_JSONL.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("stage") != "readqc":
                continue
            if e.get("event") == "stage_start":
                cfg = e.get("config") or {}
                if "haiku" in str(cfg.get("model") or ""):
                    last_haiku_start_ts = e.get("ts")
                    last_haiku_end = None  # reset on new start
                else:
                    last_haiku_start_ts = None
            elif e.get("event") == "stage_end" and last_haiku_start_ts:
                last_haiku_end = e

    if last_haiku_end is not None:
        counters = last_haiku_end.get("counters") or {}
        elapsed = float(counters.get("elapsed_s") or 0.0)
        # n_photos isn't in the end event; recover by counting Haiku rows.
        return elapsed, _count_haiku_rows()

    if last_haiku_start_ts is None:
        return 0.0, 0

    # Stage still running. Compute elapsed from start_ts -> now.
    started = datetime.fromisoformat(last_haiku_start_ts).timestamp()
    elapsed = max(0.0, time.time() - started)
    return elapsed, _count_haiku_rows()


def _count_haiku_rows() -> int:
    n = 0
    if not READQC_JSONL.exists():
        return 0
    with READQC_JSONL.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("model") == HAIKU_MODEL_ID:
                n += 1
    return n


def _haiku_gt_cost_and_count(gt_ids: set[str]) -> tuple[float, int]:
    cost = 0.0
    n = 0
    if not READQC_JSONL.exists():
        return 0.0, 0
    with READQC_JSONL.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("model") != HAIKU_MODEL_ID:
                continue
            if r.get("photo_id") in gt_ids:
                cost += float(r.get("cost_usd") or 0.0)
                n += 1
    return cost, n


def main() -> int:
    gt_ids = _gt_ids()
    print(f"[backfill] {len(gt_ids)} ground-truth photo_ids")

    bench_cost, bench_n = _haiku_gt_cost_and_count(gt_ids)
    stage_elapsed_s, stage_n = _haiku_stage_seconds_and_n()
    if stage_n == 0:
        print("[backfill] no Haiku rows in readqc.jsonl; nothing to do.")
        return 1
    per_photo_s = stage_elapsed_s / stage_n
    bench_seconds = per_photo_s * bench_n
    stage_state = ("running" if (time.time() - _stage_start_age()) > 0
                   else "completed")
    print(f"[backfill] haiku production stage: {stage_n} photos, "
          f"{stage_elapsed_s:.0f}s ({stage_state}) → "
          f"{per_photo_s:.2f}s/photo")
    print(f"[backfill] GT subset: bench_n={bench_n}, "
          f"bench_seconds={bench_seconds:.0f}, bench_cost=${bench_cost:.3f}")

    timings: dict = {}
    if BENCH_TIMINGS.exists():
        try:
            timings = json.loads(BENCH_TIMINGS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            timings = {}
    timings["haiku"] = {
        "model": HAIKU_MODEL_ID,
        "seconds": bench_seconds,
        "cost_usd": bench_cost,
        "n": bench_n,
        "source": "backfilled_from_production",
        "last_run_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    BENCH_TIMINGS.parent.mkdir(parents=True, exist_ok=True)
    BENCH_TIMINGS.write_text(
        json.dumps(timings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[backfill] wrote {BENCH_TIMINGS}")
    return 0


def _stage_start_age() -> float:
    # Used only as a sentinel for the running/completed print; returns
    # an arbitrary positive value if we couldn't tell. Keep simple.
    return 1.0


if __name__ == "__main__":
    sys.exit(main())
