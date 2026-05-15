"""
Validation spike for the new QC schema (phase + relevance + 5 checks + overlay).

Runs Claude Haiku 4.5 vision on N random photos and writes:
  scripts/out/spike_qc_results.jsonl  — one row per photo
  scripts/out/spike_qc_summary.txt    — counts + cache hit rate

Decision question: are the phase and relevance labels stable/plausible enough to
build the rest of the pipeline around them, or do we need to retune the schema?

Run from repo root:
  .venv/Scripts/python.exe scripts/spike_qc_schema.py --n 30
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
PHOTOS_DIR = REPO_ROOT / "data" / "Fotos" / "Fotos"
EXEMPLARS_DIR = REPO_ROOT / "data" / "Beispiele" / "Beispiele"
OUT_DIR = REPO_ROOT / "scripts" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

EXEMPLARS = [
    ("bad",        EXEMPLARS_DIR / "bad.jpeg",        "Junk / non-scorable — bad reference."),
    ("duct_sand",  EXEMPLARS_DIR / "duct_sand.jpg",   "Duct laid with visible sand bedding — phase=sand_bedded."),
    ("duct_depth", EXEMPLARS_DIR / "duct_depth.jpg",  "Duct with measuring rod showing trench depth — phase=depth_measure."),
    ("warnband",   EXEMPLARS_DIR / "warnband.jpeg",   "Yellow/red warning tape laid above duct — phase=tape_laid."),
]

SYSTEM_INSTRUCTIONS = """\
You are a quality-control inspector for fiber-optic trench construction photos in Maria Rain, Carinthia, Austria.

For each photo you receive, return exactly the JSON object the schema describes — no prose.

Field guidance:

relevance — gate before we score this photo at all:
  scorable    — Real construction-process scene we can grade. INCLUDES all work phases from open trench through restoration — depth-measure, duct-laid, sand-bedded, tape-laid, backfilled, restored asphalt patches, AND paper-label close-ups documenting which FCP/duct is being connected. If you can see any documentation of the fiber-build process, it is scorable.
  portrait    — A PERSON is the primary subject of the frame. Workers' hands or feet at the edge of an otherwise-construction shot do NOT count. Paper labels, equipment, vehicles, and signs are NOT portraits.
  off_topic   — Nothing related to the fiber build: food, indoor furniture, screenshots, generic landscape with no work in frame, selfies of someone unrelated to the work.
  unreadable  — Too dark, too blurry, too occluded, or so badly framed that you can identify nothing about the work or location. If you can read the overlay AND see *something* construction-related, default to scorable, not unreadable.

phase — what stage of work the photo documents. **When multiple phases are visible (e.g. a measuring rod is still in frame after tape has been laid), pick the LATEST one in this progression:**
  excavation → depth_measure → duct_laid → sand_bedded → tape_laid → backfilled → restored

  Plus three non-progression buckets:
  paper_label    — A paper FCP label (e.g. "F012-R001-7-br") held up to the camera dominates the frame. Use this even if a trench is also visible.
  staging        — Equipment / skip / dumpster / cones / parked truck on site; no trench-process work in frame.
  other          — Genuinely doesn't fit any of the above.

  Phase definitions:
  excavation     — Open trench, no duct / sand / tape yet. Side profile of raw soil walls.
  depth_measure  — Measuring rod / ruler / yardstick in the trench AND no later-phase elements (no tape, no sand fill).
  duct_laid      — Colored ducts / cables visible in the trench, before sand bedding.
  sand_bedded    — Ducts surrounded by clean sand fill, no warning tape yet.
  tape_laid      — Yellow/red warning tape laid over the backfill. Even if a measuring rod is still in frame, tape_laid wins.
  backfilled     — Trench refilled with native soil, surface not yet restored (no asphalt patch).
  restored       — Final restoration done — fresh asphalt patch, paving, lawn re-laid.

The 5 visual checks — answer yes / no / occluded based on what is CLEARLY visible in THIS photo. **When in doubt, answer "no". Only answer "yes" if the feature is unmistakable.**
  warning_tape_visible    — Red-white or yellow warning tape (often printed "ACHTUNG" or similar) across the trench.
  sand_bedding_visible    — Clean lighter-colored sand layer around/under the ducts (distinct from native soil).
  side_view_present       — Photo shows the trench profile from the side (wall + depth), not just top-down.
  depth_reference_visible — Measuring rod, ruler, or labeled stick that lets a reviewer read depth.
  duct_visible            — One or more ducts / cables physically in the trench (not just at the surface).

Overlay fields — burned-in text overlay added by the camera app.
  overlay_date         — Date string exactly as printed (e.g. "27.08.2024 13:22:54" or "27 авг. 2024 г. 13:22:54"). Empty string if no overlay.
  overlay_address      — Street + house number + locality as printed (e.g. "20 Toppelsdorferstraße, Maria Rain"). Empty string if not present.
  overlay_latlon       — Latitude/longitude as printed. **Transcribe digit-by-digit; do not "round" or "guess" digits. Maria Rain is at ~46°33' N / 14°17' E or ~46.55 / 14.29 — but trust what is printed, not what you expect.** null if not visible.
  paper_label_code     — Code from a paper label INSIDE the photo (not the overlay). Pattern like "F012-R001-7-br" (F + 3 digits, R + 3 digits, slot, color). null if none.

note — one sentence, max 400 chars: what you saw and why you chose this phase/relevance.

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
    overlay_date: str = ""
    overlay_address: str = ""
    overlay_latlon: str | None = None
    paper_label_code: str | None = None
    note: str = Field(default="", max_length=500)


def b64(p: Path) -> tuple[str, str]:
    media = "image/jpeg" if p.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return media, base64.standard_b64encode(p.read_bytes()).decode("ascii")


def build_exemplar_prefix() -> list[dict]:
    """Cacheable user-message prefix: 4 exemplar (caption + image) pairs.
    cache_control on the last block freezes everything before it. The target
    photo gets appended after this prefix on every request."""
    blocks: list[dict] = []
    for i, (name, path, caption) in enumerate(EXEMPLARS):
        if not path.exists():
            raise FileNotFoundError(f"Missing exemplar: {path}")
        media, data = b64(path)
        blocks.append({"type": "text", "text": f"Exemplar {i + 1} — {name}: {caption}"})
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def classify_photo(client: anthropic.Anthropic, exemplar_prefix: list[dict], photo: Path) -> tuple[QCResult | None, dict, str | None]:
    media, data = b64(photo)
    user_content = list(exemplar_prefix) + [
        {"type": "text", "text": "Now score the following photo per the schema:"},
        {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}},
    ]
    try:
        resp = client.messages.parse(
            model="claude-haiku-4-5",
            max_tokens=1024,
            system=[{"type": "text", "text": SYSTEM_INSTRUCTIONS, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_content}],
            output_format=QCResult,
        )
    except Exception as e:
        return None, {}, f"{type(e).__name__}: {e}"

    usage = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
    }
    return resp.parsed_output, usage, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30, help="number of random photos")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        env = REPO_ROOT / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    files = sorted(PHOTOS_DIR.glob("*"))
    if not files:
        print(f"No photos under {PHOTOS_DIR}", file=sys.stderr)
        return 1

    random.seed(args.seed)
    sample = random.sample(files, min(args.n, len(files)))
    print(f"[spike] {len(sample)} photos sampled from {len(files)} (seed={args.seed})")

    client = anthropic.Anthropic()
    exemplar_prefix = build_exemplar_prefix()
    print(f"[spike] cached prefix: system text + {len(exemplar_prefix)} user blocks (4 exemplars)")

    results_path = OUT_DIR / "spike_qc_results.jsonl"
    summary_path = OUT_DIR / "spike_qc_summary.txt"

    phases, relevance, errors = Counter(), Counter(), []
    cache_creates, cache_reads, uncached = 0, 0, 0
    t0 = time.time()

    with results_path.open("w", encoding="utf-8") as fh:
        for i, photo in enumerate(sample, 1):
            t_start = time.time()
            result, usage, err = classify_photo(client, exemplar_prefix, photo)
            dt = time.time() - t_start

            row = {"file": photo.name, "elapsed_s": round(dt, 2)}
            if err:
                errors.append((photo.name, err))
                row["error"] = err
                print(f"[{i:>2}/{len(sample)}] FAIL  {photo.name[:60]}  {err[:80]}")
            else:
                phases[result.phase] += 1
                relevance[result.relevance] += 1
                cache_creates += usage["cache_creation_input_tokens"]
                cache_reads += usage["cache_read_input_tokens"]
                uncached += usage["input_tokens"]
                row.update({"result": result.model_dump(), "usage": usage})
                print(
                    f"[{i:>2}/{len(sample)}] {result.relevance:9s} {result.phase:14s} "
                    f"tape={result.warning_tape_visible:8s} sand={result.sand_bedding_visible:8s} "
                    f"depth={result.depth_reference_visible:3s} duct={result.duct_visible:8s} "
                    f"cache_r={usage['cache_read_input_tokens']:>5d} "
                    f"{photo.name[:40]}"
                )
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    total_dt = time.time() - t0
    n_ok = sum(phases.values())

    lines = [
        f"Spike summary — {n_ok}/{len(sample)} OK, {len(errors)} errors, {total_dt:.1f}s total ({total_dt / len(sample):.1f}s/photo avg)",
        "",
        "Relevance distribution:",
        *[f"  {k:11s} {v:>3d}" for k, v in relevance.most_common()],
        "",
        "Phase distribution:",
        *[f"  {k:14s} {v:>3d}" for k, v in phases.most_common()],
        "",
        f"Cache: {cache_creates} written, {cache_reads} read, {uncached} uncached input tokens",
        f"Cache-read ratio: {cache_reads / max(1, cache_creates + cache_reads + uncached):.1%}",
    ]
    if errors:
        lines += ["", "Errors:", *[f"  {n}: {e[:120]}" for n, e in errors]]
    summary = "\n".join(lines)
    summary_path.write_text(summary, encoding="utf-8")
    print()
    print(summary)
    print(f"\nResults: {results_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
