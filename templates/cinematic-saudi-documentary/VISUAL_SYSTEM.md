# VISUAL_SYSTEM.md — brand frame at 1920×1080

Implementation: `starter/components/brand-frame.css`.

The fixed visual system every scene sits inside. Elements never compete with
imagery — they sit in the chrome margins defined below, imagery stays full
bleed. Safe-zone numbers are the landscape row of `../../VIDEO_WORKFLOW.md`
§Safe zones, not new values.

## Layout

| Zone | Value | Notes |
|------|-------|-------|
| Chrome inset (logo slot / bottom line) | 56px | matches existing landscape chrome inset |
| Text-safe padding (top / side / bottom) | 150 / 120 / 130 | lower third and title never violate this |
| Full-bleed media | edge to edge; text band 150px from bottom, max 1180px wide | Ken Burns stills and footage fill the frame |
| Section title | centered, max 1600px | used sparingly — see `components/title.md` |

## Elements

1. **Logo slot** (top-right identity) — `components/logo-slot.md`. Small,
   quiet, present every scene. Never the subject's own logo unless the
   project is explicitly about that institution and the logo is sourced per
   `../../ASSET_POLICY.md`.
2. **Lower-third Arabic text area** — `components/lower-third.md`. Carries
   the narrative sentence for the current beat. RTL, safe inside the text
   band.
3. **Optional small section title** — `components/title.md`. Used only at
   structural pivots (e.g. entering "التحول" / transformation), not on every
   scene.
4. **Thin bottom accent line** — `components/bottom-line.md`. A single
   hairline, brand-colored, not a progress bar (this template is not
   beat-segmented like `tech-news-ar`'s footer progress).
5. **`@your_handle` footer option** and **source/credit area** —
   `components/source-credit.md`. Present whenever an asset needs credit;
   the handle is always present.

## RTL

- Never set `dir="rtl"` on `<html>`. Scope `direction: rtl` to each text
  container (`.lower-third`, `.title`), same rule as
  `../../CONTENT_RULES.md` §RTL / bidi.
- Start every Arabic line with an Arabic word; wrap inline Latin terms in
  `<span class="hl">` rather than reordering.

## Scaling

- Authored at 1920×1080. All chrome elements use `px` sized against that
  canvas and rely on HyperFrames' fixed-canvas render (no runtime viewport
  scaling to account for).
- Mobile readability: keep body/lower-third text at or above the landscape
  floor in `lib/type-scale.json` → `readability_policy` (copied from
  `../tech-news-ar/lib/`). Do not shrink chrome text below that floor for
  this template.
- Elements stay inside the text-safe padding at every breakpoint the
  template is delivered at; there is no separate mobile layout — HyperFrames
  renders a fixed frame, downstream players scale the whole frame.

## What this system does not do

No competing motion behind text (lower third and title enter with a simple
fade/slide per `components/lower-third.md`; the imagery underneath carries
the Ken Burns motion, not the chrome). No stacked chrome — at most one of
{title, lower-third} animates in at a time.
