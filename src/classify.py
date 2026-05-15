"""Stage 5 -- Classify (per-segment rollup -> GREEN / YELLOW / RED).

Groups photos by segment_id, sorts them by position along the segment,
applies the 5-meter density rule (Layer A) AND the per-photo compliance
filter (Layer B), and produces one verdict per segment.

Reads:
    - data/processed/readqc.jsonl    (per-photo checks, only representatives)
    - data/processed/geomatch.csv    (photo -> segment + position, includes inherited duplicates)
    - data/processed/forensics.jsonl (phash_cluster_id, is_phash_representative)
    - Trenches geo data (segment lengths) via src.ingest.load_geo()

Writes:
    - data/processed/verdicts.csv    (one row per segment, columns per PLAN)

What counts as a "compliant" photo (Layer B):
    1. readqc.relevance == "scorable"
    2. readqc.personal_data_visible == "no"
    3. geomatch.latlon_vs_address_flag == False
    4. geomatch.fcp_assignment != "off_cluster"  (photo was on the cluster at all)
    5. snapped within 75m of the LineString it documents (anything farther is
       almost certainly the photographer standing off-route, not evidence
       FOR that segment)
    6. The phase-relevant subset of the visual checks is all "yes".
       "occluded" is treated as a FAIL (keep the rule sharp).
    7. We dedup by phash_cluster_id within a segment -- one cluster
       contributes one evidence point, not many. Otherwise reused photos
       could artificially fill an entire segment.

Phase-relevant visual checks:
    excavation     -> side_view_present
    depth_measure  -> depth_reference_visible, side_view_present
    duct_laid      -> duct_visible
    sand_bedded    -> sand_bedding_visible, duct_visible
    tape_laid      -> warning_tape_visible
    backfilled     -> (no specific check; photo just documents the state)
    restored       -> (no specific check)
    paper_label    -> *not counted* for trench coverage (it documents which
                       FCP/duct, not the trench itself)
    staging        -> *not counted* (no trench work in frame)
    other          -> *not counted*

Verdict rule (PLAN Layer A):
    GREEN  -- compliant photo every <= 5 m along the segment AND
              the first compliant photo is within 5 m of the start AND
              the last compliant photo is within 5 m of the end.
    RED    -- 0 compliant photos OR compliant_count < length / 10.
    YELLOW -- anything in between.

The `reasons` column is the semicolon-joined human-readable string that
shows in the deficiency report and the demo side panel.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict

from src.audit import log_event, log_stage_end, log_stage_start
from src.ingest import load_geo
from src.paths import (
    FORENSICS_JSONL,
    GEOMATCH_CSV,
    READQC_JSONL,
    VERDICTS_CSV,
    ensure_dirs,
)

UTM_EPSG = 32633
MAX_SNAP_DISTANCE_M = 75.0    # photo this far from a trench isn't documenting it
GREEN_MAX_GAP_M = 5.0
RED_MIN_DENSITY_PER_M = 1.0 / 10.0   # i.e. one compliant photo per 10 m or less is RED

# Phase -> set of visual checks required to be "yes"
PHASE_CHECKS: dict[str, list[str]] = {
    "excavation":   ["side_view_present"],
    "depth_measure": ["depth_reference_visible", "side_view_present"],
    "duct_laid":    ["duct_visible"],
    "sand_bedded":  ["sand_bedding_visible", "duct_visible"],
    "tape_laid":    ["warning_tape_visible"],
    "backfilled":   [],
    "restored":     [],
    "paper_label":  None,   # None means "not evidence for trench coverage"
    "staging":      None,
    "other":        None,
}


def is_photo_compliant(readqc_row: dict, geomatch_row: dict) -> tuple[bool, list[str]]:
    """Return (compliant?, list of human-readable failure reasons)."""
    reasons: list[str] = []

    if readqc_row.get("relevance") != "scorable":
        reasons.append(f"relevance={readqc_row.get('relevance')}")

    if readqc_row.get("personal_data_visible") == "yes":
        reasons.append("personal_data_visible")

    if str(geomatch_row.get("latlon_vs_address_flag")).lower() == "true":
        reasons.append("latlon_vs_address_disagree")

    if geomatch_row.get("fcp_assignment") == "off_cluster":
        reasons.append("off_cluster")

    try:
        snap_d = float(geomatch_row.get("snap_distance_m") or 0)
    except (TypeError, ValueError):
        snap_d = 0.0
    if snap_d > MAX_SNAP_DISTANCE_M:
        reasons.append(f"snap_distance={snap_d:.0f}m")

    phase = readqc_row.get("phase")
    needed = PHASE_CHECKS.get(phase)
    if needed is None:
        # paper_label / staging / other -- not trench evidence
        reasons.append(f"phase={phase}")
    else:
        for check in needed:
            if readqc_row.get(check) != "yes":
                reasons.append(f"{check}={readqc_row.get(check)}")

    return (not reasons), reasons


def segment_verdict(
    segment_length_m: float,
    compliant_positions_m: list[float],
) -> tuple[str, float, list[str]]:
    """Return (verdict, max_gap_m, reasons). Positions in meters along the segment."""
    n = len(compliant_positions_m)
    reasons: list[str] = []

    if n == 0:
        return "RED", segment_length_m, ["no compliant photos snapped"]

    # Short-segment shortcut: a segment shorter than the 5m gap window can
    # never have a >5m internal gap, and "within 5m of start and end" is
    # trivially true once at least one compliant photo exists.
    if segment_length_m <= GREEN_MAX_GAP_M:
        return "GREEN", 0.0, []

    # Density check
    if segment_length_m > 0 and (n / segment_length_m) < RED_MIN_DENSITY_PER_M:
        reasons.append(f"density {n}/{segment_length_m:.0f}m below 1/10m")
        # Compute gaps for the reason string too
        positions = sorted(compliant_positions_m)
        gaps = (
            [positions[0]]
            + [positions[i + 1] - positions[i] for i in range(n - 1)]
            + [segment_length_m - positions[-1]]
        )
        max_gap = max(gaps)
        return "RED", max_gap, reasons

    # Gap check
    positions = sorted(compliant_positions_m)
    gaps = (
        [positions[0]]
        + [positions[i + 1] - positions[i] for i in range(n - 1)]
        + [segment_length_m - positions[-1]]
    )
    max_gap = max(gaps)

    if max_gap <= GREEN_MAX_GAP_M:
        return "GREEN", max_gap, []
    # Locate the worst gap for the reason
    worst_i = gaps.index(max_gap)
    if worst_i == 0:
        reasons.append(f"first compliant photo at meter {positions[0]:.0f} (>{GREEN_MAX_GAP_M:.0f}m from start)")
    elif worst_i == n:
        reasons.append(f"last compliant photo at meter {positions[-1]:.0f} (>{GREEN_MAX_GAP_M:.0f}m from end of {segment_length_m:.0f}m)")
    else:
        a = positions[worst_i - 1]
        b = positions[worst_i]
        reasons.append(f"max gap {max_gap:.0f}m > {GREEN_MAX_GAP_M:.0f}m between meter {a:.0f} and meter {b:.0f}")
    return "YELLOW", max_gap, reasons


def main() -> int:
    if not VERDICTS_CSV.parent.exists():
        ensure_dirs()
    if not READQC_JSONL.exists() or not GEOMATCH_CSV.exists() or not FORENSICS_JSONL.exists():
        print("[classify] need readqc.jsonl, geomatch.csv, forensics.jsonl -- run earlier stages first", file=sys.stderr)
        return 1

    log_stage_start("classify",
                    green_max_gap_m=GREEN_MAX_GAP_M,
                    red_min_density_per_m=RED_MIN_DENSITY_PER_M,
                    max_snap_distance_m=MAX_SNAP_DISTANCE_M)
    print("[classify] loading geo + intermediate rows ...")
    trenches, _fcps, _cluster = load_geo()
    trenches_utm = trenches.to_crs(epsg=UTM_EPSG)
    seg_length_m = {row["externalID"]: row.geometry.length for _, row in trenches_utm.iterrows()}
    seg_fcp = {row["externalID"]: row["fcp_name"] for _, row in trenches_utm.iterrows()}

    # Load forensics: cluster_id and rep status per photo
    forensics = {}
    cluster_to_rep: dict[int, str] = {}
    for line in FORENSICS_JSONL.open(encoding="utf-8"):
        r = json.loads(line)
        forensics[r["photo_id"]] = r
        if r["is_phash_representative"]:
            cluster_to_rep[r["phash_cluster_id"]] = r["photo_id"]

    # Load readqc (representatives only)
    readqc_by_photo: dict[str, dict] = {}
    for line in READQC_JSONL.open(encoding="utf-8"):
        r = json.loads(line)
        readqc_by_photo[r["photo_id"]] = r

    # Load geomatch (every photo, including inherited duplicates)
    geomatch_by_photo: dict[str, dict] = {}
    with GEOMATCH_CSV.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            geomatch_by_photo[row["photo_id"]] = row

    # For each photo, find its readqc (own or inherited via representative)
    def readqc_for(photo_id: str) -> dict | None:
        if photo_id in readqc_by_photo:
            return readqc_by_photo[photo_id]
        cid = forensics.get(photo_id, {}).get("phash_cluster_id")
        if cid is None:
            return None
        rep = cluster_to_rep.get(cid)
        if rep is None:
            return None
        return readqc_by_photo.get(rep)

    # Group photos by segment, then dedup by phash_cluster_id
    photos_by_segment: dict[str, dict[int, dict]] = defaultdict(dict)  # seg -> cid -> {pid, t, compliant, reasons}
    n_skipped_no_qc = 0
    n_skipped_no_seg = 0

    for pid, geo in geomatch_by_photo.items():
        seg_id = geo.get("segment_id") or ""
        if not seg_id:
            n_skipped_no_seg += 1
            log_event("classify", "drop_no_segment", photo_id=pid)
            continue
        qc = readqc_for(pid)
        if qc is None:
            n_skipped_no_qc += 1
            log_event("classify", "drop_no_qc", photo_id=pid)
            continue
        cid = forensics.get(pid, {}).get("phash_cluster_id", -1)
        compliant, reasons = is_photo_compliant(qc, geo)
        # Cluster dedup: one entry per (segment, phash cluster). Tiebreaks,
        # in order: compliant beats non-compliant, the representative beats
        # inherited duplicates, the lowest photo_id wins (deterministic).
        rep_id = cluster_to_rep.get(cid)
        existing = photos_by_segment[seg_id].get(cid)

        def _score(entry: dict) -> tuple:
            return (
                0 if entry["compliant"] else 1,
                0 if entry["photo_id"] == rep_id else 1,
                entry["photo_id"],
            )

        candidate = {
            "photo_id": pid,
            "t": float(geo.get("segment_t") or 0.0),
            "compliant": compliant,
            "reasons": reasons,
        }
        if existing is None or _score(candidate) < _score(existing):
            photos_by_segment[seg_id][cid] = candidate

    # Per-segment verdicts
    rows_out: list[dict] = []
    counter = {"GREEN": 0, "YELLOW": 0, "RED": 0}
    for seg_id, length_m in seg_length_m.items():
        entries = list(photos_by_segment.get(seg_id, {}).values())
        photo_count = len(entries)
        compliant_entries = [e for e in entries if e["compliant"]]
        compliant_count = len(compliant_entries)
        compliant_positions_m = [e["t"] * length_m for e in compliant_entries]

        verdict, max_gap_m, gap_reasons = segment_verdict(length_m, compliant_positions_m)
        counter[verdict] += 1

        # Build the reasons string
        seg_reasons = list(gap_reasons)
        # Surface the most common Layer B failures among the non-compliant photos
        if photo_count > 0 and compliant_count < photo_count:
            bad_reasons = [r for e in entries if not e["compliant"] for r in e["reasons"]]
            from collections import Counter
            top = Counter(bad_reasons).most_common(3)
            for reason, count in top:
                seg_reasons.append(f"{count}x {reason}")
        # Surface personal-data on any photo of this segment (even if compliant-otherwise)
        n_personal = sum(1 for e in entries if any("personal_data_visible" == r for r in e["reasons"]))
        if n_personal:
            seg_reasons.append(f"{n_personal} personal-data photo(s)")

        density = (compliant_count / (length_m / 5.0)) if length_m > 0 else 0.0
        rows_out.append({
            "segment_id": seg_id,
            "fcp_name": seg_fcp.get(seg_id, ""),
            "length_m": round(length_m, 2),
            "photo_count": photo_count,
            "compliant_photo_count": compliant_count,
            "max_gap_m": round(max_gap_m, 2),
            "density_photos_per_5m": round(density, 3),
            "verdict": verdict,
            "reasons": "; ".join(seg_reasons),
        })

    # Sort: red first, then yellow, then green; within colour by length descending
    order = {"RED": 0, "YELLOW": 1, "GREEN": 2}
    rows_out.sort(key=lambda r: (order[r["verdict"]], -r["length_m"]))

    fields = [
        "segment_id", "fcp_name", "length_m", "photo_count",
        "compliant_photo_count", "max_gap_m", "density_photos_per_5m",
        "verdict", "reasons",
    ]
    with VERDICTS_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows_out)

    print(
        f"[classify] {len(rows_out)} segments -> {VERDICTS_CSV.name}  "
        f"(GREEN={counter['GREEN']}, YELLOW={counter['YELLOW']}, RED={counter['RED']})"
    )
    print(
        f"[classify] skipped: {n_skipped_no_seg} no segment, {n_skipped_no_qc} no readqc row"
    )
    log_stage_end("classify", n_segments=len(rows_out),
                  n_green=counter["GREEN"], n_yellow=counter["YELLOW"], n_red=counter["RED"],
                  n_skipped_no_segment=n_skipped_no_seg, n_skipped_no_qc=n_skipped_no_qc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
