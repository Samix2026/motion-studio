# TEMPLATE_RULES.md — Cinematic Saudi Documentary standard

Rules for every video produced from `templates/cinematic-saudi-documentary/`.
Extends `../../CONTENT_RULES.md` and `../../ASSET_POLICY.md`; where this file
is silent, those govern.

## 1. Asset standard

Every project requires **8–18 genuinely strong visual assets** before a
scene map is built. **Story determines the final count inside that range —
quality over quantity.** If the narrative only needs 9 excellent assets, do
not pad the cut with filler to reach a higher number.

**Accept:**
- High-quality cinematic footage.
- Strong archival/historical images.
- Official institutional footage.
- Licensed premium stock.
- High-resolution stills suitable for subtle Ken Burns motion (≥ 4K for a
  full-bleed still, so a 3–6% push still reads sharp).

**Reject:**
- Generic Gulf stock (desert/skyline shots with no specific subject).
- Weak framing (dead center, cluttered, unintentional negative space).
- Shaky, handheld-without-purpose, or low-bitrate footage.
- Repetitive city shots (more than one skyline/traffic beat in a cut).
- Low-resolution imagery (below delivery resolution after crop).
- Obvious filler — a shot with no narrative job.
- Visuals that need an on-screen caption to explain why they are Saudi. The
  image must carry its own context (a recognizable place, craft, dress,
  landscape, or institution).

**Gate:** before building any video, complete an **asset checkpoint**
(`asset-checkpoint-template.md`) recording, per asset: name, source, license,
resolution, type (video/still), Saudi authenticity, cinematic quality,
recommended duration, and why it earns a place in the cut.

**If there are not enough genuinely strong assets to tell the story (fewer
than 8 pass the checkpoint, or the narrative's beats aren't covered even
with more than 8): STOP. Do not build the video.** Go back to sourcing, not
to lowering the bar, and never add a passing-but-unneeded asset just to hit
a number.

## 2. Narrative system

Write `narrative.md`: **10–15 short Arabic sentences.**

- Simple Arabic (فصحى), short sentences — one idea per sentence.
- No long paragraphs.
- Each sentence corresponds to exactly one visual beat.
- The narrative progresses as a **story**, not a list of facts.
- No generic motivational language ("نحو مستقبل أفضل" and similar filler).
- No repetition — each sentence adds a new beat, never restates the last.
- No unsupported claims; only state what the chosen assets and known facts
  support.
- Follows `../../CONTENT_RULES.md` §Language and §Arabic tashkeel in full:
  no diacritics, MSA only, product/place names kept as officially written.

**Suggested flow:** past / roots → identity → people → transformation →
present → future → closing statement. See `narrative-example.md`.

Every sentence in `narrative.md` must map to: shot (which checkpoint asset),
timing (start–end), and visual purpose (what the image is doing for the
line — establishing, contrasting, humanizing, resolving). Put that mapping
in the scene map, not inline in the narrative file — keep `narrative.md`
readable as prose.

## 3. Reusable systems

Each of the following is built **once**, as a reusable preset/module/
component set, and referenced — not re-authored per scene:

- **Grade** — `COLOR_GRADE.md`. Applied once at the composition root.
- **Ken Burns** — `components/ken-burns-still.md`. One module, parameterized
  per still (direction, duration), never hand-authored per scene.
- **Audio profile** — `AUDIO_PROFILE.md`.
- **Brand frame** — `components/` (logo slot, title, lower third, bottom
  line, credit area).

Do not bake a one-off effect into a single scene when a reusable version
would serve every project made from this template.

The working implementations live in `starter/` and are copied per project
(`README.md` §Use it): `components/color-grade.css` (Stage B),
`components/cinematic-frame.css` (frame + Stage A),
`components/brand-frame.css` (logo slot, lower third, title, bottom line,
credit, handle), `components/ken-burns.js` (`CinKB`), and
`components/transitions.js` (`CinTransitions`). A project references them; it
does not re-author them.

Two visual constraints hold everywhere:

- **Imagery is dominant.** The image carries the frame; chrome lives only in
  the margins and never over the point of interest.
- **No card / dashboard look.** Full-bleed frames only — no rounded cards, no
  panels, no boxed media, no UI/dashboard composition.

## 4. Ken Burns rules

- Allowed: slow push-in, slow pull-out, subtle lateral movement, optional
  foreground/background parallax only when the asset genuinely has separable
  layers and the parallax reads as safe (no ghosting, no cropping error).
- Default movement: **3–6%** scale/translation change across the shot.
- No aggressive zoom, no face distortion, no fake 3D on architecture, no
  random direction changes mid-shot.
- Mark intended overscan — an image that deliberately extends past the safe
  frame so the move has headroom — with `data-layout-allow-overflow` on that
  element, so the layout check reads the overflow as intentional.
- Full parameters: `components/ken-burns-still.md`.

## 5. Transition language

Exactly **3 transition families**, no others:

1. **Hard cut** — the default between beats.
2. **Short dissolve** — used at a narrative pivot (e.g. past → present),
   ≤ 0.6s.
3. **Sound-led transition** — a whoosh or ambient swell carries the cut; the
   visual change can be a hard cut riding the sound. Only when the brief
   requests audio (`../../AUDIO_DESIGN.md` §0); a silent video uses 1–2 only.

No flashy transition packs, no wipes, no glitch/zoom-blur transitions.

## 6. Reference video boundary

The previously reviewed Saudi reference video is **stylistic inspiration
only**. Do not copy its text, its exact shot sequence, its logo, its music,
or reproduce its branding. Extract only: pacing logic, visual hierarchy,
restrained motion, narrative rhythm, and the unified-grading concept — the
same legal/design test as `../../ASSET_POLICY.md` §Brand logos: a reasonable
viewer must not mistake the output for a copy of that video.

## 7. Attribution

- `@your_handle` footer/credit area present per `components/source-credit.md`.
- Every archival/borrowed asset carries a source credit and a `sources.md`
  row, per `../../ASSET_POLICY.md`.

## 8. Forbidden

- Fewer than 8 checkpoint-passing assets, or a story whose beats aren't
  actually covered by what passed.
- Padding the cut with a passing-but-unneeded asset just to raise the count.
- AI-generated images (`../../ASSET_POLICY.md`).
- Unlicensed or unclear music; copyrighted patriotic melodies without a
  license.
- Synthetic/low-quality music beds.
- Heavy per-scene effects instead of the one reusable grade.
- Aggressive Ken Burns (> 6%, direction changes mid-shot, face distortion).
- More than the 3 defined transition families.
- Recoloring or altering the Saudi flag's colors in any asset or overlay.
- Rendering, downloading paid assets, or publishing before the Phase 1
  checkpoint (§10) is returned and accepted.

## 9. Quality bar

A cut is ready for the scene-map stage only when every checkpoint asset
passes §1, `narrative.md` passes §2, and the reusable systems in §3 are
defined (not just described). If any of these are missing, the answer is
"not yet," not a lowered bar.

## 10. Phase 1 return checkpoint

Before any render, return:

1. Template structure.
2. Asset quality rules.
3. Narrative framework.
4. Grade specification.
5. Ken Burns rules.
6. Audio system.
7. Brand-frame system.
8. Transition system.
9. A sample 35–45s scene map.
10. What is still missing before production.

Do not download paid assets, generate paid media, render a final video, or
publish until this checkpoint has been returned and accepted.

**Status:** this checkpoint was returned and accepted, and the template was
validated against `videos/cinematic-saudi-documentary-pilot/`
(`README.md` §Validation). The render gate is now the ordered run sheet in
`PRODUCTION_CHECKLIST.md` — in particular §1 (asset gate), §2 (license) and §8
(lint / check / tashkeel) before any render, and §9 (final review) before any
publish.
