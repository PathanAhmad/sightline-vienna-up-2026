# Follow a photo through the pipeline

The previous two docs explain what the tool does and what it's made of. This one walks through what *actually happens* when you press the button — a single photo's journey from the contractor's phone to a colored line on the map.

We'll follow a concrete example. Imagine a contractor finishing a 30-meter stretch of trench. They've taken six photos on their phone: one of the open trench, two of the duct (cable bundle) being laid, one of the sand bedding, one of the orange warning tape, and a close-up of the paper label held against the camera. The camera app stamps the date, address, and GPS coordinates onto each photo as visible text. The contractor uploads all six to our tool.

Here's what happens, step by step.

---

## Stage 1 — Ingest: making the list

The tool walks through the folder where the photos landed and writes down what it found. For each photo:

- compute a **unique ID** for the file (a short code derived from the file's contents — change one pixel and the code changes; rename the file and the code stays the same)
- record the file's size and when it was created
- save it all into a small **index file** (a single file that works like a spreadsheet for the computer)

At the same time, the tool loads the **trench map** — the official list of every trench segment on the project — into memory. There are 2,983 segments across 9 zones. This is the "where could each photo possibly belong?" reference.

What you'd see on screen at the end of this stage: `[ingest] indexed 6 photos, loaded 2,983 trench segments`.

Nothing has been *judged* yet. The tool just knows what's there.

## Stage 2 — Forensics: visual fingerprints

Now the tool opens each photo and computes a **visual fingerprint** — a 16-character code derived from what the picture looks like, not what bytes it's made of. The key trick:

- Two photos that *look* the same get the same fingerprint, even if one was resized, recompressed, or re-saved.
- Two photos that look different get very different fingerprints.

The tool compares all 6 fingerprints against each other. For our contractor today: all 6 are different — no duplicates. (When this stage ran on the full pilot of 3,929 photos, it found about 600 reused photos this way — contractors submitting the same shot to multiple jobs.)

The tool also runs a light **tampering check** on each photo: re-save it at a known quality, then compare the re-saved copy to the original and look for regions that stand out as different. Edited regions usually show up as bright patches. Today: nothing suspicious.

On-screen line: `[forensics] 6 photos, 6 unique, 0 tamper-flagged`.

## Stage 3 — Read: asking Claude

This is the only step where the AI is involved.

For each unique photo (all 6 today), the tool opens it and sends it to **Claude's servers** along with a request that reads roughly like this:

> "Look at this photo. In a structured form, tell me:
> - Is the orange warning tape visible? yes / no / unclear
> - Is sand visible underneath the cable? yes / no / unclear
> - Is this a side view of the trench? yes / no
> - Is a depth-measurement reference (ruler, rod) visible? yes / no
> - Are the cable ends sealed? yes / no / unclear / not applicable
> - Are people's faces or license plates visible? yes / no
> - What stage of work does this show? (just-dug? duct laid? sand bedded? warning tape on? backfilled? a paper label close-up? staging? something else?)
> - Is this photo even relevant for compliance review? (scorable, portrait, off-topic, unreadable)
> - What date is printed on the photo?
> - What address is printed?
> - What GPS coordinates are printed (if any)?
> - What paper-label code is in frame (if any, like `F170-R084-11-or`)?
> - One free-text note explaining anything odd."

Claude looks at the photo and answers. We get back a **structured response** — basically a small filled-in form — that the tool reads and stores.

For our contractor's six photos, Claude might come back with answers like:

- *Photo 1* (open trench): stage = `excavation`. Side view = yes. Sand = no (correct — none has been poured yet). Tape = no. Address printed. GPS printed. No personal data. Relevant.
- *Photo 2 & 3* (duct laid): stage = `duct_laid`. Duct visible = yes. Ends sealed = yes. Side view = yes. Address + GPS printed. Relevant.
- *Photo 4* (sand poured): stage = `sand_bedded`. Sand = yes. Address + GPS printed. Relevant.
- *Photo 5* (orange tape on): stage = `tape_laid`. Tape = yes. Address + GPS printed. Relevant.
- *Photo 6* (paper label close-up): stage = `paper_label`. Paper-label code read out as `F170-R084-11-or`. Address visible. No GPS in frame. Relevance = scorable but won't be used to fill a gap in the segment — it's documentation, not a compliance photo.

This step costs about half a cent per photo. For the full pilot of 3,929 photos, the bill is about $15.

On-screen line: `[readqc] 6 photos scored, 0 parse failures`.

## Stage 4 — Map: pinning each photo to a trench segment

Now we know what each photo *shows*. We need to know *where* each photo was taken.

For each photo, the tool follows a small decision tree (a short checklist of if-this-then-that questions):

1. **Did Claude read GPS coordinates off the photo overlay?** If yes — drop a pin at those coordinates, find the closest trench segment on the map, snap the photo to that segment, and note the position along the segment (e.g. "4 meters from the start of a 30-meter segment").
2. **No GPS but an address was visible?** Look up that address using **Nominatim** (a free address-to-coordinates service run by the OpenStreetMap project), then snap to the nearest trench segment within the right project zone.
3. **Neither?** Photo goes in an "unmappable" bucket — listed in the report but not used for scoring.

For our six photos: photos 1–5 had GPS, all five snapped to the same trench segment at positions 4m, 9m, 14m, 19m, and 24m. Photo 6 (the paper label) had no GPS but did have an address — geocoded, snapped to the same segment.

Two cross-checks run after the snap:

- **GPS vs address sanity check.** For any photo that had *both* GPS coordinates and an address, look up the address's coordinates and compare. If the two are more than 150 meters apart AND on different streets, flag the photo as suspicious. (Same-street disagreement is normal: the paper label is for the property being connected; the overlay shows where the photographer is standing.)
- **Paper-label sanity check.** If a paper-label code was read, check that its zone code (the `F170` part) and duct code (the `R084` part) match the zone and duct of the snapped segment. Mismatch → flag.

Today: no flags on any of the 6 photos.

On-screen line: `[geomatch] 6 photos snapped, 0 off-cluster, 0 mismatches`.

## Stage 5 — Classify: the verdict

For each trench segment, the tool now has:

- the list of photos pinned to that segment
- the position of each photo along the segment
- the per-photo check results from Claude
- the segment's total length

It walks along each segment from start to end and checks the **5-meter rule**:

- Is there a compliant photo within 5 meters of the start of the segment?
- For every pair of consecutive compliant photos, is the gap between them ≤ 5 meters?
- Is there a compliant photo within 5 meters of the end of the segment?

Only photos that *passed* all the relevant checks count as "compliant." A blurry photo, an unrelated selfie, or a photo flagged for personal data does not fill a gap.

For our 30-meter example segment with compliant photos at 4, 9, 14, 19, 24 meters:

- Start gap (0m → 4m) = 4 meters. OK.
- 4m → 9m = 5 meters. OK.
- 9m → 14m = 5 meters. OK.
- 14m → 19m = 5 meters. OK.
- 19m → 24m = 5 meters. OK.
- End gap (24m → 30m) = **6 meters. Not OK.**

**Verdict: YELLOW.** Reason written in plain English: *"last 6 meters of the segment uncovered."*

If the contractor takes one more photo near the 30m mark, the segment will turn GREEN. This is exactly what the operator upload page is for — surface the gap on site, while the trench is still open and easy to photograph.

On-screen line: `[classify] 1 segment processed, 0 green, 1 yellow, 0 red`.

## What lands on disk

When all five stages have run, the tool has produced a small set of output files. (`.csv` is a spreadsheet file you can open in Excel; `.jsonl` is similar but one record per line, used for the AI's structured answers.)

The headline reports a reviewer would actually look at:

- **verdicts.csv** — one row per trench segment: color, reason, photo count, length. This is what colors the map.
- **deficiency.csv** — only the yellow and red segments, with reasons. This is the report the reviewer hands to the contractor.
- **summary.html** — a one-page overview shown next to the live map (totals, counts, a short list of the worst segments).
- **personal_data.csv** — photos flagged for faces or plates, routed to the "retake" bucket.
- **not_classified.csv** — photos dropped by the relevance gate (selfies, lunch shots, etc.), kept for audit.

Plus the intermediate working files the earlier stages produced, kept on disk so the dashboard can show "why" without re-running anything:

- **manifest.sqlite** — the index of every photo file (output of Stage 1).
- **forensics.jsonl** — each photo's visual fingerprint and tamper score (Stage 2).
- **readqc.jsonl** — everything Claude returned, per photo (Stage 3).
- **geomatch.csv** — per photo: which segment it landed on, where along it, any flags raised (Stage 4).

The dashboard opens these files at startup. Nothing is recomputed when a reviewer clicks around — they're just looking at what the pipeline already produced.

## What happens differently in the failure paths

Same pipeline, different photos, different outcomes:

- **A photo flagged for personal data** (face or license plate). It still counts toward the segment's photo total, but the dashboard replaces the image on screen with a small privacy-notice card. It also goes into `personal_data.csv` as a "needs retake."
- **A duplicate.** The original gets credited to whichever segment it first snapped to. The duplicate inherits the original's check results and is logged with a `duplicate_of=...` tag — it doesn't double-count on either segment.
- **A photo that Claude marked as not relevant** (a selfie, a paper-only shot, a blurry mess). Dropped from the segment entirely. Listed in `not_classified.csv` with the reason. Doesn't hurt anyone's score.
- **A photo with GPS coordinates that point outside the project area.** Flagged in `geomatch.csv` as `off_cluster`. Listed in the report but not used to fill a gap.
- **A photo with no GPS and no readable address.** Goes in the unmappable bucket. Surfaces in the report as "can't place this — please re-shoot or label."

## The whole journey, in one paragraph

The tool indexes the photos, fingerprints them visually to spot reuse, sends each unique photo to Claude for a structured review, snaps each photo to the right trench segment using either printed GPS or a geocoded address, then walks each segment end-to-end checking that no gap between compliant photos exceeds 5 meters. Anything that fails a check shows up on a colored map with a one-sentence reason.

That's the pipeline.
