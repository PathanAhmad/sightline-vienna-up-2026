"""Stage 4 — Geomatch (photo → LineString segment).

What it does: for every photo we have a QC row for, figure out which
trench segment it documents and where along that segment it sits.

Reads:
    - data/processed/readqc.jsonl  (overlay_latlon, overlay_address, paper_label_code)
    - data/geo/*.geojson           (trenches, FCPs, site cluster)

Writes:
    - data/processed/geomatch.csv
        See PLAN.md → Data contracts → geomatch for the column list.

Snap order of preference:
    1. Overlay lat/lon parsed (any of 4 formats incl. DMS with comma
       decimals) → nearest LineString in trenches.
    2. No lat/lon, address present → Nominatim forward-geocode (cached,
       1 req/sec) → nearest LineString within the FCP polygon that
       contains the geocoded point.
    3. Neither → coord_source = "none", segment_id empty.

FCP gap fallback:
    FCP polygons cover 102.8% of the SiteCluster but with 18.7% interior
    gaps. If point-in-polygon fails for all FCPs, assign to the nearest
    FCP centroid and set fcp_assignment = "nearest_fallback".

Cross-checks (don't block; just flag):
    - latlon_vs_address_flag = lat/lon present AND geocoded address present
      AND haversine(latlon, geocoded) > 150m AND different street name.
    - label_match = compare paper_label_code's F### and R### against the
      snapped segment's fcpName and ductMainShort.

Duplicates:
    Photos with is_phash_representative=false inherit the geomatch row of
    their representative. They appear in geomatch.csv as their own rows
    but with identical lat/lon/segment_id. Do this at the very end so the
    representative is positioned first.

Nominatim contract:
    User-Agent: "ViennaUP2026/0.1 (pathanahmad2334@gmail.com)"
    Rate limit: ≤ 1 request/second (time.sleep(1.1) between calls).
    Cache responses in memory keyed by exact address string.
"""

from __future__ import annotations


def parse_overlay_latlon(s: str | None) -> tuple[float, float] | None:
    """Parse DMS-period, DMS-comma, decimal-no-separators, or labeled-decimal."""
    raise NotImplementedError("see PLAN.md → Data contracts → geomatch")


def geocode_address(addr: str) -> tuple[float, float] | None:
    """Nominatim forward-geocode with proper UA and 1 req/sec throttle. Cached."""
    raise NotImplementedError("see PLAN.md → Data contracts → geomatch")


def snap_to_segment(lat: float, lon: float, within_fcp: str | None = None) -> tuple[str, float, float]:
    """Return (segment_id, segment_t in [0,1], snap_distance_m)."""
    raise NotImplementedError("see PLAN.md → Data contracts → geomatch")


def assign_fcp(lat: float, lon: float) -> tuple[str, str]:
    """Return (fcp_name, fcp_assignment). fcp_assignment ∈ {inside_polygon, nearest_fallback, off_cluster}."""
    raise NotImplementedError("see PLAN.md → Data contracts → geomatch")


def main() -> int:
    """Entry point for `python -m src.geomatch`. Writes geomatch.csv."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
