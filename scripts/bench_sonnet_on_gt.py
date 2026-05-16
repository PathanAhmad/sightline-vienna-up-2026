"""Score the 214 hand-labeled ground-truth photos with Sonnet so the
phase-accuracy benchmark has a fair Sonnet-vs-Haiku comparison.

Production readqc only scores each photo once. The original 723-photo
run used Haiku for all 214 GT photos, so audit_groundtruth.py reports
'Sonnet: 0 test photos'. This script scores the same 214 photos with
Sonnet and appends new rows to readqc.jsonl. classify.py uses
last-write-wins on (photo_id), so the Sonnet rows then replace the
Haiku rows for those 214 photos in the production pipeline too — which
is the correct outcome if Sonnet's accuracy is higher.

Run:
    uv run python -m scripts.bench_sonnet_on_gt
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.paths import DATA_DIR, MANIFEST_DB, READQC_JSONL
from src.readqc import (
    MODELS,
    build_exemplar_prefix,
    cost_of,
    load_env_key,
    _score_with_retry,
)

GT_DIRS = [DATA_DIR / "Resources" / "examples" / "depth",
           DATA_DIR / "Resources" / "examples" / "duct"]
MODEL_KEY = "sonnet"


def sha1_bytes(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    import anthropic

    load_env_key()
    model = MODELS[MODEL_KEY]

    gt_ids: dict[str, Path] = {}
    for d in GT_DIRS:
        for p in sorted(d.iterdir()):
            if p.is_file():
                gt_ids[sha1_bytes(p)] = p
    print(f"[bench] {len(gt_ids)} ground-truth photos")

    # Cross-check against the manifest so we know rel_path exists.
    conn = sqlite3.connect(MANIFEST_DB)
    rows = conn.execute("SELECT photo_id, rel_path FROM photos").fetchall()
    conn.close()
    in_manifest = {pid for pid, _ in rows}

    # Build (photo_id, photo_path) work list.
    todo: list[tuple[str, Path]] = []
    for pid, p in gt_ids.items():
        if pid not in in_manifest:
            print(f"[bench] WARN: GT photo {pid[:10]} not in manifest")
            continue
        todo.append((pid, p))

    # Skip photo_ids already scored by Sonnet (idempotent reruns).
    already_sonnet = set()
    for line in READQC_JSONL.open(encoding="utf-8"):
        r = json.loads(line)
        if "sonnet" in (r.get("model") or "").lower():
            already_sonnet.add(r["photo_id"])
    todo = [(pid, p) for pid, p in todo if pid not in already_sonnet]
    print(f"[bench] {len(todo)} photos to score with {model}")
    if not todo:
        print("[bench] nothing to do")
        return 0

    client = anthropic.Anthropic()
    exemplar_prefix = build_exemplar_prefix()

    state_lock = threading.Lock()
    file_lock = threading.Lock()
    completed = 0
    total_cost = 0.0
    fails = 0
    t0 = time.time()

    # Warm the prompt cache with one sequential call before fanning out.
    first_pid, first_path = todo[0]
    result, usage, err = _score_with_retry(
        client, model, exemplar_prefix, first_path,
    )
    if err is None and result is not None:
        usd = cost_of(model, usage)
        total_cost += usd
        completed += 1
        row = {
            "photo_id": first_pid,
            "model": model,
            "cost_usd": usd,
            **result.model_dump(),
        }
        with READQC_JSONL.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[bench] [   1/{len(todo)}] {result.phase:<14} ${usd:.3f}")
    else:
        fails += 1
        print(f"[bench] [   1/{len(todo)}] FAIL {err}")

    def process(pid: str, path: Path) -> None:
        nonlocal completed, total_cost, fails
        result, usage, err = _score_with_retry(
            client, model, exemplar_prefix, path,
        )
        with state_lock:
            completed += 1
            if err is None and result is not None:
                usd = cost_of(model, usage)
                total_cost += usd
                row = {
                    "photo_id": pid,
                    "model": model,
                    "cost_usd": usd,
                    **result.model_dump(),
                }
                with file_lock:
                    with READQC_JSONL.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                if completed % 25 == 0:
                    print(f"[bench] [{completed:>4}/{len(todo)}] "
                          f"{result.phase:<14} ${total_cost:.2f} "
                          f"rate={completed / (time.time() - t0):.1f}/s")
            else:
                fails += 1
                print(f"[bench] [{completed:>4}/{len(todo)}] FAIL "
                      f"{(err or '')[:60]}")

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(process, pid, p) for pid, p in todo[1:]]
        for _ in as_completed(futs):
            pass

    dt = time.time() - t0
    print(
        f"[bench] done. {completed} scored, {fails} failed, "
        f"${total_cost:.2f}, {dt:.0f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
