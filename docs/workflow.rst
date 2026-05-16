Main Workflow
=============

The workflow turns a folder of trench photos plus GeoJSON route data into a
map and report that a reviewer can triage quickly. The dashboard uses real
pipeline outputs from ``data/processed/`` when present and falls back to the
committed ``demo_fixtures/`` data for the hackathon demo.

1. Ingest Photos and Route Data
-------------------------------

The ingest stage walks the photo folder, records each photo in
``manifest.sqlite``, and loads the trench, FCP, and site-cluster GeoJSON files.

Each photo receives a stable ``photo_id`` derived from file bytes so duplicate
or renamed submissions can still be linked back to the same underlying image.
The route data is treated as WGS84/EPSG:4326 and the trench segment identifier
comes from the GeoJSON ``externalID`` field.

2. Detect Duplicate and Suspicious Images
-----------------------------------------

Before any AI review, ``src/forensics.py`` performs cheap local checks:

* perceptual hash clustering to find reused or duplicated photos;
* one representative image per duplicate cluster is sent onward;
* ELA scoring is recorded as a tamper hint.

This keeps repeated images from being scored repeatedly and makes duplicate
photo reuse visible in the reviewer dashboard.

3. Run Photo Quality Review
---------------------------

``src/readqc.py`` sends each unique representative photo to Claude vision and
stores one structured JSONL row per reviewed photo. The model extracts the
photo phase, relevance, overlay address, overlay coordinates, paper label, and
visual compliance signals.

Photos are first gated by relevance:

* ``scorable`` photos continue into geomatching and classification;
* ``portrait``, ``off_topic``, and ``unreadable`` photos are dropped from
  segment scoring and shown separately as not classified.

The review also flags personal data such as faces or license plates. Those
photos remain in the audit trail but are withheld from the on-screen image grid.

4. Match Photos to Trench Segments
----------------------------------

``src/geomatch.py`` assigns photos to exact trench segments:

* overlay latitude/longitude is parsed and snapped to the nearest LineString;
* address-only photos can be geocoded and snapped as a fallback;
* the snapped point is checked against the site cluster and FCP polygons;
* overlay coordinates and geocoded address are compared for location mismatch;
* paper labels such as ``F170-R084-11-or`` are used as consistency checks.

The output is ``geomatch.csv`` with the snapped ``segment_id``, position along
the segment, snap distance, FCP assignment, label match, and location flags.

5. Classify Each Segment
------------------------

``src/classify.py`` rolls photo evidence up to trench segments. A segment is
considered fully covered only when compliant photos appear at least every
5 meters along the segment.

Verdicts are assigned as:

* ``GREEN``: compliant photo coverage every 5 meters and no failing checks;
* ``YELLOW``: photos exist, but density or quality is insufficient;
* ``RED``: no usable compliant evidence or very sparse photo coverage.

The classifier writes ``verdicts.csv`` with segment length, photo counts,
maximum evidence gap, density, verdict, and human-readable reasons.

6. Review in Streamlit
----------------------

``app.py`` exposes two views from the same Streamlit process:

* reviewer dashboard at ``/``;
* operator upload view at ``/?view=upload``.

The reviewer dashboard renders the colored folium map, project KPIs, duplicate
and location catches, downloadable deficiency outputs, and a segment drill-down
panel. Clicking a segment shows the evidence, reasons, and related photo rows.

The upload view supports contractor-style batch submission. A small live batch
can be scored, snapped to the route, and reflected back on the dashboard so an
operator can retake missing or non-compliant photos before leaving the site.

7. Export Deficiency Outputs
----------------------------

The reporting stage produces reviewer artifacts under
``data/processed/report/``:

* ``deficiency.csv`` for red and yellow segments;
* ``not_classified.csv`` for dropped or irrelevant photos;
* ``personal_data.csv`` for privacy-sensitive evidence;
* ``summary.html`` for a compact overview.

These outputs support the app's review flow and provide a handoff artifact for
APG or partner reviewers.

