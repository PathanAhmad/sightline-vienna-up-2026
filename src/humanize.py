"""Translate machine-coded reasons into action-oriented English.

The classifier in src/classify.py emits short codes
("warning_tape_visible=no", "max gap 31m > 5m between meter 2 and meter
33"). Those are accurate but a foreman reading them sees a diagnostic,
not an instruction. This module owns the mapping from those codes to
imperative sentences a crew can act on at the trench: "Re-shoot one
photo showing the orange warning tape", not "no warning tape visible".

Public:
    VERDICT_LABEL — verdict code → display label
    humanize_reasons(field) — semicolon-joined reasons → action sentences
    humanize_reason(reason) — one reason → one action sentence
"""
from __future__ import annotations

import re


VERDICT_LABEL: dict[str, str] = {
    "RED": "Needs review",
    "YELLOW": "Warning",
    "GREEN": "Passing",
}


# Fixed-string reasons emitted verbatim by classify.py or hand-written
# in the demo fixtures.
_FIXED_SUBS: dict[str, str] = {
    "personal_data_visible":
        "Re-shoot the affected photo — keep faces and licence plates "
        "out of frame.",
    "latlon_vs_address_disagree":
        "Re-take photos here — the GPS does not match the printed "
        "address.",
    "off_cluster":
        "Re-shoot at this section — the photo's location is far from "
        "the rest of the section.",
    "no compliant photos snapped":
        "Re-shoot 4–6 photos along this section, one for each work "
        "stage (open trench, sand bedding, cable laid, warning tape).",
    "no photos snapped to this segment":
        "Re-shoot 4–6 photos along this section, one for each work "
        "stage (open trench, sand bedding, cable laid, warning tape).",
}


# Templated reasons. Order matters: more specific patterns first so
# they preempt the catch-alls.
_REGEX_SUBS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"relevance=portrait"),
     "Re-shoot — the photo was a portrait of a person, not the trench."),
    (re.compile(r"relevance=off_topic"),
     "Re-shoot — the photo was not of the trench."),
    (re.compile(r"relevance=unreadable"),
     "Re-shoot — the photo was too blurry or dark."),
    (re.compile(r"relevance=(\w+)"),
     r"Re-shoot — the previous photo was flagged as \1."),
    (re.compile(r"snap_distance=(\d+)m"),
     r"Re-shoot — the photo was \1 m off the trench centreline."),
    (re.compile(r"phase=paper_label"),
     "Re-shoot — the photo showed only the paper label, no trench."),
    (re.compile(r"phase=staging"),
     "Re-shoot — the photo showed staging only, not the trench."),
    (re.compile(r"phase=other"),
     "Re-shoot — the photo did not show a recognised work stage."),
    (re.compile(r"phase=(\w+)"),
     r"Re-shoot — the photo at the \1 stage showed no trench evidence."),
    # Demo fixture phrasing: "<phase> phase but <feature> not visible".
    # Maps to a concrete re-shoot instruction.
    (re.compile(r"(\w+) phase but (.+?) not visible"),
     r"Re-shoot one photo showing the \2, during the \1 stage."),
    (re.compile(r"warning_tape_visible=no"),
     "Re-shoot one photo showing the orange warning tape on top of "
     "the cable."),
    (re.compile(r"warning_tape_visible=occluded"),
     "Re-shoot — keep the warning tape clearly visible in the frame."),
    (re.compile(r"sand_bedding_visible=no"),
     "Re-shoot one photo showing the sand bedding under the cable."),
    (re.compile(r"sand_bedding_visible=occluded"),
     "Re-shoot — keep the sand bedding clearly visible in the frame."),
    (re.compile(r"duct_visible=no"),
     "Re-shoot one photo showing the duct / conduit clearly."),
    (re.compile(r"duct_visible=occluded"),
     "Re-shoot — keep the duct unblocked in the frame."),
    (re.compile(r"density \d+/(\d+)m below 1/10m"),
     r"Re-shoot — take more photos along the \1 m section "
     r"(one every 5 m at minimum)."),
    (re.compile(
        r"first compliant photo at meter (\d+) "
        r"\(>(\d+)m from start\)"),
     r"Re-shoot — cover the first \2 m of the section (no usable "
     r"photo before meter \1)."),
    (re.compile(
        r"last compliant photo at meter (\d+) "
        r"\(>(\d+)m from end of (\d+)m\)"),
     r"Re-shoot — cover the last \2 m of the \3 m section (no usable "
     r"photo after meter \1)."),
    (re.compile(
        r"max gap (\d+)m > (\d+)m between meter "
        r"(\d+) and meter (\d+)"),
     r"Re-shoot one photo every \2 m between meter \3 and meter \4 "
     r"(currently a \1 m gap)."),
    (re.compile(r"(\d+) personal-data photo\(s\)"),
     r"Re-shoot \1 photo(s) without faces or licence plates in frame."),
    (re.compile(r"(\d+) personal-data photo excluded"),
     r"Re-shoot \1 photo(s) without faces or licence plates in frame."),
    (re.compile(r"(\d+) off-topic photo excluded"),
     r"Re-shoot \1 photo(s) showing the actual trench, not other "
     r"subjects."),
    (re.compile(r"^no other photos$"),
     "Re-shoot enough photos to cover this section after the "
     "excluded ones."),
    (re.compile(r"duplicate photo reused on this segment.*"),
     "Re-shoot fresh photos for this section — duplicates of older "
     "submissions were detected."),
    (re.compile(r"duplicate photo reused"),
     "Re-shoot fresh photos for this section — duplicates of older "
     "submissions were detected."),
    (re.compile(
        r"lat/lon and printed address disagree by ([\d.]+) km "
        r"\(off-cluster\)"),
     r"Re-take photos here — the GPS is \1 km away from the printed "
     r"address; the photo is not where it claims."),
    (re.compile(
        r"lat/lon and printed address disagree by ([\d.]+) km"),
     r"Re-take photos here — the GPS is \1 km away from the printed "
     r"address."),
]


# Engineer-speak stage codes get a friendlier surface form when they
# survive the substitutions above. Past-tense "tape_laid" reads as
# jargon; "tape-laying" reads as a stage of work.
_STAGE_NAMES: dict[str, str] = {
    "tape_laid": "tape-laying",
    "sand_bedded": "sand-bedding",
    "duct_laid": "duct-laying",
    "depth_measure": "depth-measuring",
    "paper_label": "paper-label",
    "backfilled": "back-filled",
}


def humanize_reason(reason: str) -> str:
    """Translate one reason string into an action sentence for the crew."""
    r = reason.strip()
    if not r:
        return r

    # classify.py rolls up N identical per-photo failures into "Nx <code>"
    # to keep the segment reasons compact. Recurse so the inner code goes
    # through the full action mapping — otherwise it would leak raw
    # codes like "warning_tape_visible=no" into the card text.
    m = re.match(r"^(\d+)x (.+)$", r)
    if m:
        count = m.group(1)
        inner = humanize_reason(m.group(2))
        return f"({count} photos) {inner}"

    if r in _FIXED_SUBS:
        r = _FIXED_SUBS[r]
    else:
        for pattern, repl in _REGEX_SUBS:
            new_r, n = pattern.subn(repl, r)
            if n:
                r = new_r
    for code, friendly in _STAGE_NAMES.items():
        r = r.replace(code, friendly)
    return r


def humanize_reasons(reasons_field: str) -> str:
    """Split a semicolon-joined reasons field and humanize each entry."""
    if not reasons_field:
        return "Re-check this section on site — no specific issue recorded."
    parts = [p for p in (s.strip() for s in reasons_field.split(";")) if p]
    return " ".join(humanize_reason(p) for p in parts)
