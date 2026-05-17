# Backend logic — reference card

Dense lookup doc for the demo. If a judge asks something technical and you blank, scan here. Companion to [HOW_IT_WORKS.md](HOW_IT_WORKS.md) (plain-English narrative) and [BEHIND_THE_SCENES.md](BEHIND_THE_SCENES.md) (technical narrative).

---

## Pipeline at a glance

| # | Stage | Reads | Writes | Key file |
|---|---|---|---|---|
| 1 | Ingest | photo folder, geo files | photo index, geo in memory | `src/ingest.py` |
| 2 | Forensics | photo bytes | phash + tamper score per photo | `src/forensics.py` |
| 3 | Read (Claude) | one unique photo per phash group | per-photo QC row | `src/readqc.py` |
| 4 | Geomatch | readqc + forensics + geo | pin + snapped trench per photo | `src/geomatch.py` |
| 5 | Classify | geomatch + readqc + trenches | per-segment GREEN / YELLOW / RED | `src/classify.py` |
| 6 | Report | classify + readqc + geomatch | dashboard JSON, PDF, deficiency.csv | `src/report.py` |

Only one Claude call per **unique** photo (per phash group). Duplicates inherit the rep's row.

---

## Thresholds — one place

| Thing | Value | Where |
|---|---|---|
| Photo-spacing rule | 1 compliant photo per 5m of trench | `GREEN_MAX_GAP_M = 5.0` ([classify.py:73](src/classify.py#L73)) |
| RED density floor | < 1 compliant photo per 10m | `RED_MIN_DENSITY_PER_M = 0.1` ([classify.py:74](src/classify.py#L74)) |
| Max snap distance | 75m (further = "this photo isn't documenting any trench") | `MAX_SNAP_DISTANCE_M = 75` ([classify.py:72](src/classify.py#L72)) |
| latlon-vs-address mismatch | > 150m AND street names disagree | `LATLON_VS_ADDRESS_DIST_M = 150` ([geomatch.py:63](src/geomatch.py#L63)) |
| Internal CRS for distance math | UTM zone 33N (EPSG:32633) | Carinthia is in this zone |
| Storage CRS | WGS84 (EPSG:4326) | All lat/lon outputs |
| Nominatim throttle | 1.1 sec between uncached calls | `NOMINATIM_THROTTLE_S` ([geomatch.py:72](src/geomatch.py#L72)) |

The 5m number is **photo spacing**, not snap tolerance. Two different things.

---

## Per-photo checks (the 8)

Claude returns these fields. Six are visual, two are computed.

| # | Field | Type | What it answers |
|---|---|---|---|
| 1 | `warning_tape_visible` | yes/no/occluded | Orange tape over the cable |
| 2 | `sand_bedding_visible` | yes/no | Sand under the cable |
| 3 | `side_view_present` | yes/no | Side view of the trench (depth is visible) |
| 4 | `depth_reference_visible` | yes/no | Ruler / measuring rod in frame |
| 5 | `duct_visible` | yes/no | Conduit pipe in frame |
| 6 | `personal_data_visible` | yes/no | Faces / license plates (privacy flag) |
| 7 | `phash_cluster_id` (computed) | int | Group ID for visually identical photos |
| 8 | `latlon_vs_address_flag` (computed) | bool | GPS and address disagree on a different street |

Plus two **gating** fields that decide if the checks even apply:

| Field | Values | Effect |
|---|---|---|
| `relevance` | scorable / portrait / off_topic / unreadable | Non-scorable = ignored for trench scoring, kept in audit |
| `phase` | excavation / depth_measure / duct_laid / sand_bedded / tape_laid / backfilled / restored / paper_label / staging / other | Decides which subset of checks apply |

**Phase → required-checks mapping** at [classify.py:77-88](src/classify.py#L77-L88):

```
excavation     → side_view_present
depth_measure  → depth_reference_visible, side_view_present
duct_laid      → duct_visible
sand_bedded    → sand_bedding_visible, duct_visible
tape_laid      → warning_tape_visible
backfilled     → (no checks required)
restored       → (no checks required)
paper_label    → not trench evidence (excluded from scoring)
staging        → not trench evidence (excluded from scoring)
other          → not trench evidence (excluded from scoring)
```

A photo is **compliant** if all relevance/privacy/distance gates pass AND every check required for its phase returns `yes`. Logic at [classify.py:91-124](src/classify.py#L91-L124).

---

## Per-photo verdict (upload screen)

Returned by `verdict_for_photo()` at [live_score.py:119-138](src/ui/components/live_score.py#L119-L138):

| Verdict | Color | Condition |
|---|---|---|
| `DROP` | grey | `relevance != "scorable"` |
| `WITHHELD` | grey | `personal_data_visible == "yes"` |
| `PASS` | green `#22c55e` | All required visual checks = yes |
| `WARN` | yellow `#eab308` | 1-2 required checks failing |
| `FAIL` | red `#ef4444` | 3+ required checks failing |

`DROP` and `WITHHELD` photos are not penalized — they're just not evidence.

---

## Coordinate source — how a photo gets a pin

Decision order at [geomatch.py:370-379](src/geomatch.py#L370-L379):

1. `overlay_latlon` parsed from photo text → use it. Tag `coord_source = "overlay_latlon"`.
2. Else if `overlay_address` present → Nominatim forward-geocode (cached) → use the result. Tag `coord_source = "geocoded_address"`.
3. Else → no pin, photo goes in the unmappable bucket. Tag `coord_source = "none"`.

GPS-text parsing supports four formats (DMS with `°`, decimal with hemisphere letter, labeled `Lat:/Long:`, comma-as-decimal for German locale). See [geomatch.py:82-160](src/geomatch.py#L82-L160).

### Snap (same logic for both coord sources)

Project the pin to UTM, find the **nearest LineString** within the photo's FCP zone, record `segment_id`, `segment_t` (0–1 position along the segment), `snap_distance_m`. No distance threshold during snap — but `snap_distance > 75m` will downgrade the photo to non-compliant later. [geomatch.py:290-306](src/geomatch.py#L290-L306).

### FCP assignment

| `fcp_assignment` | Meaning |
|---|---|
| `inside_polygon` | Pin landed inside an FCP zone — restrict snap to trenches inside that zone |
| `nearest_fallback` | Inside the cluster but in a gap between FCPs — snap globally |
| `off_cluster` | Outside the project cluster entirely — flagged, still snapped to nearest |

---

## Trust signal for address-only photos

A geocoded address pin sits at the **building centroid**, not the trench. Saying "purple pin = this photo's location" is honest about the source but doesn't verify the work happened there. The verification comes from the **paper label**.

### `label_match` field — the verification

A photo often shows a handwritten card like `F170-R084-11-or`. We parse `(F-code, R-code)` and compare to the snapped trench. Values:

| `label_match` | Meaning | Trust |
|---|---|---|
| `ok` | F-code AND R-code on the card match the snapped trench | High — paper label confirms position |
| `fcp_mismatch` | F-code on card disagrees with the snapped FCP zone | Low — likely wrong location |
| `r_mismatch` | F-code matches but R-code (segment) doesn't | Medium — right zone, wrong segment |
| `no_label` | No readable card in the photo | Unverifiable — fall back to coord_source confidence |

Logic at [geomatch.py:425-444](src/geomatch.py#L425-L444). This is what saves us on address-only photos: even if the pin is fuzzy, an `ok` label means the photo really is at the trench it claims to be at.

### latlon-vs-address mismatch flag

When **both** overlay GPS and overlay address are present, we cross-check. We geocode the address, compute haversine distance to the GPS pin, and check if the street names disagree. Flag fires only if `distance > 150m` AND streets are different — because same-street number mismatch is normal (the photographer's number vs the property being connected). [geomatch.py:411-422](src/geomatch.py#L411-L422).

---

## Segment scoring (GREEN / YELLOW / RED)

For each trench segment, gather snapped compliant photos, sort by position, look for the largest gap.

```
no compliant photos                              → RED
segment ≤ 5m and ≥1 compliant photo              → GREEN
n_compliant / length < 1/10                      → RED (density floor)
max_gap ≤ 5m                                     → GREEN
otherwise                                        → YELLOW
```

Gaps include start-to-first-photo and last-photo-to-end. So a 47m segment with one photo at meter 23 has gaps of [23, 24] → max 24m → YELLOW. [classify.py:127-178](src/classify.py#L127-L178).

The "reason" string is plain English: *"max gap 24m > 5m between meter 0 and meter 23"*.

---

## Duplicate detection (forensics)

- **Perceptual hash** (`imagehash` library) computes a 16-char fingerprint per photo. Identical fingerprint = the same image, even after resize / re-save.
- Photos grouped by fingerprint → `phash_cluster_id`.
- One photo per cluster is the **representative** (sent to Claude). Others inherit its readqc + geomatch row.
- The cluster relationship is preserved in the output, so the report can say "this photo also appears at job #X, photo #Y".

Caught ~600 reused photos in the 3,929-photo pilot.

---

## Tampering check (forensics)

**ELA (Error Level Analysis)** via Pillow. Re-save each photo at known JPEG quality, diff against the original, look at high-variance regions. Edited regions stand out. Recorded as a `tamper_score` per photo. **Hint, not auto-fail.**

---

## Privacy handling

- Claude returns `personal_data_visible = yes` for faces / license plates.
- Photo gets verdict `WITHHELD` (grey pin, neutral).
- Dashboard swaps the image for a privacy-notice card. The image is **not** rendered on screen during the demo. Original file is untouched.
- Photo is listed in a "needs retake" bucket. Not penalized in scoring (because the worker just needs to re-shoot).

No black boxes are painted on the image. That would need a dedicated tool.

---

## What runs where

- **Anthropic servers**: Claude vision calls. We send photo bytes only. **No route-alignment data is sent over the network** (NDA).
- **Laptop**: everything else. Phash, ELA, geomatch, classify, report. One Python program.
- **Demo dashboard**: reads pre-computed files from disk. **No live AI calls during the pitch.**
- **Upload page (Screen A)**: the one live AI surface. Operator drops photos, Claude reviews them in ~5 seconds.

---

## Output files (what each one is for)

| File | Source stage | Used by |
|---|---|---|
| `data/processed/readqc.jsonl` | Read (Claude) | Geomatch, Classify, Dashboard |
| `data/processed/forensics.jsonl` | Forensics | Geomatch (cluster lookup), Dashboard |
| `data/processed/geomatch.csv` | Geomatch | Classify, Dashboard |
| `data/processed/nominatim_cache.json` | Geomatch | Re-runs (avoid re-querying) |
| `data/processed/verdicts.csv` | Classify | Report, Dashboard |
| `data/processed/deficiency.csv` | Report | Reviewer (RED/YELLOW rows only) |
| `data/reports/*.pdf` | Report | Operator handoff |

---

## Common judge questions — where to look

| Question | Section |
|---|---|
| "How do you know a photo is in the right place?" | Coordinate source + Trust signal |
| "What if there's no GPS?" | Coordinate source step 2 + `label_match` |
| "Why 5 meters?" | Thresholds table — adopted from partner's QC deck |
| "What if the AI is wrong?" | Per-photo checks (8) + 219 hand-labeled ground-truth photos |
| "Can a contractor fool it?" | Duplicate detection + latlon-vs-address mismatch |
| "How would this scale?" | Same code; ~$1,900 + a few days for 424k photos |
| "What about privacy?" | Privacy handling |
| "What CRS / projection?" | Thresholds table — UTM 33N internally, WGS84 for storage |

---

## Things we deliberately do NOT do

- Measure depth in cm (no operator spec; we just check "is a depth reference visible")
- Do RTK-grade GPS verification (our GPS comes from photo overlay, ~4m accurate)
- Censor faces inside the image bytes
- Train a custom vision model (would underperform Claude on the variation we see)
- Reproject to Lambert 31287 (the data is already WGS84)
