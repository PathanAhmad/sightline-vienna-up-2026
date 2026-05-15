# PLAN — Challenge 2 build

48 hours. APG photo-QC prototype. Three deliverables: working pipeline, deficiency report, 3-minute demo.

---

## The one-liner

> Ingest trench photos + a GeoJSON route. Phase-classify each photo, then score each **FCP + duct (R-code)** unit **green / yellow / red** against six compliance checks aggregated over its photos. Produce a reviewer-ready deficiency report.

## The six checks (from the APG brief)

Per-photo signals; aggregated per duct (an R-code under an FCP) for the green/yellow/red verdict. A check is "satisfied for the duct" if ≥1 photo of the relevant phase confirms it.

| # | Check | How we detect it | Relevant phases |
|---|---|---|---|
| 1 | **Warning tape (Warnband) visible** | Claude vision — yes / no / occluded | tape-laid, backfilled |
| 2 | **Sand bedding documented** before backfilling | Claude vision — yes / no / occluded | sand-bedded, duct-laid |
| 3 | **Side view / trench profile** present | Claude vision — yes / no | excavation, depth-measure, duct-laid |
| 4 | **Trench depth** confirmed with visible reference (ruler / measuring rod) | Claude vision — depth reference visible yes/no; OCR the value if a ruler is in frame | depth-measure |
| 5 | **Duplicate / reused photo** across lots | `imagehash.phash` Hamming-distance ≤ 6 across the corpus | all |
| 6 | **GPS location consistent** with declared project site | Overlay address / lat/lon + paper-label FCP code; cross-check against FCP polygon and SiteCluster | all |

Privacy (no faces / plates / addresses leaking) is mentioned in the brief — keep it as a flag-only signal, no pixel-level redaction.

## What data we have (in `Resources/`)

- **3,929 trench photos** (`Fotos-...zip`) — Maria Rain, Carinthia. Mixed WhatsApp uploads + a TimePhoto-style overlay app. **No EXIF GPS.** Each photo has a printed overlay with date + street address; a minority also has lat/lon printed.
- **223 labeled example photos** (`Beispiele-...zip`):
  - `Beispiele/depth/` — 114 examples of visible depth measurement
  - `Beispiele/duct/` — 105 examples of visible duct / cable
  - 4 root exemplars: `bad.jpeg`, `duct_sand.jpg`, `duct_depth.jpg`, `warnband.jpeg`. **Use as few-shot anchors in the Claude prompt.**
- **Geo data** (`CLP20417A-P1-B00__...zip`) — one cluster: 1 POP, 9 FCPs, 2,983 trench LineString segments, FCP polygons, SiteCluster polygon. CRS **WGS84 / EPSG:4326** — no reprojection.
- **Reference decks** (`oegig_ai_qc_*.pptx`) — example pitch shape, ÖGIG-themed (not ours). Steal the structure, not the numbers.
- **The brief** (`Hackathon Challenge_ ... .docx`) — source of truth.

## Stack (locked, see [pyproject.toml](pyproject.toml))

Python 3.11 + uv · Streamlit (no FastAPI — one process) · Claude Haiku 4.5 vision as QC engine · `imagehash` (pHash) + Pillow ELA for forensics · `geopandas` + `folium` for geo · `pillow-heif` defensive for HEIC (current data is JPEG, keep it). No YOLO. No torch. No `easyocr`/`paddleocr`.

## Pipeline (named stages, each in its own file)

```
01 ingest       → walk photos, load GeoJSONs into geopandas
02 forensics    → pHash dedup across the corpus (cheap, no API) + ELA pass for tamper hints
03 readqc       → ONE Claude vision call per unique photo: phase + relevance + overlay fields + 5 visual checks
04 geomatch     → (a) lat/lon ↔ printed-address sanity check, then (b) join overlay address / paper FCP+R code → FCP polygon and duct (R-code)
05 classify     → roll up per FCP+duct: complete / partial / missing per phase-relevant check
06 report       → Streamlit UI: folium map + clickable duct panel + downloadable deficiency CSV; surface the "obvious-error" flags (duplicates + geo-mismatch) at the top
```

**Pre-filter ordering rationale:**
- **Dedup runs *before* the Claude call** so we don't pay to score the same image twice. One representative per pHash cluster goes through `readqc`; duplicates inherit its result with a `duplicate_of=…` tag.
- **Relevance gate inside `readqc`:** Claude returns `relevance ∈ {scorable, portrait, off_topic, unreadable}`. `portrait` / `off_topic` / `unreadable` photos are **hard-dropped from scoring** (logged separately in the report as "not classified" with reason) — they don't drag a duct's score down. `scorable` photos go to phase-aware check rollup.
- **Phase-aware scoring (soft gate):** Each `scorable` photo also returns a `phase`. The per-photo check verdicts only count toward the *checks listed as relevant for that phase* in the six-checks table. A depth-measure photo missing warning tape doesn't penalize the duct — tape is a later phase. A duct is **green** when ≥1 photo confirms each of the 6 checks across all its photos; **yellow** when 1–2 checks lack supporting photos; **red** when ≥3 do.
- **Lat/lon ↔ address sanity check:** post-process `readqc` — forward-geocode the printed address (Nominatim, cached) and haversine-compare to printed coords. Threshold **>150 m AND different street** → flag. Within-street disagreement (overlay says "7 Bahnhofstraße", paper label says "Bahnhofstraße 9") is *normal* and not a fraud signal — paper documents the property being connected, overlay documents where the photographer is standing.

Folder skeleton to create Friday night:

```
src/
  ingest.py
  readoverlay.py
  qc.py
  forensics.py
  geomatch.py
  classify.py
  report.py
app.py
data/
  Fotos/        # unpacked from Resources/
  Beispiele/
  geo/
```

Each stage prints what it did in plain English. Example: `[qc] 3920/3929 scored, 9 read failures → qc_failures.json`.

## The geomatch redesign (biggest single change from the old plan)

**Old plan assumed EXIF GPS, and PLAN.md v1 also assumed per-segment scoring.** Both wrong:
- 0/50 random photos sampled have any EXIF (WhatsApp strips it). Signal = overlay text + paper label.
- The paper labels carry `F### + R### + slot + color` — they encode **FCP + duct main + bundle-position**, NOT LineString segment ID. Of 2,983 segments, the median R-code spans 4 segments — so a paper label can't pick one. Per-segment scoring is unsupported by the data we have.

**Granularity decision (2026-05-15 evening):** scoring unit is the **FCP+duct (R-code) pair** — ~200 cells across the 9 FCPs. Map shows colored ducts, click drills into the photo set per duct. Pitch line: "9 zones, 200 ducts, 3,929 photos, 12 deficient ducts."

**Why a vision model, not OCR + regex (research + 21-photo eyes-on sample):**
- **Overlay position varies.** Bottom-right (TimePhoto family, most common), top-right (TimeStamp Camera with English locale), top-left (GPS Map Camera, with its own watermark). No fixed crop covers all cases.
- **Lat/lon has at least four formats in the wild:** DMS-period (`46°33'56.226"N 14°17'5.222"E`), **DMS-comma-decimal** (`46°33'29,30965"N 14°17'23,54444"E` — German locale), decimal-no-separators (`46.56153856N 14.28786228E`), labeled-decimal (`Lat 46.551972, Long 14.294088`).
- **Language mixes German, English, Russian (Cyrillic), and partial transliterations** on the *same* fields — country renders as `Austria` / `Австрия` / `Kärnten`; city as `Maria Rain` / `Мария-Райн`; months as `авг.` / `ноя6.` / `Oct`.
- **~30% of sampled photos show no visible lat/lon at all** — just date + address.
- **Overlay can be partially occluded** by paper labels held against the camera.
- A regex pipeline would silently fail on a meaningful fraction; Claude vision handles every variation in one shot, returns structured JSON, also reads the paper FCP label, classifies phase, and assigns relevance — one call.

**What we do:**
1. **One Claude vision call per unique photo** (post-dedup) returns the overlay fields, the QC signals, the phase, and the relevance gate — see schema below.
2. **Sanity flag — lat/lon vs printed address.** If both are present, forward-geocode the address (Nominatim, cached) and haversine to the printed coords. Flag only when distance >150 m **and** different street/locality. Within-street differences are expected (paper = destination property, overlay = photographer's location).
3. **Paper-label codes** look like `F170-R084-11-or`. `F170` → `fcpName` in `FCPs.geojson`. `R084` → `ductMainShort` in `Trenches.geojson` (200 unique R-codes). The `-11-` is the slot in the cable bundle and `-or` is the duct colour — those identify the *specific cable*, not the LineString segment.
4. **Match logic, in order of preference:**
   - **Paper label visible** → direct join to (FCP, R-code).
   - **Lat/lon printed** → point-in-polygon against the 9 FCP polygons; if inside one, FCP assigned. R-code resolved by snapping to nearest LineString of that FCP and reading its `ductMainShort`.
   - **Address only** → match street/house number to the closest FCP polygon. If ambiguous, leave R-code blank; the photo still counts toward FCP-level coverage.
   - **None of the above (off-cluster, e.g. `Lambichl` overlay)** → flagged as `geo_mismatch`.
5. **Check 6 (location consistency):** photo's resolved FCP/R must lie inside the SiteCluster polygon (Maria Rain, CLP20417A). FCP code on paper must match the polygon's `fcpName`. Mismatches → flagged, not silently dropped.

## Claude prompt sketch (one call per photo)

```python
QC_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        # Relevance gate (hard drop if not 'scorable')
        "relevance":               {"enum": ["scorable", "portrait", "off_topic", "unreadable"]},
        # Phase of work — only the checks relevant to this phase count toward the duct's rollup
        "phase":                   {"enum": ["excavation", "depth_measure", "duct_laid",
                                              "sand_bedded", "tape_laid", "backfilled",
                                              "restored", "paper_label", "staging", "other"]},
        # The 5 visual checks
        "warning_tape_visible":    {"enum": ["yes", "no", "occluded"]},
        "sand_bedding_visible":    {"enum": ["yes", "no", "occluded"]},
        "side_view_present":       {"enum": ["yes", "no"]},
        "depth_reference_visible": {"enum": ["yes", "no"]},
        "depth_value_cm":          {"type": ["number", "null"]},
        "duct_visible":            {"enum": ["yes", "no", "occluded"]},
        # Overlay + paper label (the geomatch signals)
        "overlay_date":            {"type": "string"},
        "overlay_address":         {"type": "string"},
        "overlay_latlon":          {"type": ["string", "null"]},
        "paper_label_code":        {"type": ["string", "null"]},
        # Free-text reason — especially useful when relevance != scorable
        "note":                    {"type": "string", "maxLength": 200},
    },
    "required": ["relevance", "phase",
                 "warning_tape_visible", "sand_bedding_visible", "side_view_present",
                 "depth_reference_visible", "duct_visible",
                 "overlay_date", "overlay_address", "note"],
}
```

System prompt loads the 4 root exemplars (`bad`, `duct_sand`, `duct_depth`, `warnband`) once with a cache breakpoint.

## 48-hour timeline (loose, spine firm)

### Friday tonight (now → 23:00)
- Unpack `Resources/Fotos.zip` and `Resources/Beispiele.zip` and `Resources/CLP....zip` into `data/`.
- Get the spine running: ingest photos + GeoJSONs, save a manifest to SQLite.
- One Claude vision call working end-to-end on a single photo, returning the full JSON schema.
- Folium map showing the SiteCluster polygon + the 2,983 trench segments.
- **End-state by midnight:** `streamlit run app.py` shows "loaded 3,929 photos, here's the map."

### Saturday morning (09:00 → 14:00)
- Batch-run Claude QC on all unique photos (post-dedup). Cost: ~3,900 × ~$0.0012 (Batch API) ≈ **$5**.
- pHash duplicate detection across the corpus.
- ELA tamper pass on a sample.
- Geomatch: join paper FCP+R / overlay address to FCP polygons + duct R-codes. Log unmatched.
- **Goal by 14:00:** ducts coloring green/yellow/red on the map; "not classified" bucket lists hard-dropped photos with reason.

### Saturday afternoon (14:00 → 17:00)
- Click a red duct → side panel with photo grid + per-photo phase + signal table + Claude's note.
- Deficiency report: CSV + a one-page HTML summary.
- **17:00 tech checkpoint with Sustainista.** Show what works.

### Saturday evening (17:00 → 23:00)
- Pre-rig the demo set-piece: 4–5 photos (one clean, one duplicate pair, one tampered, one with missing bedding).
- 5-slide deck (see below).
- **Record a 90-second backup demo video.** Non-negotiable.

### Sunday (09:00 → 10:30)
- Two full pitch rehearsals. Cut anything that takes >15 seconds to load.
- 10:30 — pitch.

## Killer demo moves (steal these)

1. **Live tamper:** mid-pitch, doctor a photo on stage → run it → tool flags it.
2. **The "wrong segment" catch:** show two near-identical photos submitted to different segments → tool calls duplicate-use.
3. **Click the red duct:** map mostly green with one screaming red duct line → click → photo grid + reason list per phase ("no depth-measure photo on file for this duct").
4. **Cost on screen:** "this segment protects €X of grid asset" — translates ML to euros.

## Pitch outline (5 slides, 3 minutes)

1. **The pain in one number.** APG has 424,000 trench photos in scope. Engineers review them by hand. Manipulation and re-use go undetected.
2. **What we built.** Screenshot of the map. Name the buyer: APG.
3. **How it works.** 5-step arrow diagram (ingest → OCR overlay → QC → classify → report).
4. **Who pays + what we save.** Engineer-hours per project × portfolio size = SaaS pricing.
5. **What's next.** Contractor accountability, real-time upload from job phones, NIS2 audit trail.

## Open questions for Martin Fuhrmann (he's around till ~20:00 today)

1. **Is APG actually the partner, or APG + ÖGIG joint?** Brief says APG; data is fiber. Need clarity.
2. **Per-photo manifest** — CSV/sheet linking each filename to its declared lot / project / GPS? Brief implies declared-location exists somewhere.
3. **APG trench-depth spec number** — for the prompt and for the pitch.
4. **Pilot scope vs deployable scope** — 3,929 is the pilot; is the deployable target really 424,000?
5. **NDA timing** — does it constrain what we can show on stage Sunday?
6. **Cross-photo duplicates** — is duplicate-fraud actually a real APG operational pain, or is missing-evidence the bigger one?

## Risks / what not to do

- **Don't rebuild the EXIF-GPS path.** It's empty for 715/720 photos; OCR the overlay instead.
- **Don't try a fixed-crop + regex overlay parser.** Overlay position, lat/lon format, and language all vary across the corpus — see the geomatch redesign section. Claude vision is the extractor.
- **Don't hard-code "30–40 cm" depth.** That was a fiber spec. Wait for Martin's APG number.
- **Don't burn time on pixel-level privacy redaction.** Flag-only is enough for the prototype.
- **Don't commit `Resources/` or `.audit_samples/`.** NDA on route data.
- **Don't depend on live Claude calls during the live pitch.** Pre-run Saturday night; cache the JSON; demo reads from disk (except any judge-handed photo).
- **Don't pivot silently.** Anyone changing approach says it out loud.
