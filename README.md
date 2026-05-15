# Vienna UP / Europe Tech Hackathon 2026

48 hours. Vienna. 15–17 May 2026. Working from **ÖBB Open Innovation Factory**, Lassallestraße 5, 1020 Wien.

## What we're doing

**Challenge 2: AI-Powered Construction Photo Compliance Audit** for **APG (Austrian Power Grid)**.

We're building a prototype that ingests construction-site trench photos plus a GeoJSON route, runs each photo through six compliance checks, classifies each route segment **green / yellow / red**, and produces a reviewer-ready deficiency report.

- **Brief partner:** APG. High-voltage grid trenches; ~424,000 photos in their full backlog.
- **Pilot data delivered:** 3,929 fiber-trench photos from Maria Rain, Carinthia (one project cluster, CLP20417A) + 223 labeled example photos + GeoJSONs. Stand-in dataset; the QC approach generalizes.

## What to read

1. **[CLAUDE.md](CLAUDE.md)** — hard rules we cannot get wrong. Read first.
2. **[PLAN.md](PLAN.md)** — what we're building, by when, with what stack.
3. **[DECISIONS.md](DECISIONS.md)** — one-line log of every decision so far. No re-litigating.

## Schedule

| When | What |
|---|---|
| **Fri 15 May** | Kickoff 16:00 · workshop with Martin Fuhrmann · hacking after · venue closes 23:00 |
| **Sat 16 May** | Build day · mentoring 10:00–14:00 · **tech checkpoint 17:00** · venue closes 23:00 |
| **Sun 17 May** | Pitch session **10:30–12:00** (3 min/team) · awards 12:30 |

Venue: ÖBB Open Innovation Factory, Lassallestraße 5, 1020 Wien. Slack: `europetechhac-yix2175`.

## Run it locally

```bash
uv sync                # install Python 3.11 deps from pyproject.toml
streamlit run app.py   # once app.py exists
```

Anthropic API key in `.env` (Claude Haiku 4.5 vision is the QC engine).

## Resources

`Resources/` is partner-provided data: the brief docx, the 3,929 trench photos, 223 labeled exemplars, GeoJSONs, two reference decks. **Untracked. NDA on route data per the brief.**

## Evaluation rubric (Sunday)

30% tech & AI · 20% problem fit · 15% UX · 15% business · 10% impact · 10% pitch. **Jury:** Jan Juriga (Wirtschaftsagentur Wien), Kati Schneeberger (BEJ), Johannes Adler (investor), Martin Fuhrmann (APG / Challenge 2 domain expert — we are literally being judged by the customer).
