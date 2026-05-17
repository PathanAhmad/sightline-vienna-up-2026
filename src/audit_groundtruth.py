"""Phase-classification accuracy on the data provider's 219 hand-labeled photos.

The provider hand-tagged each photo as either "depth-measurement" or
"cable-laying" (filed into `data/Resources/examples/depth/` and
`.../examples/duct/`). We run the model on them blind, then compare the
model's `phase` to the ground-truth folder.

Ground-truth → expected model phase:
    depth → "depth_measure"
    duct  → "duct_laid"               (strict)
            "duct_laid" | "sand_bedded" | "tape_laid"   (lenient — all
                                                         show duct in trench)

Writes a per-model summary JSON to data/processed/model_benchmark.json
so the dashboard hero can render accuracy alongside cost/time.

Run:
    python -m src.audit_groundtruth
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.paths import READQC_JSONL, DATA_DIR, PROCESSED_DIR

GT_ROOT = DATA_DIR / "Resources" / "examples"
DEPTH_DIR = GT_ROOT / "depth"
DUCT_DIR = GT_ROOT / "duct"
BENCHMARK_JSON = PROCESSED_DIR / "model_benchmark.json"
# Side files populated by scripts/bench_sonnet_on_gt.py — one row per
# (photo_id, model) when re-scoring the GT set with a model that didn't
# get it from production, plus per-model elapsed_s + cost_usd. We read
# them here so the bench-only Sonnet rows count toward Sonnet accuracy
# without polluting readqc.jsonl (which is the production pipeline's
# input — last-write-wins on photo_id).
BENCH_JSONL = PROCESSED_DIR / "readqc_bench.jsonl"
BENCH_TIMINGS = PROCESSED_DIR / "bench_timings.json"

DUCT_PHASES_LENIENT = {"duct_laid", "sand_bedded", "tape_laid"}


def sha1_bytes(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_readqc_rows() -> list[dict]:
    """Merge production + bench scoring rows, dedup by (photo_id, model).

    Bench rows win over production rows for the same (photo_id, model)
    because bench is the controlled run we trust for benchmark stats.
    Different models on the same photo are kept — that's the point of
    the bench, to compare them.
    """
    merged: dict[tuple[str, str], dict] = {}
    for path in (READQC_JSONL, BENCH_JSONL):
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = (r.get("photo_id", ""), r.get("model", ""))
                merged[key] = r  # BENCH_JSONL iterated second → wins
    return list(merged.values())


def _load_bench_timings() -> dict[str, dict]:
    if not BENCH_TIMINGS.exists():
        return {}
    try:
        return json.loads(BENCH_TIMINGS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _model_short(model_id: str) -> str:
    """'claude-sonnet-4-6' → 'sonnet', 'claude-haiku-4-5' → 'haiku'."""
    if "haiku" in model_id:
        return "haiku"
    if "sonnet" in model_id:
        return "sonnet"
    if "opus" in model_id:
        return "opus"
    return model_id or "unknown"


def _ground_truth_photo_ids() -> dict[str, str]:
    """sha1 → 'depth' | 'duct'."""
    out: dict[str, str] = {}
    for label, folder in [("depth", DEPTH_DIR), ("duct", DUCT_DIR)]:
        for p in sorted(folder.iterdir()):
            if p.is_file():
                out[sha1_bytes(p)] = label
    return out


def _evaluate_one_model(
    rows: list[dict], gt: dict[str, str],
) -> dict:
    """Per-class & overall accuracy for one model's rows."""
    confusion: dict[str, dict[str, int]] = {"depth": {}, "duct": {}}
    for r in rows:
        pid = r["photo_id"]
        label = gt.get(pid)
        if label is None:
            continue
        ph = r.get("phase", "")
        confusion[label][ph] = confusion[label].get(ph, 0) + 1

    d_correct = confusion["depth"].get("depth_measure", 0)
    d_total = sum(confusion["depth"].values())
    u_correct = confusion["duct"].get("duct_laid", 0)
    u_correct_lenient = sum(
        confusion["duct"].get(ph, 0) for ph in DUCT_PHASES_LENIENT
    )
    u_total = sum(confusion["duct"].values())

    def pct(num: int, den: int) -> float:
        return (100.0 * num / den) if den else 0.0

    total_n = d_total + u_total
    strict_total = d_correct + u_correct
    lenient_total = d_correct + u_correct_lenient

    return {
        "n_test": total_n,
        "depth": {"correct": d_correct, "total": d_total, "pct": pct(d_correct, d_total)},
        "duct_strict": {"correct": u_correct, "total": u_total, "pct": pct(u_correct, u_total)},
        "duct_lenient": {"correct": u_correct_lenient, "total": u_total, "pct": pct(u_correct_lenient, u_total)},
        "overall_strict": {"correct": strict_total, "total": total_n, "pct": pct(strict_total, total_n)},
        "overall_lenient": {"correct": lenient_total, "total": total_n, "pct": pct(lenient_total, total_n)},
        "confusion": confusion,
    }


def evaluate() -> dict:
    all_rows = load_readqc_rows()
    gt = _ground_truth_photo_ids()

    # Group rows by model short name
    by_model: dict[str, list[dict]] = {}
    for r in all_rows:
        m = _model_short(r.get("model", ""))
        by_model.setdefault(m, []).append(r)

    results: dict[str, dict] = {}
    for m, rows in by_model.items():
        results[m] = _evaluate_one_model(rows, gt)

    # Fold in per-model bench timing (wall-time + cost spent scoring the
    # 214 GT photos with that model). These are apples-to-apples — same
    # photo set, same exemplar prefix — so the hero KPI can show them
    # next to accuracy instead of cumulative production totals.
    timings = _load_bench_timings()
    for short, t in timings.items():
        r = results.setdefault(short, {})
        r["bench_seconds"] = float(t.get("seconds") or 0.0)
        r["bench_cost_usd"] = float(t.get("cost_usd") or 0.0)
        r["bench_n"] = int(t.get("n") or 0)

    BENCHMARK_JSON.parent.mkdir(parents=True, exist_ok=True)
    with BENCHMARK_JSON.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    _print_summary(results)
    print(f"\nwrote {BENCHMARK_JSON}")
    return results


def _print_summary(results: dict[str, dict]) -> None:
    print("=" * 60)
    print("Phase-classification accuracy by model")
    print("=" * 60)
    for model, r in sorted(results.items()):
        bench_s = r.get("bench_seconds", 0.0)
        bench_c = r.get("bench_cost_usd", 0.0)
        bench_n = r.get("bench_n", 0)
        bench_tag = (
            f"  ·  bench {bench_n} photos in {bench_s:.0f}s · ${bench_c:.2f}"
            if bench_n else ""
        )
        print(f"\n[{model}]  ({r['n_test']} test photos){bench_tag}")
        print(f"  depth         : {r['depth']['correct']}/{r['depth']['total']}"
              f" = {r['depth']['pct']:.1f}%")
        print(f"  duct (strict) : {r['duct_strict']['correct']}/{r['duct_strict']['total']}"
              f" = {r['duct_strict']['pct']:.1f}%")
        print(f"  duct (lenient): {r['duct_lenient']['correct']}/{r['duct_lenient']['total']}"
              f" = {r['duct_lenient']['pct']:.1f}%")
        print(f"  OVERALL strict : {r['overall_strict']['correct']}/{r['overall_strict']['total']}"
              f" = {r['overall_strict']['pct']:.1f}%")
        print(f"  OVERALL lenient: {r['overall_lenient']['correct']}/{r['overall_lenient']['total']}"
              f" = {r['overall_lenient']['pct']:.1f}%")


if __name__ == "__main__":
    evaluate()
