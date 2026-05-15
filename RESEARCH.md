# RESEARCH LOG

Append-only log of research-driven evaluations. Each entry captures **what we were deciding**, **options considered**, and **the verdict + why**.

The one-line verdict lives in [DECISIONS.md](DECISIONS.md). The reasoning lives here — so future-us (or anyone reading the repo) sees not just "we picked X" but "we considered Y, ruled it out because Z."

Newest entries on top.

---

## 2026-05-15 — Approach for the photo QC engine

**Question:** How do we actually inspect 500 trench photos for compliance signals (duct visible, sand bedding, seals, ruler legibility, etc.)?

**Options considered:**

| Approach | What it means | Verdict |
|---|---|---|
| **Train a custom ML model** (YOLO fine-tune, custom CNN) | Label 30–50 photos by hand, train a model from scratch, run inference locally. | **Rejected.** 30 photos is below the practical small-data floor — model will overfit or be garbage on demo-day photos. Burns 4–6 h training. 3–6 GB install + Windows CUDA roulette. Demo-failure risk is asymmetric (one false positive on the judge's chosen photo loses the room). This was the 2022 approach. |
| **Pre-trained vision-language model (VLM)** | Send each photo + prompt to Claude Haiku 4.5; get structured JSON back. No training, just prompting. | **Strong on its own.** Zero training. Handles novel photos. Outputs signals directly. State of the art for "is X present in this photo?" in 2026. |
| **Hybrid: VLM + classical CV + forensics** | VLM for semantic ("duct visible?") + Laplacian variance for blur + pHash for duplicates + ELA + EXIF sanity for tamper. | **Chosen.** Each tool does the part it's best at. VLM handles semantic vision; classical CV handles cheap deterministic checks; forensics catches the things VLMs can't (duplicate submission across segments, ELA-visible re-saves). |

**Decision:** Hybrid (VLM + classical CV + forensics). One-liner in [DECISIONS.md](DECISIONS.md). Implementation lives in [06_tech_resources.md](06_tech_resources.md) (Claude vision QC engine, pHash dedup, ELA snippet).

**Why this matters for the pitch:** if a judge asks "why didn't you train a custom model?" — we have a defensible answer: 30 photos isn't enough; Claude already knows what a duct looks like; we spent the 48 h on engineering value-add (forensics layer, geomatching, deficiency reporting) rather than recreating commodity vision.

**Sources / prior art:**
- Deepomatic Lens (IQGeo telecom suite) — VLM-based fiber-trench QC, already in market. Validates the approach.
- Ultralytics' own small-data guidance ("hundreds per class") confirms 30 images is below floor.
- arXiv 2512.13974 — multi-layer VLM→LLM pipeline pattern for site inspection.

---

## 2026-05-15 — Vision model choice: Haiku 4.5 vs Gemini 2.5 Flash

**Question:** Which vision model runs the per-photo QC?

**Options considered:**

| Model | Free tier? | Cost for 500 photos | Rate limit risk | Notes |
|---|---|---|---|---|
| **Claude Haiku 4.5** | No | ~$0.60 (Batch) / ~$1.25 (regular) | None at this scale | Excellent JSON adherence; same vendor as Claude Code → consistent idioms |
| **Gemini 2.5 / 2.0 Flash** | Yes (1500/day) | $0 on free tier | 15 RPM cap on free tier → 500 photos = ~33 min minimum | Slightly stronger on OCR historically; needs second API key + console |

**Decision:** Haiku 4.5. One-liner in [DECISIONS.md](DECISIONS.md).

**Why:** Quality is a wash for this task — both are well above the bar for structured visual QA. The real axis is **iteration friction during Saturday tuning**: Gemini's 15-RPM free-tier cap would burn 3+ minutes per re-run on a 50-photo subset, which adds up across the weekend. $5–10 on Anthropic API removes that bottleneck. Same-vendor model also means Claude Code (our pair-programmer) writes Anthropic-flavored call sites by reflex, no constant correction.

**When Gemini would win instead:** if we were on a 5000+ photo dataset where free tier mattered, or if cost was a hard constraint. Neither applies.

---

## Template for new entries

```
## YYYY-MM-DD — Short title (what we were deciding)

**Question:** One sentence — what choice were we making?

**Options considered:**

| Option | What it means | Verdict |
|---|---|---|
| Option A | … | Rejected / Chosen / Plan B — short reason |
| Option B | … | … |

**Decision:** One line. Pointer to DECISIONS.md if logged there.

**Why:** 2–4 sentences. The reasoning a future reviewer needs to understand the call.

**Sources / prior art:** (optional) links, papers, prior incidents.
```
