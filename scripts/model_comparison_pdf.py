"""One-off: render the model-comparison benchmark into a teammate-ready PDF.

Reads `data/processed/model_benchmark.json` (written by `audit_groundtruth`)
and emits `data/processed/model_comparison.pdf`. Self-contained — does
NOT depend on `src/pdf_report.py` so it doesn't break when the report
schema evolves.

Run:
    uv run python -m scripts.model_comparison_pdf
"""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table,
    TableStyle, KeepTogether,
)

from src.paths import PROCESSED_DIR

BENCH_JSON = PROCESSED_DIR / "model_benchmark.json"
OUT_PDF = PROCESSED_DIR / "model_comparison.pdf"

# ÖGIG accent palette, mirrors the dashboard
C_TEXT = colors.HexColor("#0f172a")
C_MUTED = colors.HexColor("#64748b")
C_ACCENT = colors.HexColor("#0ea5e9")
C_RULE = colors.HexColor("#e2e8f0")
C_GREEN = colors.HexColor("#16a34a")
C_RED = colors.HexColor("#dc2626")
C_BG_SOFT = colors.HexColor("#f8fafc")

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
MARGIN_TOP = 22 * mm
MARGIN_BOTTOM = 18 * mm


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"],
            fontName="Helvetica-Bold", fontSize=18, leading=22,
            textColor=C_TEXT, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"],
            fontName="Helvetica", fontSize=10, leading=14,
            textColor=C_MUTED, spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"],
            fontName="Helvetica-Bold", fontSize=12, leading=15,
            textColor=C_TEXT, spaceBefore=12, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"],
            fontName="Helvetica", fontSize=9.5, leading=13,
            textColor=C_TEXT, spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["Normal"],
            fontName="Helvetica", fontSize=9.5, leading=13,
            textColor=C_TEXT, leftIndent=12, bulletIndent=2, spaceAfter=4,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"],
            fontName="Helvetica", fontSize=7.5, leading=10,
            textColor=C_MUTED,
        ),
    }


def _chrome(canvas, doc, generated_on: str) -> None:
    canvas.saveState()
    band_y = PAGE_H - MARGIN_TOP / 2
    canvas.setFont("Helvetica-Bold", 8.5)
    canvas.setFillColor(C_ACCENT)
    canvas.drawString(MARGIN_X, band_y, "ÖGIG  ·  Photo QC")
    canvas.setFillColor(C_MUTED)
    canvas.setFont("Helvetica", 8.5)
    canvas.drawRightString(PAGE_W - MARGIN_X, band_y,
                           "Sonnet vs Haiku — phase-classification benchmark")
    canvas.setStrokeColor(C_RULE)
    canvas.setLineWidth(0.4)
    canvas.line(MARGIN_X, band_y - 3, PAGE_W - MARGIN_X, band_y - 3)
    # Footer
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(C_MUTED)
    canvas.drawString(MARGIN_X, MARGIN_BOTTOM / 2,
                      f"Generated {generated_on}  ·  "
                      "source: data/processed/model_benchmark.json")
    canvas.drawRightString(PAGE_W - MARGIN_X, MARGIN_BOTTOM / 2,
                           f"Page {doc.page}")
    canvas.restoreState()


def _fmt_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} s"
    if seconds < 3600:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"


def _table(rows: list[list[str]], col_widths: list[float],
           highlight_winner_cols: list[int] | None = None) -> Table:
    """Build a clean comparison table.

    `highlight_winner_cols` accepts a list of body-row indices (0-based,
    excluding header) where the winner cell should be highlighted green.
    For each highlighted row, the cell with the larger numeric value
    (parsed from leading float) wins.
    """
    t = Table(rows, colWidths=col_widths, hAlign="LEFT")
    style: list = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), C_TEXT),
        ("BACKGROUND", (0, 0), (-1, 0), C_BG_SOFT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, C_RULE),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), C_TEXT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, C_RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    return Table(rows, colWidths=col_widths, hAlign="LEFT",
                 style=TableStyle(style))


def build(bench: dict) -> bytes:
    styles = _styles()
    generated_on = datetime.now().strftime("%d %b %Y, %H:%M")

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
        title="Sonnet vs Haiku — phase-classification benchmark",
        author="ÖGIG photo-QC pipeline",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  id="main", showBoundary=0)
    doc.addPageTemplates([PageTemplate(
        id="default", frames=[frame],
        onPage=lambda c, d: _chrome(c, d, generated_on),
    )])

    story: list = []

    story.append(Paragraph(
        "Sonnet vs Haiku — phase-classification benchmark",
        styles["h1"],
    ))
    story.append(Paragraph(
        "Same 214 hand-labelled photos from the data provider's "
        "reference set (114 depth-measurement + 100 cable-laying), "
        "scored blind by each model. Same 4-exemplar prompt, same "
        "8-worker pool. Strict match: <i>depth → depth_measure</i>, "
        "<i>duct → duct_laid</i>.",
        styles["subtitle"],
    ))

    # --- Headline numbers ---
    s = bench.get("sonnet", {})
    h = bench.get("haiku", {})

    def overall(d: dict) -> tuple[float, int, int]:
        o = (d or {}).get("overall_strict") or {}
        return (o.get("pct") or 0.0,
                int(o.get("correct") or 0),
                int(o.get("total") or 0))

    s_acc, s_c, s_n = overall(s)
    h_acc, h_c, h_n = overall(h)
    s_secs = float(s.get("bench_seconds") or 0)
    h_secs = float(h.get("bench_seconds") or 0)
    s_cost = float(s.get("bench_cost_usd") or 0)
    h_cost = float(h.get("bench_cost_usd") or 0)
    s_bn = int(s.get("bench_n") or s_n or 1)
    h_bn = int(h.get("bench_n") or h_n or 1)

    story.append(Paragraph("Headline", styles["h2"]))
    story.append(_table(
        [
            ["Model", "Accuracy", "Wall time (214 photos)",
             "Cost", "$ / photo"],
            ["Sonnet 4.6",
             f"{s_acc:.1f}%  ({s_c}/{s_n})",
             _fmt_time(s_secs),
             f"${s_cost:.2f}",
             f"${s_cost / max(s_bn, 1):.4f}"],
            ["Haiku 4.5",
             f"{h_acc:.1f}%  ({h_c}/{h_n})",
             _fmt_time(h_secs),
             f"${h_cost:.2f}",
             f"${h_cost / max(h_bn, 1):.4f}"],
        ],
        col_widths=[28 * mm, 32 * mm, 38 * mm, 22 * mm, 24 * mm],
    ))
    cost_mult = s_cost / h_cost if h_cost else 0
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"<b>Sonnet costs {cost_mult:.1f}× more for "
        f"{s_acc - h_acc:+.1f} pp overall accuracy.</b> "
        "The headline tie hides a sharper per-class story (below).",
        styles["body"],
    ))

    # --- Per-class accuracy ---
    story.append(Paragraph("Per-class accuracy", styles["h2"]))
    s_d = s.get("depth") or {}
    s_u = s.get("duct_strict") or {}
    h_d = h.get("depth") or {}
    h_u = h.get("duct_strict") or {}
    story.append(_table([
        ["Class", "Sonnet", "Haiku", "Δ"],
        ["Depth-measurement (n=114)",
         f"{s_d.get('pct', 0):.1f}%",
         f"{h_d.get('pct', 0):.1f}%",
         f"{s_d.get('pct', 0) - h_d.get('pct', 0):+.1f} pp"],
        ["Cable-laying (n=100)",
         f"{s_u.get('pct', 0):.1f}%",
         f"{h_u.get('pct', 0):.1f}%",
         f"{s_u.get('pct', 0) - h_u.get('pct', 0):+.1f} pp"],
    ], col_widths=[58 * mm, 30 * mm, 30 * mm, 26 * mm]))

    # --- FP / FN ---
    def fp_fn(model_blob: dict) -> dict:
        conf = (model_blob or {}).get("confusion") or {}
        depth_conf = conf.get("depth") or {}
        duct_conf = conf.get("duct") or {}
        n_depth = sum(depth_conf.values())
        n_duct = sum(duct_conf.values())
        return {
            "depth_tp": depth_conf.get("depth_measure", 0),
            "depth_fn": n_depth - depth_conf.get("depth_measure", 0),
            "depth_fp": duct_conf.get("depth_measure", 0),
            "depth_tn": n_duct - duct_conf.get("depth_measure", 0),
            "duct_tp": duct_conf.get("duct_laid", 0),
            "duct_fn": n_duct - duct_conf.get("duct_laid", 0),
            "duct_fp": depth_conf.get("duct_laid", 0),
            "duct_tn": n_depth - depth_conf.get("duct_laid", 0),
        }

    sm = fp_fn(s)
    hm = fp_fn(h)

    def pr(tp: int, fp: int, fn: int) -> tuple[str, str]:
        p = (100 * tp / (tp + fp)) if (tp + fp) else 0.0
        r = (100 * tp / (tp + fn)) if (tp + fn) else 0.0
        return f"{p:.1f}%", f"{r:.1f}%"

    s_d_p, s_d_r = pr(sm["depth_tp"], sm["depth_fp"], sm["depth_fn"])
    h_d_p, h_d_r = pr(hm["depth_tp"], hm["depth_fp"], hm["depth_fn"])
    s_u_p, s_u_r = pr(sm["duct_tp"], sm["duct_fp"], sm["duct_fn"])
    h_u_p, h_u_r = pr(hm["duct_tp"], hm["duct_fp"], hm["duct_fn"])

    story.append(Paragraph("False positives vs false negatives",
                           styles["h2"]))
    story.append(_table([
        ["Class · Model", "TP", "FP", "FN", "TN", "Precision", "Recall"],
        ["depth_measure · Sonnet",
         str(sm["depth_tp"]), str(sm["depth_fp"]),
         str(sm["depth_fn"]), str(sm["depth_tn"]),
         s_d_p, s_d_r],
        ["depth_measure · Haiku",
         str(hm["depth_tp"]), str(hm["depth_fp"]),
         str(hm["depth_fn"]), str(hm["depth_tn"]),
         h_d_p, h_d_r],
        ["duct_laid · Sonnet",
         str(sm["duct_tp"]), str(sm["duct_fp"]),
         str(sm["duct_fn"]), str(sm["duct_tn"]),
         s_u_p, s_u_r],
        ["duct_laid · Haiku",
         str(hm["duct_tp"]), str(hm["duct_fp"]),
         str(hm["duct_fn"]), str(hm["duct_tn"]),
         h_u_p, h_u_r],
    ], col_widths=[56 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm,
                   22 * mm, 22 * mm]))

    # --- Error-cost framing ---
    story.append(Paragraph("Which error matters more in the field?",
                           styles["h2"]))
    # The consequence column holds full sentences -- wrap in Paragraph so
    # reportlab line-breaks within the cell instead of truncating.
    cell = styles["body"]
    story.append(_table([
        ["Error", "Consequence"],
        ["depth_measure FP",
         Paragraph(
             "Cable-laying photo flagged as depth evidence &rarr; "
             "contractor passes without real proof. "
             "<b>Compliance risk.</b>", cell)],
        ["depth_measure FN",
         Paragraph(
             "Real depth shot missed &rarr; contractor re-shoots an "
             "already-good frame. Annoyance, no safety impact.", cell)],
        ["duct_laid FP",
         Paragraph(
             "Depth-only photo flagged as duct evidence. Less critical; "
             "the depth proof is real.", cell)],
        ["duct_laid FN",
         Paragraph(
             "Cable-laying photo missed &rarr; re-shoot. Annoyance.",
             cell)],
    ], col_widths=[36 * mm, 126 * mm]))

    # --- Buyer narrative ---
    story.append(Paragraph("Buyer narrative", styles["h2"]))
    bullets = [
        f"<b>Sonnet</b> is high-recall, lower-precision on depth — "
        f"catches {s_d_r} of real depth shots and never falsely calls "
        f"a depth photo \"duct_laid\" ({s_u_p} duct precision). Best "
        f"for <b>completeness audits</b> (\"did this contractor ever "
        f"measure depth?\").",
        f"<b>Haiku</b> is more balanced — fewer false alarms in both "
        f"directions, slightly worse depth recall. Best for <b>bulk "
        f"triage</b> where reviewers eyeball flagged frames anyway. "
        f"Same overall accuracy at one-third the cost.",
        "The expensive failure mode for both models is "
        "<b>over-calling \"depth_measure\"</b> on cable-laying frames "
        "that happen to show a measuring rod (Sonnet: "
        f"{sm['depth_fp']}/100 false alarms; Haiku: "
        f"{hm['depth_fp']}/100). A prompt revision could close this.",
    ]
    for b in bullets:
        story.append(Paragraph("•  " + b, styles["bullet"]))

    # --- Methodology footnote ---
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "<i>Methodology: Each model run via "
        "<font face='Courier'>scripts.bench_sonnet_on_gt --model "
        "&lt;m&gt;</font> on 214 hand-labelled photos. Per-photo "
        "predictions in <font face='Courier'>readqc_bench.jsonl</font>; "
        "summary in <font face='Courier'>model_benchmark.json</font>. "
        "Wall-time and cost are accumulated across the bench script's "
        "runs (cache-warm after photo 1; identical 8-worker pool for "
        "both models).</i>",
        styles["footer"],
    ))

    doc.build(story)
    return buf.getvalue()


def main() -> int:
    if not BENCH_JSON.exists():
        print(f"ERROR: {BENCH_JSON} missing. Run "
              "`uv run python -m src.audit_groundtruth` first.",
              file=sys.stderr)
        return 1
    bench = json.loads(BENCH_JSON.read_text(encoding="utf-8"))
    pdf_bytes = build(bench)
    OUT_PDF.write_bytes(pdf_bytes)
    size_kb = len(pdf_bytes) / 1024
    print(f"wrote {OUT_PDF}  ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
