"""False-positive stats per model on the 214-photo GT bench.

Focuses on the *dangerous* FP: a non-depth photo classified as
`depth_measure`. That's the case where a cable-laying frame gets
counted as depth-measurement evidence -- contractor passes without
ever taking a real depth photo. The depth_measure FP is the
compliance-risk class; everything else costs at most a re-shoot.

For each model that has bench rows, prints:
  - depth_measure FP count + rate (out of GT duct photos)
  - duct_laid FP count + rate (out of GT depth photos)
  - paper_label FP count + rate (out of GT real-work photos)
  - precision/recall for depth_measure and duct_laid

Run: uv run python -m scripts.fp_stats
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from src.paths import DATA_DIR, PROCESSED_DIR


def sha1(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    gt = {}
    for label, d in [("depth", "examples/depth"), ("duct", "examples/duct")]:
        for p in (DATA_DIR / "Resources" / d).iterdir():
            if p.is_file():
                gt[sha1(p)] = label

    preds_by_model: dict[str, dict[str, dict]] = defaultdict(dict)
    for line in (PROCESSED_DIR / "readqc_bench.jsonl").open():
        r = json.loads(line)
        preds_by_model[r["model"]][r["photo_id"]] = r

    n_depth = sum(1 for lbl in gt.values() if lbl == "depth")
    n_duct = sum(1 for lbl in gt.values() if lbl == "duct")
    print("=" * 72)
    print(
        f"False-positive stats · {len(gt)} GT photos "
        f"(depth={n_depth}, duct={n_duct})"
    )
    print("=" * 72)

    for model in sorted(preds_by_model.keys()):
        preds = preds_by_model[model]
        depth_total = sum(1 for pid, lbl in gt.items() if lbl == "depth" and pid in preds)
        duct_total = sum(1 for pid, lbl in gt.items() if lbl == "duct" and pid in preds)

        # DANGEROUS FP: GT=duct, predicted=depth_measure
        depth_fp = sum(
            1 for pid, lbl in gt.items()
            if lbl == "duct" and pid in preds
            and preds[pid]["phase"] == "depth_measure"
        )
        # LESS DANGEROUS FP: GT=depth, predicted=duct_laid
        duct_fp = sum(
            1 for pid, lbl in gt.items()
            if lbl == "depth" and pid in preds
            and preds[pid]["phase"] == "duct_laid"
        )
        # MODERATE FP: real work photo classified as paper_label
        paper_fp_on_duct = sum(
            1 for pid, lbl in gt.items()
            if lbl == "duct" and pid in preds
            and preds[pid]["phase"] == "paper_label"
        )
        paper_fp_on_depth = sum(
            1 for pid, lbl in gt.items()
            if lbl == "depth" and pid in preds
            and preds[pid]["phase"] == "paper_label"
        )

        # Precision/recall for depth_measure
        dp_tp = sum(
            1 for pid, lbl in gt.items()
            if lbl == "depth" and pid in preds
            and preds[pid]["phase"] == "depth_measure"
        )
        dp_predicted_total = sum(
            1 for pid in preds if preds[pid]["phase"] == "depth_measure"
        )
        dp_precision = dp_tp / dp_predicted_total if dp_predicted_total else 0
        dp_recall = dp_tp / depth_total if depth_total else 0

        # Precision/recall for duct_laid
        du_tp = sum(
            1 for pid, lbl in gt.items()
            if lbl == "duct" and pid in preds
            and preds[pid]["phase"] == "duct_laid"
        )
        du_predicted_total = sum(
            1 for pid in preds if preds[pid]["phase"] == "duct_laid"
        )
        du_precision = du_tp / du_predicted_total if du_predicted_total else 0
        du_recall = du_tp / duct_total if duct_total else 0

        print()
        print(f"[{model}]  n_scored={len(preds)}")
        print(f"  DANGEROUS depth_measure FP (duct labeled depth):  "
              f"{depth_fp}/{duct_total} = {(depth_fp/duct_total*100) if duct_total else 0:.1f}%")
        print(f"  duct_laid FP            (depth labeled duct):     "
              f"{duct_fp}/{depth_total} = {(duct_fp/depth_total*100) if depth_total else 0:.1f}%")
        print(f"  paper_label FP on duct  (work hidden as label):   "
              f"{paper_fp_on_duct}/{duct_total} = "
              f"{(paper_fp_on_duct/duct_total*100) if duct_total else 0:.1f}%")
        print(f"  paper_label FP on depth (work hidden as label):   "
              f"{paper_fp_on_depth}/{depth_total} = "
              f"{(paper_fp_on_depth/depth_total*100) if depth_total else 0:.1f}%")
        print(f"  depth_measure:  precision {dp_precision*100:5.1f}%  "
              f"recall {dp_recall*100:5.1f}%  (TP={dp_tp})")
        print(f"  duct_laid:      precision {du_precision*100:5.1f}%  "
              f"recall {du_recall*100:5.1f}%  (TP={du_tp})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
