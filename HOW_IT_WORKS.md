# How it works — in plain words

A no-jargon explainer of what we built. If a word looks technical, we define it the first time. If something here still feels fuzzy, that's a bug in the writing — tell us and we'll fix it.

---

## 1. The problem we picked

A power-grid company (APG, the people who own Austria's high-voltage lines) hires contractors to dig long trenches and lay cable. To prove the work was done correctly, the contractors take photos at each stage — open trench, sand poured in, cable laid, warning tape on top, hole filled back up.

There are **a lot** of photos. APG has roughly **424,000** of them sitting in a folder. A human reviewer looks through them one by one to answer questions like:

- Is the cable actually sitting on sand, or just on dirt?
- Is the orange warning tape there, so the next person who digs here doesn't slice the cable?
- Is this photo actually from the site they say it's from?
- Wait — haven't I seen this exact photo before, attached to a different job?

A person doing this carefully needs **3–5 days per project section**. There are hundreds of sections. So in practice, the review either takes forever or gets skipped, and problems only surface years later when somebody else's excavator hits an undocumented cable.

## 2. What we built

A tool that does that review automatically and produces a colored map of the work site:

- **Green** stretch of trench → fully documented, no problems found.
- **Yellow** → some photos exist but something's off — gaps in coverage, or a check failed.
- **Red** → barely any photos, or no photos at all. A reviewer should look here first.

The user clicks any segment on the map and sees the actual photos, plus a plain-English list of what's wrong ("no compliant photo between meter 12 and meter 31 of this 47-meter stretch"; "this photo was already submitted on job #X").

For our pilot, we ran it on **3,929 photos** from a real fiber-trench project in Maria Rain, Carinthia. Total cost: about **$15** in AI fees. Total time: **under 30 minutes**.

## 3. The two screens

We built two separate web pages, because there are two different people in this story:

**Screen A — the operator upload page.**
A contractor on site finishes a stretch of trench, takes their photos, and drops them into our page. The tool reviews them on the spot and tells the contractor: "you're missing a sand-bedding photo for this section — go take one before you leave." This catches problems while the trench is still open and easy to fix. Live AI calls happen here.

**Screen B — the reviewer dashboard.**
An office reviewer at APG opens the dashboard and sees the colored map of the whole project. They click the red bits first, look at the evidence, and decide what to do. No live AI calls here — everything was pre-computed, so the page is fast.

Both screens are the same app — you just put `?view=upload` at the end of the web address to flip between them.

## 4. The eight things we check on every photo

We send each unique photo to **Claude** (the AI we use — same family of AI as ChatGPT but made by Anthropic). Claude looks at the photo and answers eight yes/no/unclear questions:

1. **Is the orange warning tape visible?** (The tape that tells a future digger "stop, cable below.")
2. **Is sand visible underneath the cable?** (Cables on bare dirt get damaged. Sand is the cushion.)
3. **Is this a side view of the trench?** (You can't judge depth from a top-down photo.)
4. **Is there a depth reference visible?** (A measuring rod or ruler in the frame, so you can actually see how deep the trench is.)
5. **Is the cable bundle visible, and are its ends sealed?** (Open cable ends let water in. White caps = sealed.)
6. **Are there any people's faces or license plates visible?** (European privacy law — we have to flag these.)
7. **What stage of the work is this photo from?** (Just-dug? Cable laid? Filled back in? We don't penalize a "cable laid" photo for missing the warning tape — the tape goes on later.)
8. **Is this photo even relevant?** (Sometimes contractors upload selfies, photos of paperwork, or pictures of their lunch. Those get filed under "not classified" and don't hurt anyone's score.)

Plus two checks Claude doesn't do — we handle them separately:

9. **Have we seen this exact photo before?** Computers can compare images very cheaply. We check every photo against every other photo and flag matches. (This caught about **600 duplicates** in our pilot dataset — photos a contractor had submitted to multiple jobs.)
10. **Does this photo come from where it says it comes from?** Most photos have the GPS coordinates and street address printed right on them (the contractors' camera apps stamp this in). We compare the two and flag anything where the GPS says one village and the address says another.

## 5. How a stretch of trench gets its color

The trench network is split into **2,983 short stretches** (a typical one is around 10–50 meters long). For each stretch, we:

1. **Figure out which photos belong here.** Each photo has GPS coordinates printed on it. We pin the photo to the nearest stretch of trench.
2. **Sort the photos along the stretch** — from one end to the other.
3. **Check the rule:** there should be one compliant photo every 5 meters. No bigger gap allowed.
4. **Assign a color:**
   - **GREEN** — photos every 5 meters or better, all of them pass the checks.
   - **YELLOW** — photos exist but there's a gap bigger than 5 meters, or some photo failed a check.
   - **RED** — almost no photos, or none at all.

A photo only counts toward the "every 5 meters" rule if it passed all the per-photo checks (sand visible, tape visible, etc., for whichever checks apply to its stage of work). A photo of a paper label, or a portrait of the contractor, doesn't fill the gap.

## 6. The catches the tool surfaces

These three are the "wow" moments — the kinds of things a human reviewer would miss because they don't have time:

- **Reused photos.** Someone took a nice photo of a well-laid cable once, and has been submitting it to every job for six months. The tool spots it because the photo's "fingerprint" matches one we've already seen. We catch the original, the copy, and which jobs each one was submitted to.
- **Wrong location.** Someone took a real photo, but the location it's tagged with is somewhere else (sometimes by accident, sometimes not). The tool catches it because the GPS coordinates and the printed address disagree, or because both of them land outside the project area entirely.
- **Privacy violations.** A worker's face or a car license plate is in the photo. European law (NIS2) says we have to handle these carefully. The tool flags them, hides the image in the on-screen grid (replaces it with a "GDPR notice" card), and puts them in a "needs retake" list.

## 7. What we deliberately don't do

We're being honest about scope, both to the team and on stage:

- **We don't measure trench depth in centimeters.** We only check whether a depth reference (a ruler) is visible in the photo. Setting a number would need APG's specific spec, which we don't have.
- **We don't do survey-grade GPS verification.** The full industry standard uses a survey instrument called "RTK GPS" — accurate to a centimeter or two. Our GPS is the kind that's printed on the photo, accurate to about 4 meters. We say this explicitly in the pitch: "We do the photo half of the check. Survey verification is a separate, future phase."
- **We don't censor faces inside the photo file.** We flag the photo, hide it from the screen, and route it to a "needs retake" list. Actually painting black boxes over faces would need a separate tool.

## 8. Why this approach (and not something else)

A few decisions worth knowing because judges may ask:

- **Why an AI that looks at the whole photo, instead of a traditional "find the orange thing" detector?** Because the photos vary enormously — different camera apps, different overlay positions, four languages on the printed text, GPS coordinates in four different formats. A traditional rule-based reader fails silently on every weird case. The AI handles all the variation in one shot.
- **Why pin each photo to a specific stretch of trench, instead of just a project zone?** Because the rule we're checking is "one photo every 5 meters." You can't check that without knowing where along the trench each photo was taken.
- **Why screen out copies before sending photos to the AI?** Because sending the same photo twice costs the same as sending two different photos. We dedupe first (cheap, runs on our laptop) and only pay the AI once per unique photo.

## 9. The numbers from our pilot

Run on the Maria Rain dataset that APG's partner gave us:

- **3,929 photos** ingested.
- **~600 duplicates** caught automatically (the dataset had hidden ground-truth markers we could check against).
- **~3,400 unique photos** sent to Claude for review.
- **2,983 trench stretches** scored green / yellow / red.
- **About $15** in AI costs.
- **Under 30 minutes** end-to-end.

For comparison, the equivalent manual review for this size of dataset would take a person 3–5 days for each major section. There are 9 major sections in this single project. APG's full backlog is roughly 100× this dataset.
