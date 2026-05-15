# Challenge 2 — AI-Powered Construction Photo Compliance Audit

**Source:** https://www.sustainista.net/challengeoegig
**Domain expert (on-site whole weekend, also on jury):** Martin Fuhrmann
**Partner:** ÖGIG — Österreichische Glasfaser-Infrastrukturgesellschaft
**Prize:** €1,000

---

## The one-liner

> Build a working AI quality-control pipeline that ingests **trench documentation photos + a GeoJSON route**, scores each segment **green / yellow / red**, and produces a reviewer-ready risk report.

The phrase in the brief: **"Find the risk before it becomes expensive."**

---

## Why ÖGIG cares (the real-world context)

ÖGIG lays fiber-optic infrastructure across Austria — they plan, finance and operate **100+ long-term fiber projects** with €1bn+ Allianz-backed investment. Current state:

- Construction is outsourced to regional builders (Leyrer + Graf, Josef Kaim Bau, mih Fiber Austria).
- Each section has to be photo-documented at burial time — once the trench is backfilled, what's down there is invisible for 50 years.
- They already use PlanRadar for digital docs and saved "2 hours per day per inspection." But the **review** is still manual.
- A single route section can need **~500 photos** to review.
- **€42 M+ of network asset value** is at risk per project if documentation defects go undetected — that's the brief's stated number.

**Pain in plain terms:** bad documentation can invalidate warranty claims, shift liability when someone digs into the cable years later, and trigger expensive fiber cuts during road works.

---

## What the AI has to detect

### Coverage signals
- **Missing evidence:** route sections with no usable photo at all
- **Poor documentation:** photos exist but you can't see ducts, bedding, ruler, seals, context

### Risk signals
- **Acceptance hotspots:** missing evidence on segments that *should not* be signed off

### Compliance signals (the brief's explicit checklist)
| Check | What we're verifying |
|---|---|
| **GPS / date metadata** | EXIF GPS exists, timestamp plausible, no obvious tampering |
| **Duct visibility** | Conduit / micro-duct is in frame, identifiable |
| **Sand bedding** | Sand cushion is present around the duct (industry std ≥150 mm) |
| **Pipe-end seals** | End caps / seals on ducts — water/dirt ingress prevention |
| **Ruler readability** | Depth-measurement ruler legible (so depth claim is provable) |
| **Privacy** | No license plates, no faces, no addresses visible |

### And two "is this photo for real?" signals
- **Duplicate use:** same photo submitted for multiple segments → perceptual-hash collision
- **Manipulation:** photoshop, splicing, re-saved JPEG → ELA, noise analysis, metadata inconsistencies

---

## Trench-depth ground truth (general industry norms)

Austrian ÖNORM specifics weren't directly indexable, but standard EU/global guidance the AI can score against:

- **Green areas / pedestrian zones:** ≥ 0.35 m cover
- **Driveways / under traffic:** ≥ 0.55 m cover
- **Frost zones:** ≥ 0.70 m cover
- **Sand bedding cushion:** ≥ 150 mm under and around duct
- **Warning tape:** placed in the backfill layer above the sand
- ≥ 700 mm cover above the crown of the duct is a common default

> Confirm specifics with Martin Fuhrmann on Friday afternoon — ÖGIG will have a stricter internal spec.

---

## The pipeline (5 steps from the brief)

```
01 Ingest      ──►  load trench photos + GeoJSON route geometry
02 Geo-match   ──►  match EXIF GPS to nearest route segment
03 AI review   ──►  score photo quality + presence of required elements
04 Classify    ──►  segment = COMPLETE | PARTIAL | MISSING
05 Report      ──►  interactive map + risk summary
```

---

## Deliverables (must have all three)

1. **Prototype** — end-to-end pipeline: photo in → QC logic → segment classification out
2. **Output** — map or report with red/yellow/green segments
3. **Business case** — reviewer persona, risk reduction story, scaling rationale

## Demo skeleton (3 min)
- **0:00–0:30** ~500 photos, €42 M at risk, 50-year liability — the pain
- **0:30–1:30** Live: drop photos in → see map color up → click a red segment → see the deficiency list
- **1:30–2:30** What we automate today, what we'd add next, who pays (ÖGIG, contractor mgmt, warranty insurance)
- **2:30–3:00** Scale story across 100+ projects

---

## Saturday tech checkpoint

Show by Saturday late afternoon:
- A pipeline that ingests photos and runs at least one check
- A first cut of green/yellow/red segmentation with defensible logic

A rough segmentation Saturday > a polished slide deck.

---

## Must-haves vs nice-to-haves (from the brief)

**Must-have**
- End-to-end pipeline works (photo → logic → risk output)
- Segment-level classification (complete/partial/missing)
- At least **one clear compliance signal** detected

**Nice-to-have**
- Interactive web map (Leaflet/Folium)
- All 6 compliance signals
- PDF report generator
- Contractor scorecard / accountability
- Historical audit trail

---

## Resources promised in the brief

| Resource | Use |
|---|---|
| Trench photos (sample set) | Main input — wait for download link from organizers |
| GeoJSON route | Geo-match photos to segments |
| Compliance signals framework | Template for our QC logic |
| Example interactive map + report | Output format reference |

**Important:** final dataset is "shared shortly before hackathon to ensure equal starting conditions." Don't expect it Friday 15:00 — expect it ~16:00 at kickoff.

---

## Tech recipe (greenfield in 48 h, opinionated)

> **Updated 2026-05-15 after research pass.** The earlier version of this doc leaned on YOLOv8 fine-tuning as the central CV move. Research overturned that — see [06_tech_resources.md](06_tech_resources.md) for the full rationale. New plan below.

### Stack (lean, installed via [pyproject.toml](pyproject.toml))
- **Python 3.11** + uv (`uv sync` at repo root)
- **Streamlit** for the UI — one process, handles UI + logic, no separate FastAPI for the spine
- **Claude Haiku 4.5** as the QC engine (cost: ~$0.60 for all 500 photos via Batch API)
- Classical CV (`imagehash` + ELA-via-Pillow) for the forensics signals

### Image ingest & EXIF
- `Pillow` 12+ — image I/O + EXIF/GPS via `getexif().get_ifd(IFD.GPSInfo)` (drops `piexif`/`exifread`)
- `pillow-heif` — iPhone photos default to HEIC; **Claude API doesn't accept HEIC**, must convert to JPEG before upload
- `pyproj` — installed transitively via geopandas; coordinate transforms if route is EPSG:31287 (Austrian Lambert)

### Geo-matching
- `geopandas` (1.0+ uses `pyogrio`, no Fiona/GDAL pain on Windows in 2026) — one-line `gpd.sjoin_nearest`
- `folium` for the interactive map
- ÖGIG GeoJSON CRS check FIRST: 4326 vs 31287. Reproject once to metric (3857 or 31287) before distance ops.

### Computer vision — the QC checks
- **Object presence (duct, ruler, sand, seal):** **Claude Haiku 4.5 vision** with a strict JSON schema (see [06_tech_resources.md](06_tech_resources.md#claude-vision--the-qc-engine-haiku-45-default-batch--caching)). Not a fine-tuned YOLO — 30 hand-labels / 4 classes / 4 hours is below the practical small-data floor, and VLMs reliably win on "is X present" questions. Plan B for bounding boxes (e.g. auto-cropping a ruler to OCR tick marks): YOLO-World zero-shot, no training.
- **OCR on ruler:** ask Claude to read the value directly; if accuracy drops, crop with YOLO-World + read with a stronger model. Skip standalone `easyocr`/`paddleocr` unless we hit a wall — they pull torch.
- **Quality (blur, exposure):** Laplacian variance via `cv2` (cheap, 5 lines)
- **Privacy redaction:** Claude can flag presence; if we need pixel-level redaction, pull a face/plate model only at that point.

### Forensics (the "is this real?" pile — our likely differentiator, see Strategic angle below)
- **Duplicate detection:** `imagehash` pHash with Hamming-distance threshold ~6. (Skipping `imagededup` — pulls torch ~2.5 GB, redundant for our scale.)
- **Manipulation:** ELA hand-rolled with `Pillow.ImageChops.difference` against a quality-90 re-save (~15 lines). If we want a real forensics library, [`PhotoHolmes`](https://github.com/photoholmes/photoholmes) bundles ELA + Splicebuster + TruFor + CAT-Net behind one API.
- **EXIF sanity:** `DateTimeOriginal` vs `GPSDateStamp` agreement, `Software` field flags (`Adobe Photoshop`, `Snapseed`), `ModifyDate > CreateDate`.
- **Cross-photo recycling:** pHash + EXIF-timestamp + GPS-cluster across the corpus → catch photos submitted across multiple segments.

---

## Strategic angle (research-driven, 2026-05-15)

**The market already exists.** [Deepomatic Lens](https://www.iqgeo.com/blog/real-time-visual-ai-in-fiber-network-construction-building-it-right-the-first-time) (now in IQGeo's telecom suite) is purpose-built for fiber technicians to photograph a trench/splice/cabinet and get instant pass/fail on depth, cable presence, OCR-read cable IDs, seal integrity. Competitors: Groundhawk (UK, fiber-specific), AI Clearing (Austin), Sitetracker Scout (2025), and Vienna-based PlanRadar for the doc-mgmt layer.

**Pitch consequence:** name Deepomatic in slide 2 — proves we know the market. Then frame our differentiator: **cross-photo authenticity / recycling detection.** None of the commercial fiber-QC tools market this; insurance-fraud platforms (TruthScan, Verisk) do. The killer demo line: *"this photo was already submitted on job #4471, three weeks ago."*

**ÖGIG's actual spec** (per oegig.at/oefiber/): trench depth **30–40 cm**. Hard-code this number into the rule prompt — concrete beats generic industry norms.

**Cost of running 500 photos through Claude:** ~$0.60 on Haiku 4.5 + Batch API. The API budget is not a constraint; iterate freely.

**Shortcuts to bookmark (don't reinvent):**
- HF dataset `LouisChen15/ConstructionSite` — VQA + rule-violation annotations including underground/excavation scenes
- GitHub `Co-UDlabs/sewer_defects` — reference-object-based depth measurement code (directly applicable to ruler-in-photo)
- arXiv 2512.13974 — multi-layer VLM→LLM pipeline architecture for site inspection (the pattern we're copying)

### Output
- HTML report (Jinja2) + Folium map embedded
- Per-segment JSON: `{segment_id, status, signals: {duct: true, bedding: false, seal: unknown}, photos: [...], reasons: [...]}`

---

## Sample folder layout to spin up Friday night

```
trench-qc/
  data/
    photos/             # drop ÖGIG sample photos here
    route.geojson
  src/
    ingest.py           # walk photos, extract EXIF
    geomatch.py         # snap to segment
    checks/
      duct.py           # YOLO-based
      bedding.py
      ruler_ocr.py
      seal.py
      privacy.py
      forensics.py      # ELA + phash + EXIF sanity
    classify.py         # combine signals → status
    report.py           # html + folium map
  app.py                # streamlit demo
  pyproject.toml
```

---

## Killer demo moves (steal these)

1. **Live "tamper" demo:** hand-doctor a photo on stage → run it → tool flags it. Judges remember this.
2. **The "wrong segment" catch:** show two photos with near-identical pHash submitted for different segments → tool calls duplicate-use → savings.
3. **"Click the red dot" UX:** map full of green dots with one screaming red one → click it → 6 panel diagnostic → that's the deficiency report.
4. **Cost number on screen:** "this segment alone protects €X of network value over 50 years" — translates ML to euros.

---

## Risks / pitfalls to avoid

- **Building privacy redaction first** is a trap — it's the easiest sub-task but not the highest-value signal. Do geo-match + duct/bedding detection first.
- ~~**Overtraining YOLO with too few labels**~~ — already decided: skip YOLO entirely, use Claude vision as the QC engine. See Strategic angle above and [06_tech_resources.md](06_tech_resources.md).
- **Don't believe the EXIF GPS blindly** — phones strip/round GPS. Have a fallback: filename parsing, manual upload, or LLM-extracted hint.
- **Coordinate systems** — ÖGIG GeoJSON might be EPSG:4326 or Austria's 31287 / 31256. Check before you geomatch or all your points land in the wrong country.
