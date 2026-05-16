"""Generate APG_TrenchVerify_Pitch.pptx — run with: uv run python generate_ppt.py"""

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

# ── Palette ────────────────────────────────────────────────────────────────
DARK_BG    = RGBColor(0x0D, 0x1B, 0x2A)   # deep navy
ACCENT     = RGBColor(0x00, 0xA8, 0xE8)   # APG-ish electric blue
ACCENT2    = RGBColor(0x00, 0xD4, 0x7E)   # green (compliance)
WARN       = RGBColor(0xFF, 0xC1, 0x07)   # amber (problems)
DANGER     = RGBColor(0xFF, 0x4D, 0x4D)   # red
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_GREY = RGBColor(0xCC, 0xD6, 0xE0)
MID_GREY   = RGBColor(0x44, 0x55, 0x66)

W = Inches(13.33)   # widescreen 16:9
H = Inches(7.5)


def prs() -> Presentation:
    p = Presentation()
    p.slide_width  = W
    p.slide_height = H
    return p


def blank(p: Presentation):
    blank_layout = p.slide_layouts[6]  # completely blank
    return p.slides.add_slide(blank_layout)


def bg(slide, color: RGBColor = DARK_BG):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def txb(slide, left, top, width, height,
        text="", size=18, bold=False, color=WHITE,
        align=PP_ALIGN.LEFT, italic=False, wrap=True):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = wrap
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    return tb


def accent_bar(slide, top=Inches(0.12), color=ACCENT):
    bar = slide.shapes.add_shape(
        1,  # rectangle
        Inches(0), top, W, Inches(0.08)
    )
    bar.fill.solid()
    bar.fill.fore_color.rgb = color
    bar.line.fill.background()


def card(slide, left, top, width, height, fill_color=MID_GREY, radius=False):
    shape = slide.shapes.add_shape(1, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    shape.line.fill.background()
    return shape


def section_label(slide, text):
    txb(slide, Inches(0.5), Inches(0.25), Inches(12), Inches(0.4),
        text=text.upper(), size=9, color=ACCENT, bold=True)


# ── SLIDE 1 — Title ─────────────────────────────────────────────────────────
def slide_title(p):
    s = blank(p)
    bg(s)
    accent_bar(s, Inches(0), ACCENT)
    accent_bar(s, Inches(7.4), ACCENT2)

    # Large project name
    txb(s, Inches(0.7), Inches(1.6), Inches(11.5), Inches(1.4),
        "TrenchVerify", size=72, bold=True, color=WHITE, align=PP_ALIGN.LEFT)
    txb(s, Inches(0.7), Inches(3.0), Inches(11.5), Inches(0.7),
        "From Site Photo to Compliance Audit — Automatically",
        size=26, bold=False, color=ACCENT, align=PP_ALIGN.LEFT)

    # Tagline pills
    tagline = "AI-powered photo review  ·  Full audit trail  ·  GDPR-compliant  ·  Zero data retained"
    txb(s, Inches(0.7), Inches(3.9), Inches(11.5), Inches(0.5),
        tagline, size=14, color=LIGHT_GREY)

    # Team + event
    txb(s, Inches(0.7), Inches(6.4), Inches(8), Inches(0.5),
        "Team: [Name 1]  ·  [Name 2]  ·  [Name 3]",
        size=13, color=LIGHT_GREY)
    txb(s, Inches(9.5), Inches(6.4), Inches(3.5), Inches(0.5),
        "Vienna UP 2026  ·  May 2026",
        size=13, color=LIGHT_GREY, align=PP_ALIGN.RIGHT)


# ── SLIDE 2 — Problem ───────────────────────────────────────────────────────
def slide_problem(p):
    s = blank(p)
    bg(s)
    accent_bar(s, color=WARN)
    section_label(s, "The Problem")

    txb(s, Inches(0.5), Inches(0.55), Inches(12), Inches(0.7),
        "What APG Cannot See Will Cost Millions",
        size=32, bold=True, color=WHITE)

    problems = [
        ("Missing\nDocumentation",
         "No compliant photo evidence for open trench, duct positioning, or sand bedding at critical sections.\n\nResult: Warranty claims invalid — liability shifts from contractors to APG."),
        ("No Audit\nTrail",
         "Manual spot-checks miss ~30% of defects. No timestamped, per-meter record exists.\n\nResult: Cannot prove contractual compliance after work is buried and closed."),
        ("Slow &\nImpossible to Scale",
         "3–5 days per section × 9 sections × 100× backlog = thousands of person-days of review.\n\nResult: Review gets skipped. Problems surface years later via excavator damage."),
    ]

    col_w = Inches(3.9)
    col_gap = Inches(0.3)
    for i, (title, body) in enumerate(problems):
        x = Inches(0.5) + i * (col_w + col_gap)
        card(s, x, Inches(1.5), col_w, Inches(5.5), RGBColor(0x1A, 0x2E, 0x42))
        txb(s, x + Inches(0.2), Inches(1.65), col_w - Inches(0.4), Inches(0.9),
            title, size=20, bold=True, color=WARN)
        txb(s, x + Inches(0.2), Inches(2.65), col_w - Inches(0.4), Inches(4.0),
            body, size=20, color=LIGHT_GREY, wrap=True)


# ── SLIDE 3 — Cost of Inaction ──────────────────────────────────────────────
def slide_cost(p):
    s = blank(p)
    bg(s)
    accent_bar(s, color=DANGER)
    section_label(s, "Cost of Inaction")

    txb(s, Inches(0.5), Inches(0.55), Inches(12), Inches(0.7),
        "Poor Documentation Today = Exponential Costs Tomorrow",
        size=32, bold=True, color=WHITE)

    stats = [
        ("€120K+",  "Average cost per\nfiber-cut incident"),
        ("3–5×",    "Cost multiplier when\nwork is undocumented"),
        ("€2.4M+",  "Estimated 5-year\nexposure if unresolved"),
        ("50 yrs",  "Planned asset lifespan\nnow at risk"),
    ]

    box_w = Inches(2.8)
    box_h = Inches(2.8)
    gap   = Inches(0.4)
    start_x = Inches(0.8)
    for i, (num, label) in enumerate(stats):
        x = start_x + i * (box_w + gap)
        card(s, x, Inches(2.0), box_w, box_h, RGBColor(0x3A, 0x10, 0x10))
        txb(s, x, Inches(2.1), box_w, Inches(1.2),
            num, size=40, bold=True, color=DANGER, align=PP_ALIGN.CENTER)
        txb(s, x, Inches(3.3), box_w, Inches(1.2),
            label, size=19, color=LIGHT_GREY, align=PP_ALIGN.CENTER)

    txb(s, Inches(0.5), Inches(5.2), Inches(12), Inches(0.4),
        "* Based on industry benchmarks and internal öGIG / APG estimates",
        size=10, color=MID_GREY, italic=True)

    txb(s, Inches(0.5), Inches(5.8), Inches(12), Inches(1.3),
        "The real question isn't whether to fix this.\nIt's whether to fix it before or after the next fiber cut.",
        size=18, bold=True, color=WARN, align=PP_ALIGN.CENTER)


# ── SLIDE 4 — Our Solution ──────────────────────────────────────────────────
def slide_solution(p):
    s = blank(p)
    bg(s)
    accent_bar(s, color=ACCENT2)
    section_label(s, "Our Solution")

    txb(s, Inches(0.5), Inches(0.55), Inches(12), Inches(0.7),
        "A Digital Compliance Platform — Built for APG",
        size=32, bold=True, color=WHITE)

    pillars = [
        (ACCENT2,  "100%\nCoverage",
         "Every trench segment reviewed automatically.\nNo spot-checks. No gaps."),
        (ACCENT,   "Full\nAudit Trail",
         "Every photo timestamped, GPS-matched,\ncompliance-scored, and logged."),
        (WARN,     "GDPR\nSafe",
         "Faces & plates auto-detected and withheld.\nNothing stored on our infrastructure."),
        (WHITE,    "99%\nFaster",
         "< 30 minutes for the full route —\nvs. 3–5 days per section manually."),
    ]

    box_w = Inches(2.8)
    gap   = Inches(0.4)
    start_x = Inches(0.8)
    for i, (color, title, body) in enumerate(pillars):
        x = start_x + i * (box_w + gap)
        card(s, x, Inches(1.6), box_w, Inches(5.3), RGBColor(0x12, 0x26, 0x36))
        # top accent stripe
        top_bar = s.shapes.add_shape(1, x, Inches(1.6), box_w, Inches(0.12))
        top_bar.fill.solid(); top_bar.fill.fore_color.rgb = color
        top_bar.line.fill.background()
        txb(s, x, Inches(1.85), box_w, Inches(1.1),
            title, size=22, bold=True, color=color, align=PP_ALIGN.CENTER)
        txb(s, x + Inches(0.15), Inches(3.1), box_w - Inches(0.3), Inches(3.5),
            body, size=20, color=LIGHT_GREY, align=PP_ALIGN.CENTER, wrap=True)


# ── SLIDE 5 — Pipeline ──────────────────────────────────────────────────────
def slide_pipeline(p):
    s = blank(p)
    bg(s)
    accent_bar(s, color=ACCENT)
    section_label(s, "How It Works")

    txb(s, Inches(0.5), Inches(0.55), Inches(12), Inches(0.7),
        "Six Steps, 30 Minutes, Zero Human Bottleneck",
        size=32, bold=True, color=WHITE)

    steps = [
        ("1", "Ingest",      "~3,929 photos +\nGeoJSON route file\nloaded into pipeline"),
        ("2", "Geo-Match",   "GPS overlay text\nmatched to trench\nsegment at 5 m res."),
        ("3", "AI Review",   "8 compliance checks\nper photo via\nClaude vision model"),
        ("4", "Classify",    "Each segment scored:\nGREEN / YELLOW / RED\nbased on check results"),
        ("5", "Map",         "Interactive color\nmap rendered in\nbrowser — click any seg."),
        ("6", "Audit Report","CSV + HTML report\ndownloaded; full\nper-meter log exported"),
    ]

    box_w  = Inches(1.9)
    box_h  = Inches(3.8)
    gap    = Inches(0.22)
    start_x = Inches(0.35)

    for i, (num, title, body) in enumerate(steps):
        x = start_x + i * (box_w + gap)
        card(s, x, Inches(1.55), box_w, box_h, RGBColor(0x12, 0x26, 0x36))
        # number circle (small box acting as badge)
        badge = s.shapes.add_shape(1, x + Inches(0.7), Inches(1.45), Inches(0.5), Inches(0.4))
        badge.fill.solid(); badge.fill.fore_color.rgb = ACCENT
        badge.line.fill.background()
        txb(s, x + Inches(0.7), Inches(1.45), Inches(0.5), Inches(0.4),
            num, size=13, bold=True, color=DARK_BG, align=PP_ALIGN.CENTER)

        txb(s, x, Inches(2.0), box_w, Inches(0.6),
            title, size=16, bold=True, color=ACCENT, align=PP_ALIGN.CENTER)
        txb(s, x + Inches(0.1), Inches(2.7), box_w - Inches(0.2), Inches(2.4),
            body, size=18, color=LIGHT_GREY, align=PP_ALIGN.CENTER, wrap=True)

        # arrow between steps (except last)
        if i < len(steps) - 1:
            ax = x + box_w + Inches(0.03)
            txb(s, ax, Inches(3.1), Inches(0.2), Inches(0.4),
                "→", size=18, bold=True, color=ACCENT, align=PP_ALIGN.CENTER)

    # 8 checks footnote
    checks = ("8 checks: warning tape · sand bedding · side-view angle · depth reference · "
              "sealed cable ends · GDPR (faces/plates) · duplicate detection · GPS↔address match")
    txb(s, Inches(0.5), Inches(5.55), Inches(12.3), Inches(0.45),
        checks, size=10, color=MID_GREY, italic=True)

    # comparison bar
    card(s, Inches(0.5), Inches(6.15), Inches(12.3), Inches(0.95), RGBColor(0x0A, 0x3A, 0x1A))
    txb(s, Inches(0.7), Inches(6.2), Inches(12), Inches(0.85),
        "Manual review: 3–5 days per section   →   TrenchVerify: < 30 minutes for the full 2,983-segment route",
        size=16, bold=True, color=ACCENT2, align=PP_ALIGN.CENTER)


# ── SLIDE 6 — Architecture ──────────────────────────────────────────────────
def slide_arch(p):
    s = blank(p)
    bg(s)
    accent_bar(s, color=ACCENT)
    section_label(s, "Architecture")

    txb(s, Inches(0.5), Inches(0.55), Inches(12), Inches(0.7),
        "Two Screens. One Pipeline. Zero Data Retained.",
        size=32, bold=True, color=WHITE)

    # Left tier — Operator
    card(s, Inches(0.4), Inches(1.5), Inches(5.5), Inches(5.3), RGBColor(0x0C, 0x2A, 0x1A))
    txb(s, Inches(0.5), Inches(1.6), Inches(5.3), Inches(0.5),
        "OPERATOR SCREEN  (on-site)", size=13, bold=True, color=ACCENT2)
    op_steps = [
        "Upload photos from site tablet",
        "Instant per-photo feedback",
        "\"Missing sand photo — retake now\"",
        "Catches gaps while trench is open",
    ]
    for j, line in enumerate(op_steps):
        txb(s, Inches(0.6), Inches(2.15) + j * Inches(0.75), Inches(5.1), Inches(0.65),
            f"• {line}", size=16, color=WHITE)

    # Right tier — Reviewer
    card(s, Inches(7.1), Inches(1.5), Inches(5.8), Inches(5.3), RGBColor(0x0C, 0x1A, 0x2E))
    txb(s, Inches(7.2), Inches(1.6), Inches(5.6), Inches(0.5),
        "REVIEWER DASHBOARD  (APG office)", size=13, bold=True, color=ACCENT)
    rev_steps = [
        "AI runs once at upload — results stored, zero re-processing per session",
        "Color map: click any red segment",
        "View evidence photos + check results",
        "Download audit CSV / HTML report",
    ]
    for j, line in enumerate(rev_steps):
        txb(s, Inches(7.3), Inches(2.15) + j * Inches(0.75), Inches(5.4), Inches(0.65),
            f"• {line}", size=16, color=WHITE)

    # Centre connector
    txb(s, Inches(5.95), Inches(3.1), Inches(1.2), Inches(0.6),
        "⟷", size=30, bold=True, color=ACCENT, align=PP_ALIGN.CENTER)
    txb(s, Inches(5.75), Inches(3.75), Inches(1.6), Inches(0.55),
        "One platform\ntwo entry points", size=10, color=LIGHT_GREY, align=PP_ALIGN.CENTER)

    # Data-flow note
    card(s, Inches(0.4), Inches(6.85), Inches(12.5), Inches(0.5), RGBColor(0x1A, 0x1A, 0x1A))
    txb(s, Inches(0.6), Inches(6.88), Inches(12.2), Inches(0.45),
        "Data flow: photos processed transiently in customer cloud  ·  AI model called via API — no photo stored  ·  Results written to customer-owned DB only",
        size=11, color=LIGHT_GREY, italic=True)


# ── SLIDE 7 — Compliance & GDPR ──────────────────────────────────────────────
def slide_compliance(p):
    s = blank(p)
    bg(s)
    accent_bar(s, color=ACCENT2)
    section_label(s, "Compliance & GDPR")

    txb(s, Inches(0.5), Inches(0.55), Inches(12), Inches(0.7),
        "Regulatory Compliance Baked In — Not Bolted On",
        size=32, bold=True, color=WHITE)

    items = [
        (ACCENT2, "GDPR / NIS2\nCompliant",
         "Faces and license plates detected in every photo before any reviewer sees them. "
         "Flagged images are withheld from the display grid and routed to a \"needs retake\" list. "
         "No personal data is ever shown, stored, or transmitted to our infrastructure."),
        (ACCENT,  "Zero Data\nRetention",
         "Photos are processed transiently — held in memory for the duration of the AI call, then released. "
         "Nothing is persisted on our servers. "
         "All results (scores, logs) are written exclusively to the customer's own database."),
        (WARN,    "Full Audit\nTrail",
         "Every check result is logged with: photo ID · trench segment · GPS coordinates · timestamp · "
         "pass/fail per check. The export is a court-admissible evidence trail, not just a summary report."),
        (WHITE,   "Contractor\nAccountability",
         "Duplicate-photo detection fingerprints every image. "
         "If a contractor reuses the same photo across jobs, the system catches the original, the copy, "
         "and all job IDs it was submitted to. In our pilot: ~600 duplicates detected automatically."),
    ]

    box_w = Inches(5.8)
    box_h = Inches(2.5)
    positions = [
        (Inches(0.4),  Inches(1.5)),
        (Inches(6.9),  Inches(1.5)),
        (Inches(0.4),  Inches(4.2)),
        (Inches(6.9),  Inches(4.2)),
    ]

    for (x, y), (color, title, body) in zip(positions, items):
        card(s, x, y, box_w, box_h, RGBColor(0x12, 0x26, 0x36))
        top_bar = s.shapes.add_shape(1, x, y, box_w, Inches(0.1))
        top_bar.fill.solid(); top_bar.fill.fore_color.rgb = color
        top_bar.line.fill.background()
        txb(s, x + Inches(0.2), y + Inches(0.15), box_w - Inches(0.4), Inches(0.75),
            title, size=17, bold=True, color=color)
        txb(s, x + Inches(0.2), y + Inches(0.95), box_w - Inches(0.4), Inches(1.4),
            body, size=18, color=LIGHT_GREY, wrap=True)


# ── SLIDE 8 — Business Value (Google XYZ) ───────────────────────────────────
def slide_value(p):
    s = blank(p)
    bg(s)
    accent_bar(s, color=ACCENT2)
    section_label(s, "Business Value")

    txb(s, Inches(0.5), Inches(0.55), Inches(12), Inches(0.7),
        "The Numbers Speak for Themselves",
        size=32, bold=True, color=WHITE)

    xyz = [
        ("€2.4M+",   "5-year liability exposure eliminated",
         "by catching every defect before contractor sign-off\n(€120K/incident × ~30% miss rate)"),
        ("99%",      "faster review time",
         "3–5 days per section → < 30 min for the full route\n(measured: 3,929 photos in 28 min)"),
        ("100%",     "segment coverage",
         "zero trench meters go unreviewed\n(photo-per-5 m rule across all 2,983 segments)"),
        ("100%",     "audit transparency",
         "every check logged per photo · per meter · per timestamp\n(exportable CSV/HTML, court-admissible)"),
        ("0%",       "hidden GDPR risk",
         "faces & plates flagged and withheld before any reviewer sees them\n(NIS2/GDPR checks run on 100% of photos)"),
    ]

    row_h = Inches(1.0)
    for i, (stat, label, detail) in enumerate(xyz):
        y = Inches(1.5) + i * row_h
        card(s, Inches(0.4), y, Inches(12.5), row_h - Inches(0.06),
             RGBColor(0x12, 0x26, 0x36))
        color = {"99%": ACCENT}.get(stat, ACCENT2)
        txb(s, Inches(0.6), y + Inches(0.1), Inches(1.6), Inches(0.8),
            stat, size=34, bold=True, color=color, align=PP_ALIGN.CENTER)
        txb(s, Inches(2.4), y + Inches(0.05), Inches(4.0), Inches(0.5),
            label, size=16, bold=True, color=WHITE)
        txb(s, Inches(2.4), y + Inches(0.52), Inches(10.0), Inches(0.42),
            detail, size=17, color=LIGHT_GREY, italic=True)

    # Pilot stats bar
    card(s, Inches(0.4), Inches(6.65), Inches(12.5), Inches(0.65),
         RGBColor(0x00, 0x3A, 0x20))
    txb(s, Inches(0.6), Inches(6.7), Inches(12.2), Inches(0.55),
        "$15 in AI cost  ·  28 minutes end-to-end  ·  3,929 photos  ·  2,983 segments scored  ·  ~600 duplicates caught",
        size=14, bold=True, color=ACCENT2, align=PP_ALIGN.CENTER)


# ── SLIDE 9 — Call to Action ─────────────────────────────────────────────────
def slide_cta(p):
    s = blank(p)
    bg(s)
    accent_bar(s, Inches(0), ACCENT)
    accent_bar(s, Inches(7.4), ACCENT2)

    txb(s, Inches(0.7), Inches(0.6), Inches(11.5), Inches(0.9),
        "Every Unreviewed Meter Is a Liability.\nWe Close That Gap — Automatically.",
        size=28, bold=True, color=WHITE, align=PP_ALIGN.CENTER)

    steps = [
        ("01", ACCENT,  "Approve Pilot",
         "Authorise the TrenchVerify AI pilot\nfor the current Klosterneuburg\nroute build"),
        ("02", WARN,    "Define KPIs",
         "Set acceptance thresholds:\ncoverage %, photo compliance rate,\ntime-to-report"),
        ("03", ACCENT2, "Scale",
         "Roll out across all future APG\nconstruction phases — protect\nthe full network"),
    ]

    box_w = Inches(3.6)
    gap   = Inches(0.5)
    start_x = Inches(0.95)
    for i, (num, color, title, body) in enumerate(steps):
        x = start_x + i * (box_w + gap)
        card(s, x, Inches(1.75), box_w, Inches(4.2), RGBColor(0x12, 0x26, 0x36))
        top_bar2 = s.shapes.add_shape(1, x, Inches(1.75), box_w, Inches(0.15))
        top_bar2.fill.solid(); top_bar2.fill.fore_color.rgb = color
        top_bar2.line.fill.background()
        txb(s, x, Inches(2.0), box_w, Inches(0.65),
            num, size=30, bold=True, color=color, align=PP_ALIGN.CENTER)
        txb(s, x, Inches(2.7), box_w, Inches(0.65),
            title, size=20, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        txb(s, x + Inches(0.2), Inches(3.5), box_w - Inches(0.4), Inches(2.2),
            body, size=16, color=LIGHT_GREY, align=PP_ALIGN.CENTER, wrap=True)

    txb(s, Inches(0.5), Inches(6.15), Inches(12.3), Inches(0.65),
        "Protect €42M+ in infrastructure.  Secure the 50-year network lifespan.  Act today.",
        size=17, bold=True, color=ACCENT2, align=PP_ALIGN.CENTER)


# ── SLIDE 10 — Thank You ────────────────────────────────────────────────────
def slide_thankyou(p):
    s = blank(p)
    bg(s)
    accent_bar(s, Inches(0), ACCENT)
    accent_bar(s, Inches(7.4), ACCENT2)

    txb(s, Inches(0.5), Inches(1.8), Inches(12.3), Inches(1.8),
        "Thank You", size=80, bold=True, color=WHITE, align=PP_ALIGN.CENTER)

    txb(s, Inches(0.5), Inches(3.7), Inches(12.3), Inches(0.7),
        "Questions welcome", size=30, bold=False, color=ACCENT, align=PP_ALIGN.CENTER)

    txb(s, Inches(0.5), Inches(4.6), Inches(12.3), Inches(0.55),
        "TrenchVerify — From Site Photo to Compliance Audit — Automatically",
        size=16, color=LIGHT_GREY, align=PP_ALIGN.CENTER)

    txb(s, Inches(0.5), Inches(5.2), Inches(12.3), Inches(0.5),
        "Team: [Name 1]  ·  [Name 2]  ·  [Name 3]",
        size=15, color=LIGHT_GREY, align=PP_ALIGN.CENTER)

    txb(s, Inches(0.5), Inches(6.55), Inches(12.3), Inches(0.4),
        "Built at Vienna UP 2026  ·  All pilot data from APG partner dataset",
        size=11, color=MID_GREY, italic=True, align=PP_ALIGN.CENTER)


# ── Build ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    deck = prs()
    slide_title(deck)
    slide_problem(deck)
    slide_cost(deck)
    slide_solution(deck)
    slide_pipeline(deck)
    slide_arch(deck)
    slide_compliance(deck)
    slide_value(deck)
    slide_cta(deck)
    slide_thankyou(deck)

    out = "APG_TrenchVerify_Pitch.pptx"
    deck.save(out)
    print(f"Saved → {out}  ({len(deck.slides)} slides)")
