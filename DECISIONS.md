# DECISIONS

One line per decision. Timestamped. No re-litigating.

- **2026-05-15** Going Challenge 2 (construction-photo QC). Rationale in [07_strategy.md](07_strategy.md).
- **2026-05-15** Stack: Python 3.11 + uv, Streamlit (no FastAPI for the spine), Claude Haiku 4.5 vision as the QC engine, classical CV (`imagehash` + ELA-via-Pillow) for forensics. Lib list and skip-list rationale in [pyproject.toml](pyproject.toml) and [08_plan.md](08_plan.md).
- **2026-05-15** No custom YOLO training. 30 hand-labels / 4 classes / 4 hours is below the practical small-data floor; VLMs win the "is X present" questions; YOLO-World zero-shot is Plan B if we need bounding boxes.
- **2026-05-15** No `imagededup`, `piexif`, `exifread`, `fastapi`, `uvicorn`, `easyocr`, `paddleocr` in the pre-pull. Reasons: torch weight, redundant with Pillow, Streamlit-is-enough.
- **2026-05-15** Differentiator vs Deepomatic Lens / IQGeo: cross-photo authenticity / recycling detection. Demo line: "this photo was already submitted on job #4471, three weeks ago."
- **2026-05-15** Hard-code ÖGIG depth spec 30–40 cm into the rule prompt (per oegig.at/oefiber/).
- **2026-05-15** HEIC handling required: `pillow-heif` opener + `.convert("RGB")` + JPEG save before any Claude API upload. API does not accept HEIC.
- **2026-05-15** Architecture: hybrid (VLM + classical CV + forensics), not VLM-alone. Reasoning + alternatives in [04_research_log.md](04_research_log.md#architecture--why-hybrid-vlm--classical-cv--forensics-not-vlm-alone).
- **2026-05-15** Vision model: Claude Haiku 4.5 default; escalate to Sonnet 4.6 within Anthropic before cross-shopping vendors. Comparison + escalation rule in [04_research_log.md](04_research_log.md#vision-model-selection--why-anthropic-claude-haiku-45).
- **2026-05-15** Research learnings + non-trivial comparisons live in [04_research_log.md](04_research_log.md). DECISIONS.md stays one-line-per-decision.
