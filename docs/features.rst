Features
========

Reviewer Dashboard
------------------

The default Streamlit view gives reviewers a map-first triage surface. It shows
the project area, FCP zones, trench LineStrings, and segment verdict colors.
Reviewers can click a segment to see the segment reasons and the supporting
photo evidence.

Operator Upload View
--------------------

The ``?view=upload`` surface is intended for a contractor or operator submitting
a small batch of photos. It can score uploaded evidence, snap GPS-bearing photos
to the route, and show which segments changed after the batch.

Eight Compliance Signals
------------------------

The prototype combines AI vision and local checks:

* warning tape visible;
* sand bedding visible;
* side view or trench profile present;
* depth reference visible;
* duct visible and pipe ends sealed where applicable;
* personal data visible;
* duplicate or reused photo;
* GPS and address consistency.

Phase-Aware Scoring
-------------------

The app records the construction phase of each photo so checks are applied only
where they make sense. A depth-measure photo is not penalized for missing warning
tape that belongs to a later work phase.

Duplicate Detection
-------------------

Perceptual hashes group near-identical photos before the AI step. This reduces
cost and surfaces reused submissions as a reviewer catch.

Location Consistency
--------------------

Overlay coordinates, printed addresses, paper FCP labels, site-cluster polygons,
and trench LineStrings are cross-checked. Off-cluster photos and meaningful
address-vs-coordinate mismatches are flagged instead of silently discarded.

Privacy-Aware Display
---------------------

Photos with visible personal data are kept in backend outputs for auditability
but are hidden in the dashboard photo grid. The UI shows a notice card instead
of rendering sensitive image bytes.

Demo Fixtures and Live Data
---------------------------

The dashboard prefers real pipeline artifacts from ``data/processed/`` and real
GeoJSONs from ``data/geo/``. If those files are missing, it falls back to
``demo_fixtures/`` so the app remains runnable from the committed repository.

Downloadable Reports
--------------------

Reviewers can export deficiency and audit outputs that list problematic
segments, unclassified evidence, personal-data photos, and supporting reasons.

