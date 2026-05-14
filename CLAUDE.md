# CLAUDE.md — hard rules

Open list. Add as we learn. Only things we **cannot** get wrong.

## Mindset
- **This is your project too.** Own the call. If you see a better path, take it — don't wait to be told.
- **Make good decisions, then move.** When something's unclear, pick a direction and say it out loud. Indecision burns more hours than wrong calls.
- **Talk simple. Talk concise.** If a teammate or judge asks what we're doing and you go blank — you don't understand it yet. Stop and re-explain it to yourself in one sentence. Then you can answer in one sentence.
- **No ego on cuts.** If your feature gets cut Saturday afternoon, it's because the demo wins. Same goes for everyone else's.

## Process
- **Git from minute zero.** Push constantly. Conflict-free > perfect.
- **No silent pivots.** Changing approach? Say it in chat.
- **DECISIONS.md, one line per decision, timestamped.** No re-litigating.
- **Anyone can call "this is taking too long."** Cut scope, don't argue.

## Saturday checkpoints (non-negotiable)
- **~17:00 tech checkpoint** — spine works end-to-end by then. Rough is fine.
- **Backup demo video recorded Saturday night.** Even if the live demo "will be fine."

## Demo / pitch
- **3 minutes is hard-capped.** Demo eats ≥60%. Slides are rails.
- **Name the buyer in slide 2.** ÖGIG, not "operators."

## Tech traps (Challenge 2)
- **Check the GeoJSON CRS before geomatching** (EPSG:4326 vs 31287). Wrong CRS = points in the wrong country.
- **Don't trust EXIF GPS blindly** — have a fallback (filename / manual upload / LLM hint).
- **No `pip install` on venue Wi-Fi.** Pre-install everything Thursday.

## Tech traps (Challenge 1)
- **Prefer weclapp over Odoo** if going C1 — partner sympathy (Wals Professional).
- **Respect access-level tiering** (L1–L4) — don't leak authority-only fields to a public scan.
