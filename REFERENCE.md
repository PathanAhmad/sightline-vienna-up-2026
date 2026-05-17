# REFERENCE — pipeline architecture & validation logic

Scan-fast technical reference. One pipeline, 6 stages, plus cross-cutting audit. Every bullet pulled from the code in [src/](src/).

---

## PIPELINE AT A GLANCE

```
photos/ + 3 GeoJSONs
      │
      ▼
[1 INGEST]   sha1 every file, walk folder, load geo
      │        →  manifest.sqlite  +  in-mem trenches/FCPs/cluster (WGS84)
      ▼
[2 FORENSICS]  pHash + ELA per photo, single-linkage cluster
      │        →  forensics.jsonl  (one row per photo, marks representatives)
      ▼
[3 READ/QC]  Claude vision, ONE call per representative
      │        →  readqc.jsonl  (10 enum fields + 4 overlay fields + note per photo)
      ▼
[4 GEOMATCH] parse overlay latlon → else Nominatim → snap to LineString
      │        →  geomatch.csv  (photo → segment_id + position t)
      ▼
[5 CLASSIFY] Layer-B per-photo gate, then Layer-A segment verdict
      │        →  verdicts.csv  (one row per segment, GREEN/YELLOW/RED)
      ▼
[6 REPORT]   deficiency.csv, not_classified.csv, personal_data.csv,
             summary.html, cover_prose.json  (PDF built on-demand by dashboard)
```

- **Linear pipeline, file-handoff between stages.** No shared state, no DB except `manifest.sqlite` (lookup only).
- **Resume-by-photo-id** at stage 3 (skip rows already in `readqc.jsonl`).
- **Audit log** ([src/audit.py](src/audit.py)) writes to `data/processed/audit.jsonl` from every stage — start/end banners + per-event drop lines.
- **Run order:** `python -m src.ingest` → `src.forensics` → `src.readqc` → `src.geomatch` → `src.classify` → `src.report`. Each stage exits non-zero if a required upstream artifact is missing.

---

## STAGE 1 — INGEST  ([src/ingest.py](src/ingest.py))

**Reads:** `data/Resources/all/**/*.{jpg,jpeg,png,heic}` + 3 GeoJSONs in `data/geo/`.
**Writes:** `data/processed/manifest.sqlite` (table `photos`).
**In-memory only:** `trenches_gdf`, `fcps_gdf`, `cluster_gdf` returned by `load_geo()`.

**Photo manifest:**
- **`photo_id` = SHA1 of file bytes** (1MB chunked). Survives renames. Stable across runs.
- Row: `(photo_id PK, rel_path, filename, bytes, mtime)`. Index on `filename`.
- **Byte-identical collision → `INSERT` fails → skip + audit event `byte_identical_skip`.** Keeps first occurrence.
- Iteration: `sorted(PHOTOS_DIR.iterdir())` for determinism.

**Geo loading:**
- All 3 GeoJSONs forced to **EPSG:4326** (`to_crs` if not already).
- **FCP code extraction:** `fcps["kmlDescriptionSimple"]` is `"F012 [81]"` → split on `" ["` → `fcp_name = "F012"`.
- **Trench → FCP tagging** (added in this stage, used downstream):
  - `mid = trench.interpolate(0.5, normalized=True)` — midpoint of the LineString.
  - For each FCP polygon, `poly.contains(mid)` → first match wins.
  - **Fallback** when midpoint sits in an interior gap (the 18.7% gap problem): nearest FCP by centroid distance.
  - Distance computed in degrees (lat/lon) — acceptable inside a ~5km cluster, only used for ordering.

---

## STAGE 2 — FORENSICS  ([src/forensics.py](src/forensics.py))

Local-only. No API cost. ProcessPool with 4 workers.

**Reads:** `manifest.sqlite`.
**Writes:** `data/processed/forensics.jsonl`.
**Row:** `{photo_id, phash, phash_cluster_id, is_phash_representative, ela_score, ela_flag}`.

**Per-photo work** (`_compute_one`):
- Open → convert RGB → downsize once so `max(side) ≤ 1024px`. **Both pHash and ELA share the downsized image.**
- **pHash = `imagehash.phash(img)`** — 64 bits / 16 hex chars.
- **ELA = re-save JPEG quality 90 → diff vs original → `ImageStat.mean` per-channel → average on 0–255.** Pure PIL, no numpy in worker (avoids OpenBLAS thread pool fights).
- BLAS/OMP env vars capped to 1 thread per worker — otherwise 4 workers each fork an OMP team and run out of memory.

**Clustering** (`cluster_phashes`):
- **Single-linkage union-find.** Hamming distance via XOR + popcount: `bin(h_i ^ h_j).count("1")`.
- **Threshold:** `≤ 6` → same cluster (`PHASH_HAMMING_THRESHOLD`).
- ~3.2k photos = ~5M pairwise XOR+popcount → well under a second.
- Cluster IDs are small ints assigned in discovery order.

**Representatives** (`pick_representatives`):
- **One rep per cluster: `min(photo_id)`.** SHA1 hex sorts lexicographically → deterministic across runs.
- Only representatives go to Stage 3. Non-reps inherit the representative's QC row later.

**ELA flag:**
- `ela_flag = ela_score > 15.0` (`ELA_THRESHOLD`). **Weak hint, not auto-fail.** Surfaced in report; no compliance impact.

**Validation tied to ground truth:**
- Filenames carry `N_` prefixes (submission counters) and `— копия` suffixes — pre-labeled duplicates baked into the dataset.
- `canonical_stem()` strips both → family key for recall check.
- Reported: byte-identical merges at ingest + pHash extras + count of pHash clusters with >1 member.

---

## STAGE 3 — READ / QC  ([src/readqc.py](src/readqc.py))

The only AI stage. **One Claude vision call per representative photo.**

**Reads:** `forensics.jsonl` (filter `is_phash_representative=true`), photo bytes via `manifest.sqlite`.
**Writes:** `data/processed/readqc.jsonl` (append-only; resume-safe), `readqc_failures.json` (redacted errors).

**Model selection:**
- `--model sonnet` → `claude-sonnet-4-6` (default).
- `--model haiku`  → `claude-haiku-4-5`.
- Pricing table per model (in / cache_w / cache_r / out, per Mtok).

**Output schema** — Pydantic `QCResult`, parsed via `client.messages.parse(output_format=QCResult)`:

| Field | Type / values |
|---|---|
| `relevance` | `scorable` / `portrait` / `off_topic` / `unreadable` |
| `phase` | `excavation` / `depth_measure` / `duct_laid` / `sand_bedded` / `tape_laid` / `backfilled` / `restored` / `paper_label` / `staging` / `other` |
| `warning_tape_visible` | `yes` / `no` / `occluded` |
| `sand_bedding_visible` | `yes` / `no` / `occluded` |
| `side_view_present` | `yes` / `no` |
| `depth_reference_visible` | `yes` / `no` |
| `depth_value_cm` | `float \| None` (currently informational only) |
| `duct_visible` | `yes` / `no` / `occluded` |
| `pipe_ends_sealed` | `yes` / `no` / `occluded` / `not_applicable` |
| `personal_data_visible` | `yes` / `no` |
| `overlay_date` | str (raw) |
| `overlay_address` | str (raw) |
| `overlay_latlon` | str \| None (raw — parser lives in Stage 4) |
| `paper_label_code` | str \| None (e.g. `F170-R084-11-or`) |
| `note` | str, max 500 chars |

**Phase rule (key validation):** when multiple phases visible, **latest in `excavation → depth_measure → duct_laid → sand_bedded → tape_laid → backfilled → restored` wins.** Tape over rod = `tape_laid`.

**Prompt construction:**
- System prompt: `SYSTEM_INSTRUCTIONS` (compliance rules), `cache_control: ephemeral`.
- User content: **14 exemplars × 2 blocks (caption + image)** = 28 user blocks, then the photo being scored. `cache_control: ephemeral` set on the last exemplar image block (everything up to it is cached).
- 4 original exemplars (bad_lowlight_label, duct_sand, duct_depth_rod_prominent, warnband) + 10 added to fix bench failures (3 paper-label-vs-duct disambiguation, 2 clean unambiguous cases, 4 missing phases, 1 off-topic gate).

**Concurrency & cost control:**
- **Pre-warm:** photo #1 runs **sequential** so the system+exemplar prefix lands in Anthropic's cache before the pool fans out (cache_read ~$0.011 vs cache_write ~$0.039).
- **ThreadPoolExecutor, 8 workers default** (`--workers`). SDK is thread-safe, httpx pools under the hood.
- **Cost ceiling:** `--max-cost-usd` (default $40). Shared `cost_exceeded: threading.Event`. New work short-circuits; in-flight calls complete. Worst-case overshoot = `n_workers × ~$0.011 ≈ $0.10`.
- **Retry policy** (`_score_with_retry`, max_attempts=3, geometric 2s/4s/8s + ±25% jitter):
  - Retriable: `429`, `rate_limit`, `Overloaded`, `502/503/504`, `Bad gateway`, `APIConnectionError`, `APITimeoutError`, `InternalServerError`.
  - Permanent: auth, schema, bad image → return immediately.

**Resume:** `load_target_photos()` reads existing `readqc.jsonl` and skips those photo_ids. Membership filter done in Python (SQLite's 999-host-parameter limit).

**Failure handling:**
- Error string redacts `Authorization`, `x-api-key`, `sk-ant-` before persisting.
- `worker_raised` exceptions caught at the as_completed boundary so a single bad photo doesn't lose the whole batch.

---

## STAGE 4 — GEOMATCH  ([src/geomatch.py](src/geomatch.py))

Photo → trench LineString segment + position along it.

**Reads:** `readqc.jsonl`, `forensics.jsonl`, geo from `load_geo()`.
**Writes:** `data/processed/geomatch.csv`, persistent `nominatim_cache.json`.

**CRS:** reproject **once** to UTM 33N (EPSG:32633) for distance & `interpolate`. Output lat/lon back in WGS84.

**Snap order (for each representative photo):**
1. **`parse_overlay_latlon(qc.overlay_latlon)`** — Stage 4 owns the parser, not Stage 3.
   - DMS: `46°33'56.226"N` (period or comma decimal; `°` REQUIRED to avoid matching a stray decimal).
   - Decimal-with-hemisphere: `46.56153856N 14.28786228E`.
   - Labeled decimal: `Lat 46.55, Long 14.29` (hemisphere inferred from label).
   - **Validator** `_valid_latlon`: `-90 ≤ lat ≤ 90` AND `-180 ≤ lon ≤ 180` — guards OCR digit-drop/duplicate (`"46.33..."` becoming `"6.33..."`).
   - **First parser that succeeds wins.** Fail through all three → `None`.
   - Set `coord_source = "overlay_latlon"`.
2. **Else if `overlay_address` non-empty:** Nominatim forward-geocode → `coord_source = "geocoded_address"`.
3. **Else:** `coord_source = "none"`, segment_id empty, audit `drop_no_coords`. Photo still appears in CSV.

**FCP assignment** (`_assign_fcp`):
- `cluster_polygon.contains(point)`?
  - **No** → still attach **nearest FCP** by centroid distance, but flag `fcp_assignment = "off_cluster"` + audit event.
  - **Yes** → first FCP whose polygon contains the point.
  - **Yes but in interior gap** → nearest FCP by centroid distance, `fcp_assignment = "nearest_fallback"`.

**Snap** (`_snap_one`):
- Restrict candidate trenches to assigned FCP. Empty → fall back to all trenches.
- Brute-force `min(geom.distance(point))` over candidates.
- `segment_t = geom.project(point) / geom.length`, clipped to `[0, 1]`.
- `idx == -1` (every distance NaN, or empty candidates) → emit empty row, audit `drop_snap_failed`.

**Cross-checks (don't block scoring, surfaced as flags / audit):**

| Check | When | Threshold | Result |
|---|---|---|---|
| **lat/lon vs address** | both signals present | `haversine_m > 150m` AND `streets_disagree()` | `latlon_vs_address_flag = True`, audit `latlon_address_mismatch` |
| **paper label** | `paper_label_code` parses (regex `F### + R###`) | F-code ≠ snapped fcp_name's leading F-code | `label_match = "fcp_mismatch"` |
| **paper label** | same | R-code ∉ snapped `ductMainShort` tokens (split on `^` and `:`) | `label_match = "r_mismatch"` |
| **paper label** | match | — | `label_match = "ok"` |

- **`streets_disagree`**: NFKD-strip diacritics → lowercase → split on non-letters → keep tokens len>2 → set intersection empty? Tolerates `strasse`/`straße` suffix.

**Nominatim contract:**
- User-Agent: `ViennaUP2026/0.1 (pathanahmad2334@gmail.com)`.
- Throttle: **1.1s between uncached calls** (`NOMINATIM_THROTTLE_S`).
- Persistent cache: `nominatim_cache.json` (saved every 200 photos + on exit). Null results cached too — don't retry every run.
- **Viewbox = cluster bounds + 0.15° padding, `bounded=1`** — hard-filter, not just ranking hint. Prevents ambiguous street names from resolving to Vienna/Innsbruck.
- `--no-geocode` flag: cache reads only, no network calls (use when rate-limited).
- Errors: stamp `_last_call` before returning so throttle applies to failures too; address redacted in stderr (first 3 chars + `...`), audit log carries `error_class` only.

**Inheritance:** representative's full row copied verbatim to every non-rep `photo_id` in its `phash_cluster_id` (only `photo_id` field changes).

**Output columns** in `geomatch.csv`:
`photo_id, lat, lon, coord_source, segment_id, segment_t, snap_distance_m, fcp_name, fcp_assignment, label_match, latlon_vs_address_flag`

---

## STAGE 5 — CLASSIFY  ([src/classify.py](src/classify.py))

Two validation layers stacked: **Layer B per-photo → Layer A per-segment.**

**Reads:** `readqc.jsonl`, `geomatch.csv`, `forensics.jsonl`, geo via `load_geo()`.
**Writes:** `data/processed/verdicts.csv`.

### LAYER B — per-photo compliance gate (`is_photo_compliant`)

A photo is **compliant** iff **ALL** of:

1. `relevance == "scorable"`.
2. `personal_data_visible != "yes"`.
3. `latlon_vs_address_flag` not True.
4. `fcp_assignment != "off_cluster"`.
5. `snap_distance_m ≤ 75m` (`MAX_SNAP_DISTANCE_M`).
6. **Phase-relevant visual checks all `"yes"`** — `"occluded"` counts as FAIL (sharp rule).

**Phase → required checks** (`PHASE_CHECKS`):

| phase | required to be `"yes"` |
|---|---|
| `excavation` | `side_view_present` |
| `depth_measure` | `depth_reference_visible`, `side_view_present` |
| `duct_laid` | `duct_visible` |
| `sand_bedded` | `sand_bedding_visible`, `duct_visible` |
| `tape_laid` | `warning_tape_visible` |
| `backfilled` | (none — state documentation) |
| `restored` | (none — state documentation) |
| `paper_label` / `staging` / `other` | **`None`** = not trench evidence, always FAILS Layer B |

**Cluster dedup within segment:** one entry per `(segment_id, phash_cluster_id)`. Tiebreak order:
1. `compliant` beats non-compliant.
2. Representative beats inherited duplicate.
3. Lowest `photo_id` wins (deterministic).

Prevents one good photo, submitted 5 times, from filling 5 evidence slots.

**Inheritance for missing readqc:** if a photo (e.g. an inherited dup) has no own row, look up its cluster's representative's row via `cluster_to_rep`. None → audit `drop_no_qc` + skip.

### LAYER A — per-segment verdict (`segment_verdict`)

Inputs: `segment_length_m` (from UTM-projected LineString `.length`), `compliant_positions_m` (= `segment_t × length`).

```
n = len(compliant_positions_m)

if n == 0:
    return RED, max_gap = length, reason = "no compliant photos snapped"

if length ≤ 5m:                        # short-segment shortcut
    return GREEN  (any single compliant photo is enough)

if n / length < 1/10:                  # density floor
    return RED, max_gap, reason = "density n/length below 1/10m"

# Gap analysis — start gap + internal gaps + end gap
gaps = [positions[0]] + diffs(positions) + [length - positions[-1]]
max_gap = max(gaps)

if max_gap ≤ 5m:
    return GREEN
else:
    return YELLOW
```

**Constants:**
- `GREEN_MAX_GAP_M = 5.0`
- `RED_MIN_DENSITY_PER_M = 1/10`
- `MAX_SNAP_DISTANCE_M = 75.0`

**Reasons string assembly:**
- Layer A reason (max-gap position OR density).
- Top-3 most-common Layer B failure reasons among non-compliant photos in the segment (e.g. `"3x depth_reference_visible=no"`).
- Personal-data-flagged count surfaced even if the segment is otherwise compliant.

**Output columns** in `verdicts.csv`:
`segment_id, fcp_name, length_m, photo_count, compliant_photo_count, max_gap_m, density_photos_per_5m, verdict, reasons`

**Sort order in `verdicts.csv`:** `RED → YELLOW → GREEN`, then by `length_m DESC` within color.
**Sort order in `deficiency.csv` (Stage 6):** `(fcp_name ASC, length_m DESC)`, non-GREEN only — different because the partner reads the deficiency report grouped by zone, not by severity.

---

## STAGE 6 — REPORT  ([src/report.py](src/report.py))

**Resolves inputs** with fallback (`resolve_inputs()`):
- If `data/processed/verdicts.csv` exists → "live" pipeline outputs.
- Else → `demo_fixtures/` bundle (committed pre-computed CSVs for offline demos).
- Stage exits with code 1 if any required input is missing.

**Writes to `data/processed/report/`:**

| File | Source | Row contract |
|---|---|---|
| `deficiency.csv` | `write_deficiency_csv` | One row per **non-GREEN** segment. Sorted by `(fcp_name, -length_m)` — note: different from the `RED→YELLOW→GREEN, -length` order in `verdicts.csv`. Columns: segment_id, fcp_name, verdict, length_m, photo_count, compliant_photo_count, max_gap_m, density_photos_per_5m, reasons. |
| `not_classified.csv` | `write_not_classified_csv` | One row per photo where `relevance != "scorable"`. `reason` = relevance label, optionally with the readqc `note` appended. |
| `personal_data.csv` | `write_personal_data_csv` | One row per photo where `personal_data_visible == "yes"`. Just photo_id + rel_path. |
| `summary.html` | `write_summary_html` | One-page overview: 4 KPI cards (segments / G-Y-R / photos scored / run cost split Sonnet vs Haiku) + 5-row bucket table (duplicates, geo-mismatch, personal-data, ELA hints, not-classified). |
| `cover_prose.json` | `src/cover_prose.write_cover_prose` | **Optional.** Pipeline-time Claude call (`claude-sonnet-4-6`) that drafts intro/situation/closing paragraphs for the PDF. Fails silently → PDF falls back to templated prose. |

**PDF report** ([src/pdf_report.py](src/pdf_report.py)):
- **Not produced by the pipeline.** Generated **on demand** by the dashboard download component (`src/ui/components/download.py`) via `build_pdf(verdicts, source, intake)`.
- A4 layout, reportlab. Page 1: KPI strip + intake table. Page 2+: FCP-grouped section cards with severity pill, length, gap, plain-language reasons (via `src/humanize.py`). Final page: passing-section list + severity legend + 8 checks crib.
- Reads `cover_prose.json` if present → prose; else templated fallback.

**Rule:** every artifact is a single, openable-in-Excel file (CSVs) or a single printable doc (HTML / PDF). No nested JSON for the partner.

---

## TWO-SURFACE UI  ([app.py](app.py))

One Streamlit process, two surfaces routed by `?view=` query param:

- `/` → **reviewer dashboard** (map + KPI hero + drill-down + downloads). Reads `data/processed/` if every required artifact exists, else `demo_fixtures/` (all-or-nothing — partial live state would crash a loader).
- `/?view=upload` → **operator submission form** ([src/ui/upload_view.py](src/ui/upload_view.py)). Live Claude calls. Drops merge into the dashboard's verdicts in-session.

**Live-upload merge** (`src/ui/components/live_geomatch.py`):
- Dropped photos run through `score_one_photo` → `qc_to_readqc_row` + `qc_to_geomatch_row`.
- `recompute_verdicts(verdicts, geomatch, readqc, forensics, upload_geomatch, upload_readqc, geom_handle)` re-runs Stage 5's per-segment logic on the merged dataset — only affected segments change color.
- Δ-counts (e.g. `RED→YELLOW: 3`) stashed in `st.session_state` for the rail's summary + the "Fly to changes" button.

**Photo source resolution for the dashboard's photo grid:**
- Live mode → `data/Fotos/Fotos/` (curated symlinks; can be dangling).
- Fixtures mode OR fallback when symlinks dangle → `data/Resources/all/` (the flat 3,929-photo corpus).

**Demo-day rule (CLAUDE.md):** no live Claude calls during the **dashboard** demo — all data is pre-computed file reads. The **upload** view is the only live AI surface and is demonstrated separately.

**Off-cluster pin hiding:** the dashboard map filters out `fcp_assignment == "off_cluster"` pins client-side, even though they still exist in `geomatch.csv`. Upstream parser bounds + Nominatim viewbox prevent new ones — this filter cleans rows written before those fixes.

**Verdict seeding for session-lot mode:** when an operator drops a fresh contractor bundle (`session_lot` set), the dashboard seeds one all-RED row per segment via `_seed_lot_verdicts(geom_handle)` so the map and KPI agree before any photo is scored.

---

## CROSS-CUTTING — AUDIT  ([src/audit.py](src/audit.py))

Append-only JSONL at `data/processed/audit.jsonl`. Gitignored. Reset (truncated) **only by Stage 1's `audit_reset()`** — re-running a single stage appends to the existing file.

**Line format:** `{"ts": "<ISO-8601, second precision>", "stage": "<module>", "event": "<verb_or_noun>", ...fields}`.

**Banners:**
- `stage_start` carries `config={...}` — the stage's run parameters (workers, thresholds, model id, cost ceiling). Reproducible/comparable across runs.
- `stage_end` carries `counters={...}` — summary tallies.

**Per-event drop / flag types:**

| stage | event | meaning |
|---|---|---|
| ingest | `byte_identical_skip` | SHA1 collision on insert |
| forensics | `phash_fail` | worker exception during pHash/ELA |
| readqc | `api_fail` | retried-and-failed Claude call |
| readqc | `worker_raised` | thread-pool worker raised |
| readqc | `cost_ceiling_hit` | `total_cost_usd > max_cost_usd` |
| geomatch | `nominatim_fail` | network/HTTP error (no address fragment in log) |
| geomatch | `drop_no_coords` | no overlay latlon AND geocode failed/absent |
| geomatch | `drop_snap_failed` | snap returned `idx == -1` |
| geomatch | `off_cluster` | point outside SiteCluster polygon |
| geomatch | `latlon_address_mismatch` | >150m AND streets disagree |
| geomatch | `label_mismatch` | F or R code disagrees with snapped segment |
| classify | `drop_no_segment` | photo has no `segment_id` (Stage 4 couldn't snap) |
| classify | `drop_no_qc` | photo has no readqc row even via inheritance |

**PII contract:** audit log carries `photo_id` only — never filenames, addresses, or raw lat/lon. Safe to share / paste in bug reports.

---

## DATA CONTRACTS (cross-stage invariants)

- **`photo_id`** = SHA1 of file bytes. Defined in Stage 1; referenced everywhere.
- **`segment_id`** = `externalID` from `Trenches.geojson`. Format `SDIRouteSection_<digits>_<digits>`. **NOT `globalID`** — that field doesn't exist in the file we got.
- **CRS:** WGS84 / EPSG:4326 for all storage and output. UTM 33N / EPSG:32633 only inside Stages 4 & 5 for distance math.
- **`fcp_name`** = leading F-code (e.g. `F012`), stripped from `kmlDescriptionSimple = "F012 [81]"` in Stage 1.
- **`phash_cluster_id`** = small int per pHash equivalence class. `is_phash_representative` marks the canonical member.
- **Phase progression** (latest-wins): `excavation → depth_measure → duct_laid → sand_bedded → tape_laid → backfilled → restored`. Plus three orthogonal buckets: `paper_label`, `staging`, `other`.

---

## VALIDATION LAYERS — quick lookup

| Layer | Where | What it gates | Failure surface |
|---|---|---|---|
| Ingest collision | Stage 1 | byte-identical SHA1 | `byte_identical_skip` audit only |
| pHash cluster | Stage 2 | near-duplicate fingerprints (Hamming ≤6) | one rep per cluster goes to Stage 3 |
| ELA tamper hint | Stage 2 | mean delta > 15 after JPEG-90 re-save | `ela_flag` in JSONL, not enforced |
| Relevance gate | Stage 3 (Claude) | `scorable` vs `portrait/off_topic/unreadable` | Layer B fail |
| Phase classifier | Stage 3 (Claude) | which checks apply (or none) | Layer B fail if phase is `paper_label`/`staging`/`other` |
| Lat/lon parser | Stage 4 | 3 format parsers + range validator | `coord_source = none` → drop from scoring |
| FCP cluster gate | Stage 4 | point inside SiteCluster polygon | `off_cluster` flag → Layer B fail |
| Lat/lon vs address | Stage 4 | both signals + >150m + different streets | `latlon_vs_address_flag = True` → Layer B fail |
| Paper label consistency | Stage 4 | F-code + R-code vs snapped segment | `label_match` field, surfaced not enforced |
| Snap distance | Stage 5 | `≤ 75m` from LineString | Layer B fail |
| Per-photo Layer B | Stage 5 | 6 conditions ALL must pass | photo doesn't count toward segment coverage |
| Density floor | Stage 5 | `compliant / length ≥ 1/10` | RED |
| Gap floor | Stage 5 | `max_gap ≤ 5m` (incl. start/end) | GREEN vs YELLOW |
| Cluster dedup within segment | Stage 5 | one entry per `(segment, phash_cluster)` | reused photos can't pad a segment |

---

## EDGE CASES THE CODE EXPLICITLY HANDLES

- **OCR digit-drop on lat/lon** (`46.33...` → `6.33...`): `_valid_latlon()` range check rejects → falls back to address geocode.
- **DMS `°` required** so a stray decimal `46.56153856` doesn't get matched by the DMS regex first and produce garbage.
- **Comma-decimal lat/lon** (German locale): `_to_float()` replaces `,` with `.` before float parse.
- **FCP interior gap (~19% of cluster area)**: midpoint-in-polygon falls through to nearest-FCP-centroid.
- **Off-cluster photos**: still get an FCP attached (so the report lists them) but Layer B fails them.
- **Same-street address mismatch** (paper label = property, overlay = photographer): tolerated. Flag only fires when streets *differ* AND distance >150m.
- **Ambiguous Austrian street names** (`Hauptstraße`): Nominatim viewbox = cluster bounds + 0.15° pad, `bounded=1` hard-filter.
- **Cost overrun mid-batch**: hard ceiling + shared event; worst-case overshoot ~8 × $0.011 with 8 workers.
- **Cache-write surcharge multiplier**: photo #1 pre-warmed sequentially; pool fans out only after cache is hot.
- **SDK transient 429/5xx**: 3-attempt retry with jittered geometric backoff.
- **Worker raised mid-pool**: caught at `as_completed`, recorded against the right `photo_id`, batch continues.
- **`readqc_failures.json` secrets leak**: `Authorization`, `x-api-key`, `sk-ant-` stripped before persisting.
- **SQLite 999-param limit**: target filter done in Python after a full manifest scan (~3k rows, cheap).
- **`idx == -1` on snap**: emit empty row + audit, don't crash the batch.
- **Snap candidate FCP empty**: fall back to all trenches.
- **Inherited dups missing readqc**: look up via `cluster_to_rep`; still missing → `drop_no_qc`.
- **Demo fallback**: Stage 6 falls back to `demo_fixtures/` if live `verdicts.csv` is missing.
