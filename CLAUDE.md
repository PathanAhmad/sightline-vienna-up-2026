# CLAUDE.md — hard rules

Open list. Add as we learn. Only things we **cannot** get wrong.

## Mindset
- **This is your project too.** Own the call. If you see a better path, take it — don't wait to be told.
- **Winning is the goal — not comfort, not familiarity.** The prize, the demo, and the contacts at ÖGIG / Wals Professional / Sustainista are what we're optimizing for. If the best path runs through a stack we've never touched, that's the path. We close the skill gap with teammates and Claude. No self-imposed limits because of what we shipped last project.
- **Don't infer preferences from partial signals.** A resume, a past stack, the language someone happened to use last week — none of that tells you what they'd pick for *this* problem. When in doubt, ask in one sentence. Don't decide for them.
- **Think the maze through before entering it, then move.** A wrong fork that costs 4 hours of backtracking is more expensive than 30 minutes of upfront research. Weigh the realistic options honestly — what breaks, what scales, what's reversible — then commit and go. Indecision burns hours; but research-shopping without committing is just indecision in a lab coat. Trigger for the upfront research: any choice that locks in a stack, an API, or a data shape for more than the next hour of work.
- **Talk simple. Talk concise.** If a teammate or judge asks what we're doing and you go blank — you don't understand it yet. Stop and re-explain it to yourself in one sentence. Then you can answer in one sentence.
- **No ego on cuts.** If your feature gets cut Saturday afternoon, it's because the demo wins. Same goes for everyone else's.

## Talking to us (Claude reads this)
- **Two teammates, both non-experts vibing this build.** Streamlit, SDKs, EXIF, geopandas, pyproject — none of it is in our muscle memory. Don't assume context that isn't there.
- **No jargon-bombs.** Every library name, acronym, or API concept gets a one-sentence plain-English definition the first time it appears in a conversation. Then keep going.
- **Check before pushing deeper.** Before the next install, config change, or rabbit hole, say in plain words what we'd be committing to and confirm that's the path we want.
- **"WTF" or "I'm confused" = full stop.** Don't paraphrase the same jargon with different jargon. Back up two steps. Ask what we already understand. Reset from there.
- **Choices come with plain-language tradeoffs.** When we need to decide, give 2–3 options with one-line tradeoffs a non-expert reads in 10 seconds. Not a technical menu.
- **Translation, not vocabulary.** If we ask "what is X" and the answer uses three more X's, you failed.

## Process
- **Git from minute zero. Push small and often.** Don't hoard commits waiting for "perfect." Merge conflicts are cheaper than lost work.
- **No silent pivots.** Changing approach? Say it in chat.
- **DECISIONS.md, one line per decision, timestamped.** No re-litigating.
- **[04_research_log.md](04_research_log.md) captures the *reasoning* behind a decision.** When we evaluate alternatives (libraries, model choices, architectures, approaches) and rule some out, log the comparison + the why. DECISIONS.md = the one-line verdict. 04_research_log.md = "we considered X and Y, picked Z because…". Trigger: any decision a teammate or judge might later ask "why did you pick that over X?" — if we'd freeze for 10 seconds answering it, that means it belongs in 04_research_log.md. Questions we can't answer yet park in the Open Questions sections of that file.
- **Anyone can call "this is taking too long."** Cut scope, don't argue.

## Code
- **One thing at a time.** Build the smallest working slice, log it, verify it, then add the next. No "I'll wire it all up and debug at the end."
- **Separate concerns by file/function.** Ingest, transform, match, output — each in its own function with a clear input/output. No 200-line do-everything scripts.
- **Pipeline stages = named + human-logged.** Each stage prints what it did in plain English (`[geomatch] 47/52 matched, 5 unmatched → unmatched.json`). One-off scripts exempt.
- **Research before coding unfamiliar tech.** Triggers: new library, version-sensitive API, CRS/EPSG, GeoJSON, EXIF, weclapp/Odoo. Use context7 for library docs; web search otherwise. 30s of reading beats 2h of debugging.

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
