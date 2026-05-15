"""Stage 5 — Classify (per-segment rollup → GREEN/YELLOW/RED).

What it does: groups photos by segment_id, sorts them by position along
the segment, applies the 5-meter density rule (Layer A) AND the photo
quality filter (Layer B), and produces one verdict per segment.

Reads:
    - data/processed/readqc.jsonl   (per-photo checks)
    - data/processed/geomatch.csv   (photo → segment + position)
    - data/processed/forensics.jsonl (to drop duplicates from compliant count)
    - data/geo/...Trenches.geojson  (segment lengths)

Writes:
    - data/processed/verdicts.csv
        See PLAN.md → Data contracts → classify for the column list.

What counts as a "compliant photo" for the density rule:
    - readqc.relevance == "scorable"
    - readqc.personal_data_visible == "no"
    - forensics.is_phash_representative == true (or, if false, only
      counted once per cluster on this segment)
    - geomatch.latlon_vs_address_flag == false
    - The phase-relevant subset of {warning_tape, sand_bedding, side_view,
      depth_reference, duct, pipe_ends_sealed} is all "yes". "occluded"
      is treated as a fail, not partial credit (keep the rule sharp; we
      can soften later if recall is bad).

Verdict rule (PLAN.md Layer A):
    GREEN  — at least one compliant photo per 5 m of segment length AND
             no gap > 5 m between consecutive compliant photos AND the
             start and end of the segment are each within 5 m of a
             compliant photo.
    YELLOW — photos exist but the GREEN rule fails (gaps, or quality
             checks fail).
    RED    — fewer than 1 compliant photo per 10 m of segment length, OR
             no photos at all.

The `reasons` column is a semicolon-joined human-readable string —
that's what shows up in the deficiency report and the demo side panel.
Examples:
    "max gap 12m > 5m between meter 18 and meter 30"
    "2 photos personal-data flagged"
    "no photos snapped to this segment"
"""

from __future__ import annotations


def is_photo_compliant(readqc_row: dict, geomatch_row: dict) -> tuple[bool, list[str]]:
    """Return (compliant?, list of reasons it failed if not)."""
    raise NotImplementedError("see PLAN.md → Data contracts → classify")


def segment_verdict(segment_length_m: float, compliant_positions_m: list[float]) -> tuple[str, float, list[str]]:
    """Return (verdict, max_gap_m, reasons). Inputs are meter offsets along the segment."""
    raise NotImplementedError("see PLAN.md → Data contracts → classify")


def main() -> int:
    """Entry point for `python -m src.classify`. Writes verdicts.csv."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
