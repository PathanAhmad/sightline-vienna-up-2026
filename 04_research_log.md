# Research Log

Reasoning, comparisons, and learnings that don't fit a one-line DECISIONS entry.
Paired with [DECISIONS.md](DECISIONS.md) — that file = *what*, this file = *why* and *what else we considered*.

---

## Architecture — why hybrid (VLM + classical CV + forensics), not VLM-alone

**Date:** 2026-05-15
**Decided:** Hybrid pipeline

### The three options we weighed

| Approach | What it means | Verdict |
|---|---|---|
| Train a custom ML model (YOLO fine-tune, custom CNN) | Label 30–50 photos by hand, train from scratch, run inference locally | **Wrong in 2026.** 30 photos is below the practical data floor — model will overfit and fail on judge-handed photos. Burns 4–6h we don't have. |
| Pre-trained VLM only (Claude Haiku 4.5) | Send each photo + prompt to Claude, get structured JSON back. No training, just prompting. | **State of the art, but incomplete.** Misses capabilities the VLM literally can't do (see below). |
| **VLM + classical CV + forensics** (chosen) | VLM for "is X visible?" + Laplacian for blur + pHash for duplicates + ELA/EXIF for tamper | **Best.** Each tool does the job it's actually best at. |

### Why VLM-alone wasn't enough

A VLM sees one photo at a time and reasons about pixels. Hard limits:

| Signal | VLM can do it? | Why / why not |
|---|---|---|
| Duct / bedding / seal / ruler visible | ✅ Yes | Pure semantic vision — VLM strength |
| Blur / exposure | 🟡 Yes but wasteful | 5-line Laplacian-variance check is free and runs in microseconds |
| GPS coordinate extraction | ❌ No | EXIF metadata, not pixels — VLM doesn't see it |
| Cross-photo duplicate detection | ❌ No | VLM sees one photo per call; can't compare across the corpus. `imagehash.phash` does it in microseconds |
| Photoshop / re-save tampering | ❌ Mostly no | Lives in JPEG compression layers + metadata, not semantic pixels. ELA + EXIF sanity catches it |

### The killer-demo move *requires* the hybrid

The most memorable demo line — *"this photo was already submitted on job #4471, three weeks ago"* — comes from pHash, not the VLM. Option 2 cannot deliver that. Tamper detection demo (judge hands a doctored photo, tool flags it) = ELA + EXIF, also not VLM.

### Cost + speed math

- Asking the VLM "is this blurry?" = 1 API call, ~1s, real money over 500 photos
- Laplacian variance = 5 lines OpenCV, 0.001s, $0
- Routing every signal through the VLM wastes ~80% of API budget + runtime on questions a free deterministic function answers better

### Defensibility answer for jury Q&A

> *"Each signal goes to the cheapest reliable method. Semantic 'is X visible' goes to the VLM where it dominates. Duplicate detection goes to perceptual hashing because the VLM literally can't compare across photos. Forensics goes to ELA + EXIF because tampering is a compression-artifact signal, not a pixel-semantic signal. The pipeline runs in seconds instead of minutes and costs cents instead of dollars."*

"We sent everything to Claude" doesn't win the 30% tech-rigor mark. This does.

---

## Vision model selection — why Anthropic Claude Haiku 4.5

**Date:** 2026-05-15
**Decided:** Claude Haiku 4.5 default; escalate to Sonnet 4.6 *within Anthropic* before cross-shopping vendors

### What we compared

| Model | Quality on our task | Cost (500 photos) | JSON output | Catch |
|---|---|---|---|---|
| **Claude Haiku 4.5** | Excellent | ~$0.60 Batch / ~$1.25 standard | Native schema mode, very reliable | Chosen |
| GPT-4.1 mini (OpenAI) | Excellent — arguably slightly stronger on fine detail | ~$0.80 | Native structured outputs | Different SDK, separate key/billing |
| Gemini 2.5 Flash (Google) | Excellent, strong on OCR | $0 (free tier) | Structured output mode | 15 req/min rate-limit on free tier — painful in iteration |
| Llama 3.2 Vision 90B (open) | Good, not great | $0 self-hosted or ~$2–5 via Together | Less reliable JSON | Setup friction kills 48h budget |
| Pixtral / Qwen2-VL | Decent | $0 self-hosted | JSON reliability concerns | Same |

### Why the small-delta capability gap didn't decide it

For "structured visual QA on industrial photos," the top three (Haiku, GPT-4.1 mini, Gemini Flash) are within margin of error. The deciding axis was **integration friction, not raw capability**:

- Claude Code (our weekend pair-programmer) writes Anthropic-flavored API calls by reflex — same vendor = zero correction overhead
- Switching to OpenAI/Gemini = different SDK, env var, schema syntax, plus Claude Code keeps auto-suggesting Anthropic patterns we'd have to redirect

### Escalation rule (when to deviate)

Only one scenario justifies a switch: during Friday testing, Haiku consistently fails on a specific signal (e.g. mis-reads the ruler >30% of the time). Then:

1. **First:** try Sonnet 4.6 on the ambiguous photos (~$1.70 / 500 Batch). Stay in-vendor.
2. **Only if Sonnet also fails:** cross-shop GPT-4.1 mini.

Don't pre-optimize. Measure on real ÖGIG photos Saturday morning, escalate only on real evidence.

---

## Saturday morning bake-off protocol — Haiku 4.5 vs Sonnet 4.6

**When:** Saturday morning. Dataset drops at Friday ~16:00 kickoff; Friday night = ingest + geomatch wired up; bake-off runs against a 20-photo sample Saturday morning once we have something to point at.
**Cost:** ~$0.20 total.
**Time:** ~5 min setup + 1 min runtime + ~10 min to eyeball results.

**Why we do this (rubric-mapped):**
- Generates evidence for **Tech/AI execution (30%)** — "we measured before we picked"
- Generates the unit-economics number for **Business Model (15%)** — "$X per route section across ÖGIG's 100-project portfolio"
- Generates a Q&A-proof answer for **Pitch / Demo (10%)** — defensible model choice under jury pressure
- Output is a **pitch artifact**, not just an engineering choice

### Sample selection (20 photos)

- **5 hand-labeled by us** — pick photos with clear ground truth across the 6 signals: one obviously-clean, one with missing bedding, one duplicate-pair, one with an unreadable ruler, one occluded. These are the accuracy gold standard.
- **15 randomly sampled** from the rest of the dataset — these surface disagreement and edge-case behavior.

### Run both models with identical prompt + schema

```python
for model in ["claude-haiku-4-5-20251001", "claude-sonnet-4-6-20251022"]:
    for photo in sample_20:
        t0 = time.time()
        result = qc(photo, model=model)   # same prompt, same schema
        log(model, photo, result, latency_ms=int((time.time()-t0)*1000))
```

### Score three things

1. **Accuracy on the 5 hand-labeled photos** — Haiku vs Sonnet, per-signal (6 signals × 5 photos = 30 cells per model)
2. **Disagreement on the 15 random photos** — count photos where the two models give different verdicts on the same signal. Eyeball those manually: which model was right? (Isolates *which signals* each model struggles with.)
3. **Average latency per call** — Haiku ms vs Sonnet ms

### Decision tree from the results

| Outcome | Action | Pitch line |
|---|---|---|
| Haiku within 1 of Sonnet on hand-labels | Ship Haiku for the 500-photo pass | *"Measured both. Haiku within margin, 3× cheaper."* |
| Haiku loses on a specific signal (e.g. ruler OCR) | Haiku as workhorse + route that one signal to Sonnet | *"Deliberate routing — cheap model for cheap questions, expensive model for hard ones."* |
| Haiku meaningfully worse across the board | Ship Sonnet for the full pass | *"We measured. Sonnet earned the budget."* |

### Log the result here when done

Drop a subsection right below this one the moment results are in:

> **Bake-off result — 2026-05-16 ~10:00**
> - Haiku accuracy on hand-labels: __/30 signal-checks
> - Sonnet accuracy on hand-labels: __/30 signal-checks
> - Disagreement on random sample: __/15, on signals: [...]
> - Latency: Haiku __ms, Sonnet __ms
> - **Decision:** [chosen model + routing rule]
> - **Pitch line locked in:** [...]

---

## Competitor landscape

**Date:** 2026-05-15
**Source:** Our pre-hackathon research, NOT the ÖGIG brief.

| Player | Mentioned by ÖGIG? | Notes |
|---|---|---|
| **PlanRadar** | ✅ Yes (in brief) | ÖGIG already uses it for digital docs; saved "2 hours/day per inspection." Doc-management layer, not photo-QC AI. |
| **Deepomatic Lens** (now in IQGeo telecom suite) | ❌ No — our research | Purpose-built for fiber technicians. Instant pass/fail on depth, cable presence, OCR cable IDs, seal integrity. **The direct competitor for the photo-AI layer.** |
| Groundhawk (UK) | ❌ No — our research | Fiber-specific QC |
| AI Clearing (Austin) | ❌ No — our research | Construction-site QC, broader scope |
| Sitetracker Scout | ❌ No — our research | 2025 entrant |

### Why naming Deepomatic in slide 2 is a strength

1. Signals we did market homework before showing up → points on *Problem Fit & Solution Relevance (20%)*.
2. Lets us position our differentiator sharply: *"Deepomatic Lens already does pass/fail compliance checks. We do that **plus** cross-photo authenticity detection — the part their tool misses."*

That positioning only works because we brought Deepomatic into the room. ÖGIG didn't.

### Caveat: verify with Martin Friday

If ÖGIG already evaluated Deepomatic internally and passed for a specific reason (price, integration, language), we want that reason — it sharpens our pitch. Question is in the Open Questions section below.

---

## Cost reality check

For the team's mental model:

- Haiku 4.5 vision per photo: ~$0.0012 (Batch) / ~$0.0025 (standard)
- 500 photos one full pass: ~$0.60 / ~$1.25
- Full weekend with iteration (5–10 full passes + tuning + dry-runs): **~$5–10 total**
- Top-up: **$10** on https://console.anthropic.com → leaves margin and any unused balance carries to the next project

**$0.60 is the total for 500 photos, NOT per photo.** Reminder for anyone glancing at numbers without context.

### Demo safety (so we don't run out mid-pitch)

1. Pre-compute the demo run Saturday night → save Claude's JSON responses to disk. Sunday demo reads from cached JSON, not live API (except for any judge-handed photo).
2. $10 buffer covers any live calls + retries.
3. Backup demo video Saturday night = final safety net.

---

## Open questions for Martin Fuhrmann (Friday workshop)

Park questions here as they come up; check off after the workshop.

- [ ] **Have you evaluated Deepomatic Lens or similar fiber-QC tools — and if so, what didn't fit?** (Reframes our positioning either way: never heard of it → we inform the customer; evaluated and passed → we have a concrete gap to position against.)
- [ ] **What single check, if automated, saves your team the most hours per week?** (Prioritizes which signal we ship first.)
- [ ] **ÖGIG internal trench-depth spec — confirm 30–40 cm from oegig.at/oefiber/, and any other numerical specs we should hard-code into the prompt.**
- [ ] **GeoJSON coordinate system — EPSG:4326 or 31287?** (Affects geomatching code; can ask the moment dataset drops.)
- [ ] **Are cross-photo duplicates actually a real problem operationally, or is the bigger pain missing-evidence segments?** (Decides whether to lean forensics-heavy or coverage-heavy in the pitch.)
- [ ] **Privacy redaction — required for the prototype or a "nice-to-have"?** (Cheapest signal to detect; high-effort if we have to actually redact pixels.)

---

## Open questions for organizers (Slack / Friday)

- [ ] **AI coding tools (Cursor, Copilot, Claude Code) explicitly allowed?** Silence in the rules = default allowed, but a 10-second Slack confirmation removes ambiguity. No declaration required per the rubric.
- [ ] **Dataset drop time and format** — confirmed via brief as "shortly before kickoff," likely ~16:00 Friday.

---

## How to use this doc

- **Add a section** any time we make a non-trivial choice with alternatives we considered → captures the *why* so a future teammate (or jury Q&A) can reconstruct the reasoning.
- **Add a question** to the Open Questions sections any time we realize we don't know something but can't get the answer yet.
- **DECISIONS.md still gets the one-liner** for every concrete decision — this doc is the long-form companion, not a replacement.
