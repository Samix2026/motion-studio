# templates/tech-news-ar

Technical foundation for standard Arabic technology videos: **1920×1080 (16:9)**,
30 fps, Alexandria, RTL, silent by default, `@your_handle` in the chrome.

It supplies typography, spacing, safe zones, the timeline structure, motion
primitives, chrome and brand handling. It does **not** supply the visual concept:
what the viewer sees in each scene is designed per subject
(`../../VIDEO_WORKFLOW.md` §Visual-first rule).

## Use it

```bash
mkdir -p videos && npx hyperframes@0.8.35 init videos/<slug> \
  --non-interactive --example=blank --skill=motion-graphics --resolution=landscape
T=templates/tech-news-ar
cp $T/starter/standard.html videos/<slug>/index.html
cp $T/script.md $T/storyboard.md $T/sources.md videos/<slug>/
mkdir -p videos/<slug>/assets/fonts videos/<slug>/tools
cp $T/tools/check-tashkeel.py videos/<slug>/tools/
cp -R $T/lib videos/<slug>/lib
cp $T/assets/fonts/* videos/<slug>/assets/fonts/
```

**9:16 only on explicit request:** `--resolution=portrait`, copy `index.html`
(the portrait starter) instead of `starter/standard.html`, and set
`"format": "portrait"` in `meta.json`. Without that declaration the pipeline
expects 1920×1080 and fails a portrait composition.

Then, in the copied project:
1. **Select a brand profile** (see below) and apply its tokens.
2. `storyboard.md` — record the source assets, then SEE / DOES / READ per beat.
3. `script.md`, `sources.md` — the captions and the provenance.
4. `index.html` — build each scene from its SEE / DOES / READ, replacing the
   placeholder scene; give every scene `data-visual`.
5. `assets/` — official media from the primary source, per `ASSET_POLICY.md`.

`examples/grammar-demo-{landscape,portrait}/` show the optional scene grammars;
they are references, not starters.

You never edit the template itself in place; copy it per project.

## Brand profile

When the story is mainly about one company, select that company's profile from
`brands/` and apply its visual tokens. Rules and confidence levels are in
`brands/README.md`. If no supported company is detected (or several are equally
central), use `generic`.

```bash
python3 ../templates/tech-news-ar/tools/apply-brand.py \
  ../templates/tech-news-ar/brands/<id>.json index.html
```

This replaces the `/* brand:start … brand:end */` CSS custom-property block in
`index.html` and writes `"brand"` / `"brandCompany"` into `meta.json`. The
typography scale, safe zones, timeline, footer, and all Arabic rules stay
unchanged. A profile's `identity` block (palette, shapes, motifs, surface,
motion — `brands/README.md`) is meant to reach the scene content, not only the
chrome; a brand never changes the wording or the editorial tone.

## Audio (only when requested)

Videos are **silent by default** (`../../AUDIO_DESIGN.md` §0): the storyboard
keeps `Audio cue: none` and the render has 0 audio streams. The steps below apply
only when the brief requests audio.

- Plan one **Audio cue** block per storyboard beat (type, trigger, timestamp,
  duration, purpose, intensity, source).
- Source only licensed audio; track every external file in `sources.md`
  (`ASSET_POLICY.md`). If licensing is unclear, use no music.
- Put files under `assets/audio/sfx/`, `assets/audio/music/`,
  `assets/audio/ambient/`.
- Wire cues with standard HyperFrames `<audio>` elements and GSAP `volume`
  tweens; use FFmpeg for the final mix (AAC, 48 kHz, no clipping, `-shortest`).

## Files
- `starter/standard.html` — the standard 1920×1080 starter: foundation only.
  It is a source file, not a project: copy it to `videos/<slug>/index.html`
  next to `lib/` and `assets/fonts/` (it lives in `starter/` so this directory
  keeps a single root composition). It holds the bundled font, type scale,
  chrome, `--brand-*` tokens and a single paused GSAP timeline, with one
  placeholder scene.
- `index.html` — the portrait (1080×1920) starter, for explicit 9:16 requests.
- `lib/type.css` + `lib/type-scale.json` — typography system (per-format scale,
  safe zones, frame-0 rule).
- `lib/grammars.json` + `lib/grammar.css` + `lib/motion.js` — 8 optional scene grammars,
  10 motions, 6 screenshot-choreography treatments.
- `assets/fonts/` — Alexandria (variable, Arabic + Latin subsets) + `OFL-Alexandria.txt` (SIL OFL 1.1). Required family; enforced by `design/cli.py fonts` and the production build check.
- `examples/grammar-demo-{landscape,portrait}/` — validated demo compositions.
- `brands/` — JSON visual-identity profiles (`nvidia`, `anthropic`, `openai`,
  `google`, `microsoft`, `apple`, `xai`, `deepseek`, `meta`, `generic`) plus
  `README.md` with the selection rules.
- `script.md` / `storyboard.md` / `sources.md` — document templates.
- `components/` — paste-in snippets (topbar, footer, beat, media card, credit).
- `tools/check-tashkeel.py` — stdlib-only guard for the no-tashkeel rule.
- `tools/apply-brand.py` — stdlib-only JSON → CSS token applier.
- `assets/` — put official media here.
- `assets/audio/` — SFX / music / ambience, only when the brief requests audio (`../../AUDIO_DESIGN.md` §0).

## Validate before render
```bash
python3 tools/check-tashkeel.py .        # 0 marks expected
python3 ../../design/cli.py fonts . --render   # "status": "loaded"
python3 ../../design/cli.py validate .   # scene grammar: 0 errors
npx hyperframes@0.8.35 lint .                   # 0 errors / 0 warnings
npx hyperframes@0.8.35 check . --at 3,10,17,24,30 --snapshots
npx hyperframes@0.8.35 render . --skill=motion-graphics -q high -f 30 -o ./renders/video.mp4
# silent default: expect no output (0 audio streams; AUDIO_DESIGN.md §0)
ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 ./renders/video.mp4
# only if the brief requested audio: verify the stream and duration (AUDIO_DESIGN.md §8)
ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels -of default=noprint_wrappers=1 ./renders/video.mp4
```

Conventions: `../../VIDEO_WORKFLOW.md`, `../../CONTENT_RULES.md`,
`../../ASSET_POLICY.md`.
