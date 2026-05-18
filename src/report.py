"""Stage 6 — Report (deliverables for the partner + the demo).

What it does: turns verdicts.csv into a deficiency report and the
supporting CSVs (not-classified photos, personal-data-flagged photos).
Also renders a one-page HTML summary. The live Streamlit map is in
app.py — this module produces the static handover artifacts.

Reads (preferred → fallback):
    data/processed/verdicts.csv      (or demo_fixtures/verdicts.csv)
    data/processed/geomatch.csv      (or demo_fixtures/geomatch.csv)
    data/processed/readqc.jsonl      (or demo_fixtures/readqc.jsonl)
    data/processed/forensics.jsonl   (or demo_fixtures/forensics.jsonl)
    data/processed/manifest.sqlite   (or demo_fixtures/manifest.sqlite)

Writes (always to data/processed/report/):
    deficiency.csv       — one row per RED or YELLOW segment.
    not_classified.csv   — photos where readqc.relevance != "scorable".
    personal_data.csv    — photos where readqc.personal_data_visible == "yes".
    summary.html         — one-page overview + top-line numbers.

Design rule:
    Every output file is one human-readable artifact. No nested JSON,
    no surprises. A reviewer should be able to open deficiency.csv in
    Excel and start working immediately.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src import paths


@dataclass
class ReportInputs:
    """Resolved input paths + a label naming where the data came from."""
    source: str  # "live" or "fixtures"
    verdicts_csv: Path
    geomatch_csv: Path
    readqc_jsonl: Path
    forensics_jsonl: Path
    manifest_sqlite: Path


def resolve_inputs() -> ReportInputs:
    """Prefer real pipeline outputs at data/processed/; fall back to
    demo_fixtures/. The decision is made by whether verdicts.csv exists
    in data/processed/."""
    live_v = paths.VERDICTS_CSV
    if live_v.exists():
        return ReportInputs(
            source="live",
            verdicts_csv=live_v,
            geomatch_csv=paths.GEOMATCH_CSV,
            readqc_jsonl=paths.READQC_JSONL,
            forensics_jsonl=paths.FORENSICS_JSONL,
            manifest_sqlite=paths.MANIFEST_DB,
        )
    fx = paths.REPO_ROOT / "demo_fixtures"
    return ReportInputs(
        source="fixtures",
        verdicts_csv=fx / "verdicts.csv",
        geomatch_csv=fx / "geomatch.csv",
        readqc_jsonl=fx / "readqc.jsonl",
        forensics_jsonl=fx / "forensics.jsonl",
        manifest_sqlite=fx / "manifest.sqlite",
    )


# --- Helpers ------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _read_manifest(path: Path) -> dict[str, str]:
    """photo_id → rel_path."""
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT photo_id, rel_path FROM photos").fetchall()
    finally:
        conn.close()
    return {pid: rp for pid, rp in rows}


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _length_key(row: dict) -> float:
    try:
        return float(row.get("length_m") or 0.0)
    except (TypeError, ValueError):
        return 0.0


# --- Writers ------------------------------------------------------------

DEFICIENCY_FIELDS = [
    "segment_id", "fcp_name", "verdict", "length_m",
    "photo_count", "compliant_photo_count", "max_gap_m",
    "density_photos_per_5m", "reasons",
]


def write_deficiency_csv(verdicts: list[dict], out_path: Path) -> int:
    """One row per non-green segment, sorted by FCP then by length desc.
    Returns the number of rows written."""
    bad = [r for r in verdicts if (r.get("verdict") or "").upper() != "GREEN"]
    bad.sort(key=lambda r: (r.get("fcp_name", ""), -_length_key(r)))
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DEFICIENCY_FIELDS,
                           extrasaction="ignore")
        w.writeheader()
        for r in bad:
            w.writerow(r)
    return len(bad)


NOT_CLASSIFIED_FIELDS = ["photo_id", "rel_path", "reason"]


def write_not_classified_csv(
    readqc: list[dict], manifest: dict[str, str], out_path: Path
) -> int:
    """One row per photo whose relevance != 'scorable'.

    The `reason` column is the readqc relevance label (portrait,
    off_topic, unreadable) plus the note when present, so the partner
    can sort retake requests by cause.
    """
    rows: list[dict] = []
    for r in readqc:
        relevance = r.get("relevance")
        if relevance == "scorable" or relevance is None:
            continue
        pid = r["photo_id"]
        note = (r.get("note") or "").strip()
        reason = relevance if not note else f"{relevance} — {note}"
        rows.append(
            {
                "photo_id": pid,
                "rel_path": manifest.get(pid, ""),
                "reason": reason,
            }
        )
    rows.sort(key=lambda r: (r["reason"], r["photo_id"]))
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=NOT_CLASSIFIED_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


PERSONAL_DATA_FIELDS = ["photo_id", "rel_path"]


def write_personal_data_csv(
    readqc: list[dict], manifest: dict[str, str], out_path: Path
) -> int:
    """One row per photo flagged personal_data_visible='yes'."""
    rows = [
        {"photo_id": r["photo_id"],
            "rel_path": manifest.get(r["photo_id"], "")}
        for r in readqc
        if r.get("personal_data_visible") == "yes"
    ]
    rows.sort(key=lambda r: r["photo_id"])
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PERSONAL_DATA_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


SUMMARY_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Sightline — summary</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 32px; color: #1e293b; }}
  h1 {{ margin-bottom: 4px; }}
  .source {{ color: #64748b; font-size: 13px; margin-bottom: 24px; }}
  .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px;
          margin-bottom: 24px; }}
  .card {{ border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px;
           background: #f8fafc; }}
  .card .label {{ color: #64748b; font-size: 13px; }}
  .card .value {{ font-size: 28px; font-weight: 600; margin-top: 4px; }}
  .pill {{ display: inline-block; padding: 2px 8px; border-radius: 4px;
            color: white; font-size: 13px; }}
  .green {{ background: #22c55e; }}
  .yellow {{ background: #eab308; }}
  .red {{ background: #ef4444; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #e2e8f0; }}
  th {{ background: #f1f5f9; }}
  .footer {{ color: #64748b; font-size: 12px; margin-top: 32px; }}
</style>
</head>
<body>
<h1>Sightline — summary</h1>
<div class="source">Source: <code>{source}</code></div>

<div class="grid">
  <div class="card">
    <div class="label">Segments scored</div>
    <div class="value">{n_segments}</div>
  </div>
  <div class="card">
    <div class="label">GREEN / YELLOW / RED</div>
    <div class="value">
      <span class="pill green">{n_green}</span>
      <span class="pill yellow">{n_yellow}</span>
      <span class="pill red">{n_red}</span>
    </div>
  </div>
  <div class="card">
    <div class="label">Photos scored</div>
    <div class="value">{n_photos_scored}</div>
  </div>
  <div class="card">
    <div class="label">Run cost</div>
    <div class="value">${total_cost:.2f}</div>
    <div style="font-size:12px;color:#64748b;margin-top:4px;">
      Sonnet {n_sonnet:,} · ${cost_sonnet:.2f}<br>
      Haiku {n_haiku:,} · ${cost_haiku:.2f}
    </div>
  </div>
</div>

<h2>Buckets</h2>
<table>
<tr><th>Category</th><th>Count</th><th>Notes</th></tr>
<tr><td>Duplicates (re-submitted across jobs)</td><td>{n_dups}</td>
    <td>Inherited a representative's QC result; flagged for contractor follow-up.</td></tr>
<tr><td>Geo-mismatch (lat/lon ↔ printed address &gt;150 m)</td><td>{n_geo_mismatch}</td>
    <td>Off-cluster or wrong-street; flagged not silently dropped.</td></tr>
<tr><td>Personal-data flagged (NIS2)</td><td>{n_personal_data}</td>
    <td>Routed to retake bucket; not counted toward compliance.</td></tr>
<tr><td>ELA tamper hints</td><td>{n_ela}</td>
    <td>Soft warning — re-save / re-compression suspected.</td></tr>
<tr><td>Not classified (relevance gate)</td><td>{n_not_classified}</td>
    <td>portrait / off_topic / unreadable — not counted.</td></tr>
</table>

<div class="footer">
Generated by <code>src/report.py</code>. Open
<code>deficiency.csv</code> for the per-segment punch list.
</div>
</body>
</html>
"""


def write_summary_html(
    verdicts: list[dict],
    readqc: list[dict],
    forensics: list[dict],
    geomatch: list[dict],
    source: str,
    out_path: Path,
) -> None:
    from collections import Counter
    verdict_counts = Counter((r.get("verdict") or "").upper()
                             for r in verdicts)
    n_dups = sum(
        1 for r in forensics
        if not r.get("is_phash_representative", True)
    )
    n_ela = sum(1 for r in forensics if r.get("ela_flag"))
    n_personal_data = sum(
        1 for r in readqc if r.get("personal_data_visible") == "yes"
    )
    n_not_classified = sum(
        1 for r in readqc
        if (r.get("relevance") or "scorable") != "scorable"
    )
    n_geo_mismatch = sum(
        1 for r in geomatch
        if (r.get("latlon_vs_address_flag") or "").lower() == "true"
    )
    total_cost = sum(float(r.get("cost_usd") or 0.0) for r in readqc)
    n_sonnet = sum(1 for r in readqc if "sonnet" in (r.get("model") or "").lower())
    n_haiku = sum(1 for r in readqc if "haiku" in (r.get("model") or "").lower())
    cost_sonnet = sum(
        float(r.get("cost_usd") or 0.0) for r in readqc
        if "sonnet" in (r.get("model") or "").lower()
    )
    cost_haiku = sum(
        float(r.get("cost_usd") or 0.0) for r in readqc
        if "haiku" in (r.get("model") or "").lower()
    )

    html = SUMMARY_HTML_TEMPLATE.format(
        source=source,
        n_segments=len(verdicts),
        n_green=verdict_counts.get("GREEN", 0),
        n_yellow=verdict_counts.get("YELLOW", 0),
        n_red=verdict_counts.get("RED", 0),
        n_photos_scored=len(readqc),
        total_cost=total_cost,
        n_sonnet=n_sonnet,
        n_haiku=n_haiku,
        cost_sonnet=cost_sonnet,
        cost_haiku=cost_haiku,
        n_dups=n_dups,
        n_geo_mismatch=n_geo_mismatch,
        n_personal_data=n_personal_data,
        n_ela=n_ela,
        n_not_classified=n_not_classified,
    )
    out_path.write_text(html, encoding="utf-8")


# --- Entry point --------------------------------------------------------

def main() -> int:
    """Read intermediate artifacts, write the report bundle. Returns 0
    on success, 1 if a required input is missing."""
    inp = resolve_inputs()

    missing = [
        p for p in (
            inp.verdicts_csv, inp.geomatch_csv, inp.readqc_jsonl,
            inp.forensics_jsonl, inp.manifest_sqlite,
        ) if not p.exists()
    ]
    if missing:
        for p in missing:
            print(f"[report] missing input: {p}")
        return 1

    verdicts = _read_csv(inp.verdicts_csv)
    geomatch = _read_csv(inp.geomatch_csv)
    readqc = _read_jsonl(inp.readqc_jsonl)
    forensics = _read_jsonl(inp.forensics_jsonl)
    manifest = _read_manifest(inp.manifest_sqlite)

    paths.ensure_dirs()

    n_def = write_deficiency_csv(verdicts, paths.DEFICIENCY_CSV)
    n_nc = write_not_classified_csv(readqc, manifest, paths.NOT_CLASSIFIED_CSV)
    n_pd = write_personal_data_csv(readqc, manifest, paths.PERSONAL_DATA_CSV)
    write_summary_html(
        verdicts, readqc, forensics, geomatch, inp.source, paths.SUMMARY_HTML
    )

    # Bake cover prose so the deficiency PDF reads as a written report,
    # not a templated dashboard export. Pipeline-time call keeps the
    # dashboard demo free of live Claude calls. Falls back silently if
    # the API key is missing or the call fails — the PDF still works.
    from src.cover_prose import write_cover_prose
    from src.pdf_report import compute_photo_intake

    intake = compute_photo_intake(readqc, forensics, geomatch)
    prose_path = paths.REPORT_DIR / "cover_prose.json"
    prose_ok = write_cover_prose(verdicts, intake, prose_path)
    if prose_ok:
        print(
            f"[report] cover prose written → {prose_path.relative_to(paths.REPO_ROOT)}")
    else:
        print("[report] cover prose skipped (no API key or call failed) — "
              "PDF will use templated prose")

    print(
        f"[report] source={inp.source} → "
        f"{n_def} deficiency rows, {n_nc} not-classified, "
        f"{n_pd} personal-data → {paths.REPORT_DIR.relative_to(paths.REPO_ROOT)}/"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
