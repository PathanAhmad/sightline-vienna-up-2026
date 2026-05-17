"""Score the 214 hand-labeled ground-truth photos with an OpenAI vision
model so we can compare against Sonnet/Haiku on the same task.

Mirrors scripts.bench_sonnet_on_gt: same exemplar prefix + system prompt
imported from src.readqc, same readqc_bench.jsonl output, same audit
pipeline. Idempotent (skips already-scored photo_ids per model).

Run:
    uv run python -m scripts.bench_openai_on_gt --model gpt-4o
    uv run python -m scripts.bench_openai_on_gt --model gpt-4o-mini
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.paths import DATA_DIR, MANIFEST_DB, PROCESSED_DIR, REPO_ROOT
from src.readqc import EXEMPLARS, QCResult, SYSTEM_INSTRUCTIONS

GT_DIRS = [DATA_DIR / "Resources" / "examples" / "depth",
           DATA_DIR / "Resources" / "examples" / "duct"]
BENCH_JSONL = PROCESSED_DIR / "readqc_bench.jsonl"
BENCH_TIMINGS = PROCESSED_DIR / "bench_timings.json"

# Per-Mtok pricing in USD. Cached input is OpenAI's automatic prompt-cache
# discount; applied automatically when the same prefix is re-seen within
# the cache TTL (~5-60 min as of late 2025).
PRICING = {
    "gpt-4o":      {"in": 2.50, "cached_in": 1.25, "out": 10.00},
    "gpt-4o-mini": {"in": 0.15, "cached_in": 0.075, "out":  0.60},
    "gpt-4.1":     {"in": 2.00, "cached_in": 0.50, "out":  8.00},
    "gpt-4.1-mini":{"in": 0.40, "cached_in": 0.10, "out":  1.60},
    # gpt-5 family pricing (best estimate at Jan-2026 cutoff; SDK billing
    # is authoritative -- this only feeds the live cost meter display).
    "gpt-5":       {"in": 1.25, "cached_in": 0.125, "out": 10.00},
    "gpt-5-mini":  {"in": 0.25, "cached_in": 0.025, "out":  2.00},
    "gpt-5-nano":  {"in": 0.05, "cached_in": 0.005, "out":  0.40},
}


def load_openai_key() -> None:
    if os.environ.get("OPENAI_API_KEY"):
        return
    env = REPO_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if line.startswith("OPENAI_API_KEY="):
            os.environ["OPENAI_API_KEY"] = (
                line.split("=", 1)[1].strip().strip('"').strip("'")
            )
            return


def b64_data_url(p: Path) -> str:
    media = "image/jpeg" if p.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    data = base64.standard_b64encode(p.read_bytes()).decode("ascii")
    return f"data:{media};base64,{data}"


def build_exemplar_user_blocks() -> list[dict]:
    """OpenAI's chat.completions format: alternating text + image_url
    blocks in a single user message. We embed all 14 exemplars here,
    then append the scored photo block per call."""
    blocks: list[dict] = []
    for i, (name, path, caption) in enumerate(EXEMPLARS):
        if not path.exists():
            raise FileNotFoundError(f"Missing exemplar: {path}")
        blocks.append({
            "type": "text",
            "text": f"Exemplar {i + 1} -- {name}: {caption}",
        })
        blocks.append({
            "type": "image_url",
            "image_url": {"url": b64_data_url(path), "detail": "high"},
        })
    return blocks


def cost_of(model: str, usage) -> float:
    """Compute USD cost from OpenAI usage object. Cached tokens are
    counted separately under prompt_tokens_details.cached_tokens."""
    p = PRICING.get(model, PRICING["gpt-4o"])
    prompt_tokens = usage.prompt_tokens
    cached = 0
    if (details := getattr(usage, "prompt_tokens_details", None)) is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
    uncached = max(prompt_tokens - cached, 0)
    return (
        uncached       * p["in"]        / 1_000_000
        + cached       * p["cached_in"] / 1_000_000
        + usage.completion_tokens * p["out"] / 1_000_000
    )


def score_one(client, model: str, exemplar_blocks: list[dict],
              photo_path: Path) -> tuple[QCResult | None, object | None, str | None]:
    """One vision call via OpenAI structured outputs."""
    user_content = list(exemplar_blocks) + [
        {"type": "text", "text": "Now score the following photo per the schema:"},
        {
            "type": "image_url",
            "image_url": {"url": b64_data_url(photo_path), "detail": "high"},
        },
    ]
    try:
        # `max_completion_tokens` is the post-o1 spelling and is required
        # for gpt-5 family (max_tokens returns HTTP 400 there). It also
        # works on gpt-4o, so we use it unconditionally.
        # gpt-5 is a reasoning model: it burns tokens on internal thinking
        # BEFORE producing the JSON. 1024 is too small (LengthFinishReason
        # errors out before output). 16384 leaves headroom; the cost meter
        # still bills only actual usage.
        kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": user_content},
            ],
            "response_format": QCResult,
            "max_completion_tokens": 16384,
        }
        # gpt-5 family supports `reasoning_effort` -- "minimal" cuts
        # internal reasoning tokens drastically, which is what we want
        # for a structured classification task that doesn't benefit from
        # long chains of thought.
        if model.startswith("gpt-5") or model.startswith("o"):
            kwargs["reasoning_effort"] = "minimal"
        resp = client.chat.completions.parse(**kwargs)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        for redact in ("Authorization", "api-key", "sk-"):
            if redact in msg:
                msg = msg.split(redact, 1)[0] + f"[{redact} redacted]"
        return None, None, msg[:300]

    return resp.choices[0].message.parsed, resp.usage, None


def score_with_retry(client, model, exemplar_blocks, photo_path,
                     max_attempts: int = 3):
    """Retry on 429, 5xx, connection errors. Backoff 2/4/8s with jitter."""
    for attempt in range(max_attempts):
        result, usage, err = score_one(
            client, model, exemplar_blocks, photo_path,
        )
        if err is None or attempt == max_attempts - 1:
            return result, usage, err
        err_l = err.lower()
        retriable = (
            "429" in err_l or "rate" in err_l or "ratelimit" in err_l
            or "502" in err_l or "503" in err_l or "504" in err_l
            or "timeout" in err_l or "connection" in err_l
            or "overloaded" in err_l or "internalservererror" in err_l
        )
        if not retriable:
            return result, usage, err
        base = 2.0 * (2 ** attempt)
        time.sleep(base * random.uniform(0.75, 1.25))
    return None, None, "exhausted retries"


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
        json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def main() -> int:
    import openai

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-4o",
                    help="OpenAI model id (gpt-4o, gpt-4o-mini, gpt-4.1, etc.)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-cost-usd", type=float, default=20.0)
    args = ap.parse_args()
    model = args.model

    load_openai_key()
    if not os.environ.get("OPENAI_API_KEY"):
        print("[bench] OPENAI_API_KEY not set and .env missing the entry",
              file=sys.stderr)
        return 1

    gt_ids: dict[str, Path] = {}
    for d in GT_DIRS:
        for p in sorted(d.iterdir()):
            if p.is_file():
                gt_ids[sha1_bytes(p)] = p
    print(f"[bench] {len(gt_ids)} ground-truth photos · model={model}")

    conn = sqlite3.connect(MANIFEST_DB)
    rows = conn.execute("SELECT photo_id FROM photos").fetchall()
    conn.close()
    in_manifest = {pid for (pid,) in rows}

    todo: list[tuple[str, Path]] = []
    for pid, p in gt_ids.items():
        if pid not in in_manifest:
            print(f"[bench] WARN: GT photo {pid[:10]} not in manifest",
                  file=sys.stderr)
            continue
        todo.append((pid, p))

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
    print(f"[bench] {len(todo)} photos to score "
          f"(skipped {len(already_done)} already done)")
    if not todo:
        return 0

    client = openai.OpenAI()
    exemplar_blocks = build_exemplar_user_blocks()

    state_lock = threading.Lock()
    file_lock = threading.Lock()
    completed = 0
    total_cost = 0.0
    fails = 0
    cost_exceeded = threading.Event()
    t0 = time.time()

    def write_row(pid: str, result: QCResult, usd: float) -> None:
        row = {
            "photo_id": pid,
            "model": model,
            "cost_usd": usd,
            **result.model_dump(),
        }
        with file_lock:
            with BENCH_JSONL.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Warm the prompt cache with one sequential call so the worker pool's
    # 8 concurrent calls hit cached pricing.
    first_pid, first_path = todo[0]
    result, usage, err = score_with_retry(
        client, model, exemplar_blocks, first_path,
    )
    if err is None and result is not None:
        usd = cost_of(model, usage)
        total_cost += usd
        completed += 1
        write_row(first_pid, result, usd)
        print(f"[bench] [   1/{len(todo)}] {result.phase:<14} ${usd:.3f}")
    else:
        fails += 1
        print(f"[bench] [   1/{len(todo)}] FAIL {(err or '')[:120]}")

    def process(pid: str, path: Path) -> None:
        nonlocal completed, total_cost, fails
        if cost_exceeded.is_set():
            return
        result, usage, err = score_with_retry(
            client, model, exemplar_blocks, path,
        )
        with state_lock:
            completed += 1
            done = completed
        if err is None and result is not None:
            usd = cost_of(model, usage)
            with state_lock:
                total_cost += usd
                cum = total_cost
                if total_cost > args.max_cost_usd:
                    cost_exceeded.set()
            write_row(pid, result, usd)
            if done % 25 == 0:
                rate = done / (time.time() - t0)
                eta = (len(todo) - done) / max(rate, 0.01)
                print(f"[bench] [{done:>4}/{len(todo)}] "
                      f"{result.phase:<14} ${cum:.2f} "
                      f"rate={rate:.1f}/s eta={eta/60:.1f}m")
        else:
            with state_lock:
                fails += 1
            print(f"[bench] [{done:>4}/{len(todo)}] FAIL "
                  f"{(err or '')[:80]}")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(process, pid, p) for pid, p in todo[1:]]
        for _ in as_completed(futs):
            pass

    dt = time.time() - t0
    print(
        f"[bench] {model} done. {completed} scored, {fails} failed, "
        f"${total_cost:.2f}, {dt:.1f}s"
    )

    # Append per-model timing, additive on resume. The audit groups rows
    # by _model_short(model_id) which returns the verbatim id for non-
    # Claude models. The Claude bench keys "sonnet"/"haiku" historically,
    # so for any OpenAI model we use the id verbatim too -- audit looks
    # up timings by the same short name it uses to group rows.
    timings = _load_timings()
    prev = timings.get(model, {"seconds": 0.0, "cost_usd": 0.0, "n": 0})
    timings[model] = {
        "model": model,
        "seconds": prev["seconds"] + dt,
        "cost_usd": prev["cost_usd"] + total_cost,
        "n": prev["n"] + completed,
    }
    _save_timings(timings)
    return 0 if fails == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
