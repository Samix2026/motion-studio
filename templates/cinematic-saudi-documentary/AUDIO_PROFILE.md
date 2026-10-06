# AUDIO_PROFILE.md — sound direction for the documentary template

Extends `../../AUDIO_DESIGN.md`. That file owns the mechanism (HyperFrames
`<audio>` pattern, GSAP volume tweens, FFmpeg final mix, levels table,
quality checks) — this file only narrows the **direction** for this
template. Read both; this one does not repeat the mechanism.

**Applies only when the brief requests audio.** Videos are silent by default
(`../../AUDIO_DESIGN.md` §0); a silent documentary uses `type: none` in every
scene-map row and no sound-led transitions.

## Music direction

- Cinematic, emotional, national/documentary tone — restrained, not a
  trailer score.
- **No copyrighted patriotic melody unless licensed.** Never use a national
  anthem excerpt or a recognizable patriotic composition without a
  confirmed license recorded in `sources.md`.
- No synthetic/low-quality music (thin MIDI-sounding beds, generic
  "corporate uplift" loops). If nothing licensed and high-quality is
  available, use no music — same fallback rule as `../../AUDIO_DESIGN.md`
  §4.
- One bed for the whole piece is preferred over stitching multiple tracks;
  duck it under narration-carrying lower thirds and sound-led transitions.

## SFX — light and contextual only

Allowed vocabulary for this template (a narrowing of
`../../AUDIO_DESIGN.md` §2's general table):

| Cue | Use |
|-----|-----|
| Whoosh | sound-led transitions only (`TEMPLATE_RULES.md` §5) |
| Cloth | garment/thobe/ghutra movement, close on a person |
| Flag | flag movement in wind, only when a flag is in frame |
| Footsteps | a walking beat, matched to visible steps |
| Ambient city | one establishing city beat, not stacked across scenes |
| Crowd | a gathering/market/crowd beat, low and textural |
| Heritage / craft | a craft sound (weaving, pottery, coffee pouring) matched to a visible action |
| Low impact | a soft landing on a hard cut at a narrative pivot, not a trailer boom |

- Every cue needs a visible trigger (`../../AUDIO_DESIGN.md` §1) — no cue
  without a reason.
- **Do not overuse SFX.** Prefer silence over an unjustified cue. A 35–45s
  cut typically carries 3–6 SFX cues total, not one per scene.
- No stacked/loud/trailer effects; see `../../AUDIO_DESIGN.md` §3.

## Sourcing and mix

- Sourcing priority, license rules, and the free-tier ElevenLabs Music
  restriction are exactly `../../AUDIO_DESIGN.md` §4a and
  `../../ASSET_POLICY.md` §Audio assets — no template-specific exception.
- Every external audio file is recorded in `sources.md` per
  `../../ASSET_POLICY.md`.
- Levels, ducking, HyperFrames `<audio>` wiring, and the FFmpeg final mix
  follow `../../AUDIO_DESIGN.md` §7–§9 unchanged.

## Storyboard integration

Each row of the scene map (`scene-map-example.md`) carries an **Audio cue**
block in the same shape as `../../AUDIO_DESIGN.md` §5, restricted to the
vocabulary above (or `type: none`).
