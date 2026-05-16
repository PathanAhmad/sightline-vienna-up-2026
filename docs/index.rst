Vienna UP 2026 Photo QC Documentation
======================================

This documentation describes the APG construction-photo compliance audit
prototype built during Vienna UP / Europe Tech Hackathon 2026.

The app ingests trench-site photos and route GeoJSON data, checks the evidence
for construction compliance, maps each trench segment as green, yellow, or red,
and produces reviewer-ready deficiency outputs.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   workflow
   features

Quick Start
-----------

Install dependencies and run the Streamlit app from the repository root:

.. code-block:: bash

   uv sync
   uv run streamlit run app.py

Open the default URL for the reviewer dashboard, or add ``?view=upload`` for
the operator upload surface.

