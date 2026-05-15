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

### Late Friday evening — eyes-on photo audit

- **2026-05-15 evening** Brief line `Kärntner Projekt ohne App` (Carinthia project w/o the GPS overlay app) is **wrong for *this* dataset**. Visual audit of 21 random photos across all naming patterns: 21/21 carry a burned-in overlay (date + address, often lat/lon, sometimes mini-map). EXIF audit of a 50-photo random sample: 0/50 have EXIF GPS. Overlay-OCR via Claude vision remains the right path. Do not rebuild around the brief's "ohne App" note.
- **2026-05-15 evening** Scoring granularity moves from **per-segment (2,983 LineStrings)** to **per (FCP, duct R-code) pair (~200 cells)**. The paper labels read `F### + R### + slot + color` — they encode FCP + duct main + position-in-bundle, never LineString segment ID. Median R-code spans 4 LineStrings; per-segment scoring was unsupported by the signals we can extract. FCP-level (9 cells) kept as drill-up only.
- **2026-05-15 evening** Add a **phase classifier** as a first-class output of the Claude vision call. Photos document different phases of work (excavation → depth-measure → duct-laid → sand-bedded → tape-laid → backfilled → restored, plus paper-label, staging, other). Each of the 6 QC checks is only scored on photos of its phase-relevant subset — a depth-measure photo missing warning tape no longer drags the duct's score down. Why: scene audit found dumpster shots, finished-asphalt shots, night flashlight shots, paper-label close-ups, etc.; treating all of them as "must score all 6" produced noise.
- **2026-05-15 evening** Add a **`relevance` gate** to the same call: `scorable / portrait / off_topic / unreadable`. Non-scorable photos are **hard-dropped** from per-duct scoring and surfaced separately on the report as "not classified" with reason. Hard-drop + soft-gate hybrid — cleanest demo, least unfair to contractors.
- **2026-05-15 evening** Soften the lat/lon-vs-address mismatch rule from `>100 m → flag` to `>150 m AND different street → flag`. Within-street disagreements between paper label and overlay are normal (paper = property being connected, overlay = photographer's standing position), not a fraud signal.
- **2026-05-15 evening** Off-cluster overlay addresses (e.g., `Lambichl`, neighboring village) → flagged as `geo_mismatch`, not silently dropped. SiteCluster polygon is the gate.
- **2026-05-15 evening** Confirmed overlay variability bigger than v1: 4 languages (DE/EN/Russian Cyrillic/transliterated), 4 lat/lon formats (incl. DMS-with-comma-decimal `46°33'29,30965"N`), 3 overlay positions (BR / TR / TL), ≥2 camera apps (TimePhoto family + GPS Map Camera). Overlay sometimes partially occluded by paper labels held against camera. Reinforces the vision-not-regex choice.
- **2026-05-15 evening** 43 files carry `— копия` suffix (Russian "copy") — pre-labeled duplicates baked into filenames. Showcase pair for the duplicate-detection demo segment.
