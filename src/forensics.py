"""Stage 2 -- Forensics (local, no API cost).

Computes pHash for every photo, clusters near-duplicates (Hamming <= 6),
picks one representative per cluster (lowest photo_id), and runs a cheap
Error Level Analysis (ELA) pass for a weak tamper hint.

Reads:
    - data/processed/manifest.sqlite

Writes:
    - data/processed/forensics.jsonl
        {photo_id, phash, phash_cluster_id, is_phash_representative,
         ela_score, ela_flag}

Validation:
    PLAN expected ~600 known duplicates from `N_` prefixes / `kopia`
    suffixes, recoverable by pHash. In reality the submission system
    stored byte-identical copies, so all but 15 of those families
    collapse at the ingest sha1 step (702 file-pairs absorbed there).
    The 15 families that survive into the manifest are different
    photos that happen to share a filename pattern -- pHash should
    correctly NOT merge them. We report:
      * byte-identical merges absorbed at ingest (sha1)
      * extra merges produced by pHash on top of that
      * pHash clusters that include >1 distinct sha1 (the real signal)

Cluster id is just a small int; representative wins by lowest photo_id
(sha1 -- deterministic across runs).
"""

from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Stop BLAS / OpenMP runtimes from spinning up their own thread pools inside
# each worker. Without this, 4 ProcessPool workers each fork an OMP team and
# we run out of memory before the first image is hashed.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

from src.paths import FORENSICS_JSONL, MANIFEST_DB, PHOTOS_DIR, ensure_dirs

PHASH_HAMMING_THRESHOLD = 6
ELA_QUALITY = 90        # re-save quality for the ELA pass
ELA_THRESHOLD = 15.0    # mean per-pixel delta on 0-255 scale; calibrate after first run

# Strip leading "N_" digit-prefix (submission counter) to recover the original stem.
N_PREFIX_RE = re.compile(r"^(\d+)_(.+)$")
# Russian "kopia" suffix variants we saw in the corpus.
KOPIA_RE = re.compile(r"\s*[- ]+\s*копия(?:\s*\(\d+\))?", re.IGNORECASE)


def canonical_stem(filename: str) -> str:
    """Reduce a filename to the 'family' key used for known-duplicate recall."""
    name = filename
    # Drop extension
    stem = Path(name).stem
    # Strip N_ prefix
    m = N_PREFIX_RE.match(stem)
    if m:
        stem = m.group(2)
    # Strip Russian "kopia" suffix
    stem = KOPIA_RE.sub("", stem).strip()
    return stem.lower()


def _compute_one(args: tuple[str, str]) -> dict:
    """Worker: compute pHash + ELA for one photo. Runs in a separate process."""
    photo_id, rel_path = args
    from PIL import Image, ImageChops, ImageStat
    import imagehash

    path = PHOTOS_DIR / rel_path
    img = Image.open(path).convert("RGB")

    # Downsize once. 4000x3000 -> ~1024 wide. Both pHash and ELA share this.
    if max(img.size) > 1024:
        scale = 1024 / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))

    # pHash on the downsized RGB
    phash_hex = str(imagehash.phash(img))

    # ELA: re-save at quality 90, diff against current, mean per-pixel delta.
    # Pure PIL -- no numpy in the worker, so we don't fight OpenBLAS thread pools.
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=ELA_QUALITY)
    buf.seek(0)
    resaved = Image.open(buf).convert("RGB")
    diff = ImageChops.difference(img, resaved)
    means = ImageStat.Stat(diff).mean  # list of channel means, 0..255
    delta = sum(means) / len(means)

    return {
        "photo_id": photo_id,
        "phash": phash_hex,
        "ela_score": float(delta),
    }


def compute_phashes_and_ela(workers: int = 4) -> list[dict]:
    """Compute pHash + ELA for every photo. Returns list of partial rows."""
    conn = sqlite3.connect(MANIFEST_DB)
    rows = conn.execute("SELECT photo_id, rel_path FROM photos ORDER BY photo_id").fetchall()
    conn.close()
    total = len(rows)
    print(f"[forensics] hashing {total} photos with {workers} workers ...")

    results: list[dict] = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_compute_one, r): r for r in rows}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                results.append(fut.result())
            except Exception as e:
                pid, rp = futures[fut]
                print(f"[forensics] FAIL {rp}: {type(e).__name__}: {e}")
            if i % 200 == 0 or i == total:
                rate = i / (time.time() - t0)
                print(f"[forensics]   {i}/{total} ({rate:.1f}/s)")
    return results


def cluster_phashes(rows: list[dict], threshold: int = PHASH_HAMMING_THRESHOLD) -> dict[str, int]:
    """Single-linkage cluster by Hamming distance. Returns {photo_id: cluster_id}.

    Pairwise comparison of 64-bit ints is cheap. For ~3.2k photos that's
    ~5M XOR+popcount operations -- well under a second.
    """
    # Convert hex to int once
    ids = [r["photo_id"] for r in rows]
    hashes = [int(r["phash"], 16) for r in rows]
    n = len(ids)

    # Union-Find
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        hi = hashes[i]
        for j in range(i + 1, n):
            # Hamming distance via XOR + popcount
            if bin(hi ^ hashes[j]).count("1") <= threshold:
                union(i, j)

    # Materialise cluster ids -- one int per distinct root
    root_to_cid: dict[int, int] = {}
    out: dict[str, int] = {}
    for i, pid in enumerate(ids):
        root = find(i)
        if root not in root_to_cid:
            root_to_cid[root] = len(root_to_cid)
        out[pid] = root_to_cid[root]
    return out


def pick_representatives(cluster_map: dict[str, int]) -> set[str]:
    """One representative per cluster: lowest photo_id wins. Returns set of reps."""
    buckets: dict[int, list[str]] = {}
    for pid, cid in cluster_map.items():
        buckets.setdefault(cid, []).append(pid)
    reps: set[str] = set()
    for cid, members in buckets.items():
        reps.add(min(members))  # sha1 hex strings sort lexicographically
    return reps


def phash_extra_merges(cluster_map: dict[str, int]) -> tuple[int, list[tuple[int, int]]]:
    """Count pHash clusters with >1 member (each member is a distinct sha1).
    These are the duplicates pHash catches that ingest's sha1 missed.

    Returns (n_multi_clusters, sample_sizes) where sample_sizes is up to 5
    (cluster_id, member_count) pairs for inspection.
    """
    buckets: dict[int, list[str]] = {}
    for pid, cid in cluster_map.items():
        buckets.setdefault(cid, []).append(pid)
    multi = [(cid, len(members)) for cid, members in buckets.items() if len(members) > 1]
    multi.sort(key=lambda t: -t[1])
    return len(multi), multi[:5]


def write_forensics(rows: list[dict], cluster_map: dict[str, int], reps: set[str]) -> None:
    ensure_dirs()
    with FORENSICS_JSONL.open("w", encoding="utf-8") as fh:
        for r in rows:
            pid = r["photo_id"]
            out = {
                "photo_id": pid,
                "phash": r["phash"],
                "phash_cluster_id": cluster_map[pid],
                "is_phash_representative": pid in reps,
                "ela_score": round(r["ela_score"], 4),
                "ela_flag": r["ela_score"] > ELA_THRESHOLD,
            }
            fh.write(json.dumps(out) + "\n")


def main() -> int:
    if not MANIFEST_DB.exists():
        print("[forensics] manifest.sqlite missing -- run `python -m src.ingest` first", file=sys.stderr)
        return 1

    rows = compute_phashes_and_ela(workers=4)
    cluster_map = cluster_phashes(rows)
    reps = pick_representatives(cluster_map)

    n_total = len(rows)
    n_clusters = len(set(cluster_map.values()))
    n_reps = len(reps)
    n_ela = sum(1 for r in rows if r["ela_score"] > ELA_THRESHOLD)

    n_multi, samples = phash_extra_merges(cluster_map)
    write_forensics(rows, cluster_map, reps)

    print(
        f"[forensics] {n_total} photos, {n_clusters} pHash clusters, "
        f"{n_reps} representatives -> {FORENSICS_JSONL.name}"
    )
    print(f"[forensics] ELA: {n_ela} flagged (score > {ELA_THRESHOLD})")
    print(f"[forensics] pHash merged {n_total - n_reps} extra photos into {n_multi} multi-member clusters")
    if samples:
        print(f"[forensics]   largest multi-clusters (cid, size): {samples}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
