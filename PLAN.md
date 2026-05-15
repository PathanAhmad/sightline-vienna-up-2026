# PLAN — Challenge 2 build

48 hours. APG photo-QC prototype. Three deliverables: working pipeline, deficiency report, 3-minute demo.

---

## The one-liner

> Ingest trench photos + a GeoJSON route. Position each photo along the trench network using overlay-OCR'd lat/lon and address. Score each **LineString trench segment** **green / yellow / red** by the **photo-every-5m density rule** + per-photo compliance checks. Produce a reviewer-ready deficiency report.

## The rubric

Two layers — both need to be green for a segment to be GREEN:

**Layer A — per-segment spatial coverage** (the rule the reference ÖGIG deck reveals):
- **GREEN** — at least one compliant photo per 5 m of trench length, no gaps > 5 m.
- **YELLOW** — photos exist but density < 1/5m, OR photos exist but a quality check fails.
- **RED** — fewer than 1 photo per 10 m, OR no photos at all.

**Layer B — per-photo compliance checks** (superset of the APG brief + ÖGIG-deck additions):

| # | Check | Source | How we detect |
|---|---|---|---|
| 1 | **Warning tape (Warnband) visible** | APG brief | Claude vision — yes / no / occluded |
| 2 | **Sand bedding visible** before backfilling | APG brief + ÖGIG deck | Claude vision — yes / no / occluded |
| 3 | **Side view / trench profile** present | APG brief | Claude vision — yes / no |
| 4 | **Trench depth confirmed** with visible reference (ruler / measuring rod) | APG brief + ÖGIG deck ("ruler readable") | Claude vision — depth reference visible yes/no; OCR the value if a ruler is in frame |
| 5 | **Duplicate / reused photo** across the corpus | APG brief (our differentiator) | `imagehash.phash` Hamming-distance ≤ 6 |
| 6 | **GPS / location consistent** with declared project site | APG brief + ÖGIG deck ("GPS stamp") | Overlay address / lat/lon + paper-label FCP code; cross-check against FCP polygon and SiteCluster |
| 7 | **Pipe ends sealed** (white end-caps on duct bundle) | ÖGIG deck only — **not in the APG brief** but industry-standard | Claude vision — yes / no / occluded |
| 8 | **No personal data** (faces / license plates) visible | ÖGIG deck only — NIS2 compliance | Claude vision — yes / no |

**How Layer B feeds Layer A.** A photo counts as **compliant** for the 5m density rule if ALL of these hold:
- `relevance = scorable` (the relevance gate passed)
- `personal_data_visible = no` (NIS2 clean)
- It is NOT a duplicate of another photo we've already counted (check 5)
- Its overlay address / lat/lon snapped to a segment without a >150m disagreement (check 6 passed)
- The phase-relevant subset of `{warning_tape, sand_bedding, side_view, depth_reference, duct, pipe_ends_sealed}` is all `yes` (treating `occluded` as a partial credit, not pass)

A `scorable` photo that fails any of the above is counted as "photo present but quality insufficient" (the YELLOW driver). A photo that fails the relevance gate is dropped from the segment entirely (logged in a separate bucket).

## What we cannot assess

The reference deck also requires **RTK GPS survey verification** (centimeter-grade survey data). We do not have RTK data for this dataset — only photo-overlay GPS at ±3.79m accuracy. We frame this explicitly in the pitch: "We assess the photo half of compliance. RTK survey verification is a complementary future phase."

## What data we have (in `Resources/`)

- **3,929 trench photos** (`Fotos-...zip`) — Maria Rain, Carinthia. Mixed WhatsApp uploads + a TimePhoto-style overlay app (also occasionally GPS Map Camera). **No EXIF GPS.** Each photo has a printed overlay with date + street address; ~70% also have lat/lon printed.
  - **Hidden duplicate ground truth in filenames.** 1027 files carry an `N_` prefix (`1_IMG-...`, `2_IMG-...`). Same image stem appearing under multiple N_ prefixes = same photo submitted to multiple jobs. **471 unique stems → 556 known duplicates pre-labeled by the submission system.** Plus 43 files with the Russian `— копия` ("copy") suffix. Together ~600 known duplicates for free — perfect ground truth for our pHash dedup recall check.
- **219 labeled example photos** (`Beispiele-...zip`) — these are a **labeled subset of Fotos**, not separate data:
  - `Beispiele/depth/` — 114 photos labeled "depth-primary" (measuring rod is the dominant feature)
  - `Beispiele/duct/` — 105 photos labeled "duct-primary" (cable bundle is the dominant feature)
  - 0 overlap between depth/ and duct/ — labels are mutually exclusive
  - 4 root exemplars: `bad.jpeg`, `duct_sand.jpg`, `duct_depth.jpg`, `warnband.jpeg`. Used as few-shot anchors in the Claude prompt.
  - **Use these as a calibration set:** after the batch run, measure our classifier's accuracy at predicting phase=`depth_measure` for `Beispiele/depth/` photos and phase=`duct_laid` for `Beispiele/duct/` photos. Becomes a pitch-able accuracy number.
- **Geo data** (`CLP20417A-P1-B00__...zip`) — one cluster: POP file empty, 9 FCPs, 2,983 trench LineString segments, FCP polygons, SiteCluster polygon. CRS **WGS84 / EPSG:4326** — no reprojection.
  - **Coverage gotcha:** FCP polygons cover 102.8% of the SiteCluster but with 18.7% gap inside the cluster and 21.5% spill outside. Point-in-polygon alone isn't sufficient for FCP assignment — need a nearest-FCP fallback when an address falls into a gap.
- **Reference decks** (`oegig_ai_qc_*.pptx`) — ÖGIG-themed, **but contain the actual scoring rubric** (per-segment, photo-every-5m, 6 photo-compliance criteria). Pitch arc borrowed; rubric adopted; cost numbers used pending Martin's APG-specific replacements.
- **The brief** (`Hackathon Challenge_ ... .docx`) — source of truth. 6 APG checks: warning tape, sand bedding, side view, depth, duplicate, GPS-consistent.

## Stack (locked, see [pyproject.toml](pyproject.toml))

Python 3.11 + uv · Streamlit (no FastAPI — one process) · **Claude Sonnet 4.6** vision as QC engine (upgraded from Haiku 4.5 after a 5-photo head-to-head: Sonnet wins 3/5 on hard cases — night shots, multi-phase priority, edge-of-frame tape — for ~$15 batch cost vs Haiku's ~$5; the $10 delta buys correctness on the hardest demo cases) · `imagehash` (pHash) + Pillow ELA for forensics · `geopandas` + `folium` for geo · `pillow-heif` defensive for HEIC (current data is JPEG, keep it). No YOLO. No torch. No `easyocr`/`paddleocr`.

## Pipeline (named stages, each in its own file)

```
01 ingest       → walk photos, load GeoJSONs into geopandas
02 forensics    → pHash dedup across the corpus (cheap, no API) + ELA pass for tamper hints
03 readqc       → ONE Claude Sonnet 4.6 vision call per unique photo: phase + relevance + overlay fields + 7 visual checks (incl. pipe_ends_sealed, personal_data_visible)
04 geomatch     → snap each photo to a precise point on the trench network:
                  (a) Overlay lat/lon → nearest LineString segment + position along that segment
                  (b) Address-only photos → forward-geocode via Nominatim → nearest LineString within the FCP polygon
                  (c) Cross-check: if lat/lon and geocoded-address disagree by >150m AND different street → flag
                  (d) Paper-label FCP + R code (when present) → consistency check against the snapped segment
05 classify     → per-segment rollup:
                  - sort photos by position along the segment
                  - check the 5m density rule
                  - check each photo's compliance status (passes phase-relevant subset of checks 1-7, fails check 8)
                  - verdict: GREEN / YELLOW / RED
06 report       → Streamlit UI: folium map (LineStrings colored by verdict) + clickable segment panel + downloadable deficiency CSV; surface the "obvious-error" flags (duplicates + geo-mismatch + personal-data-present) at the top
```

**Pre-filter ordering rationale:**
- **Dedup runs *before* the Claude call** so we don't pay to score the same image twice. One representative per pHash cluster goes through `readqc`; duplicates inherit its result with a `duplicate_of=…` tag. Bonus: the 1027 `N_`-prefixed filenames give us ground-truth duplicate pairs to validate pHash recall.
- **Relevance gate inside `readqc`:** Claude returns `relevance ∈ {scorable, portrait, off_topic, unreadable}`. `portrait` / `off_topic` / `unreadable` photos are **hard-dropped from scoring** (logged separately in the report as "not classified" with reason) — they don't drag a segment's score down. `scorable` photos go to the density rollup.
- **Personal-data gate inside `readqc`:** Claude returns `personal_data_visible: yes/no`. Photos with `yes` are excluded from the segment's compliance count and listed in a "needs retake" bucket — addresses NIS2 without claiming pixel-level pre-filtering.
- **Lat/lon ↔ address sanity check:** post-process `readqc` — forward-geocode the printed address (Nominatim, cached) and haversine-compare to printed coords. Threshold **>150 m AND different street** → flag. Within-street disagreement (overlay says "7 Bahnhofstraße", paper label says "Bahnhofstraße 9") is *normal* and not a fraud signal — paper documents the property being connected, overlay documents where the photographer is standing.

Folder skeleton to create first thing Saturday morning:

```
src/
  ingest.py        # walk Fotos/, load GeoJSONs into geopandas, write manifest.sqlite
  forensics.py     # imagehash pHash dedup + Pillow ELA tamper pass
  readqc.py        # one Claude Sonnet 4.6 vision call per unique photo → QCResult Pydantic
  geomatch.py      # snap each photo to a LineString segment (lat/lon → nearest; address → Nominatim → nearest within FCP)
  classify.py      # per-segment 5m density rollup → GREEN/YELLOW/RED
  report.py        # Streamlit + folium UI; deficiency CSV; "not classified" / "personal-data" buckets
app.py             # `streamlit run app.py` entrypoint
scripts/           # one-off spikes (already committed: spike_qc_schema.py, spike_nominatim.py, spike_sonnet_vs_haiku.py)
data/              # gitignored — Fotos/, Beispiele/, geo/
```

Each stage prints what it did in plain English. Example: `[readqc] 3,372 photos scored, 9 parse failures → readqc_failures.json` and `[geomatch] 2,948 snapped to segment, 384 FCP-only (gap), 17 off-cluster → geomatch.csv`.

## The geomatch redesign (corrected after PPT review)

**Two earlier pivots and one correction:**

1. **Old plan (PLAN.md v1) assumed EXIF GPS for segment positioning.** Wrong — 0/50 random photos sampled have any EXIF. WhatsApp strips it. The geolocation signal is **overlay-OCR'd lat/lon + address + paper-label FCP code**, not EXIF.

2. **First pivot moved to per-FCP+duct (R-code) granularity** because paper labels don't encode segment IDs. **That pivot was wrong** — it ignored the reference ÖGIG deck's rubric, which is explicitly per-segment with a 5m photo-density rule.

3. **Correction (now):** scoring unit is **per LineString segment** (2,983 cells across the 9 FCPs). Segment positioning is achieved via **overlay lat/lon → nearest-LineString snap**, not via paper labels. Paper labels are a *consistency check* (FCP + R code should match the snapped segment), not the primary geomatch signal.

**Pitch line:** "2,983 trench segments across 9 zones. We can tell you, segment by segment, which ones have compliant photo coverage every 5 meters and which ones have gaps."

**Why a vision model, not OCR + regex (research + 21-photo eyes-on sample):**
- **Overlay position varies.** Bottom-right (TimePhoto family, most common), top-right (TimeStamp Camera with English locale), top-left (GPS Map Camera, with its own watermark). No fixed crop covers all cases.
- **Lat/lon has at least four formats in the wild:** DMS-period (`46°33'56.226"N 14°17'5.222"E`), **DMS-comma-decimal** (`46°33'29,30965"N 14°17'23,54444"E` — German locale), decimal-no-separators (`46.56153856N 14.28786228E`), labeled-decimal (`Lat 46.551972, Long 14.294088`).
- **Language mixes German, English, Russian (Cyrillic), and partial transliterations** on the *same* fields — country renders as `Austria` / `Австрия` / `Kärnten`; city as `Maria Rain` / `Мария-Райн`; months as `авг.` / `ноя6.` / `Oct`.
- **~30% of sampled photos show no visible lat/lon at all** — just date + address.
- **Overlay can be partially occluded** by paper labels held against the camera.
- A regex pipeline would silently fail on a meaningful fraction; Claude Sonnet 4.6 vision handles every variation in one shot, returns structured JSON, classifies phase, reads the paper FCP label, and assigns relevance — one call.

**What we do:**
1. **One Claude Sonnet 4.6 vision call per unique photo** (post-dedup) returns the overlay fields, the 7 per-photo visual checks (warning tape, sand bedding, side view, depth reference, duct visible, pipe ends sealed, personal data visible), the phase, and the relevance gate — see schema below. The other 2 rubric items (duplicate detection, GPS-consistency) are handled outside this call: duplicate detection in `forensics.py` via pHash; GPS-consistency in `geomatch.py` via lat/lon ↔ geocoded address haversine check.
2. **Geo-snap order of preference:**
   - Lat/lon printed → snap to nearest LineString in `Trenches.geojson` (and record position along it).
   - Address only → Nominatim forward-geocode → snap to nearest LineString within the matching FCP polygon.
   - Neither → photo enters the "unmappable" bucket; counts toward FCP-level totals but not segment-level.
3. **Cross-checks (after snap):**
   - If lat/lon AND address both present, geocode the address and check the haversine distance to the printed coords. Threshold **>150 m AND different street** → flag. (Same-street disagreement is normal: paper label = property being connected, overlay = photographer's location.)
   - If paper label `F###-R###` present, check the FCP and duct of the snapped segment match. Mismatch → flag.
4. **Off-cluster handling.** Confirmed working: Lambichl (a neighboring village) addresses geocode to a point ~1.7 km outside the SiteCluster polygon — correctly flagged as off-cluster, not silently dropped.
5. **Density rollup per segment.** Sort the snapped points by position along the segment. The segment is GREEN if no >5 m gap exists between consecutive compliant photos AND the start and end of the segment are each within 5 m of a compliant photo. YELLOW if photos exist but gaps > 5 m or quality fails. RED if no compliant photos at all.

**Paper-label codes** look like `F170-R084-11-or`: `F170` → `fcpName` in `FCPs.geojson`, `R084` → `ductMainShort` in `Trenches.geojson` (200 unique R-codes), `-11-` is the slot in the cable bundle and `-or` is the duct colour. The slot+colour identify the *specific cable*, not the LineString segment — so paper labels are a consistency check on the snapped segment's FCP/R, not the primary geomatch signal.

## Claude prompt sketch (one call per photo)

```python
QC_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        # Relevance gate (hard drop if not 'scorable')
        "relevance":               {"enum": ["scorable", "portrait", "off_topic", "unreadable"]},
        # Phase of work — informational; the 5m density rollup uses positions, not phases
        "phase":                   {"enum": ["excavation", "depth_measure", "duct_laid",
                                              "sand_bedded", "tape_laid", "backfilled",
                                              "restored", "paper_label", "staging", "other"]},
        # 7 visual checks (APG brief 5 + ÖGIG deck additions)
        "warning_tape_visible":    {"enum": ["yes", "no", "occluded"]},
        "sand_bedding_visible":    {"enum": ["yes", "no", "occluded"]},
        "side_view_present":       {"enum": ["yes", "no"]},
        "depth_reference_visible": {"enum": ["yes", "no"]},
        "depth_value_cm":          {"type": ["number", "null"]},
        "duct_visible":            {"enum": ["yes", "no", "occluded"]},
        "pipe_ends_sealed":        {"enum": ["yes", "no", "occluded", "not_applicable"]},  # ÖGIG-deck addition
        # NIS2 / privacy gate
        "personal_data_visible":   {"enum": ["yes", "no"]},  # faces or license plates
        # Overlay + paper label (the geomatch signals)
        "overlay_date":            {"type": "string"},
        "overlay_address":         {"type": "string"},
        "overlay_latlon":          {"type": ["string", "null"]},
        "paper_label_code":        {"type": ["string", "null"]},
        # Free-text reason — especially useful when relevance != scorable
        "note":                    {"type": "string", "maxLength": 500},
    },
    "required": ["relevance", "phase",
                 "warning_tape_visible", "sand_bedding_visible", "side_view_present",
                 "depth_reference_visible", "duct_visible",
                 "pipe_ends_sealed", "personal_data_visible",
                 "overlay_date", "overlay_address", "note"],
}
```

System prompt loads the 4 root exemplars (`bad`, `duct_sand`, `duct_depth`, `warnband`) once with a cache breakpoint. **Note:** `scripts/spike_qc_schema.py` validates the v2 5-check schema (no `pipe_ends_sealed`, no `personal_data_visible`); the production `src/readqc.py` extends to the 7-check schema above. The Pydantic class in the spike script is the reference template — copy-and-extend.

## 48-hour timeline (loose, spine firm)

### Friday tonight — DONE (research, no code yet)

Friday evening was spent on a deep data audit + AI spike + the PPT-rubric discovery + a re-spike. Output: this plan, locked. Spine work moved to Saturday early morning.

Concrete deliverables committed Friday night: PLAN.md, DECISIONS.md, `scripts/spike_qc_schema.py`, `scripts/spike_nominatim.py`, `scripts/spike_sonnet_vs_haiku.py`.

### Saturday early-AM (08:00 → 09:00) — pre-batch sanity
- Folder skeleton + `src/ingest.py` (walk Fotos/, load GeoJSONs into geopandas).
- One Claude Sonnet 4.6 vision call working end-to-end on a single photo, full JSON parses via Pydantic.
- Folium map showing SiteCluster polygon + 2,983 trench segments.
- Streamlit page: "loaded 3,929 photos, here's the map."

### Saturday morning (09:00 → 14:00)
- **pHash dedup FIRST** — process the whole corpus locally (no API cost). Validate recall against the ~600 known duplicates from N_ prefixes + копия suffix.
- **Batch readqc**: send each unique photo (post-dedup) to Claude Sonnet 4.6. Cost: ~3,400 calls × ~$0.0045 ≈ **$15**. ELA tamper pass runs in parallel.
- **Geomatch**: snap each photo to a LineString via overlay lat/lon (primary) or geocoded address + nearest-LineString within nearest FCP polygon (fallback). Log unmatched.
- **Classify**: per-segment 5m density rollup → GREEN/YELLOW/RED verdict. Account for the 18.7% FCP-polygon gaps (nearest-FCP fallback).
- **Calibration check**: measure phase-classifier agreement against Beispiele/depth (114 photos labeled depth-primary) and Beispiele/duct (105 photos labeled duct-primary). Becomes a pitchable accuracy number.
- **Goal by 14:00:** segments coloring green/yellow/red on the map; "not classified" + "personal-data" + "geo-mismatch" buckets populated.

### Saturday afternoon (14:00 → 17:00)
- Click a red segment → side panel with photo grid + per-photo phase + signal table + Claude's note + gap analysis ("no compliant photo between meter 12 and meter 31").
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
3. **Click the red segment:** map mostly green with one screaming red trench segment → click → photo grid + a gap-analysis line ("no compliant photo between meter 12 and meter 31 of this 47-meter segment").
4. **Cost on screen:** "this segment protects €X of grid asset" — translates ML to euros.

## Pitch outline (5 slides, 3 minutes) — hybrid: ÖGIG deck arc, pruned, recontextualized to APG

Slides are rails — demo eats ≥60% of the 3 minutes. Each slide is 1 sentence + 1 visual, no walls of text.

1. **Hook — "A hidden risk in every meter."** APG has 424,000 trench photos. Engineers review them by hand. Manipulation, re-use, and missing-documentation go undetected today. Each undocumented fiber cut during future road works costs €120K+; a 3–5× multiplier when liability cannot be proven. (Numbers borrowed from the ÖGIG reference deck — APG-specific numbers if Martin confirms tomorrow.)
2. **Good vs bad — visual proof.** Side-by-side: one compliant photo (open trench, GPS stamp, duct bundle visible, sand bedding, ruler readable, no persons) vs one non-compliant photo (dark, occluded, no duct visible). Establishes our checklist in the audience's head with zero technical jargon.
3. **THE DEMO.** Streamlit map, 9 colored FCP zones, 2,983 colored trench segments. Click a RED segment → photo grid + the specific reasons it's red ("no compliant photo between meter 12 and meter 31"; "photo X reused from job Y"; "photo Z contains a worker's face — NIS2 violation"). This is where we spend ~60% of the time.
4. **How it works in one diagram.** 5 stages: Ingest → AI Review → Geo-Match → Classify → Report. Manual review: 3–5 days per section. Our run: <30 minutes for the entire 3,929-photo dataset, cost ~$15.
5. **CTA — "Approve, define KPIs, scale."** Pilot on Maria Rain works (today). Same pipeline scales to APG's 424,000-photo portfolio. NIS2 audit trail and contractor accountability are free side-effects of the build.

## Open questions for Martin Fuhrmann (only when we see him in person)

Most prior questions have been answered by inspection. Remaining items are pitch/positioning, not blockers:

1. **Is APG the partner alone, or APG + ÖGIG joint?** Brief says APG; data is ÖGIG-style fiber work. Affects which logo and language we lead with.
2. **For the demo: is duplicate-photo-reuse-across-jobs a real APG operational pain, or is missing-evidence the bigger pain?** Decides which demo move we open with — fraud reveal or coverage-gap reveal.

The technical plan does not depend on these answers.

## Risks / what not to do

- **Don't rebuild the EXIF-GPS path.** 0/50 random photos sampled have any EXIF (WhatsApp strips it). OCR the overlay instead.
- **Don't try a fixed-crop + regex overlay parser.** Overlay position, lat/lon format, and language all vary across the corpus. Claude Sonnet 4.6 vision is the extractor.
- **Don't hard-code a trench-depth number.** The brief and the ÖGIG deck both treat "is a depth reference visible" as the check, not a numeric threshold. Keep it that way.
- **Don't burn time on pixel-level privacy redaction.** Claude flags `personal_data_visible`; the report excludes those photos and routes them to a "needs retake" bucket. NIS2-aware, not over-engineered.
- **Don't commit `Resources/`, `data/`, or `scripts/out/`.** NDA on route data + actual addresses appear in the spike output.
- **Don't depend on live Claude calls during the live pitch.** Pre-run Saturday night; cache the JSON; demo reads from disk (except any judge-handed photo).
- **Don't pivot silently.** Anyone changing approach says it out loud — this doc is the source of truth.
