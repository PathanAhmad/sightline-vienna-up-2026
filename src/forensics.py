"""Stage 2 — Forensics (local, no API cost).

What it does: computes a perceptual hash (pHash) for every photo and
clusters near-duplicates. Also runs Error Level Analysis (ELA) for a
weak tamper hint. Picks one representative per cluster — that's the
photo that goes to the (paid) Claude vision call in stage 3.

Reads:
    - data/processed/manifest.sqlite (photo_id, rel_path)
    - the photo bytes from disk

Writes:
    - data/processed/forensics.jsonl
        {photo_id, phash, phash_cluster_id, is_phash_representative,
         ela_score, ela_flag}

Why dedup before readqc:
    Roughly 600 known duplicates exist via N_ filename prefixes. If we
    send each photo to Claude individually we pay for ~3,929 calls.
    Dedup first → ~3,300 unique → ~$15 instead of ~$18, AND duplicates
    inherit their representative's QC result for free.

Validation:
    Compare our pHash clusters against the ground-truth duplicate pairs
    from `N_` prefixes and `— копия` suffixes (~600 known pairs). Recall
    > 95% on those pairs means the threshold (Hamming-6) is right.
"""

from __future__ import annotations


def compute_phashes() -> None:
    """For every photo in manifest, compute imagehash.phash. Store in memory."""
    raise NotImplementedError("see PLAN.md → Data contracts → forensics")


def cluster_phashes(hamming_threshold: int = 6) -> None:
    """Single-linkage cluster within Hamming distance ≤ threshold."""
    raise NotImplementedError("see PLAN.md → Data contracts → forensics")


def pick_representatives() -> None:
    """One representative per cluster. Lowest photo_id wins (deterministic)."""
    raise NotImplementedError("see PLAN.md → Data contracts → forensics")


def ela_pass() -> None:
    """Pillow-based Error Level Analysis. Score = mean delta. ela_flag = score > threshold."""
    raise NotImplementedError("see PLAN.md → Data contracts → forensics")


def main() -> int:
    """Entry point for `python -m src.forensics`. Writes forensics.jsonl."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
