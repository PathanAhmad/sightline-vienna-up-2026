"""Score the 214 hand-labeled ground-truth photos with one model so the
phase-accuracy benchmark has a fair apples-to-apples comparison.

Production readqc only scores each photo once. The original 723-photo
run used Haiku for all 214 GT photos, so without re-scoring,
audit_groundtruth.py reports 'Sonnet: 0 test photos'.

This script runs each model on the SAME 214 GT photos and writes:
    data/processed/readqc_bench.jsonl   (per-photo phase predictions)
    data/processed/bench_timings.json   (per-model elapsed_s + cost_usd)

The main pipeline (classify.py) reads readqc.jsonl only — bench output
stays out of production. audit_groundtruth.py reads BOTH files and
attributes bench rows to their model when computing accuracy.

Run:
    uv run python -m scripts.bench_sonnet_on_gt --model sonnet
    uv run python -m scripts.bench_sonnet_on_gt --model haiku
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.paths import DATA_DIR, MANIFEST_DB, PROCESSED_DIR
from src.readqc import (
    MODELS,
    build_exemplar_prefix,
    cost_of,
    load_env_key,
    _score_with_retry,
)

GT_DIRS = [DATA_DIR / "Resources" / "examples" / "depth",
           DATA_DIR / "Resources" / "examples" / "duct"]
BENCH_JSONL = PROCESSED_DIR / "readqc_bench.jsonl"
BENCH_TIMINGS = PROCESSED_DIR / "bench_timings.json"


def sha1_bytes(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_timings() -> dict:
    if BENCH_TIMINGS.exists():
        try:
            return json.loads(BENCH_TIMINGS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_timings(d: dict) -> None:
    BENCH_TIMINGS.parent.mkdir(parents=True, exist_ok=True)
    BENCH_TIMINGS.write_text(
        json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    import anthropic

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--model", choices=list(MODELS.keys()), required=True,
        help="Which model variant to score the GT photos with.",
    )
    args = ap.parse_args()
    model_key = args.model

    load_env_key()
    model = MODELS[model_key]

    gt_ids: dict[str, Path] = {}
    for d in GT_DIRS:
        for p in sorted(d.iterdir()):
            if p.is_file():
                gt_ids[sha1_bytes(p)] = p
    print(f"[bench] {len(gt_ids)} ground-truth photos · model={model}")

    # Cross-check against the manifest so we know each rel_path is real.
    conn = sqlite3.connect(MANIFEST_DB)
    rows = conn.execute("SELECT photo_id FROM photos").fetchall()
    conn.close()
    in_manifest = {pid for (pid,) in rows}

    todo: list[tuple[str, Path]] = []
    for pid, p in gt_ids.items():
        if pid not in in_manifest:
            print(f"[bench] WARN: GT photo {pid[:10]} not in manifest", file=sys.stderr)
            continue
        todo.append((pid, p))

    # Idempotent reruns: skip photo_ids that this model already scored in
    # the bench file.
    already_done: set[str] = set()
    if BENCH_JSONL.exists():
        with BENCH_JSONL.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("model") == model:
                    already_done.add(r["photo_id"])
    todo = [(pid, p) for pid, p in todo if pid not in already_done]
    print(f"[bench] {len(todo)} photos to score (skipped {len(already_done)} already done)")
    if not todo:
        return 0

    client = anthropic.Anthropic()
    exemplar_prefix = build_exemplar_prefix()

    state_lock = threading.Lock()
    file_lock = threading.Lock()
    completed = 0
    total_cost = 0.0
    fails = 0
    t0 = time.time()

    def _write(pid: str, result, usd: float) -> None:
        row = {
            "photo_id": pid,
            "model": model,
            "cost_usd": usd,
            **result.model_dump(),
        }
        with file_lock:
            with BENCH_JSONL.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Warm the prompt cache with one sequential call first so the pool's
    # 8 concurrent calls hit cache_read, not 8x cache_write.
    first_pid, first_path = todo[0]
    result, usage, err = _score_with_retry(
        client, model, exemplar_prefix, first_path,
    )
    if err is None and result is not None:
        usd = cost_of(model, usage)
        total_cost += usd
        completed += 1
        _write(first_pid, result, usd)
        print(f"[bench] [   1/{len(todo)}] {result.phase:<14} ${usd:.3f}")
    else:
        fails += 1
        print(f"[bench] [   1/{len(todo)}] FAIL {(err or '')[:80]}")

    def process(pid: str, path: Path) -> None:
        nonlocal completed, total_cost, fails
        result, usage, err = _score_with_retry(
            client, model, exemplar_prefix, path,
        )
        with state_lock:
            completed += 1
            done = completed
        if err is None and result is not None:
            usd = cost_of(model, usage)
            with state_lock:
                total_cost += usd
            _write(pid, result, usd)
            if done % 25 == 0:
                print(f"[bench] [{done:>4}/{len(todo)}] "
                      f"{result.phase:<14} ${total_cost:.2f} "
                      f"rate={done / (time.time() - t0):.1f}/s")
        else:
            with state_lock:
                fails += 1
            print(f"[bench] [{done:>4}/{len(todo)}] FAIL "
                  f"{(err or '')[:60]}")

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(process, pid, p) for pid, p in todo[1:]]
        for _ in as_completed(futs):
            pass

    dt = time.time() - t0
    print(
        f"[bench] {model_key} done. {completed} scored, {fails} failed, "
        f"${total_cost:.2f}, {dt:.1f}s"
    )

    # Append timing to the per-model summary file. Reruns sum (so partial
    # bench + resume produces the right total).
    timings = _load_timings()
    short = "sonnet" if "sonnet" in model else "haiku" if "haiku" in model else model
    prev = timings.get(short, {"seconds": 0.0, "cost_usd": 0.0, "n": 0})
    timings[short] = {
        "model": model,
        "seconds": prev["seconds"] + dt,
        "cost_usd": prev["cost_usd"] + total_cost,
        "n": prev["n"] + completed,
        "failures": prev.get("failures", 0) + fails,
        "last_run_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _save_timings(timings)
    print(f"[bench] wrote timings → {BENCH_TIMINGS.relative_to(BENCH_TIMINGS.parent.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
