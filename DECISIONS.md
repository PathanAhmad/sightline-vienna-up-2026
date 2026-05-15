# DECISIONS

One line per decision. Timestamped. No re-litigating.

- **2026-05-15** Going Challenge 2 (construction-photo QC).
- **2026-05-15** Stack: Python 3.11 + uv, Streamlit (no FastAPI for the spine), Claude Haiku 4.5 vision as the QC engine, classical CV (`imagehash` + ELA-via-Pillow) for forensics. See [pyproject.toml](pyproject.toml).
- **2026-05-15** No custom YOLO training. 30 hand-labels / 4 classes / 4 hours is below the practical small-data floor; VLMs win "is X present" questions; YOLO-World zero-shot is Plan B.
- **2026-05-15** No `imagededup`, `piexif`, `exifread`, `fastapi`, `uvicorn`, `easyocr`, `paddleocr` in the pre-pull.
- **2026-05-15** Differentiator: cross-photo authenticity / recycling detection. Demo line: "this photo was already submitted on job #X."
- **2026-05-15** HEIC handling stays defensive (`pillow-heif` opener + JPEG convert before any Claude upload), even though current data is JPEG.
- **2026-05-15** Architecture: hybrid (VLM + classical CV + forensics), not VLM-alone.
- **2026-05-15** Vision model: Claude Haiku 4.5 default; escalate to Sonnet 4.6 within Anthropic before cross-shopping.

### Late Friday — data drop & audit (`Resources/`)

- **2026-05-15 PM** Partner per the brief docx is **APG (Austrian Power Grid)**, not ÖGIG. Pitch to APG; the fiber data we received (Maria Rain, Carinthia, CLP20417A) is the working pilot stand-in.
- **2026-05-15 PM** Geomatch via **overlay-OCR** (Claude vision reads the photo's printed address + optional lat/lon + paper-label FCP code), not EXIF GPS. Sampled 200/200 photos have no EXIF GPS — WhatsApp upload path strips metadata.
- **2026-05-15 PM** CRS for the provided geo data is **WGS84 / EPSG:4326** (technically OGC:CRS84, equivalent). No Lambert 31287 reprojection needed for this dataset.
- **2026-05-15 PM** Six checks per the APG brief: warning tape, sand bedding, side view, depth reference, duplicate, GPS-consistency. Privacy stays flag-only (no pixel redaction).
- **2026-05-15 PM** `Beispiele/depth` + `Beispiele/duct` (+ 4 root exemplars: `bad`, `duct_sand`, `duct_depth`, `warnband`) loaded as **few-shot exemplars** in the Claude system prompt, not as training data.
- **2026-05-15 PM** Retract: hard-coded 30–40 cm trench depth in the prompt. That was an ÖGIG/fiber spec. Until Martin gives an APG number, treat the depth check as "is a depth reference visible / readable" — no threshold.
- **2026-05-15 PM** Retract: separate `04_research_log.md` / `RESEARCH.md` workflow. Past the long-form research phase — DECISIONS.md only from here. Reasoning lives in commit messages or chat.
- **2026-05-15 PM** Doc set cut to 4: `CLAUDE.md`, `README.md`, `PLAN.md`, `DECISIONS.md`. Old hackathon docs removed from working dir; git history keeps them.
- **2026-05-15 PM** Overlay-extraction approach **locked to Claude vision (Haiku 4.5)** — not Tesseract+regex. A 10-photo spread sample of `Resources/all/` shows variation that breaks fixed-crop / fixed-regex: overlay position varies (top-right, bottom-right, top-left depending on camera app); lat/lon appears in ≥3 formats (`46°33'56.226"N` DMS, `46.56153856N` decimal without separators, `Lat 46.551997, Long 14.294176` labeled); language mixes German + Cyrillic + English on identical fields (`Австрия` / `Austria`); ~30% of sampled photos show no lat/lon at all (address only). One vision call per photo absorbs all of this and also reads the in-frame paper FCP label when present.
- **2026-05-15 PM** Pipeline opens with a **"obvious-error" pre-filter** before per-segment classification: (a) `imagehash` perceptual-hash dedup runs first across the whole corpus (no API cost); (b) lat/lon ↔ printed-address consistency runs as a sanity flag on Claude's overlay output — forward-geocode the printed address, flag if the distance to the printed coords exceeds ~100 m. The geo check only applies to the subset of photos where both lat/lon and address are visible.
