# Strategy — picking & winning

Honest take. Treat as a starting position, not gospel.

---

## Should we go Challenge 1 or Challenge 2?

### Quick scorecard

| Dimension | Challenge 1 (DPP+ERP) | Challenge 2 (Construction AI) |
|---|---|---|
| Setup cost | Medium (weclapp/Odoo trials) | High (ML stack, data prep) |
| Demo wow-factor | Low–Medium (UI-driven) | **High** (visual, map clicks, "caught the fake") |
| "AI" alignment with rubric | Soft (mostly integration logic) | **Strong** (vision, forensics, classification) |
| Crowd size (= contention) | Likely bigger | Likely smaller |
| Domain expert availability | Forster (full weekend) | Fuhrmann (full weekend **and on jury**) |
| Business buyer obviousness | Sprawling — many personas | **Sharp — ÖGIG + every fiber operator** |
| Risk of "just glue" verdict | Yes — looks like an integration project | Low — clearly ML work |
| Tech-bucket rubric weight | Worse fit | Better fit (30 % weight, biggest single bucket) |

### Our read
**Challenge 2 leans favourable.** Reasons:
1. The jury's *technical evaluator is the customer.* If we solve a real ÖGIG pain, we have a guaranteed jury vote.
2. The rubric front-loads tech quality (30 %) and AI execution. Computer vision + forensics + geo are a more legible "AI" than Odoo ↔ JSON glue.
3. Visual demos win pitch rooms. A map turning red and a "we caught a fake photo" reveal beat a screen of weclapp custom-attribute records.
4. The €42 M / 50-year-liability number is a sharper business hook than DPP, which has many possible angles but no single laser-tight one.

### When Challenge 1 wins instead
- If a teammate is already an ERP wizard or knows weclapp/Odoo cold.
- If the team is pure backend / no CV experience.
- If we specifically want to court Wals Professional or DPP-Austria for post-event work.

### Hybrid (don't)
The rules force one challenge. Pick one Friday before 17:00.

---

## Team building

Slack first. Friday 15:00–16:00 is the window to find:

- **One frontend / UX dev** (Streamlit + map UX is enough)
- **One backend / data person** (Python, pandas, FastAPI)
- **One ML or vision person**
- **Optional: business / pitch lead**

Three is a strong number for 48 h. Four maxes out. Five usually loses an afternoon to coordination.

Be explicit Friday: "I want to win, not just attend. Are you in for ~36 h of focused work?"

---

## 48-hour timeline (Challenge 2 variant)

### Friday 15:00–18:00 — Lock in
- 15:00–16:00 Gaia session + Slack scouting for teammates
- 16:00–16:45 Kickoff — listen for *any* hint about the dataset format
- 16:45–17:30 Workshop with mentors — **ask Martin Fuhrmann** the most useful narrow question we can: *"What is the single check that, if automated, would save your team the most hours per week?"*
- 17:30–18:00 Team locked, repo created, environment installed on every laptop

### Friday 18:00–23:00 — Skeleton
- Ingest pipeline that reads photos + GeoJSON
- EXIF GPS extraction (no AI yet)
- Folium map showing photos as pins
- Local Streamlit demo with a "upload + see metadata" flow
- **End Friday with a thing that loads photos and shows them on a map.** That's our spine.

### Saturday 09:00–14:00 — Signals
- Add Claude vision pass — get baseline qualitative descriptions
- Add pHash duplicate detector
- Add ELA tamper detector
- Hand-label ~30 photos, train YOLOv8 nano on `duct/sand/ruler/seal`
- Build the per-segment classifier: complete / partial / missing
- **Goal by 14:00: green/yellow/red segments on the map for the sample data.**

### Saturday 14:00–17:00 — UX polish
- Click a red segment → side panel with photo grid + signals table + AI note
- Live "upload a photo" demo flow
- Deficiency report HTML export

### Saturday 17:00–18:00 — **Tech checkpoint with organizers**
- Show the spine works end-to-end. Even if rough.
- Listen for feedback that lets us cut scope.

### Saturday 18:00–23:00 — Demo set-piece + slides
- Pre-rig the demo photos: a clean one, a duplicate-pair, a tampered one, one with missing bedding. Show in this order during the live demo.
- Slide deck: 5 slides, exactly as in [06_tech_resources.md](06_tech_resources.md)
- Record a 90-second backup video. **Non-negotiable.**

### Sunday 09:00–10:30 — Buffer & rehearse
- Two full run-throughs. Cut anything that takes >15 seconds to load.
- Time it. Three minutes is short.

### 10:30 — Pitch. Then chill.

---

## Pitch tactics (works for either challenge)

- **Number first sentence.** "Five hundred photos. Forty-two million euros. Fifty years of liability. One AI check."
- **Live demo > slides.** Spend ≥60 % of the 3 min on the working tool.
- **Name the buyer in slide 2.** Not "operators" — name *ÖGIG* (in the room) or "EU manufacturers preparing for 18 Feb 2027".
- **Show one number we'd save** (hours, € or risk).
- **End with what's next, not a thank-you.** "Next: contractor scorecards across 100+ projects."

## Q&A landmines to prep
- "How accurate is your model?" — answer with sample-set numbers + a stated limitation + a fix plan.
- "What if the photos have no GPS?" — have a fallback ready (manual upload, route-by-folder-name, LLM-inferred location).
- "Why this challenge in a year?" — production hardening: contractor portal, real-time photo upload from job phones, ESG report.
- "What does this cost ÖGIG?" — have a number. Even a back-of-envelope: "€2/photo, ~500/section, 100+ sections/year ≈ €100 k/yr SaaS." Adjust to taste.

---

## What "winning" looks like

Either:
1. Take €1k home — that's nice, but the bigger prize is
2. A working demo + repo + a contact at ÖGIG (or Wals Professional / Sustainista) who says "send me your CV."

Optimize for (2). It's the larger expected value.
