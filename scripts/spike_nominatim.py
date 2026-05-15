"""
Test whether Nominatim (free OpenStreetMap geocoder) can resolve the kind of
addresses that appear in our photo overlays, and whether the resulting coords
land inside the SiteCluster polygon.

Run: .venv/Scripts/python.exe scripts/spike_nominatim.py
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
GEO_DIR = REPO_ROOT / "data" / "geo"
SAMPLE_ADDRESSES = [
    # Mix: with house number, without, German letters, neighboring village
    "20 Toppelsdorferstraße, Maria Rain, Kärnten, Austria",
    "11 Josef-Petritsch-Straße, Maria Rain, Klagenfurt-Land, Austria",
    "13 Dahlienweg, Maria Rain, Austria",
    "Kaiserhüttenweg 7, 9161 Maria Rain, Austria",
    "76 Bundesstraße, Lambichl, Kärnten, Austria",   # neighboring village
]

USER_AGENT = "ViennaUP2026/0.1 (pathanahmad2334@gmail.com)"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def nominatim_search(q: str) -> dict | None:
    url = "https://nominatim.openstreetmap.org/search?" + urlencode({"q": q, "format": "json", "limit": 1, "countrycodes": "at"})
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "de,en"})
    with urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    return data[0] if data else None


def point_in_polygon(lon: float, lat: float, poly: list[list[float]]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-30) + xi):
            inside = not inside
        j = i
    return inside


def load_polygon(path: Path) -> list[list[float]]:
    with path.open("r", encoding="utf-8") as f:
        gj = json.load(f)
    feat = gj["features"][0]
    geom = feat["geometry"]
    if geom["type"] == "Polygon":
        return geom["coordinates"][0]
    raise ValueError(f"unexpected geom: {geom['type']}")


def main() -> int:
    cluster = load_polygon(GEO_DIR / "CLP20417A-P1-B00_SiteCluster_Polygons.geojson")
    cx = sum(p[0] for p in cluster) / len(cluster)
    cy = sum(p[1] for p in cluster) / len(cluster)
    print(f"Cluster centroid ~ ({cy:.4f}, {cx:.4f})  ({len(cluster)} vertices)\n")

    print(f"{'Address':<55}  {'Got':<25}  {'In cluster':<11}  {'Distance to centroid'}")
    print("-" * 120)
    for addr in SAMPLE_ADDRESSES:
        t0 = time.time()
        try:
            r = nominatim_search(addr)
        except Exception as e:
            print(f"{addr:<55}  ERROR  {type(e).__name__}: {e}")
            continue
        elapsed = time.time() - t0
        if r is None:
            print(f"{addr:<55}  NO RESULT  ({elapsed:.1f}s)")
        else:
            lat = float(r["lat"]); lon = float(r["lon"])
            inside = point_in_polygon(lon, lat, cluster)
            dist = haversine_m(cy, cx, lat, lon)
            print(f"{addr:<55}  ({lat:.4f}, {lon:.4f})    {'YES' if inside else 'NO':<11}  {dist:>6.0f} m  ({elapsed:.1f}s)")
        # Nominatim free-tier requires ≤ 1 request/sec
        time.sleep(1.1)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
