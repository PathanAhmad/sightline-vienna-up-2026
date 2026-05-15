"""Stage 6 — Report (deliverables for the partner + the demo).

What it does: turns verdicts.csv into a deficiency report and the
supporting CSVs (not-classified photos, personal-data-flagged photos).
Also renders a one-page HTML summary. The live Streamlit map is in
app.py — this module produces the static handover artifacts.

Reads:
    - data/processed/verdicts.csv
    - data/processed/geomatch.csv
    - data/processed/readqc.jsonl
    - data/processed/forensics.jsonl

Writes:
    - data/processed/report/deficiency.csv
        One row per RED or YELLOW segment: segment_id, fcp, verdict,
        length_m, photo_count, max_gap_m, reasons. This is what we hand
        to APG/ÖGIG.
    - data/processed/report/not_classified.csv
        photo_id, rel_path, reason — for photos dropped by the relevance
        gate (portrait/off_topic/unreadable). Lets the partner ask the
        contractor for retakes.
    - data/processed/report/personal_data.csv
        photo_id, rel_path — NIS2-sensitive photos. Same retake bucket.
    - data/processed/report/summary.html
        Title + 4 numbers (segments green/yellow/red, photos scored,
        photos dropped, duplicates found) + cost.

Design rule:
    Every output file is one human-readable artifact. No nested JSON,
    no surprises. A reviewer should be able to open deficiency.csv in
    Excel and start working immediately.
"""

from __future__ import annotations


def write_deficiency_csv() -> None:
    """One row per non-green segment. Sorted by fcp, then by length descending."""
    raise NotImplementedError("see PLAN.md → Data contracts → report")


def write_not_classified_csv() -> None:
    """One row per photo dropped by the relevance gate, with reason."""
    raise NotImplementedError("see PLAN.md → Data contracts → report")


def write_personal_data_csv() -> None:
    """One row per photo flagged personal_data_visible=yes."""
    raise NotImplementedError("see PLAN.md → Data contracts → report")


def write_summary_html() -> None:
    """One-page overview. No JS. Reads the CSVs above."""
    raise NotImplementedError("see PLAN.md → Data contracts → report")


def main() -> int:
    """Entry point for `python -m src.report`. Writes the report/ directory."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
