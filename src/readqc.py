"""Stage 3 — Read & QC the photo with Claude Sonnet 4.6 vision.

What it does: one vision call per representative photo (post-dedup).
Returns the relevance gate, the phase classification, the 7 visual
compliance checks, the overlay fields (date, address, lat/lon), and
the paper-label code — all in one structured JSON response.

Reads:
    - data/processed/forensics.jsonl  (only rows with is_phash_representative=true)
    - photo bytes from disk

Writes:
    - data/processed/readqc.jsonl
        See PLAN.md → Data contracts → readqc for the full schema.
    - data/processed/readqc_failures.json
        photo_ids that errored out, with the exception string. Allows a
        rerun without re-paying for the ones that succeeded.

Cost ceiling:
    ~3,400 unique photos × ~$0.0045 ≈ $15 total. Stop if cost crosses $25.

Prompt construction:
    - System message: SYSTEM_INSTRUCTIONS string (see spike_qc_schema.py)
    - User message: 4 exemplar (image, caption) pairs as a cached prefix
      [cache_control on the LAST block of the exemplar set], then the
      photo under test, then the schema instruction.
    - Response: client.messages.parse(..., output_format=QCResult).
    - Reference: scripts/spike_qc_schema.py is the working template;
      the spike validates the v2 5-check schema and this production
      module extends to the 7-check schema in PLAN.md.

Resume / restart behaviour:
    If readqc.jsonl already exists, skip photo_ids already present.
    This lets us interrupt mid-batch without losing progress.
"""

from __future__ import annotations


def build_exemplar_prefix() -> list[dict]:
    """Load the 4 root exemplars from Beispiele/ as cached image+caption blocks."""
    raise NotImplementedError("see PLAN.md → Data contracts → readqc")


def score_one_photo(photo_id: str, rel_path: str) -> dict:
    """Call Claude Sonnet 4.6 vision on one photo. Return the parsed QCResult as dict."""
    raise NotImplementedError("see PLAN.md → Data contracts → readqc")


def run_batch() -> None:
    """Iterate representatives, call score_one_photo, append to readqc.jsonl."""
    raise NotImplementedError("see PLAN.md → Data contracts → readqc")


def main() -> int:
    """Entry point for `python -m src.readqc`. Resumable batch."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
