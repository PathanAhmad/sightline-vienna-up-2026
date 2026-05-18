"""Stage 3 -- Read & QC the photo with Claude Sonnet 4.6 vision.

One vision call per representative photo (post-dedup). Returns the
relevance gate, phase classification, 7 visual compliance checks,
overlay fields (date, address, lat/lon), and paper-label code -- all
as a structured JSON via `client.messages.parse(output_format=QCResult)`.

Reads:
    - data/processed/forensics.jsonl (only is_phash_representative=true)
    - photo bytes from disk via manifest.sqlite

Writes:
    - data/processed/readqc.jsonl       (one row per representative)
    - data/processed/readqc_failures.json (photo_ids that errored, with reason)

Resume:
    If readqc.jsonl exists we skip photo_ids already in it. Lets us
    interrupt mid-batch (or after a quota error) without re-paying.

Cost:
    Sonnet 4.6 list pricing (as of training cutoff):
      input              $3.00 / Mtok
      cache_creation     $3.75 / Mtok
      cache_read         $0.30 / Mtok
      output            $15.00 / Mtok
    Measured on 2-photo smoke test: $0.039 (cache write) then $0.011
    (cache read). Extrapolating: ~$35 for 3,223 photos, assuming the
    5-minute cache TTL stays warm across consecutive calls (typical at
    4-5s/call). PLAN said "~$15" but the spike that estimated that was
    on Haiku; Sonnet is ~3x.

Hard ceiling: --max-cost-usd (default $40). Stop early if exceeded.

CLI:
    python -m src.readqc                 # full batch
    python -m src.readqc --n 5           # smoke test on 5 photos
    python -m src.readqc --model haiku   # fall back to Haiku
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.audit import log_event, log_stage_end, log_stage_start
from src.paths import (
    EXEMPLARS_DIR,
    FORENSICS_JSONL,
    MANIFEST_DB,
    PHOTOS_DIR,
    READQC_FAILURES_JSON,
    READQC_JSONL,
    REPO_ROOT,
    ensure_dirs,
)

MODELS = {
    "sonnet": "claude-sonnet-4-6",
    "haiku":  "claude-haiku-4-5",
}
DEFAULT_MODEL = "sonnet"

# Per-Mtok pricing in USD. Used for the live cost meter; pricing can drift,
# this only governs when we hit the ceiling and stop.
PRICING = {
    "claude-sonnet-4-6": {"in": 3.00, "cache_w": 3.75, "cache_r": 0.30, "out": 15.00},
    "claude-haiku-4-5":  {"in": 1.00, "cache_w": 1.25, "cache_r": 0.10, "out":  5.00},
}

EXEMPLARS = [
    # --- Original 4 (kept; captions tightened where needed) ---
    ("bad_lowlight_label", EXEMPLARS_DIR / "bad.jpeg",
     "Paper FCP label photographed in poor lighting -- phase=paper_label "
     "(label fills frame, no other work visible)."),
    ("duct_sand", EXEMPLARS_DIR / "duct_sand.jpg",
     "Duct laid in trench with visible sand bedding -- phase=sand_bedded."),
    ("duct_depth_rod_prominent", EXEMPLARS_DIR / "duct_depth.jpg",
     "Trench with prominent measuring rod composition AND duct visible at "
     "bottom -- phase=depth_measure. The operator labels rod-prominent frames as "
     "depth_measure even when ducts are also present; the rod composition "
     "is the documented activity."),
    ("warnband", EXEMPLARS_DIR / "warnband.jpeg",
     "Yellow/red warning tape laid above duct -- phase=tape_laid."),

    # --- 10 new exemplars added to teach the gaps the bench exposed ---
    # Paper-label vs duct disambiguation (was the largest single failure mode:
    # 11 of 100 duct/ photos misclassified as paper_label by Sonnet/Haiku).
    ("duct_with_label_1", EXEMPLARS_DIR / "duct_with_label_1.jpg",
     "Trench with red duct laid and a paper FCP label visible against the "
     "trench wall -- phase=duct_laid. The label is supporting documentation "
     "of WHICH duct; the work phase is duct laying, not paper_label."),
    ("duct_with_label_2", EXEMPLARS_DIR / "duct_with_label_2.jpg",
     "Long trench with duct visible and paper FCP label at the bottom of "
     "frame -- phase=duct_laid. Label is metadata; duct work is the subject."),
    ("paper_label_closeup", EXEMPLARS_DIR / "paper_label_closeup.jpg",
     "Paper FCP label held up as a close-up document, no active work phase "
     "visible behind -- phase=paper_label (true label-only shot)."),

    # Clean unambiguous cases for the two bench classes.
    ("rod_only_depth", EXEMPLARS_DIR / "rod_only_depth.jpg",
     "Empty trench with measuring rod only -- phase=depth_measure (clean "
     "case, no ducts in frame)."),
    ("clean_duct", EXEMPLARS_DIR / "clean_duct.jpg",
     "Duct laid in open trench, no measuring rod, no sand, no tape -- "
     "phase=duct_laid (clean case)."),

    # Phases the original 4 didn't cover.
    ("excavation", EXEMPLARS_DIR / "excavation.jpg",
     "Open empty trench, nothing laid yet -- phase=excavation."),
    ("restored", EXEMPLARS_DIR / "restored.jpg",
     "Fresh asphalt patch over a former trench line, surface restoration "
     "complete -- phase=restored."),
    ("tape_clean", EXEMPLARS_DIR / "tape_clean.jpg",
     "Backfilled trench with yellow 'ACHTUNG' warning tape laid on top -- "
     "phase=tape_laid (top-down view, no duct or rod in frame)."),
    ("sand_clean", EXEMPLARS_DIR / "sand_clean.jpg",
     "Duct bundle bedded in clean light-colored sand fill -- "
     "phase=sand_bedded."),

    # Relevance-gate example.
    ("offtopic", EXEMPLARS_DIR / "offtopic.jpg",
     "Generic street scene with parked van and signage; no trench or fiber "
     "work in frame -- relevance=off_topic."),
]

SYSTEM_INSTRUCTIONS = """\
You are a quality-control inspector for fiber-optic trench construction photos in Maria Rain, Carinthia, Austria.

For each photo you receive, return exactly the JSON object the schema describes -- no prose.

Field guidance:

relevance -- gate before we score this photo at all:
  scorable    -- Real construction-process scene we can grade. INCLUDES all work phases from open trench through restoration -- depth-measure, duct-laid, sand-bedded, tape-laid, backfilled, restored asphalt patches, AND paper-label close-ups documenting which FCP/duct is being connected. If you can see any documentation of the fiber-build process, it is scorable.
  portrait    -- A PERSON is the primary subject of the frame. Workers' hands or feet at the edge of an otherwise-construction shot do NOT count. Paper labels, equipment, vehicles, and signs are NOT portraits.
  off_topic   -- Nothing related to the fiber build: food, indoor furniture, screenshots, generic landscape with no work in frame, selfies of someone unrelated to the work.
  unreadable  -- Too dark, too blurry, too occluded, or so badly framed that you can identify nothing about the work or location. If you can read the overlay AND see *something* construction-related, default to scorable, not unreadable.

phase -- what stage of work the photo documents. **When multiple phases are visible (e.g. a measuring rod is still in frame after tape has been laid), pick the LATEST one in this progression:**
  excavation -> depth_measure -> duct_laid -> sand_bedded -> tape_laid -> backfilled -> restored

  Plus three non-progression buckets:
  paper_label    -- A paper FCP label (e.g. "F012-R001-7-br") is the PRIMARY subject of the photo, filling most of the frame as a close-up document. Use this ONLY when the label dominates AND no active work phase (ducts in trench, sand bedding, warning tape, etc.) is clearly visible behind or alongside it. **If you see ducts laid in a trench with a paper label off to the side, on the wall, at the corner, or held over the duct bundle, the phase is duct_laid (or whichever later phase is shown) — the label is supporting metadata documenting WHICH duct/FCP, not the subject. Same rule for sand_bedded, tape_laid, etc.: the work phase wins over the label.**
  staging        -- Equipment / skip / dumpster / cones / parked truck on site; no trench-process work in frame.
  other          -- Genuinely doesn't fit any of the above.

  Phase definitions:
  excavation     -- Open trench, no duct / sand / tape yet. Side profile of raw soil walls.
  depth_measure  -- Measuring rod / ruler / yardstick in the trench AND no later-phase elements (no tape, no sand fill).
  duct_laid      -- Colored ducts / cables visible in the trench, before sand bedding.
  sand_bedded    -- Ducts surrounded by clean sand fill, no warning tape yet.
  tape_laid      -- Yellow/red warning tape laid over the backfill. Even if a measuring rod is still in frame, tape_laid wins.
  backfilled     -- Trench refilled with native soil, surface not yet restored (no asphalt patch).
  restored       -- Final restoration done -- fresh asphalt patch, paving, lawn re-laid.

The 7 visual checks -- answer yes / no / occluded based on what is CLEARLY visible in THIS photo. **When in doubt, answer "no". Only answer "yes" if the feature is unmistakable.**
  warning_tape_visible    -- Red-white or yellow warning tape (often printed "ACHTUNG" or similar) across the trench.
  sand_bedding_visible    -- Clean lighter-colored sand layer around/under the ducts (distinct from native soil).
  side_view_present       -- Photo shows the trench profile from the side (wall + depth), not just top-down.
  depth_reference_visible -- Measuring rod, ruler, or labeled stick that lets a reviewer read depth.
  duct_visible            -- One or more ducts / cables physically in the trench (not just at the surface).
  pipe_ends_sealed        -- The duct bundle has WHITE END-CAPS or plugs sealing the open ends of the pipes. Answer "not_applicable" if no duct ends are visible in the frame (e.g. a sand-bedded shot looking down at the middle of a trench).
  personal_data_visible   -- Yes if a person's face is identifiable OR a vehicle licence plate is legible. Hands, feet, gloved arms, or hi-vis vests with no readable text are NOT personal data. Workers' faces at the edge of frame with features visible ARE.

Overlay fields -- burned-in text overlay added by the camera app.
  overlay_date         -- Date string exactly as printed (e.g. "27.08.2024 13:22:54" or "27 авг. 2024 г. 13:22:54"). Empty string if no overlay.
  overlay_address      -- Street + house number + locality as printed (e.g. "20 Toppelsdorferstraße, Maria Rain"). Empty string if not present.
  overlay_latlon       -- Latitude/longitude as printed. **Transcribe digit-by-digit; do not "round" or "guess" digits. Maria Rain is at ~46°33' N / 14°17' E or ~46.55 / 14.29 -- but trust what is printed, not what you expect.** null if not visible.
  paper_label_code     -- Code from a paper label INSIDE the photo (not the overlay). Pattern like "F012-R001-7-br" (F + 3 digits, R + 3 digits, slot, color). null if none.

note -- one sentence, max 400 chars: what you saw and why you chose this phase/relevance.

Below are 4 reference exemplars showing canonical phases.\
"""


class QCResult(BaseModel):
    relevance: Literal["scorable", "portrait", "off_topic", "unreadable"]
    phase: Literal[
        "excavation", "depth_measure", "duct_laid", "sand_bedded",
        "tape_laid", "backfilled", "restored", "paper_label", "staging", "other",
    ]
    warning_tape_visible: Literal["yes", "no", "occluded"]
    sand_bedding_visible: Literal["yes", "no", "occluded"]
    side_view_present: Literal["yes", "no"]
    depth_reference_visible: Literal["yes", "no"]
    depth_value_cm: float | None = None
    duct_visible: Literal["yes", "no", "occluded"]
    pipe_ends_sealed: Literal["yes", "no", "occluded", "not_applicable"]
    personal_data_visible: Literal["yes", "no"]
    overlay_date: str = ""
    overlay_address: str = ""
    overlay_latlon: str | None = None
    paper_label_code: str | None = None
    note: str = Field(default="", max_length=500)


def load_env_key() -> None:
    """Read ANTHROPIC_API_KEY from .env if not already in env."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    env = REPO_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            return


def b64(p: Path) -> tuple[str, str]:
    media = "image/jpeg" if p.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return media, base64.standard_b64encode(p.read_bytes()).decode("ascii")


def build_exemplar_prefix() -> list[dict]:
    """4 (caption, image) blocks with cache_control on the last block."""
    blocks: list[dict] = []
    for i, (name, path, caption) in enumerate(EXEMPLARS):
        if not path.exists():
            raise FileNotFoundError(f"Missing exemplar: {path}")
        media, data = b64(path)
        blocks.append({"type": "text", "text": f"Exemplar {i + 1} -- {name}: {caption}"})
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def cost_of(model: str, usage: dict) -> float:
    """USD cost from a usage dict (input_tokens, cache_creation, cache_read, output_tokens)."""
    p = PRICING[model]
    return (
        usage["input_tokens"]               * p["in"]      / 1_000_000
        + usage["cache_creation_input_tokens"] * p["cache_w"] / 1_000_000
        + usage["cache_read_input_tokens"]    * p["cache_r"] / 1_000_000
        + usage["output_tokens"]              * p["out"]     / 1_000_000
    )


def score_one_photo(client, model: str, exemplar_prefix: list[dict], photo_path: Path) -> tuple[QCResult | None, dict, str | None]:
    """One vision call. Returns (parsed_or_none, usage_dict, error_str_or_none)."""
    media, data = b64(photo_path)
    user_content = list(exemplar_prefix) + [
        {"type": "text", "text": "Now score the following photo per the schema:"},
        {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}},
    ]
    try:
        resp = client.messages.parse(
            model=model,
            max_tokens=1024,
            system=[{"type": "text", "text": SYSTEM_INSTRUCTIONS, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_content}],
            output_format=QCResult,
        )
    except Exception as e:
        # Strip Authorization/api-key substrings before storing -- SDK exception
        # messages occasionally carry header echoes that we don't want to ship
        # to a teammate via the readqc_failures.json bug-report path.
        msg = f"{type(e).__name__}: {e}"
        for redact in ("Authorization", "x-api-key", "sk-ant-"):
            if redact in msg:
                msg = msg.split(redact, 1)[0] + f"[{redact} redacted]"
        return None, {}, msg[:300]

    usage = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
    }
    return resp.parsed_output, usage, None


def load_target_photos(n_limit: int | None) -> list[tuple[str, str]]:
    """Return [(photo_id, rel_path)] for representative photos that aren't
    already scored in readqc.jsonl."""
    # Load representative photo_ids
    reps: set[str] = set()
    with FORENSICS_JSONL.open("r", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("is_phash_representative"):
                reps.add(row["photo_id"])

    # Skip what's already done
    done: set[str] = set()
    if READQC_JSONL.exists():
        with READQC_JSONL.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    done.add(json.loads(line)["photo_id"])
                except (KeyError, json.JSONDecodeError):
                    pass

    todo_ids = reps - done
    if not todo_ids:
        return []

    # Filter in Python: SQLite has a 999-host-parameter limit and we routinely
    # have ~3,200 representative photo_ids. The manifest has ~3,200 rows, so
    # a full scan + Python-side membership check is cheap and avoids the limit.
    conn = sqlite3.connect(MANIFEST_DB)
    all_rows = conn.execute("SELECT photo_id, rel_path FROM photos").fetchall()
    conn.close()
    rows = [r for r in all_rows if r[0] in todo_ids]
    rows.sort(key=lambda r: r[0])  # deterministic order
    if n_limit:
        rows = rows[:n_limit]
    return rows


def _score_with_retry(
    client, model, exemplar_prefix, photo_path: Path, max_attempts: int = 3,
):
    """One vision call, with retries on transient upstream errors:
    429 rate-limit, 5xx (Cloudflare 502/503/504 are common when Anthropic's
    edge can't reach origin), connection errors, and 'Overloaded'.
    Anything else (auth, schema, bad image) is permanent — return immediately.

    Backoff: 2s, 4s, 8s — geometric, capped at max_attempts."""
    for attempt in range(max_attempts):
        result, usage, err = score_one_photo(
            client, model, exemplar_prefix, photo_path,
        )
        if err is None or attempt == max_attempts - 1:
            return result, usage, err
        # All matches go against the lowercased error for consistency —
        # a previous version mixed case-sensitive and case-insensitive
        # checks, which silently broke if the SDK ever changed exception
        # capitalization.
        err_l = err.lower()
        retriable = (
            "429" in err_l
            or "rate_limit" in err_l
            or "ratelimiterror" in err_l
            or "overloaded" in err_l
            or "502" in err_l or "503" in err_l or "504" in err_l
            or "bad gateway" in err_l
            or "internalservererror" in err_l
            or "apiconnectionerror" in err_l
            or "apitimeouterror" in err_l
        )
        if not retriable:
            return result, usage, err
        # Geometric backoff (2s, 4s, 8s) with ±25% jitter so 8 workers
        # that all hit the same 429 don't retry in lockstep and re-trip
        # the rate limit.
        base = 2.0 * (2 ** attempt)
        time.sleep(base * random.uniform(0.75, 1.25))
    return None, {}, "exhausted retries"


def run_batch(
    model_key: str,
    n_limit: int | None,
    max_cost_usd: float,
    n_workers: int = 8,
) -> int:
    """Score all not-yet-scored representative photos.

    Parallelism: a thread pool of `n_workers` (default 8) drives sync
    `client.messages.parse` calls — the Anthropic SDK is thread-safe per
    its docs, and httpx pools connections under the hood. To avoid 8
    concurrent requests each paying the cache-write surcharge (~$0.04
    each), the first photo runs SEQUENTIALLY so the system+exemplar
    prefix is warm before the pool fans out. Subsequent calls hit
    cache_read pricing (~$0.011 vs $0.039 cold).

    Cost ceiling: the per-worker total-cost check is guarded by a lock,
    and the `cost_exceeded` event short-circuits new starts. Up to
    `n_workers` in-flight calls may complete past the ceiling — fine for
    a $40 budget, the worst-case overshoot is 8 × $0.011 ≈ $0.10.

    Set `--workers 1` to force the old sequential behavior (useful for
    debugging or when the SDK is misbehaving)."""
    import anthropic  # lazy so other stages don't pay the cost

    load_env_key()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[readqc] ANTHROPIC_API_KEY not set and .env missing the entry",
              file=sys.stderr)
        return 1

    ensure_dirs()
    model = MODELS[model_key]
    client = anthropic.Anthropic()
    exemplar_prefix = build_exemplar_prefix()

    targets = load_target_photos(n_limit)
    if not targets:
        print("[readqc] nothing to do (all representatives already scored)")
        return 0

    n_workers = max(1, n_workers)
    print(
        f"[readqc] {len(targets)} photos -> {model}, "
        f"cost ceiling ${max_cost_usd:.2f}, workers={n_workers}"
    )
    log_stage_start(
        "readqc", model=model, n_targets=len(targets),
        max_cost_usd=max_cost_usd, n_workers=n_workers,
    )

    failures: list[dict] = []
    total_cost = 0.0
    completed = 0
    t0 = time.time()
    state_lock = threading.Lock()
    file_lock = threading.Lock()
    cost_exceeded = threading.Event()

    def process_one(idx: int, photo_id: str, rel_path: str) -> dict | None:
        """Score one photo. Returns the row dict on success, None on
        failure / cost-ceiling skip. Writes to the JSONL and updates
        shared state under locks."""
        nonlocal total_cost, completed
        if cost_exceeded.is_set():
            return None
        photo_path = PHOTOS_DIR / rel_path
        result, usage, err = _score_with_retry(
            client, model, exemplar_prefix, photo_path,
        )
        if err:
            err_class = err.split(":", 1)[0] if ":" in err else err[:40]
            with state_lock:
                failures.append({
                    "photo_id": photo_id,
                    "rel_path": rel_path,
                    "error": err,
                })
                completed += 1
                done = completed
            log_event("readqc", "api_fail",
                      photo_id=photo_id, error_class=err_class)
            print(f"[readqc] [{done:>4}/{len(targets)}] "
                  f"FAIL {photo_id[:10]} {err[:80]}")
            return None

        usd = cost_of(model, usage)
        row = {
            "photo_id": photo_id,
            "model": model,
            "cost_usd": round(usd, 6),
            **result.model_dump(),
        }
        line = json.dumps(row, ensure_ascii=False) + "\n"

        with state_lock:
            total_cost += usd
            completed += 1
            done = completed
            cum_cost = total_cost
            if total_cost > max_cost_usd and not cost_exceeded.is_set():
                cost_exceeded.set()
                log_event(
                    "readqc", "cost_ceiling_hit",
                    total_cost_usd=round(total_cost, 4),
                    max_cost_usd=max_cost_usd,
                    photos_done=done,
                    photos_remaining=len(targets) - done,
                )
        with file_lock:
            out_fh.write(line)
            out_fh.flush()

        if done % 25 == 0 or done == len(targets):
            rate = done / (time.time() - t0) if (time.time() - t0) > 0 else 0
            eta_s = (len(targets) - done) / rate if rate > 0 else 0
            print(
                f"[readqc] [{done:>4}/{len(targets)}] "
                f"{result.relevance:9s} {result.phase:13s} "
                f"cost=${cum_cost:.3f} rate={rate:.1f}/s "
                f"eta={eta_s/60:.1f}m"
            )
        return row

    # Open the output file inside the try so an early raise during
    # pre-warm doesn't leak the handle.
    out_fh = None
    try:
        out_fh = READQC_JSONL.open("a", encoding="utf-8")
        # Pre-warm the cache with the first photo: one sync call before
        # the pool fans out, so subsequent workers hit cache_read pricing.
        first_pid, first_rel = targets[0]
        process_one(1, first_pid, first_rel)

        # Remaining targets fan out across the pool. ThreadPool keeps the
        # GIL-friendly httpx I/O concurrent without async-ifying anything.
        rest = targets[1:]
        if rest and not cost_exceeded.is_set() and n_workers > 1:
            # Map future -> (idx, pid, rel) so a raised worker exception
            # can be recorded against the photo it was scoring rather
            # than vanishing into stderr (the human-logged stages contract
            # in CLAUDE.md says every photo's outcome must be tracked).
            with ThreadPoolExecutor(max_workers=n_workers) as ex:
                fut_meta: dict = {
                    ex.submit(process_one, idx, pid, rel): (idx, pid, rel)
                    for idx, (pid, rel) in enumerate(rest, 2)
                }
                for fut in as_completed(fut_meta):
                    idx, pid, rel = fut_meta[fut]
                    try:
                        fut.result()
                    except Exception as e:  # noqa: BLE001
                        err_msg = f"worker_raised: {type(e).__name__}: {e}"
                        with state_lock:
                            failures.append({
                                "photo_id": pid,
                                "rel_path": rel,
                                "error": err_msg[:300],
                            })
                            completed += 1
                        log_event(
                            "readqc", "worker_raised",
                            photo_id=pid, error_class=type(e).__name__,
                        )
                        print(
                            f"[readqc] worker raised on {pid[:10]}: "
                            f"{type(e).__name__}: {e}",
                            file=sys.stderr,
                        )
        elif rest:
            # Sequential fallback (--workers 1). Preserves prior behavior.
            for idx, (pid, rel) in enumerate(rest, 2):
                if cost_exceeded.is_set():
                    break
                process_one(idx, pid, rel)
    finally:
        if out_fh is not None:
            out_fh.close()

    if cost_exceeded.is_set():
        print(f"[readqc] HALT: cost ${total_cost:.2f} exceeded "
              f"ceiling ${max_cost_usd:.2f}")

    if failures:
        prior: list[dict] = []
        if READQC_FAILURES_JSON.exists():
            try:
                prior = json.loads(READQC_FAILURES_JSON.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                prior = []
        READQC_FAILURES_JSON.write_text(
            json.dumps(prior + failures, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[readqc] {len(failures)} failures -> {READQC_FAILURES_JSON.name}")

    elapsed = time.time() - t0
    print(f"[readqc] done. total cost ${total_cost:.3f}, {elapsed:.1f}s")
    log_stage_end(
        "readqc", total_cost_usd=round(total_cost, 4),
        n_failures=len(failures), elapsed_s=round(elapsed, 1),
        n_workers=n_workers,
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=None,
                    help="limit to first N photos (smoke test)")
    ap.add_argument("--model", choices=list(MODELS.keys()),
                    default=DEFAULT_MODEL)
    ap.add_argument("--max-cost-usd", type=float, default=40.0)
    ap.add_argument(
        "--workers", type=int, default=8,
        help=(
            "concurrent API workers (default 8). 1 = sequential. "
            "Each worker holds one in-flight vision call. Stay within "
            "your tier's per-minute rate limit."
        ),
    )
    args = ap.parse_args()
    return run_batch(args.model, args.n, args.max_cost_usd, args.workers)


if __name__ == "__main__":
    sys.exit(main())
