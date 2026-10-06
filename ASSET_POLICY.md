# ASSET_POLICY.md — media sourcing, provenance, and licensing

Policy for all media used in Arabic tech-news videos. The goal is that every
external file can be traced to a primary source and a stated usage basis.

## Sourcing rules
1. **Prefer primary/official sources**: the company's own product pages, blog,
   newsroom, press kit, or documentation.
2. **No AI-generated images.**
3. **No stock photography, wikis, news aggregators, or third-party images.**
   Visual-inspiration references (Pinterest, Behance, Dribbble, …) are never
   assets (`VIDEO_WORKFLOW.md` §Visual inspiration).
4. Do not invent asset URLs. Only use URLs actually found on a fetched primary
   page, or an obvious official CDN variant of a discovered URL.
5. Prefer vector logos (SVG) and official product screenshots (WebP/PNG).
   Subject-asset discovery runs before the storyboard (`VIDEO_WORKFLOW.md`
   step 4): official product imagery, screenshots, diagrams, interface
   captures and model/product key art found in the primary source **may** be
   used, with an on-screen credit and a `sources.md` row, when they materially
   improve the story. If the source offers nothing useful, record
   `none usable` and build constructed visual objects.
6. Use the light/ivory logo variant on dark backgrounds; do not recolor logos
   to fit your palette.

## Download locally (determinism)
- Download every asset into the project's `assets/` directory. Never reference
  a remote URL at render time (render-time network fetches are non-deterministic
  and are rejected by the HyperFrames contract).
- Use a normal browser User-Agent and `curl -L`.
- Verify each download is a real image (`file <path>`) and reasonably sized
  (< 8 MB). Delete partial/failed downloads.
- Delete assets that end up unused so the provenance record stays honest.

## Asset organization
```
assets/
  <purpose>-<variant>.<ext>     # e.g. claude-logo-ivory.svg
```
- kebab-case, descriptive, no spaces, no opaque hashes.
- Keep the official logo/screenshot as downloaded; do not materially alter it.
  Cropping/zooming for layout is allowed (mark intentional overflow with
  `data-layout-allow-overflow`).
- Do not use an asset whose visible content contains fictional sample data
  (fake metrics, fake prices, placeholder analytics). Exclude it or crop until
  none of the fabricated data is visible.

## Provenance record — `sources.md`
Maintain one `sources.md` per project with three sections:

1. **Claim sources** — a table of every URL used to verify facts
   (`# | Description | URL | What it proves`).
2. **Assets used** — a table with columns:
   `file | type | origin path | direct asset URL | licensing/usage note`.
3. **Audio sources** — a table with columns:
   `file | source URL | creator/provider | license/usage | scene`.

Rules:
- Every file in `assets/` must appear in the asset table and vice versa.
  The bundled studio font (`assets/fonts/`, Alexandria, SIL OFL 1.1
  with `OFL-Alexandria.txt`) is recorded as one row. Only fonts with a verified
  redistributable license may be bundled; never copy system font files.
- Record the **source page URL** and the **direct asset URL** separately.
- Note dimensions and file type.

## Licensing / usage
- Press kits and product pages are provided for media/editorial use, but may
  not ship with an explicit license file. When no license text is served, state
  that plainly and mark usage as **editorial with attribution**, subject to the
  owner's brand guidelines.
- Always credit borrowed media on screen (`المصدر: <publisher>`) and in
  `sources.md`.
- Do not imply endorsement by the asset owner.
- If it is not clear that an asset may be used, prefer an official asset that
  is, or fall back to an asset-free composition.

## Brand logos and visual identity
- A brand profile (`brands/`) may allow an official logo in the topbar brand
  slot and/or the intro hero. Use the official asset only, from a primary
  source, per this policy.
- Never recreate, redraw, recolor, or approximate a logo, wordmark, or lockup.
- Never reproduce a whole campaign composition, a proprietary layout, or an
  exact marketing template. Showing a credited source image or key art inside
  your own scene is allowed; rebuilding the company's ad is not. Use the
  company's public identity (palette, shapes, motifs, surface) as
  **inspiration** for the scene content.
- Legal/design test: a reasonable viewer must not mistake the video for an
  official communication published by that company. When unsure, omit the logo
  and rely on typography.
- `@your_handle` and the source credit remain visible regardless of the
  selected brand profile.

## Audio assets
Audio (SFX, ambience, music) follows the same sourcing discipline as visual
media. See `AUDIO_DESIGN.md` for how audio is designed and mixed.

- **License required.** Use only audio that permits the intended use — CC0 /
  public domain, a royalty-free license with clear terms, or original audio you
  own. Do not include copyrighted audio without a clear license.
- **No copyrighted audio without a clear license.** When licensing is unclear,
  use no music rather than an unclear asset.
- **No AI-generated audio** unless the generator's terms permit the intended use
  and you own/are licensed for the output; record that basis in `sources.md`.
- **Track every external audio file** in `sources.md`: filename, source URL,
  creator/provider, license/usage status, and the scene where it is used.
- **Naming and format:** kebab-case and descriptive
  (`sfx/keyboard-typing.wav`, `music/low-tech-bed.mp3`); WAV for short SFX,
  MP3/AAC for beds; 48 kHz target for the final mix.
- **Normalize before mixing** and keep levels conservative —
  `AUDIO_DESIGN.md` §9.
- **Silent by default** (`AUDIO_DESIGN.md` §0). Audio assets are sourced only
  when the brief requests audio.
- **Sourcing priority** (`AUDIO_DESIGN.md` §4a): contextual **SFX** → prefer
  ElevenLabs Sound Effects for custom sounds (one request at a time); background
  **music** → prefer curated licensed tracks from trusted sources such as Pixabay
  or Mixkit. Do **not** use the ElevenLabs Music API while the account is on the
  free plan, and do not upgrade solely for music without repeated tests showing a
  clear quality advantage.
- **ElevenLabs-generated audio** is permitted under its terms; record the basis
  (prompt/model) plus the license/usage note in `sources.md`, like any other
  audio source.

## Asset-free fallback
When no usable primary asset exists, build the beat with typography and simple
original vector/CSS diagrams. This is always preferable to an unlicensed or
AI-generated image.

## `sources.md` template
See `templates/tech-news-ar/sources.md`.
