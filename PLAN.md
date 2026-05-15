# PLAN — Challenge 2 build

48 hours. APG photo-QC prototype. Three deliverables: working pipeline, deficiency report, 3-minute demo.

---

## The one-liner

> Ingest trench photos + a GeoJSON route. Score each route segment **green / yellow / red** against six compliance checks. Produce a reviewer-ready deficiency report.

## The six checks (from the APG brief)

| # | Check | How we detect it |
|---|---|---|
| 1 | **Warning tape (Warnband) visible** | Claude vision — yes / no / occluded |
| 2 | **Sand bedding documented** before backfilling | Claude vision — yes / no / occluded |
| 3 | **Side view / trench profile** present | Claude vision — yes / no |
| 4 | **Trench depth** confirmed with visible reference (ruler / measuring rod) | Claude vision — depth reference visible yes/no; OCR the value if a ruler is in frame |
| 5 | **Duplicate / reused photo** across lots | `imagehash.phash` Hamming-distance ≤ 6 across the corpus |
| 6 | **GPS location consistent** with declared project site | OCR the photo's printed address + optional lat/lon + paper-label FCP code; cross-check against the GeoJSON cluster polygon |

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
03 readqc       → ONE Claude vision call per unique photo: overlay fields (date, street, lat/lon, FCP code) AND the 5 visual checks (warning tape, sand, side view, depth ref, duct)
04 geomatch     → (a) lat/lon ↔ printed-address sanity check, then (b) join OCR'd address / FCP code → GeoJSON cluster / FCP / segment
05 classify     → roll up per-segment: complete / partial / missing
06 report       → Streamlit UI: folium map + clickable segment panel + downloadable deficiency CSV; surface the "obvious-error" flags (duplicates + geo-mismatch) at the top
```

**Pre-filter ordering rationale (added 2026-05-15 PM):** dedup runs *before* the Claude call so we don't pay to score the same image twice — one representative per pHash cluster goes through `readqc`, the duplicates inherit its result with a `duplicate_of=…` tag. The lat/lon-vs-address sanity check is a few lines of post-processing on `readqc`'s output (forward-geocode the address with Nominatim, compute haversine to the printed coords, flag if > 100 m). It only fires on photos where both fields are present (~70% of the sample); the rest fall through to FCP-code / route-data matching.

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

**Old plan assumed EXIF GPS.** Wrong — of 720 files in `Resources/all/`, only 5 have any GPS in EXIF (WhatsApp strips it). The signal we use instead is the **overlay text the camera app burns into the photo** (date, lat/lon, address) plus the **paper FCP label** that sometimes appears physically inside the frame.

**Why a vision model, not OCR + regex (10-photo spread sample, 2026-05-15 PM):**
- **Overlay position varies.** Most are bottom-right, but several are top-right, and the "GPS Map Camera" app puts it top-left. No fixed crop covers all cases.
- **Lat/lon has at least three formats in the wild:** DMS with symbols (`46°33'56.226"N 14°17'5.222"E`), decimal without separators (`46.56153856N 14.28786228E`), and labeled decimal (`Lat 46.551997, Long 14.294176`).
- **Language mixes German, English, and Cyrillic** on the *same* fields — e.g. country renders as `Austria`, `Австрия`, or `Kärnten`.
- **~30% of sampled photos show no visible lat/lon at all** — just date + address. Any extractor has to degrade gracefully when coords are missing.
- A regex pipeline would silently fail on a meaningful fraction of the corpus; Claude vision handles every variation in one shot, returns structured JSON, and also reads the paper FCP label when present.

**What we do:**
1. **One Claude vision call per unique photo** (post-dedup) returns the overlay fields *and* the QC signals together — see schema below. Caches the system prompt + 4 exemplars; cache reads cost 0.1× input.
2. **Sanity flag — lat/lon vs printed address.** If both are present in the overlay, forward-geocode the address (Nominatim, cached locally per unique address) and compare to the printed coords with the haversine formula. Distance > ~100 m → flag the photo. Catches OCR errors and reused/recycled photos where the camera app's coords got out of sync with the address.
3. **Paper-label codes** look like `F170-R084-11-or`. `F170` matches an `fcpName` in `FCPs.geojson`. `R084` matches `ductMainShort` in `Trenches.geojson`. The suffix is segment + duct colour code.
4. **Match logic to route data, in order of preference:**
   - If lat/lon is printed → drop a point, distance-join to the nearest trench segment.
   - Else if FCP code on paper label → join to that FCP's segments directly.
   - Else if street + house number → cluster within the SiteCluster polygon (or group by street name as a fallback).
5. **Check 6 (location consistency):** OCR'd address city must fall inside the SiteCluster polygon (Maria Rain). FCP code on paper must match the cluster ID. Flag mismatches.

## Claude prompt sketch (one call per photo)

```python
QC_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "warning_tape_visible":    {"enum": ["yes", "no", "occluded"]},
        "sand_bedding_visible":    {"enum": ["yes", "no", "occluded"]},
        "side_view_present":       {"enum": ["yes", "no"]},
        "depth_reference_visible": {"enum": ["yes", "no"]},
        "depth_value_cm":          {"type": ["number", "null"]},
        "duct_visible":            {"enum": ["yes", "no", "occluded"]},
        "overlay_date":            {"type": "string"},
        "overlay_address":         {"type": "string"},
        "overlay_latlon":          {"type": ["string", "null"]},
        "paper_label_code":        {"type": ["string", "null"]},
        "note":                    {"type": "string", "maxLength": 200},
    },
    "required": ["warning_tape_visible", "sand_bedding_visible", "side_view_present",
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
- Batch-run Claude QC on all 3,929 photos. Cost: 3,929 × ~$0.0012 (Batch API) ≈ **$5**.
- pHash duplicate detection across the corpus.
- ELA tamper pass on a sample.
- Geomatch: join OCR'd address / FCP code to the GeoJSON. Log unmatched.
- **Goal by 14:00:** segments coloring green/yellow/red on the map.

### Saturday afternoon (14:00 → 17:00)
- Click a red segment → side panel with photo grid + per-photo signal table + Claude's note.
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
3. **Click the red dot:** map mostly green with one screaming red segment → click → photo grid + reason list.
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
