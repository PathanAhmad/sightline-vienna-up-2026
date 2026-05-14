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

### Stack
- **Python 3.11** + uv / poetry
- **FastAPI** for the backend
- **Streamlit** or **Gradio** for the demo UI (fastest to ship)
- Alternative: Next.js + Leaflet if a teammate is a strong React dev

### Image ingest & EXIF
- `Pillow` — image I/O, basic EXIF
- `piexif` or `exifread` — robust EXIF including GPS
- `GPSPhoto` — convenience for lat/lon extraction
- `pyproj` — coordinate transforms if route is in EPSG:31287 (Austrian Lambert)

### Geo-matching
- `shapely` + `geopandas` — segment geometry, nearest-segment lookup
- `folium` or `leaflet.js` — interactive map output
- Buffer route by ~5 m, find nearest-point per photo

### Computer vision — the QC checks
- **Object presence (duct, ruler, sand, seal):** fine-tune **YOLOv8** on a tiny labelled set. The brief implies they'll give us photos — we label ~50 in Roboflow, train 100 epochs, demo on the rest.
- **OCR on ruler:** `easyocr` or `paddleocr` → read depth in cm
- **Quality (blur, exposure):** Laplacian variance + histogram stats
- **Privacy redaction:** an off-the-shelf face/plate detector (e.g. `yolov8n-face`, plus a license-plate model)

### Forensics (the "is this real?" pile)
- **Duplicate detection:** `imagehash` (pHash/dHash) + BK-tree for fast NN search; or `imagededup`
- **Manipulation:** `ELA` via Pillow recompression diff; `forensically` techniques (noise residual); for a stretch goal, `MantraNet` (pretrained)
- **EXIF sanity:** check `DateTimeOriginal` vs `GPSDateStamp`, software field (`Adobe Photoshop` is a red flag), check `ModifyDate > CreateDate`

### Vision-language stretch
- `OpenAI` / `Anthropic Claude` vision API for explanatory captions: *"This photo shows a partially-buried micro-duct without visible sand bedding."* — cheap, fast to ship, judges love it.

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
- **Overtraining YOLO with too few labels** — better to keep model simple, use prompt-engineered Claude/GPT vision for explanations rather than chase a perfect detector.
- **Don't believe the EXIF GPS blindly** — phones strip/round GPS. Have a fallback: filename parsing, manual upload, or LLM-extracted hint.
- **Coordinate systems** — ÖGIG GeoJSON might be EPSG:4326 or Austria's 31287 / 31256. Check before you geomatch or all your points land in the wrong country.
