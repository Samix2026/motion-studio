# templates/cinematic-saudi-documentary

Reusable starter for premium, visual-first Saudi documentary-style videos.
Landscape 1920×1080, restrained motion, one unified grade, Arabic
lower-third narration text, `@your_handle` credit.

**Status: productionized.** The template now ships a working reference
implementation (`starter/`), not only specifications. It was validated against
`videos/cinematic-saudi-documentary-pilot/` — an internal pilot (not included
in this repository) built from this template and rendered as `pilot-internal-rev2.mp4`. See §Validation below for
what that pilot proves and what it does not.

Inspired by pacing, visual hierarchy, restrained motion, and grading concept
of a reviewed reference video — never its text, shot sequence, logo, music,
or branding. See `TEMPLATE_RULES.md` §6.

## Validation

Validated (still-led pilot, PASS):
- still-led documentary videos
- mixed-source still photography
- Ken Burns motion
- cross-source grading (two-stage: per-shot correction + one global grade)
- restrained text/chrome
- documentary pacing

Not yet validated:
- motion-heavy footage
- stabilization workflow
- mixed still/video pacing
- footage-heavy sound design

The pilot itself is **INTERNAL / NOT FOR PUBLICATION** (see §Pilot below) and
must not be converted into publishable content. Its assets include an
unpurchased watermarked comp and CC BY-SA stills, so its validation is about
the template's systems, not its media clearance.

## Files

Specifications:
- `TEMPLATE_RULES.md` — asset standard, narrative rules, reference-video
  boundary, transition language, forbidden list, render gate.
- `VISUAL_SYSTEM.md` — brand-frame layout and safe zones at 1920×1080.
- `AUDIO_PROFILE.md` — music direction, SFX vocabulary, sourcing and mix rules
  (extends `../../AUDIO_DESIGN.md`, does not replace it).
- `COLOR_GRADE.md` — the two-stage color pipeline (Stage A per-shot
  correction, Stage B one global grade).
- `PRODUCTION_CHECKLIST.md` — the run sheet: asset gate, license verification,
  narrative map, shot map, color correction table, audio plan, contact sheet,
  lint/check/tashkeel, final review gate.
- `narrative-example.md` / `scene-map-example.md` — worked examples.
- `asset-checkpoint-template.md` — the asset-quality gate, copied per project.
- `components/*.md` — per-component specification and parameters.

Working implementation (copy these, do not re-derive them):
- `starter/` — a complete, lint/check-clean skeleton:
  - `starter/index.html` — four scenes wiring every component end to end;
  - `starter/components/color-grade.css` — Stage B (one grade on `#root`);
  - `starter/components/cinematic-frame.css` — full-bleed frame + Stage A
    per-shot correction;
  - `starter/components/brand-frame.css` — logo slot, bottom line, lower
    third, section title, source credit, handle;
  - `starter/components/ken-burns.js` — `CinKB` push-in / pull-out / lateral /
    parallax, parameterized per shot, clamped to the 3–6% band;
  - `starter/components/transitions.js` — `CinTransitions` hard cut / short
    dissolve / sound-led + closing fade;
  - `starter/lib/` — `motion.js`, `type.css`, `type-scale.json`, byte-identical
    to `../tech-news-ar/lib/`;
  - `starter/assets/fonts/` — IBM Plex Sans Arabic (SIL OFL 1.1) + `OFL.txt`;
  - `starter/assets/media/` — self-authored placeholder SVGs (not production
    assets);
  - `starter/tools/check-tashkeel.py`, `starter/hyperframes.json`,
    `starter/package.json` (hyperframes pinned).

## Use it

Copy the working skeleton, then plan against the specifications:

```bash
mkdir -p videos
cp -R templates/cinematic-saudi-documentary/starter videos/<slug>
cp templates/cinematic-saudi-documentary/asset-checkpoint-template.md \
   videos/<slug>/asset-checkpoint.md
```

Then, in order:
1. Fill `asset-checkpoint.md` (`TEMPLATE_RULES.md` §1). Fewer than 8 passing,
   or the story's beats not covered → stop, do not continue. Do not pad past
   what the story needs.
2. Write `narrative.md` (`TEMPLATE_RULES.md` §2, pattern in
   `narrative-example.md`).
3. Build the scene map from the narrative (`scene-map-example.md`), including
   the per-shot Stage A column.
4. Replace `starter/`'s placeholder scenes and media with the real scene map
   and checkpoint-passing assets. Keep the grade wrapper on `#root`, keep all
   Ken Burns moves inside 3–6%, and mark intended overscan with
   `data-layout-allow-overflow`.
5. Keep the video silent (`../../AUDIO_DESIGN.md` §0); plan audio per
   `AUDIO_PROFILE.md` only if the brief requests it.
6. Run `PRODUCTION_CHECKLIST.md` top to bottom.

Do not edit `starter/` in place for a project — copy it, then edit the copy.
Where this template is silent, defer to `../../VIDEO_WORKFLOW.md`,
`../../CONTENT_RULES.md`, `../../ASSET_POLICY.md`, `../../AUDIO_DESIGN.md`.

## Pilot

`videos/cinematic-saudi-documentary-pilot/` is the internal validation pilot
that exercised these systems (`meta.json`: `internalPilot: true`,
`notForPublication: true`). It is retained as evidence for the template and
must not be published, cleared, or converted into publishable content.

## Conventions

`../../VIDEO_WORKFLOW.md`, `../../CONTENT_RULES.md`, `../../ASSET_POLICY.md`,
`../../AUDIO_DESIGN.md` all still apply — this template narrows and adds to
them for the documentary format, it does not replace them.
