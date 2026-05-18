# Behind the scenes — the technical side, in plain words

Companion to [HOW_IT_WORKS.md](HOW_IT_WORKS.md). That doc explains *what* the tool does. This one explains *how* it does it — the steps the photos go through, the tools we picked, the tradeoffs we made — written so a non-technical teammate can read it once before the pitch and answer the deeper questions without going blank.

---

## 1. The five stages your photo goes through

The whole tool is a chain of five steps. Each step reads the output of the one before it and adds something. Imagine an assembly line, with the photo on the conveyor belt.

**Stage 1 — Ingest.** We walk through the folder of photos and make a list. Each photo gets a unique ID computed from its bytes (so renaming the file doesn't lose it). At the same time we load the map file — the lines that show where every trench is supposed to run. Output: an index of every photo, plus the map data sitting in memory.

**Stage 2 — Forensics.** We give every photo a visual fingerprint (a short code that's identical for two photos that look the same, even after one has been resized or re-saved). Photos with matching fingerprints get grouped — that's how duplicates surface. We also do a light tampering test: re-save each photo at a known quality, compare it to the original, and look for regions that "stand out" in a way that suggests they were edited. Output: a fingerprint per photo + a tamper score.

**Stage 3 — Read.** For each *unique* photo (one per fingerprint group — we don't pay to look at the same image twice), we send it to **Claude** (the AI). Claude returns a structured answer: the six visual checks, what stage of work the photo shows, whether it's even relevant, plus everything printed on the photo — the date, the street address, the GPS coordinates if visible, and the paper label code held up in frame. One call per photo, costs about half a cent.

**Stage 4 — Map.** We figure out which stretch of trench each photo belongs to:
- If Claude read GPS coordinates off the photo, we drop a pin on the map at those coordinates and snap to the nearest trench line.
- If only a street address was visible, we look up the address's coordinates using a free public service called **Nominatim** (it's the same underlying database OpenStreetMap uses), then snap to the nearest trench within the right project zone.
- If neither, the photo goes in an "unmappable" bucket — listed in the report but not used for scoring.

**Stage 5 — Classify.** For each trench stretch, we gather every photo that landed on it, sort the photos along the length of the stretch, and walk from one end to the other looking for gaps. If the biggest gap between two compliant photos is under 5 meters, GREEN. If photos exist but gaps are bigger or some failed a check, YELLOW. If barely any photos, RED. The reason for the color is written out in plain English ("no compliant photo between meter 12 and meter 31").

The result of all five stages is a handful of files. The dashboard reads those files when you open it — no AI calls happen during the demo itself.

## 2. The tools we use (and why)

Short list on purpose. Every tool earns its place.

- **Claude Sonnet 4.6** — the AI that looks at the photo and answers the six visual checks. Made by Anthropic. We picked Sonnet over the cheaper Haiku version after testing both on five hard photos (night shots, occluded overlays, weird GPS formats). Sonnet won three, tied one, lost one — net better on the hardest cases. The price difference for our whole batch was $10 — worth it.
- **Perceptual hash** (`imagehash` library) — the visual-fingerprint method. Turns each photo into a 16-character code. Comparing 3,929 photos against each other takes a few seconds and costs nothing. This is how we find duplicates without an AI in the loop.
- **ELA — Error Level Analysis** (Pillow library) — the tampering check. Re-saves a photo at a known quality and looks at where the new version differs from the original. Edited regions stand out. It's a hint, not proof — we surface it but don't auto-fail on it.
- **Nominatim** — the address-to-coordinates lookup. Free and public, run by the OpenStreetMap project. We use it as a fallback when the photo only shows a street address, not GPS coordinates.
- **GeoPandas** — the geometry math library. Answers "which trench line is this point closest to?", "is this point inside this zone?", "how long is this segment in meters?".
- **Streamlit** — the framework that lets us build a web page in Python. The whole tool is one Python program. No separate backend, no database, no servers.
- **Folium** — the library that draws the interactive map (with the colored trench segments and clickable detail).

That's the whole stack. Notably absent: no GPU, no custom-trained model, no cloud database, no Kubernetes. Runs on a laptop.

## 3. The numbers

- **Total photos** in the pilot: 3,929
- **Unique photos** after duplicate detection: about 3,400
- **AI cost** per photo: about half a cent ($0.0045)
- **AI cost** for the whole project: about $15
- **End-to-end runtime** on a laptop: under 30 minutes
- **Trench stretches** scored: 2,983
- **Project zones**: 9
- **Languages** the AI handles on the photo overlays: German, English, Russian (Cyrillic + transliterated), mixed within a single photo
- **GPS formats** the AI handles: four (degrees-with-dots, degrees-with-commas-for-the-decimal which is the German locale, plain decimal, labeled decimal)
- **Manual baseline** for the same review: 3–5 days per project zone. Nine zones is roughly a month of full-time human work per project.

To scale this to an operator's full 424,000-photo backlog: same code, more time. Roughly **$1,900** in AI fees and **a few days** of laptop time. No re-engineering needed.

## 4. The tricky problems and how we got past them

Worth knowing because a judge might dig into any of these.

**No GPS in the photo files.** We sampled 50 random photos — zero had any hidden GPS data. WhatsApp strips it on upload. So the location *must* come from text printed on the photo. That's why we needed a vision-capable AI rather than a simpler text extractor — the printed overlays are too inconsistent for a rule-based reader.

**The printed overlays are wildly inconsistent.** Different camera apps print text in different corners. The GPS coordinates appear in four formats. The language switches between German, English, and Russian — sometimes on the same field. A traditional text-pattern reader would silently miss a meaningful fraction. The AI handles all the variation in one shot.

**The project zones don't tile cleanly.** The zones (called FCPs in the data) are supposed to cover the whole site, but in reality they leave 19% of the project area uncovered and spill 22% outside. So we can't only ask "is this point inside zone X?" — we also have to ask "which zone is this point closest to?" as a fallback.

**Same-street address mismatch is normal, not fraud.** Photos sometimes show one street number (where the photographer is standing) while a paper label in frame shows a different number on the same street (the property being connected to the grid). That's expected, not suspicious. We only flag mismatches when the streets are *different* AND the points are over 150 meters apart.

**Privacy in a screen-recorded demo.** A photo flagged as containing a face can't be displayed on a page that's being projected at the audience. The fix: when the dashboard shows a flagged photo, it swaps the image for a small privacy-notice card instead. The flag still counts in the saved report files; only the on-screen image is hidden.

**The AI could be wrong, and we measure it.** The dataset came with 219 photos hand-tagged as either "depth-measurement-primary" or "duct-laying-primary." After our AI runs, we compare its guesses against those known labels and report the agreement rate. That's a pitchable accuracy number, not just "trust us."

## 5. What runs where

- **The AI calls happen on Anthropic's servers** (where Claude lives). We send each photo's bytes over the internet, get back a structured answer. We do not send the project's route alignment data — only individual photos. The NDA in the brief is specifically about route data, not photos.
- **Everything else runs on the laptop.** No servers we operate, no cloud database, no Kubernetes. The whole tool is one Python program plus a few output files.
- **The demo is pre-computed.** When we open the dashboard during the pitch, no AI calls happen — it just reads the files we generated the night before. Faster, and no risk of a network hiccup mid-pitch.
- **The operator upload page is the only live AI surface.** When a contractor drops a fresh photo there, that one *does* call Claude in real time — the whole point is to catch problems while the trench is still open. A 5-second wait is fine for that use case.

## 6. The questions a judge is most likely to ask

> **"What AI are you using?"**
> Claude Sonnet 4.6, made by Anthropic — same family as ChatGPT, different company. It's a vision-capable AI, meaning it can look at images, not just read text. We picked the Sonnet version over the cheaper Haiku version after head-to-head testing on hard photos.

> **"How does it know where a photo was taken without GPS metadata?"**
> The contractors' camera apps stamp the date, street address, and GPS coordinates onto the photo as visible text. The AI reads that text. About 70% of photos have all three; the rest have at least an address.

> **"Could the AI get it wrong?"**
> Yes, and we measure it. The dataset includes 219 photos pre-labeled by a human. We compare the AI's answers against those known labels and report the agreement rate.

> **"Could a contractor fool the system?"**
> Two of the eight checks exist exactly for that. The duplicate-photo check catches reusing a good photo across multiple jobs. The GPS-vs-address check catches a photo taken at the wrong site. Both are *easier* to catch automatically than by hand — a human reviewer would have to remember every photo they'd ever seen.

> **"How would you scale to 424,000 photos?"**
> Same code, more time and money. Roughly $1,900 in AI fees, a few days of laptop time. Each photo is reviewed independently, so we can run many at once — no rewrite needed to scale up.

> **"Why not train your own model?"**
> Training a custom model on 30 hand-labeled photos per category would underperform the off-the-shelf AI by a wide margin, and it would have eaten the whole hackathon. The right tool for "is the orange tape visible?" is a vision-capable AI, not a custom-trained detector.

> **"Why a 5-meter threshold?"**
> That number comes from the industry reference we found in the dataset — the same target the partner's own quality-control deck uses. We didn't pick it; we adopted it.

> **"What's the privacy story?"**
> The AI flags any photo with a visible face or license plate. The dashboard hides those images on screen and routes them to a "needs retake" bucket. The flag stays in the audit trail so the contractor can be asked to re-shoot. We don't paint over faces inside the image — that would need a separate dedicated tool.

> **"What happens if the AI service goes down mid-demo?"**
> Nothing — the dashboard doesn't call the AI during the demo. All AI work was done the night before, and the dashboard just reads files from disk. The only live AI surface is the operator upload page, which is a separate tab.

---

If a question comes up that isn't covered here, the honest answer is always: "Good question — we didn't have time to solve that in 48 hours, here's the path we'd take." That beats making something up.
