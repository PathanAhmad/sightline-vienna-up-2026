# CLAUDE.md — hard rules

Open list. Add as we learn. Only things we **cannot** get wrong.

## Mindset
- **This is your project too.** Own the call. If you see a better path, take it — don't wait to be told.
- **Winning is the goal — not comfort, not familiarity.** The prize, the demo, and the contacts at APG / Sustainista / fellow hackers are what we're optimizing for. If the best path runs through a stack we've never touched, that's the path. We close the skill gap with teammates and Claude. No self-imposed limits because of what we shipped last project.
- **Don't infer preferences from partial signals.** A resume, a past stack, the language someone happened to use last week — none of that tells you what they'd pick for *this* problem. When in doubt, ask in one sentence. Don't decide for them.
- **Think the maze through before entering it, then move.** A wrong fork that costs 4 hours of backtracking is more expensive than 30 minutes of upfront research. Weigh the realistic options honestly — what breaks, what scales, what's reversible — then commit and go. Indecision burns hours; but research-shopping without committing is just indecision in a lab coat. Trigger for the upfront research: any choice that locks in a stack, an API, or a data shape for more than the next hour of work.
- **Talk simple. Talk concise.** If a teammate or judge asks what we're doing and you go blank — you don't understand it yet. Stop and re-explain it to yourself in one sentence. Then you can answer in one sentence.
- **No ego on cuts.** If your feature gets cut Saturday afternoon, it's because the demo wins. Same goes for everyone else's.

## Talking to us (Claude reads this)
- **Two teammates, both non-experts vibing this build.** Streamlit, SDKs, OCR, geopandas, pyproject — none of it is in our muscle memory. Don't assume context that isn't there.
- **No jargon-bombs.** Every library name, acronym, or API concept gets a one-sentence plain-English definition the first time it appears in a conversation. Then keep going.
- **Check before pushing deeper.** Before the next install, config change, or rabbit hole, say in plain words what we'd be committing to and confirm that's the path we want.
- **"WTF" or "I'm confused" = full stop.** Don't paraphrase the same jargon with different jargon. Back up two steps. Ask what we already understand. Reset from there.
- **Choices come with plain-language tradeoffs.** When we need to decide, give 2–3 options with one-line tradeoffs a non-expert reads in 10 seconds. Not a technical menu.
- **Translation, not vocabulary.** If we ask "what is X" and the answer uses three more X's, you failed.

## Process
- **Git from minute zero. Push small and often.** Don't hoard commits waiting for "perfect." Merge conflicts are cheaper than lost work.
- **Agent-review every commit before pushing.** After `git commit`, run an agent review on the diff (`/review`, or spawn a subagent with the commit's diff as context). Fix issues in a follow-up commit (no amend). Push only once the review comes back clean. No exceptions — even small commits.
- **No silent pivots.** Changing approach? Say it in chat.
- **DECISIONS.md, one line per decision, timestamped.** No re-litigating. Reasoning lives in commit messages or chat — no separate research log under sprint pressure.
- **Anyone can call "this is taking too long."** Cut scope, don't argue.

## Code
- **One thing at a time.** Build the smallest working slice, log it, verify it, then add the next. No "I'll wire it all up and debug at the end."
- **Separate concerns by file/function.** Ingest, OCR, QC, geomatch, classify, report — each in its own function with a clear input/output. No 200-line do-everything scripts.
- **Pipeline stages = named + human-logged.** Each stage prints what it did in plain English (`[geomatch] 47/52 matched, 5 unmatched → unmatched.json`). One-off scripts exempt.
- **Research before coding unfamiliar tech.** Triggers: new library, version-sensitive API, CRS/EPSG, GeoJSON, Claude vision schema, OCR. Use context7 for library docs; web search otherwise. 30s of reading beats 2h of debugging.
- **Skip flake8 for this project.** Don't run it, don't report violations, don't rewrap to satisfy E501. Long CSS blocks, regex tables, and natural-language LLM system prompts trip the 79-char rule constantly and rewrapping them just makes them harder to read on a deadline. This overrides the global "all Python must pass flake8" rule. mypy --strict still applies where it's not already noisy from missing stubs.

## Saturday checkpoints (non-negotiable)
- **~17:00 tech checkpoint** — spine works end-to-end by then. Rough is fine.
- **Backup demo video recorded Saturday night.** Even if the live demo "will be fine."

## Demo / pitch
- **3 minutes is hard-capped.** Demo eats ≥60%. Slides are rails.
- **Lead with the product, not a named buyer.** Slide 2 names **Sightline** and the operator pain. (Older rule said "name APG"; rebranded 2026-05-17 — see DECISIONS.md.)

## Tech traps (Challenge 2, post-data-drop 2026-05-15 PM)
- **EXIF GPS is empty.** WhatsApp-style filenames in the dataset have all metadata stripped. Geomatch via overlay-OCR (street address printed on every photo) + paper-label FCP code (e.g. `F170-R084-11-or`), not EXIF.
- **CRS is WGS84 / EPSG:4326.** No Lambert 31287 reprojection needed for this dataset.
- **Operator trench-depth spec is unknown.** Don't hard-code a number until Martin gives one. The depth check is "is a depth reference visible / readable" — no threshold.
- **NDA on route data.** Don't paste `Resources/` contents into pastebins, public tools, third-party services, or screenshots that leak street-level paths. The brief flags this explicitly.
- **No `pip install` on venue Wi-Fi.** Use `uv sync` against a pre-warmed lock file.

## UI / design (Sightline app)

When adding components or fixing layout bugs in [`src/ui/`](src/ui/), preserve the established visual language — don't redesign as a side effect of bug-fix work:

- **Linear/Vercel-style clean look.** Single accent color (`--c-accent`, sky-700 blue). The green/yellow/red palette is reserved strictly for verdict semantics — never for chrome.
- **4pt spacing grid.** Use `--s-1` through `--s-8` from [`src/ui/tokens.py`](src/ui/tokens.py); don't invent new spacing values.
- **Numbered card eyebrows** (`01 · BATCH DETAILS`) + small-caps `.section-head` labels.
- **Subtle card chrome:** `--shadow-card` (layered ring + soft drop), `--r-md` radius, hairline borders.
- **Tabular numbers** for stats; tight negative letter-spacing on big numerals.

Confirmed user preference 2026-05-16: *"I actually like the colour choice, design style etc. Feels clean and professional with breathing room."* If a redesign is genuinely needed, that's a separate conversation — not a bug fix.

## Pitch / slide writing

When writing slide body copy, decks, or supporting text for the pitch / portfolio:

- **Sharp ≠ cryptic.** Each line should make sense to a first-time viewer who has never seen the product. If a sentence only lands after seeing the dashboard, replace it.
- **Slides scaffold the speech, they don't replicate it.** Short fragments, key numbers, single-clause statements. The speaker brings depth and tone. If the slide reads like prose, the speaker has nothing left.
- **The hook quote is the one exception** — pure punchiness wins there, because the speaker can land it cold.
- **Match language to the actual occasion.** Don't borrow stock CTA cliches without checking dates and context (e.g., "Friday you see the map" doesn't work for a Sunday final).

Origin: 2026-05-17 Sightline slide-3 rewrite — verb-headlines were fine, but bullets like *"Pinned to the meter — not the project, not the day. The meter."* read as abstract noise to a first-time viewer.

## Project mode (post-hackathon, as of 2026-05-18)

The Vienna UP 2026 hackathon ended Sunday 2026-05-17. The repo is now being polished as a portfolio piece, not extended with new features. Implications:

- **The Saturday-checkpoints / push-small-and-often / 17:00-spine rules above are historical.** The sprint pressure is gone — apply the rest of CLAUDE.md with that lens.
- **Bias toward presentation quality, not new scope.** A passerby (hiring manager, fellow hacker) lands on the repo cold; README, docs, code clarity, and demo polish are what they see first.
- **Don't expand surface area.** New features are out of scope unless they materially improve the portfolio story. Refactors, doc cleanup, and polish are in scope.
