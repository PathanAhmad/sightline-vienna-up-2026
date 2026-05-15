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
import sqlite3
import sys
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

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
    ("bad",        EXEMPLARS_DIR / "bad.jpeg",        "Junk / non-scorable -- bad reference."),
    ("duct_sand",  EXEMPLARS_DIR / "duct_sand.jpg",   "Duct laid with visible sand bedding -- phase=sand_bedded."),
    ("duct_depth", EXEMPLARS_DIR / "duct_depth.jpg",  "Duct with measuring rod showing trench depth -- phase=depth_measure."),
    ("warnband",   EXEMPLARS_DIR / "warnband.jpeg",   "Yellow/red warning tape laid above duct -- phase=tape_laid."),
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
  paper_label    -- A paper FCP label (e.g. "F012-R001-7-br") held up to the camera dominates the frame. Use this even if a trench is also visible.
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


def run_batch(model_key: str, n_limit: int | None, max_cost_usd: float) -> int:
    import anthropic  # imported lazily so other stages don't pay the cost

    load_env_key()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[readqc] ANTHROPIC_API_KEY not set and .env missing the entry", file=sys.stderr)
        return 1

    ensure_dirs()
    model = MODELS[model_key]
    client = anthropic.Anthropic()
    exemplar_prefix = build_exemplar_prefix()

    targets = load_target_photos(n_limit)
    if not targets:
        print("[readqc] nothing to do (all representatives already scored)")
        return 0

    print(f"[readqc] {len(targets)} photos -> {model}, cost ceiling ${max_cost_usd:.2f}")

    failures: list[dict] = []
    total_cost = 0.0
    t0 = time.time()

    with READQC_JSONL.open("a", encoding="utf-8") as out:
        for i, (photo_id, rel_path) in enumerate(targets, 1):
            photo_path = PHOTOS_DIR / rel_path
            t_start = time.time()
            result, usage, err = score_one_photo(client, model, exemplar_prefix, photo_path)
            dt = time.time() - t_start

            if err:
                failures.append({"photo_id": photo_id, "rel_path": rel_path, "error": err})
                print(f"[readqc] [{i:>4}/{len(targets)}] FAIL {photo_id[:10]} {err[:80]}")
                continue

            usd = cost_of(model, usage)
            total_cost += usd
            row = {
                "photo_id": photo_id,
                "model": model,
                "cost_usd": round(usd, 6),
                **result.model_dump(),
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()

            if i % 25 == 0 or i == len(targets):
                rate = i / (time.time() - t0)
                eta_s = (len(targets) - i) / rate if rate > 0 else 0
                print(
                    f"[readqc] [{i:>4}/{len(targets)}] {result.relevance:9s} {result.phase:13s} "
                    f"cost=${total_cost:.3f} rate={rate:.1f}/s eta={eta_s/60:.1f}m"
                )

            if total_cost > max_cost_usd:
                print(f"[readqc] HALT: cost ${total_cost:.2f} exceeded ceiling ${max_cost_usd:.2f}")
                break

    if failures:
        # Append to failures file (preserve any from previous runs)
        prior: list[dict] = []
        if READQC_FAILURES_JSON.exists():
            try:
                prior = json.loads(READQC_FAILURES_JSON.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                prior = []
        READQC_FAILURES_JSON.write_text(
            json.dumps(prior + failures, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"[readqc] {len(failures)} failures -> {READQC_FAILURES_JSON.name}")

    print(f"[readqc] done. total cost ${total_cost:.3f}, {time.time() - t0:.1f}s")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=None, help="limit to first N photos (smoke test)")
    ap.add_argument("--model", choices=list(MODELS.keys()), default=DEFAULT_MODEL)
    ap.add_argument("--max-cost-usd", type=float, default=40.0)
    args = ap.parse_args()
    return run_batch(args.model, args.n, args.max_cost_usd)


if __name__ == "__main__":
    sys.exit(main())
