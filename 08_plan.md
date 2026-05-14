# Plan — Europe Tech Hackathon 2026 (shareable)

**For:** the team. **Format:** a head-start, not a script.
**Spine is firm; forks are open.** We'll decide the forks together at the venue.

---

## What we're doing

Building a working prototype for **Challenge 2 — AI-Powered Construction Photo Compliance Audit** for **ÖGIG** (Austrian fiber-optic infrastructure). 48 hours. 3-minute pitch on Sunday morning.

**Why this challenge, in one line:** the jury's technical evaluator (Martin Fuhrmann) is the customer; the rubric front-loads "AI execution" (30%); CV/forensics demos pitch better than ERP integration screens.

Full deep dive: [03_challenge_2_construction_ai.md](03_challenge_2_construction_ai.md).
Why-not-Challenge-1: [07_strategy.md](07_strategy.md).

---

## What we know (the spine, locked)

1. **Input we'll be given:** trench photos + a GeoJSON route. Released at or just after the 16:00 Friday kickoff — we won't see it before.
2. **Output we have to produce:**
   - Working pipeline (photo in → QC logic → risk classification out)
   - A map or report with green / yellow / red segments
   - A 3-minute demo + business case
3. **Compliance signals to check (the brief lists six):** GPS/date metadata, duct visibility, sand bedding, pipe-end seals, ruler readability, privacy issues. **Plus** duplicate detection and tamper detection.
4. **Saturday tech checkpoint** (~17:00) — Sustainista team checks integration progress. Spine must work end-to-end by then, even if rough.
5. **Evaluation rubric (full table in README.md):** 30% tech/AI, 20% problem fit, 15% UX, 15% business model, 10% impact, 10% pitch.

---

## What we *don't* know yet (decide at venue, together)

| Unknown | When we'll find out | What it changes |
|---|---|---|
| Exact dataset format, photo count, GPS quality | Friday 16:00 kickoff | Affects pipeline shape & which signals are feasible |
| GeoJSON coordinate system (EPSG:4326 vs 31287) | When dataset drops | Geo-matching code |
| Whether photos already have EXIF GPS or not | When dataset drops | Fallback strategies (filename, manual upload, LLM hint) |
| ÖGIG's actual internal spec / priority signal | Friday workshop with Martin | Which checks to ship first |
| Team size & shape | Friday 15:00–17:00 (Slack now, lock by 17:00) | Scope, role assignment |
| Mentor availability for our angle | Saturday morning | Whose office hours we book |

**Rule:** don't pre-decide any of these. We'll burn time pivoting.

---

## Forks we'll choose at the venue (with current leans, not commitments)

### Fork A — Stack
- **Lean:** Python · Streamlit/Gradio UI · FastAPI backend · Folium map
- **Why:** fastest path to a visual demo; ML libs are Python-first
- **Open if:** teammate is strong in something else and we need to ship faster

### Fork B — Detection approach
- **Option 1:** Pretrained vision-language model (Claude / GPT-4o vision) does most of the photo reasoning, with prompts per signal
- **Option 2:** Train small YOLOv8 on 30–50 hand-labelled photos for the deterministic checks (duct, sand, ruler, seal)
- **Lean:** start Option 1 Friday night → add Option 2 Saturday for credibility. **Don't pick one and commit.**

### Fork C — Forensics depth
- **Lean:** ship pHash duplicate detection (cheap, high-impact in demo) + EXIF sanity. ELA/noise analysis only if time.
- **Open if:** Martin says "duplicates aren't actually a problem for us"

### Fork D — Demo medium
- **Lean:** live Streamlit + Folium map on the projector
- **Backup (non-negotiable):** record a 90-sec screen capture Saturday night

### Fork E — Business angle for the pitch
- **Options:** ÖGIG-internal SaaS · contractor accountability tool · warranty-claim audit trail · ESG/compliance export
- **Decide Saturday afternoon** after seeing what the prototype actually does well

---

## Day-by-day intent (loose)

### Friday — orient, team up, build the spine
- 15:00–16:00 Arrive, Gaia session, scout teammates on Slack/in person
- 16:00–16:45 Kickoff — get the dataset, read the fine print together
- 16:45–17:30 Workshop with Martin — **ask one narrow question:** *"What single check, if automated, saves your team the most hours per week?"* Use his answer to prioritize.
- 17:30–19:30 HR Corner overlaps — split it. One of us networks while the other starts repo setup.
- ~19:30–23:00 **Goal: photos load + show up on a map by midnight.** No AI yet. Just the spine.

### Saturday — fill in the AI, hit the checkpoint
- Morning: signals (vision API → first cut, then deterministic checks layer in)
- ~14:00: green/yellow/red segments visible on the map for the sample data
- 14:00–17:00: UX polish — clickable segments, deficiency panel
- **~17:00 tech checkpoint** with organizers — show the spine, take feedback
- Evening: rig the demo set-piece (a clean photo, a duplicate-pair, a tampered photo, a missing-bedding one), record the backup video, build the 5-slide deck

### Sunday — buffer, rehearse, pitch
- Two full run-throughs before 10:30
- Pitch · awards · breathe

---

## Roles (assign Friday when we meet)

Not pre-assigning — depends on who joins. Roles we'll need:

- **Driver / pitch lead** — owns the Sunday pitch + jury Q&A, decides scope cuts
- **Pipeline builder** — ingest, geomatch, classifier, report
- **CV / AI builder** — vision prompts, YOLO if we go that route, forensics layer
- **UX / demo polish** — Streamlit/map UX, demo set-piece prep
- **Mentor & partner liaison** — books mentor slots, talks to Martin, owns HR Corner side-trips

Two people can hold multiple roles. Solo + 1 teammate = both wear 2-3 hats each.

---

## How we work together (norms)

- **Git from minute zero.** Private repo, push to it constantly. Conflict-free is more important than perfect.
- **Decisions get written in a `DECISIONS.md` in the repo** — one line each, with timestamp. So we don't re-litigate.
- **Anyone can say "this is taking too long" at any time.** Cut early.
- **No silent pivots.** If you change approach, say it out loud.
- **Backup video is sacred.** Whatever happens, that gets recorded Saturday night.

---

## Pre-Friday checklist (each of us, before doors open)

- [ ] Joined the Slack (`europetechhac-yix2175`)
- [ ] Python 3.11 + uv installed, plus: `pillow piexif imagehash imagededup geopandas shapely folium ultralytics streamlit fastapi anthropic`
- [ ] Anthropic or OpenAI API key, €20+ credit
- [ ] GitHub access ready (we'll spin a private repo Friday)
- [ ] Read [03_challenge_2_construction_ai.md](03_challenge_2_construction_ai.md) and [06_tech_resources.md](06_tech_resources.md) on the train
- [ ] Laptop, charger, ID, water bottle, headphones, snacks
- [ ] (Mobile hotspot if you have one — venue Wi-Fi during demos is famously fragile)

---

## What success looks like (two layers)

1. **Working demo on Sunday** that uploads a photo, geo-matches, classifies, and shows a deficiency panel. Map turns red in one place. We click it. The story tells itself.
2. **Anyone on the jury or in the partner room saying "send me your CV"** by Sunday 13:00.

Both are wins. We don't optimize only for prize money.

---

## What's deliberately not in this plan

Specific commits, exact prompts, exact model choices, exact UI layout, who writes what. Those depend on the dataset, the teammates, and what Friday tells us. We'll decide as we go.

Spine firm. Forks open. Ship.
