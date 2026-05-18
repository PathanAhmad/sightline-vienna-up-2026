# Sightline

**Automated trench-photo QC for network operators.** Built in 48 hours at the [Vienna UP / Europe Tech Hackathon 2026](https://viennaup.com/), 15–17 May 2026 (Challenge 2: *AI-Powered Construction Photo Compliance Audit*).

Field crews shoot thousands of compliance photos per project. A reviewer normally walks each segment by hand to confirm that the right evidence exists (warning tape, sand bedding, depth reference, sealed ducts, …) and that nothing is missing. Sightline ingests the photo batch + a GeoJSON route, runs each photo through Claude vision, classifies every trench segment **green / yellow / red**, and produces a reviewer-ready deficiency report.

- **Pilot dataset:** 3,929 fiber-trench photos (Maria Rain, Carinthia — CLP20417A) + 223 labeled exemplars + GeoJSONs from the operator partner. The full backlog at the partner sits at ~424,000 photos.
- **Stack:** Python 3.11, Streamlit, Claude Sonnet 4.6 vision (with Haiku and GPT-4o benchmarks), geopandas / Shapely, ReportLab.
- **Pipeline:** ingest → forensics (pHash dedup + ELA) → Claude vision QC → geomatch (overlay-OCR + geocode fallback) → segment classify (5-m density rule) → PDF deficiency report.

## What's in the repo

- **[`app.py`](app.py)** — Streamlit app: reviewer dashboard (`/`) + operator upload view (`?view=upload`).
- **[`src/`](src/)** — pipeline modules (one stage per file: `forensics`, `readqc`, `geomatch`, `classify`, `report`, `pdf_report`, …).
- **[`scripts/`](scripts/)** — benchmark scripts (Sonnet vs Haiku vs GPT-4o on the 214-photo ground-truth set), deck builders, dev harnesses.
- **[`samples/sightline-deficiency-report.pdf`](samples/sightline-deficiency-report.pdf)** — example output the reviewer downloads from the dashboard.
- **[`docs/`](docs/)** — Sphinx workflow + features documentation ([published here](https://pathanahmad.github.io/sightline-vienna-up-2026/)).
- **[`Sightline_Pitch.pptx`](Sightline_Pitch.pptx)** — the 4-slide deck from the Sunday pitch (`generate_ppt.py` rebuilds it).
- **[`SPEECH.md`](SPEECH.md)** — the 3-minute speech, beat by beat.

## How it was built (the story)

- **[`REFERENCE.md`](REFERENCE.md)** — code-verified architecture deep-dive: every module, every output, every gotcha.
- **[`HOW_IT_WORKS.md`](HOW_IT_WORKS.md)** — plain-English explainer for non-technical readers.
- **[`DECISIONS.md`](DECISIONS.md)** — one-line log of every product / engineering decision across the 48 hours.

## Run it locally

```bash
uv sync                           # install Python 3.11 deps from pyproject.toml
uv run streamlit run app.py       # reviewer dashboard at /, operator view at /?view=upload
```

You'll need an Anthropic API key in `.env` (the QC engine is Claude Sonnet 4.6 vision — see [`DECISIONS.md`](DECISIONS.md) for the Haiku / Sonnet / GPT-4o comparison). Partner-provided photos and route GeoJSONs live under `Resources/` and `data/` (gitignored; NDA on the route data per the brief). The app falls back to bundled fixtures in [`demo_fixtures/`](demo_fixtures/) when those folders are missing, so the dashboard is runnable straight from a fresh clone.

## Team

Built by **Ahmad Khan Pathan** ([@PathanAhmad](https://github.com/PathanAhmad)) and **Valentino Sack** ([@vsack](https://github.com/vsack)). Pitch deck contributions from Himani Sharma. Sphinx docs + GitHub Pages workflow contributed by Evgeniy Avdeev.
