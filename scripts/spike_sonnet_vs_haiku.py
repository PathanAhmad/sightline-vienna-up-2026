"""
Side-by-side comparison: Haiku 4.5 vs Sonnet 4.6 on photos we expect to be hard:
  - night flashlight shot (low light)
  - tape laid over backfill (multi-phase / priority test)
  - paper-label-over-overlay occlusion
  - DMS-with-comma lat/lon (unusual format)
  - photo where Haiku misread the latlon last time

For each, compare:
  - phase + relevance
  - the 5 visual checks
  - overlay_latlon transcription accuracy
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
PHOTOS_DIR = REPO_ROOT / "data" / "Fotos" / "Fotos"
EXEMPLARS_DIR = REPO_ROOT / "data" / "Beispiele" / "Beispiele"

# Re-use the v2 prompt from the main spike — import would be cleaner but spike is throwaway
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from spike_qc_schema import SYSTEM_INSTRUCTIONS, EXEMPLARS, QCResult, b64, build_exemplar_prefix  # noqa: E402

HARD_CASES = [
    # filename, why it's hard, expected ground truth (rough)
    ("WhatsApp Image 2024-11-21 at 20_03_03 (1).jpeg",
     "Night flashlight shot at a roadside shrine. Worker + paper labels in low light."),
    ("1_IMG-20240814-WA0045.jpg",
     "Yellow ACHTUNG-tape laid OVER backfilled trench with depth rods still in frame. Should be tape_laid, not depth_measure."),
    ("WhatsApp Image  (303).jpg",
     "Overlay text is partly occluded by a paper label held in front of the camera."),
    ("1_WhatsApp Image 2024-09-04 at 22_33_35.jpeg",
     "Lat/lon uses DMS with COMMA decimal separator: 46°33'29,30965\"N. Unusual format."),
    ("WhatsApp Image 2024-08-26 at 20_50_39 (1).jpeg",
     "Haiku misread the latlon last time — said 46°23' when overlay shows 46°33'. Test Sonnet."),
]


def run_one(client: anthropic.Anthropic, model: str, exemplar_prefix: list[dict], photo: Path) -> tuple[QCResult | None, dict, str | None]:
    media, data = b64(photo)
    try:
        resp = client.messages.parse(
            model=model,
            max_tokens=1024,
            system=[{"type": "text", "text": SYSTEM_INSTRUCTIONS, "cache_control": {"type": "ephemeral"}}],
            messages=[{
                "role": "user",
                "content": list(exemplar_prefix) + [
                    {"type": "text", "text": "Now score the following photo per the schema:"},
                    {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}},
                ],
            }],
            output_format=QCResult,
        )
    except Exception as e:
        return None, {}, f"{type(e).__name__}: {e}"
    return resp.parsed_output, {
        "input_tokens": resp.usage.input_tokens,
        "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
    }, None


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        env = REPO_ROOT / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    client = anthropic.Anthropic()
    exemplar_prefix = build_exemplar_prefix()

    print(f"{'='*100}")
    print(f"Haiku 4.5 vs Sonnet 4.6 head-to-head on 5 hard cases")
    print(f"{'='*100}\n")

    for fname, why in HARD_CASES:
        path = PHOTOS_DIR / fname
        if not path.exists():
            print(f"!! Missing: {fname}\n"); continue

        print(f"--- {fname} ---")
        print(f"    Why hard: {why}")

        for model in ["claude-haiku-4-5", "claude-sonnet-4-6"]:
            result, usage, err = run_one(client, model, exemplar_prefix, path)
            if err:
                print(f"    [{model:20s}] FAIL: {err}"); continue
            r = result
            print(f"    [{model:20s}] {r.relevance:9s} {r.phase:14s} "
                  f"tape={r.warning_tape_visible:8s} sand={r.sand_bedding_visible:8s} "
                  f"depth={r.depth_reference_visible:3s} duct={r.duct_visible:8s}")
            print(f"    {'':22s} latlon={r.overlay_latlon!s:<55s}")
            print(f"    {'':22s} paper={r.paper_label_code!s}")
            print(f"    {'':22s} note: {r.note[:200]}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
