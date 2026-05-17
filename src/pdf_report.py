"""Field-friendly PDF deficiency report.

Produces an A4 PDF a foreman or reviewer can print, mark up, and bring to
the trench. Visual hierarchy:

    Page 1
        Accent header band (brand)
        Section-level stat boxes (Total / Passing / Warnings / Needs review)
        Insight sentence (top failure mode)
        Photo intake table (uploaded, passed, flagged, duplicates, …)
    Page 2+
        Sections needing attention — grouped by FCP, one card per
        section. Severity pill, length, photo coverage, biggest gap,
        plain-language reasons.
    Final page
        Passing sections (one compact list — IDs only)
        Severity legend
        Eight checks the tool applied

The page header band, page number, and "Generated" timestamp render on
every page via the page-template callback.

Public surface:
    compute_photo_intake(readqc, forensics, geomatch) -> PhotoIntake
    build_pdf(verdicts, source="live", intake=None) -> bytes
"""
from __future__ import annotations

import io
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from src.humanize import VERDICT_LABEL, humanize_reason, humanize_reasons


# ---- Colour tokens (mirror src/ui/tokens.py) ----------------------------

C_ACCENT = colors.HexColor("#0369a1")
C_ACCENT_DARK = colors.HexColor("#075985")
C_TEXT = colors.HexColor("#0f172a")
C_TEXT_2 = colors.HexColor("#475569")
C_MUTED = colors.HexColor("#64748b")
C_BORDER = colors.HexColor("#e5e7eb")
C_SURFACE = colors.HexColor("#ffffff")
C_RED = colors.HexColor("#dc2626")
C_YELLOW = colors.HexColor("#ca8a04")
C_GREEN = colors.HexColor("#16a34a")
C_REASON_BG = colors.HexColor("#f5f3ef")


# ---- Page geometry ------------------------------------------------------

PAGE_W, PAGE_H = A4
MARGIN_X = 16 * mm
MARGIN_TOP = 26 * mm  # leaves room for the header band
MARGIN_BOTTOM = 16 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X


# ---- Paragraph styles ---------------------------------------------------

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"

S_H1 = ParagraphStyle(
    "H1", fontName=_FONT_BOLD, fontSize=20, leading=24,
    textColor=C_TEXT, spaceAfter=2,
)
S_H2 = ParagraphStyle(
    "H2", fontName=_FONT_BOLD, fontSize=13, leading=16,
    textColor=C_TEXT, spaceBefore=10, spaceAfter=6,
)
S_FCP = ParagraphStyle(
    "FCP", fontName=_FONT_BOLD, fontSize=10, leading=12,
    textColor=C_ACCENT, spaceBefore=12, spaceAfter=4,
    letterSpacing=0.6,
)
S_BODY = ParagraphStyle(
    "Body", fontName=_FONT, fontSize=10, leading=14,
    textColor=C_TEXT,
)
S_BODY_MUTED = ParagraphStyle(
    "BodyMuted", fontName=_FONT, fontSize=9.5, leading=13,
    textColor=C_MUTED,
)
S_LEAD = ParagraphStyle(
    "Lead", fontName=_FONT, fontSize=11, leading=16,
    textColor=C_TEXT_2, spaceAfter=4,
)
S_CARD_REF = ParagraphStyle(
    "CardRef", fontName=_FONT_BOLD, fontSize=12, leading=14,
    textColor=C_TEXT,
)
S_CARD_ADDRESS = ParagraphStyle(
    "CardAddress", fontName=_FONT, fontSize=9, leading=12,
    textColor=C_MUTED, spaceBefore=2,
)
S_CARD_META = ParagraphStyle(
    "CardMeta", fontName=_FONT, fontSize=9.5, leading=13,
    textColor=C_TEXT_2,
)
S_REASON = ParagraphStyle(
    "Reason", fontName=_FONT, fontSize=10, leading=14,
    textColor=C_TEXT,
)
S_REASON_HEAD = ParagraphStyle(
    "ReasonHead", fontName=_FONT_BOLD, fontSize=8.5, leading=11,
    textColor=C_TEXT_2, spaceAfter=2, letterSpacing=0.5,
)
S_STAT_LABEL = ParagraphStyle(
    "StatLabel", fontName=_FONT, fontSize=8.5, leading=11,
    textColor=C_MUTED, alignment=1, letterSpacing=0.5,
)
S_STAT_VALUE = ParagraphStyle(
    "StatValue", fontName=_FONT_BOLD, fontSize=24, leading=28,
    textColor=C_TEXT, alignment=1,
)
S_PILL = ParagraphStyle(
    "Pill", fontName=_FONT_BOLD, fontSize=9, leading=11,
    textColor=colors.white, alignment=1,
)
S_LIST_DENSE = ParagraphStyle(
    "ListDense", fontName=_FONT, fontSize=9.5, leading=13,
    textColor=C_TEXT_2, leftIndent=10, spaceAfter=2,
)
S_INTAKE_LABEL = ParagraphStyle(
    "IntakeLabel", fontName=_FONT, fontSize=10, leading=13,
    textColor=C_TEXT,
)
S_INTAKE_VALUE = ParagraphStyle(
    "IntakeValue", fontName=_FONT_BOLD, fontSize=12, leading=13,
    textColor=C_TEXT, alignment=2,
)


# ---- Header / footer ----------------------------------------------------

def _draw_chrome(canvas, doc, generated_on: str) -> None:
    """Accent header band and footer on every page."""
    canvas.saveState()

    # Accent band.
    band_h = 14 * mm
    canvas.setFillColor(C_ACCENT)
    canvas.rect(0, PAGE_H - band_h, PAGE_W, band_h, fill=1, stroke=0)

    canvas.setFillColor(colors.white)
    canvas.setFont(_FONT_BOLD, 9)
    canvas.drawString(
        MARGIN_X, PAGE_H - band_h + 5.2 * mm,
        "TRENCH PHOTO DEFICIENCY REPORT",
    )
    canvas.setFont(_FONT, 8.5)
    canvas.drawRightString(
        PAGE_W - MARGIN_X, PAGE_H - band_h + 5.2 * mm,
        "Sightline  ·  Photo QC pipeline",
    )

    # Hairline under the band.
    canvas.setStrokeColor(C_ACCENT_DARK)
    canvas.setLineWidth(0.6)
    canvas.line(
        0, PAGE_H - band_h, PAGE_W, PAGE_H - band_h,
    )

    # Footer line + meta.
    canvas.setStrokeColor(C_BORDER)
    canvas.setLineWidth(0.4)
    canvas.line(
        MARGIN_X, 13 * mm,
        PAGE_W - MARGIN_X, 13 * mm,
    )
    canvas.setFillColor(C_MUTED)
    canvas.setFont(_FONT, 8)
    canvas.drawString(MARGIN_X, 9 * mm, f"Generated {generated_on}")
    canvas.drawRightString(
        PAGE_W - MARGIN_X, 9 * mm, f"Page {doc.page}",
    )
    canvas.restoreState()


# ---- Building blocks ----------------------------------------------------

def _pill(verdict_raw: str) -> Table:
    """Coloured rounded pill for the verdict."""
    label = VERDICT_LABEL.get(verdict_raw, verdict_raw.title())
    bg = C_RED if verdict_raw == "RED" else (
        C_YELLOW if verdict_raw == "YELLOW" else C_GREEN
    )
    t = Table(
        [[Paragraph(label, S_PILL)]],
        colWidths=[28 * mm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _stat_box(label: str, value: str, accent: colors.Color | None = None) -> Table:
    """One of the at-a-glance summary boxes on the cover."""
    value_style = ParagraphStyle(
        "StatValueOverride",
        parent=S_STAT_VALUE,
        textColor=accent or C_TEXT,
    )
    t = Table(
        [
            [Paragraph(value, value_style)],
            [Paragraph(label.upper(), S_STAT_LABEL)],
        ],
        colWidths=[(CONTENT_W - 18) / 4],
        rowHeights=[34, 14],
    )
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, C_BORDER),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("BACKGROUND", (0, 0), (-1, -1), C_SURFACE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (0, 0), "BOTTOM"),
        ("VALIGN", (0, 1), (0, 1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _section_card(row: dict, address: str | None = None) -> Table:
    """One per non-passing segment: header (ID + pill + optional
    address), meta line, action box.

    Returned as a single outer Table so KeepTogether can prevent it
    from splitting across a page break.
    """
    verdict = str(row.get("verdict") or "").upper()
    seg_id = str(row.get("segment_id") or "")
    short_id = _short_segment_id(seg_id)
    fcp = str(row.get("fcp_name") or "—")

    length_raw = row.get("length_m")
    try:
        length_str = f"{float(length_raw):.0f} m"
    except (TypeError, ValueError):
        length_str = "—"

    photos = int(row.get("photo_count") or 0)
    ok = int(row.get("compliant_photo_count") or 0)
    photo_line = (
        f"{ok} of {photos} photo{'s' if photos != 1 else ''} "
        "passed the per-photo checks"
    )
    if photos == 0:
        photo_line = "No photos submitted for this section"

    # Surface the biggest uncovered stretch when it isn't already
    # obvious from "no photos submitted". For 0-photo sections the gap
    # equals section length, so the second clause would be redundant.
    try:
        gap_m = float(row.get("max_gap_m") or 0.0)
    except (TypeError, ValueError):
        gap_m = 0.0
    gap_clause = ""
    if photos > 0 and gap_m > 0:
        gap_clause = (
            f" &nbsp;·&nbsp; Biggest uncovered stretch "
            f"<b>{gap_m:.0f} m</b>"
        )

    reasons_text = humanize_reasons(str(row.get("reasons") or ""))

    # Header row: section ref + optional address stacked on the left,
    # pill on the right.
    ref_p = Paragraph(
        f"Section <b>{short_id}</b> "
        f"<font color='#64748b'>·</font> "
        f"<font color='#475569'>{fcp}</font>",
        S_CARD_REF,
    )
    ref_cell: list = [ref_p]
    if address:
        ref_cell.append(Paragraph(address, S_CARD_ADDRESS))
    header = Table(
        [[ref_cell, _pill(verdict)]],
        colWidths=[CONTENT_W - 30 * mm - 16, 30 * mm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    meta_p = Paragraph(
        f"Length <b>{length_str}</b> &nbsp;·&nbsp; {photo_line}"
        f"{gap_clause}",
        S_CARD_META,
    )

    reason_inner = Table(
        [
            [Paragraph("DO NEXT", S_REASON_HEAD)],
            [Paragraph(reasons_text, S_REASON)],
        ],
        colWidths=[CONTENT_W - 24],
    )
    reason_inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_REASON_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
    ]))

    outer = Table(
        [
            [header],
            [meta_p],
            [reason_inner],
        ],
        colWidths=[CONTENT_W],
    )
    outer.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, C_BORDER),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("BACKGROUND", (0, 0), (-1, -1), C_SURFACE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (0, 0), 10),
        ("BOTTOMPADDING", (0, 0), (0, 0), 4),
        ("TOPPADDING", (0, 1), (0, 1), 0),
        ("BOTTOMPADDING", (0, 1), (0, 1), 8),
        ("TOPPADDING", (0, 2), (0, 2), 0),
        ("BOTTOMPADDING", (0, 2), (0, 2), 10),
    ]))
    return outer


# ---- Insight: pick the dominant failure mode ---------------------------

# Each bucket lists every reason-string substring that should count as
# that failure mode. classify.py phrasing comes first, demo-fixture
# phrasing second. Order matters: more specific patterns first.
_FAILURE_BUCKETS: list[tuple[tuple[str, ...], str]] = [
    (("no compliant photos snapped", "no photos snapped",
      "no photos submitted"),
     "no photos at all on the section"),
    (("relevance=", "off-topic photo"),
     "photos taken were not usable trench shots"),
    (("max gap", "gap between meter"),
     "long gaps between photos along the trench"),
    (("phase=paper_label",),
     "photos showed only paper labels, not the trench"),
    (("warning_tape_visible", "warning tape not visible"),
     "missing or hidden warning tape"),
    (("sand_bedding_visible", "no sand bedding"),
     "missing or hidden sand bedding"),
    (("duct_visible",), "missing or hidden duct"),
    (("personal_data", "personal-data"),
     "personal data in photos that must be re-shot"),
    (("latlon_vs_address_disagree", "printed address disagree"),
     "photo GPS not matching the printed address"),
    (("off_cluster", "off-cluster"),
     "photos located far from the rest of the section"),
    (("snap_distance=",),
     "photos off the trench centreline"),
    (("first compliant photo at meter",),
     "no coverage at the start of the section"),
    (("last compliant photo at meter",),
     "no coverage at the end of the section"),
    (("density",), "too few photos for the section length"),
    (("duplicate photo reused",),
     "duplicate photos reused across jobs"),
]


def _dominant_issue(bad_rows: list[dict]) -> str | None:
    """Pick the failure mode that explains the most non-passing sections.

    Returns None if no clear dominant mode emerges (or if there are no
    failures at all). A section is counted at most once per bucket so a
    single section with many overlapping reasons doesn't dominate.
    """
    if not bad_rows:
        return None
    bucket_counts: Counter[str] = Counter()
    for r in bad_rows:
        seen: set[str] = set()
        for raw in str(r.get("reasons") or "").split(";"):
            raw = raw.strip()
            for keys, label in _FAILURE_BUCKETS:
                if label in seen:
                    continue
                if any(k in raw for k in keys):
                    bucket_counts[label] += 1
                    seen.add(label)
                    break
    if not bucket_counts:
        return None
    top_label, top_count = bucket_counts.most_common(1)[0]
    if top_count < 2:
        return None
    return top_label


# ---- Photo intake -------------------------------------------------------

@dataclass(frozen=True)
class PhotoIntake:
    """Photo-level counts that augment the segment-level verdict counts.

    Frozen so it can be a cache key argument alongside the verdicts
    DataFrame in download.py.
    """
    n_uploaded: int
    n_passed_per_photo: int
    n_personal_data: int
    n_duplicates: int
    n_not_classified: int
    n_geo_mismatch: int
    n_ela_flag: int
    total_cost_usd: float


def compute_segment_addresses(
    geomatch: list[dict],
    readqc: list[dict],
) -> dict[str, str]:
    """For each segment_id, pick the address most often stamped on the
    photos snapped to it. Gives every per-section card a physical place
    the foreman can find without consulting a separate map.

    Segments with no photos at all (RED 0-photo case) get no entry; the
    card renders without an address line in that case.
    """
    address_by_photo = {
        r["photo_id"]: (r.get("overlay_address") or "").strip()
        for r in readqc
        if r.get("photo_id")
    }
    by_segment: dict[str, Counter[str]] = defaultdict(Counter)
    for g in geomatch:
        seg = (g.get("segment_id") or "").strip()
        addr = address_by_photo.get(g.get("photo_id") or "", "")
        if seg and addr:
            by_segment[seg][addr] += 1
    return {
        seg: counts.most_common(1)[0][0]
        for seg, counts in by_segment.items()
    }


def compute_photo_intake(
    readqc: list[dict],
    forensics: list[dict],
    geomatch: list[dict],
) -> PhotoIntake:
    """Roll up the per-photo artifacts into the headline counts the
    cover renders. Same logic as src/report.py's summary HTML, just
    returned as a frozen struct."""
    n_uploaded = len(readqc)
    n_personal_data = sum(
        1 for r in readqc if r.get("personal_data_visible") == "yes"
    )
    n_not_classified = sum(
        1 for r in readqc
        if (r.get("relevance") or "scorable") != "scorable"
    )
    n_passed_per_photo = sum(
        1 for r in readqc
        if (r.get("relevance") or "scorable") == "scorable"
        and r.get("personal_data_visible") != "yes"
    )
    n_duplicates = sum(
        1 for r in forensics if not r.get("is_phash_representative", True)
    )
    n_ela_flag = sum(1 for r in forensics if r.get("ela_flag"))
    n_geo_mismatch = sum(
        1 for r in geomatch
        if str(r.get("latlon_vs_address_flag", "")).lower() == "true"
    )
    total_cost = sum(float(r.get("cost_usd") or 0.0) for r in readqc)
    return PhotoIntake(
        n_uploaded=n_uploaded,
        n_passed_per_photo=n_passed_per_photo,
        n_personal_data=n_personal_data,
        n_duplicates=n_duplicates,
        n_not_classified=n_not_classified,
        n_geo_mismatch=n_geo_mismatch,
        n_ela_flag=n_ela_flag,
        total_cost_usd=total_cost,
    )


def _intake_table(intake: PhotoIntake) -> Table:
    """Two-column table: human label on the left, count on the right.

    Rows render even when a count is zero — absent rows would be a
    silent gap in the comprehensive view the foreman is meant to scan.
    """
    rows: list[list] = [
        [Paragraph("Photos uploaded", S_INTAKE_LABEL),
         Paragraph(f"<b>{intake.n_uploaded:,}</b>", S_INTAKE_VALUE)],
        [Paragraph("Passed every per-photo check", S_INTAKE_LABEL),
         Paragraph(f"<b>{intake.n_passed_per_photo:,}</b>", S_INTAKE_VALUE)],
        [Paragraph(
            "Duplicates caught "
            "<font color='#64748b'>(same photo re-submitted)</font>",
            S_INTAKE_LABEL,
        ),
            Paragraph(f"<b>{intake.n_duplicates:,}</b>", S_INTAKE_VALUE)],
        [Paragraph(
            "Flagged for re-shoot "
            "<font color='#64748b'>(faces / licence plates)</font>",
            S_INTAKE_LABEL,
        ),
            Paragraph(f"<b>{intake.n_personal_data:,}</b>", S_INTAKE_VALUE)],
        [Paragraph(
            "Not usable for QC "
            "<font color='#64748b'>(portrait, off-topic, unreadable)</font>",
            S_INTAKE_LABEL,
        ),
            Paragraph(f"<b>{intake.n_not_classified:,}</b>", S_INTAKE_VALUE)],
        [Paragraph(
            "GPS-vs-address mismatch "
            "<font color='#64748b'>(photo not where it claims)</font>",
            S_INTAKE_LABEL,
        ),
            Paragraph(f"<b>{intake.n_geo_mismatch:,}</b>", S_INTAKE_VALUE)],
    ]
    if intake.n_ela_flag:
        # Soft signal — only surface when non-zero. It's a hint that a
        # photo may have been re-saved by an editor, not a hard reject;
        # cover label stays low-key so it doesn't outshout the actionable
        # re-shoot / duplicate counts.
        rows.append([
            Paragraph(
                "Image possibly re-saved "
                "<font color='#64748b'>(low-confidence signal)</font>",
                S_INTAKE_LABEL,
            ),
            Paragraph(f"<b>{intake.n_ela_flag:,}</b>", S_INTAKE_VALUE),
        ])

    t = Table(rows, colWidths=[CONTENT_W - 28 * mm, 28 * mm])
    style: list[tuple] = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("BOX", (0, 0), (-1, -1), 0.6, C_BORDER),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
    ]
    for i in range(len(rows) - 1):
        style.append(("LINEBELOW", (0, i), (-1, i), 0.4, C_BORDER))
    t.setStyle(TableStyle(style))
    return t


# ---- Cover flowables ----------------------------------------------------

def _cover_flowables(
    verdicts: pd.DataFrame,
    source: str,
    generated_on: str,
    intake: PhotoIntake | None,
) -> list:
    counts = Counter(
        str(v).upper() for v in verdicts.get("verdict", pd.Series(dtype=str))
    )
    n_total = int(len(verdicts))
    n_green = int(counts.get("GREEN", 0))
    n_yellow = int(counts.get("YELLOW", 0))
    n_red = int(counts.get("RED", 0))
    n_bad = n_yellow + n_red

    bad_rows = [
        r for r in verdicts.to_dict("records")
        if str(r.get("verdict") or "").upper() != "GREEN"
    ]
    top_label = _dominant_issue(bad_rows)

    source_line = (
        "Live pipeline run" if source == "live" else "Demo dataset"
    )

    n_boilerplate = sum(1 for r in bad_rows if _is_no_photos_only(r))
    n_unique = n_bad - n_boilerplate

    prose = _load_baked_prose(source)
    intro_text = (prose or {}).get("intro") or _DEFAULT_INTRO

    out: list = [
        Paragraph("Trench photo deficiency report", S_H1),
        Paragraph(
            f"{source_line} &nbsp;·&nbsp; Generated {generated_on}",
            S_BODY_MUTED,
        ),
        Spacer(1, 12),
        Paragraph(intro_text, S_BODY),
        Spacer(1, 14),
        Paragraph("At a glance", S_H2),
    ]

    stat_row = Table(
        [[
            _stat_box("Sections scored", str(n_total)),
            _stat_box("Passing", str(n_green), accent=C_GREEN),
            _stat_box("Warnings", str(n_yellow), accent=C_YELLOW),
            _stat_box("Needs review", str(n_red), accent=C_RED),
        ]],
        colWidths=[CONTENT_W / 4] * 4,
    )
    stat_row.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    out.append(stat_row)
    out.append(Spacer(1, 14))

    # Interpretive paragraph. Prefer the Claude-generated version baked
    # by the pipeline (src/cover_prose.py); fall back to a templated
    # branch if there's no baked prose or the file's missing fields.
    situation_text = (prose or {}).get("situation") or _cover_context_text(
        n_total, n_bad, n_green, n_yellow, n_red,
        n_unique, n_boilerplate, top_label,
    )
    out.append(Paragraph(situation_text, S_LEAD))

    if intake is not None:
        out.append(Spacer(1, 14))
        out.append(Paragraph("Photo results", S_H2))
        out.append(Paragraph(
            "These numbers describe the photos that came in for this "
            "run. \"Passed every per-photo check\" is the pool of usable "
            "photos that actually count toward the one-photo-every-"
            "five-metres coverage rule — everything else either got "
            "rejected (faces visible, off-topic, unreadable) or never "
            "arrived in the first place.",
            S_BODY_MUTED,
        ))
        out.append(Spacer(1, 4))
        out.append(_intake_table(intake))

    out.append(Spacer(1, 12))
    closing_text = (prose or {}).get("closing") or _DEFAULT_CLOSING
    out.append(Paragraph(closing_text, S_BODY))
    return out


_DEFAULT_INTRO = (
    "This report covers every stretch of trench in the project that "
    "did not pass our automated photo review. A section is a short "
    "stretch of trench, usually between 10 and 50 metres long. The "
    "pages after this one are your re-shoot punch list — take the "
    "report to the site and tick each section as you re-shoot or "
    "re-do the work."
)

_DEFAULT_CLOSING = (
    "The body of this report groups the flagged sections by FCP route. "
    "Sections with the same issue (typically \"no photos yet\") are "
    "collapsed into a single block per route to keep the document "
    "short. The appendix at the back lists every passing section for "
    "completeness and describes the eight checks each photo runs "
    "through."
)


def _load_baked_prose(source: str) -> dict[str, str] | None:
    """Read pipeline-baked cover prose from disk. Live runs read from
    data/processed/report/cover_prose.json; demo fixture reads from
    demo_fixtures/cover_prose.json (committed). Either may be absent —
    the caller falls back to templated prose."""
    from src import paths
    from src.cover_prose import load_cover_prose

    if source == "live":
        candidates = [paths.REPORT_DIR / "cover_prose.json"]
    else:
        candidates = [paths.REPO_ROOT / "demo_fixtures" / "cover_prose.json"]
    return load_cover_prose(*candidates)


def _cover_context_text(
    n_total: int,
    n_bad: int,
    n_green: int,
    n_yellow: int,
    n_red: int,
    n_unique: int,
    n_boilerplate: int,
    top_label: str | None,
) -> str:
    """Two- or three-sentence interpretation of the at-a-glance numbers.

    Reads as plain prose so the cover doesn't feel like a dashboard
    export. The exact wording shifts with the shape of the run: a
    clean run, a partially-shot project, a mostly-good project with a
    handful of warnings, etc.
    """
    if n_total == 0:
        return (
            "There are no sections in this report. Run the QC pipeline "
            "first, then regenerate the report to see the results."
        )
    if n_bad == 0:
        return (
            f"All <b>{n_total}</b> sections passed every check. "
            "There is nothing to fix in the field — file the report "
            "with the rest of the job documentation."
        )

    bad_share = round(100 * n_bad / max(n_total, 1))

    if n_boilerplate == n_bad:
        # Common at the start of a project — nothing has been shot yet.
        return (
            f"<b>All {n_bad}</b> flagged sections are in the same "
            f"state: no photos have been uploaded for them yet. This "
            "is what a project looks like before the crew starts "
            "submitting evidence — submit the photos, re-run the QC "
            "pipeline, and regenerate the report to see what is "
            "actually passing."
        )

    sentences: list[str] = [
        f"<b>{n_bad}</b> of <b>{n_total}</b> sections need attention "
        f"({bad_share}% of the site)."
    ]
    if n_boilerplate and n_unique:
        sentences.append(
            f"<b>{n_boilerplate}</b> of those have no photos submitted "
            f"yet — those are grouped together by route in the body. "
            f"The remaining <b>{n_unique}</b> have specific issues to "
            "address (missing warning tape, photos in the wrong place, "
            "duplicates, and similar) and get their own per-section "
            "card."
        )
    elif top_label:
        sentences.append(
            f"The most common reason is <b>{top_label}</b>. Each "
            "flagged section has its own card on the pages that follow "
            "with the specific action to take."
        )
    else:
        sentences.append(
            "Each flagged section has its own card on the pages that "
            "follow with the specific action to take."
        )
    return " ".join(sentences)


# ---- Body flowables: cards grouped by FCP -------------------------------

def _length_key(row: dict) -> float:
    try:
        return float(row.get("length_m") or 0.0)
    except (TypeError, ValueError):
        return 0.0


# Live pipeline segment IDs come in as "SDIRouteSection_<bigid>_<other>".
# Stripping the long, repetitive prefix gives a stable, unique short form
# the foreman can read. Demo fixture IDs ("S001") have no prefix and
# pass through unchanged.
_SHORT_ID_PREFIXES: tuple[str, ...] = ("SDIRouteSection_",)


def _short_segment_id(seg_id: str) -> str:
    for prefix in _SHORT_ID_PREFIXES:
        if seg_id.startswith(prefix):
            return seg_id[len(prefix):]
    return seg_id


def _segment_sort_key(row: dict) -> tuple[int, float]:
    """RED before YELLOW; longer sections first within a verdict.

    Negate length so larger values sort earlier under ascending sort.
    """
    verdict = str(row.get("verdict") or "").upper()
    rank = 0 if verdict == "RED" else 1
    return (rank, -_length_key(row))


# Reasons that mean "no photos at all on this section". When most of a
# project is in this state (early in a job), rendering one full card per
# section produces a 100+ page PDF of identical content — and blocks the
# Streamlit popover for ~10s while it builds. Collapse them into one
# compact block per FCP instead, with a capped section-ID list.
_BOILERPLATE_NO_PHOTO_REASONS: frozenset[str] = frozenset({
    "no compliant photos snapped",
    "no photos snapped to this segment",
})

# Cap the collapsed list so a project with 1,000+ untouched sections per
# FCP still produces a usable PDF. The cover stats already show the full
# count; the appendix below the cap reads "and N more".
_NO_PHOTOS_LIST_CAP = 40


def _is_no_photos_only(row: dict) -> bool:
    reasons = str(row.get("reasons") or "").strip()
    return reasons in _BOILERPLATE_NO_PHOTO_REASONS


def _no_photos_block(
    fcp: str,
    rows: list[dict],
    addresses: dict[str, str] | None,
) -> Table:
    """One compact card per FCP listing the sections that have no photos
    at all. Single action line, then a capped per-section list."""
    rows_sorted = sorted(rows, key=lambda r: str(r.get("segment_id") or ""))
    total_length = sum(_length_key(r) for r in rows_sorted)

    head = Paragraph(
        f"<b>{len(rows_sorted)} sections with no photos submitted</b> "
        f"<font color='#64748b'>· {total_length:.0f} m of trench, "
        f"FCP {fcp}</font>",
        S_CARD_REF,
    )

    do_next = Table(
        [
            [Paragraph("DO NEXT", S_REASON_HEAD)],
            [Paragraph(
                "Re-shoot 4–6 photos along each section below, one for "
                "each work stage (open trench, sand bedding, cable "
                "laid, warning tape).",
                S_REASON,
            )],
        ],
        colWidths=[CONTENT_W - 24],
    )
    do_next.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_REASON_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
    ]))

    list_items: list = []
    for r in rows_sorted[:_NO_PHOTOS_LIST_CAP]:
        seg_id = str(r.get("segment_id") or "")
        short = _short_segment_id(seg_id)
        length_m = _length_key(r)
        addr = (addresses or {}).get(seg_id, "")
        line = f"<b>{short}</b> · {length_m:.0f} m"
        if addr:
            line += f" &nbsp;·&nbsp; <font color='#64748b'>{addr}</font>"
        list_items.append(Paragraph(line, S_LIST_DENSE))

    if len(rows_sorted) > _NO_PHOTOS_LIST_CAP:
        list_items.append(Paragraph(
            f"<i>… and {len(rows_sorted) - _NO_PHOTOS_LIST_CAP} more "
            "sections with no photos.</i>",
            S_LIST_DENSE,
        ))

    list_table = Table([[item] for item in list_items],
                       colWidths=[CONTENT_W - 24])
    list_table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    outer = Table(
        [[head], [do_next], [list_table]],
        colWidths=[CONTENT_W],
    )
    outer.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, C_BORDER),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("BACKGROUND", (0, 0), (-1, -1), C_SURFACE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (0, 0), 10),
        ("BOTTOMPADDING", (0, 0), (0, 0), 6),
        ("TOPPADDING", (0, 1), (0, 1), 0),
        ("BOTTOMPADDING", (0, 1), (0, 1), 8),
        ("TOPPADDING", (0, 2), (0, 2), 0),
        ("BOTTOMPADDING", (0, 2), (0, 2), 10),
    ]))
    return outer


def _body_flowables(
    verdicts: pd.DataFrame,
    addresses: dict[str, str] | None,
) -> list:
    bad_rows = [
        r for r in verdicts.to_dict("records")
        if str(r.get("verdict") or "").upper() != "GREEN"
    ]
    if not bad_rows:
        return [
            PageBreak(),
            Paragraph("Sections needing attention", S_H2),
            Spacer(1, 6),
            Paragraph(
                "No deficient sections in this run — nothing to flag.",
                S_BODY,
            ),
        ]

    grouped: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: {"unique": [], "no_photos": []}
    )
    for r in bad_rows:
        fcp = str(r.get("fcp_name") or "—")
        bucket = "no_photos" if _is_no_photos_only(r) else "unique"
        grouped[fcp][bucket].append(r)

    out: list = [PageBreak(), Paragraph("Sections needing attention", S_H2)]

    for fcp in sorted(grouped):
        unique = sorted(grouped[fcp]["unique"], key=_segment_sort_key)
        no_photos = grouped[fcp]["no_photos"]
        n_total = len(unique) + len(no_photos)
        out.append(Paragraph(
            f"FCP {fcp} &nbsp;·&nbsp; {n_total} section"
            f"{'s' if n_total != 1 else ''} flagged",
            S_FCP,
        ))
        for r in unique:
            seg_id = str(r.get("segment_id") or "")
            addr = (addresses or {}).get(seg_id)
            out.append(KeepTogether(
                [_section_card(r, address=addr), Spacer(1, 3)]
            ))
        if no_photos:
            out.append(KeepTogether(
                [_no_photos_block(fcp, no_photos, addresses), Spacer(1, 8)]
            ))
    return out


# ---- Appendix: passing sections + legend + checks -----------------------

_EIGHT_CHECKS: list[tuple[str, str]] = [
    ("Warning tape visible",
     "Orange tape on top, so a future digger knows the cable is below."),
    ("Sand bedding visible",
     "Cable sits on sand, not bare dirt — protects against damage."),
    ("Side view of trench",
     "You can only judge depth from a side angle, not a top-down shot."),
    ("Depth reference visible",
     "A ruler or measuring rod in the frame, so depth can be read."),
    ("Cable ends sealed",
     "White end-caps on the duct bundle — keeps water out."),
    ("No personal data",
     "Faces and licence plates are flagged for retake (GDPR)."),
    ("Not a duplicate photo",
     "Image fingerprint compared against every other photo — copies caught."),
    ("Printed address matches GPS",
     "The address stamp on the photo agrees with its GPS coordinates."),
]


def _appendix_flowables(verdicts: pd.DataFrame) -> list:
    out: list = [PageBreak()]

    # Passing sections — compact ID list per FCP, for completeness.
    passing = [
        r for r in verdicts.to_dict("records")
        if str(r.get("verdict") or "").upper() == "GREEN"
    ]
    if passing:
        out.append(Paragraph("Passing sections", S_H2))
        out.append(Paragraph(
            "These sections passed every check — no action needed. Listed "
            "for completeness so nothing is left unmentioned.",
            S_BODY_MUTED,
        ))
        by_fcp: dict[str, list[str]] = defaultdict(list)
        for r in passing:
            seg = str(r.get("segment_id") or "")
            by_fcp[str(r.get("fcp_name") or "—")].append(
                _short_segment_id(seg))
        for fcp in sorted(by_fcp):
            ids = ", ".join(sorted(by_fcp[fcp]))
            out.append(Paragraph(
                f"<b>FCP {fcp}</b> &nbsp;·&nbsp; {ids}",
                S_LIST_DENSE,
            ))
        out.append(Spacer(1, 10))

    # Severity legend.
    out.append(Paragraph("Severity colour codes", S_H2))
    legend = Table(
        [
            [_pill("RED"), Paragraph(
                "Not enough good photos to confirm the work is OK. A "
                "reviewer should look at this first.",
                S_BODY,
            )],
            [_pill("YELLOW"), Paragraph(
                "Some checks failed or coverage has a gap, but the "
                "section is mostly documented.",
                S_BODY,
            )],
            [_pill("GREEN"), Paragraph(
                "Every check passed and coverage meets the one-photo-per-"
                "five-metres rule. No action needed.",
                S_BODY,
            )],
        ],
        colWidths=[30 * mm, CONTENT_W - 30 * mm],
    )
    legend.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    out.append(legend)
    out.append(Spacer(1, 12))

    # The eight checks.
    out.append(Paragraph("What the tool checks on every photo", S_H2))
    out.append(Paragraph(
        "Six of these are answered by the AI model; the last two are "
        "answered by direct comparisons that don't need a model.",
        S_BODY_MUTED,
    ))
    out.append(Spacer(1, 4))
    for i, (name, gloss) in enumerate(_EIGHT_CHECKS, start=1):
        out.append(Paragraph(
            f"<b>{i}. {name}.</b> {gloss}",
            S_LIST_DENSE,
        ))
    return out


# ---- Public API ---------------------------------------------------------

def build_pdf(
    verdicts: pd.DataFrame,
    source: str = "live",
    intake: PhotoIntake | None = None,
    segment_addresses: dict[str, str] | None = None,
) -> bytes:
    """Render the full deficiency report into a PDF byte string.

    `verdicts` must contain the columns used by the cards: segment_id,
    fcp_name, verdict, length_m, photo_count, compliant_photo_count,
    max_gap_m, reasons. Extra columns are ignored.

    `intake`, when provided, adds the photo-level intake table to the
    cover (uploaded / passed / re-shoot / duplicates / …). Use
    compute_photo_intake() to build it from the readqc / forensics /
    geomatch artifacts.

    `segment_addresses`, when provided, adds a street-address line under
    each section card header so a foreman can find the section without
    consulting a separate map. Use compute_segment_addresses().
    """
    generated_on = datetime.now().strftime("%d %b %Y, %H:%M")

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
        title="Trench photo deficiency report",
        author="Sightline photo-QC pipeline",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id="main", showBoundary=0,
    )
    doc.addPageTemplates([
        PageTemplate(
            id="default",
            frames=[frame],
            onPage=lambda c, d: _draw_chrome(c, d, generated_on),
        ),
    ])

    story: list = []
    story.extend(_cover_flowables(verdicts, source, generated_on, intake))
    story.extend(_body_flowables(verdicts, segment_addresses))
    story.extend(_appendix_flowables(verdicts))

    doc.build(story)
    return buf.getvalue()
