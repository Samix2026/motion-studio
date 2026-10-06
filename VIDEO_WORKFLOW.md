# VIDEO_WORKFLOW.md — Arabic tech-news videos with HyperFrames

Reusable production workflow for short Arabic technology-news motion graphics
(25–35s, **1920×1080 / 16:9 by default**, captions, no voiceover).

This is a **convention + technical foundation**, not a framework and not a set
of layouts to fill in. Everything uses standard HyperFrames HTML compositions
and GSAP timelines.

**Output format.** The standard is 1920×1080 (16:9). Build 9:16 (1080×1920) only
when the brief, the project config or the user explicitly asks for it, and then
declare it: `"format": "portrait"` in `meta.json`. The pipeline compares the
composition and the render against the declared format (default 1920×1080) and
never infers it from the composition; a mismatch is an ERROR.

Scope: standard videos — news, tool/feature explainers, product demos, case
studies, business analysis. Viewer-facing copy follows the writing guidance in
`CONTENT_RULES.md` §Writing quality.

## Read on demand

**Default reading for a standard video:** this file, `CONTENT_RULES.md`, and
`templates/tech-news-ar/README.md`. Nothing else is required. Open the rest only
when its trigger applies:

| When | Read |
|---|---|
| A gate blocks, or you want stills / critics / strict mode | `PRODUCTION.md` |
| The user supplies a visual reference, asks to reuse or promote a style, or opts out of the handle | `CONTEXT_SCOPE.md` |
| The brief requests audio (videos are silent by default: `Audio cue: none`, 0 audio streams) | `AUDIO_DESIGN.md`, `WORKFLOW_REFERENCE.md` §Audio design and mix |
| The brief requests narration / voice | `WORD_SYNC.md`, `WORKFLOW_REFERENCE.md` §Narration mode, §Word-level timing |
| Any paid generation | `COST_GATE.md`, `WORKFLOW_REFERENCE.md` §Cost gate |
| A reference video is supplied for pacing analysis | `REFERENCE_ANALYZER.md` |
| Downloading or crediting a subject asset or logo (step 4 always runs; this is the licensing and credit detail) | `ASSET_POLICY.md` |
| Platform exports, covers, post captions (`meta.json` → `outputs`) | `WORKFLOW_REFERENCE.md` §Platform outputs |
| Optional `meta.json` fields, run manifest, managed timing, review input integrity | `WORKFLOW_REFERENCE.md` |
| Automated review, proposals, the optional visual critic | `AI_REVIEW.md` |
| Scoring and the run record at run closure | `QUALITY_SCORE.md`, `RUN_METRICS.md` |
| After publishing: retention and cleanup | `WORKFLOW_REFERENCE.md` §Published project retention policy, `CLEANUP.md` |

## The only four inputs

For each new video you supply exactly:

1. **Source URLs** — primary/official sources that support every claim.
2. **Subject assets** — official/source visuals found in the primary source,
   downloaded into `assets/` (`sources.md`), or the record "none usable".
3. **Visual story** — what the viewer sees, per beat (`storyboard.md`).
4. **Script** — the minimum Arabic text that captions those visuals (`script.md`).

The technical foundation comes from `templates/tech-news-ar/`.

## Visual-first rule

**Text captions the visual. Text is not the visual.**

| Layer | Owns | Comes from |
|---|---|---|
| Foundation | typography, spacing, safe zones, technical structure, timeline, motion primitives, chrome | `templates/tech-news-ar/` (reused as is) |
| Visual concept | what the viewer sees in every scene | the subject, decided per video |
| Subject assets | official imagery, screenshots, diagrams, interface captures, product artwork | the primary source |
| Brand identity | palette, gradients, shapes, motifs, surface, motion character, logo | the brand profile, reaching scene content, not only chrome |

The foundation never decides the visual concept. Work in this order:

```
subject → visual concept → SEE / DOES / READ per beat → assets and objects → (optional) grammar → build
```

- At most **one** scene per standard video is intentionally text-only, normally
  the takeaway. A headline over a blank background is not a visual scene.
- Grammars (§Scene grammar) are optional layout helpers chosen **after** the
  visual concept. Custom scenes without a grammar are valid. Never map
  script beat → grammar → fill text.
- A new look is not required for its own sake; a clear subject-derived concept is.

## Project convention

- One project per video: `videos/<slug>/` (kebab-case, no timestamps).
- Standard HyperFrames layout: `index.html` is the root composition; media in
  `assets/`; renders in `renders/`.
- Never `hyperframes init` in the workspace root (it refuses non-empty dirs).
- Authoring skill is `motion-graphics` (short, unnarrated, motion-first).

```
videos/<slug>/
  index.html          # the composition (from starter/standard.html)
  hyperframes.json
  package.json        # pinned hyperframes@<version> scripts
  meta.json           # brand profile id; `"format": "portrait"` only for an explicit 9:16 request
  assets/             # subject assets from the primary source, downloaded locally
  assets/audio/       # only when the brief requests audio (AUDIO_DESIGN.md §0)
  renders/video.mp4   # final output
  snapshots/          # proof frames from check --snapshots
  BRIEF.md            # confirmed intent
  DESIGN.md           # design spec + project manifest (CONTEXT_SCOPE.md §5)
  storyboard.md       # source assets + visual story (SEE / DOES / READ per beat)
  script.md           # final Arabic captions
  sources.md          # claim + asset provenance
  visual_inspiration.md  # optional — only when a new direction is needed (§Visual inspiration)
```

## Context scope and brand (summary)

- **Global preferences persist** across projects: Arabic-first, Alexandria, no
  tashkeel, IBM Plex Mono for technical text, `@your_handle`.
- **Reusable foundation.** The technical foundation (typography, spacing, safe
  zones, timeline, motion primitives, chrome, brand handling) is reused for every
  video (`composition_language: foundation`). It does not supply the visual
  concept: that is derived from the subject each time (§Visual-first rule).
  Novelty for its own sake is not required.
- **Brand priority:** current-project instruction → current-project reference →
  official subject/product identity (inspect the official assets; inspired-by,
  never a look-alike) → neutral `generic`. `generic` is only for an unbranded
  subject (`product: none`) or an explicit neutral request; a named
  product/company never falls through to it. No profile and no official
  evidence → stop before composition and ask (`brands/README.md` rules 9–10).
- **User-supplied references are project-scoped.** They, and any one-off look
  built for one subject, do not carry into another project unless the user asks.
- **Manifest.** Record it in `DESIGN.md`, mirror it in `meta.json` →
  `design_manifest`, and run `python3 design/cli.py preflight videos/<slug>`:

```yaml
brand: { subject: "…", product: "…", source: "…", identity_mode: official | user-reference | neutral,
         reference_scope: project-only, composition_language: foundation,
         inherited_from: null, inheritance_authorized: false }
user_identity: { x_handle: "@your_handle", show_handle: true }
visual_reference: { supplied: false, scope: project-only, promoted_to_template: false }
```

Full rules: `CONTEXT_SCOPE.md` (read on demand, see above).

## Primary company → brand profile

After source verification, detect the primary company and select a matching
profile from `templates/tech-news-ar/brands/`. The selection rules live in
`brands/README.md`. A profile supplies CSS tokens (`--brand-*`: colors, surface,
border, radius, density, treatments, optional logo placement) and, where it has
one, an `identity` block (palette, gradients, shapes, motifs, surface, motion)
that shapes the **scene content**. A named company/product without a profile
is resolved from official sources first (`brands/README.md` rule 10); `generic`
is for unbranded subjects. Record the choice in the project's `meta.json` as
`"brand"`.

A brand identity is not a logo plus one accent colour on gray: carry the
palette, shapes and motifs into the objects the viewer sees.
`python3 design/cli.py brand <project>` gives an advisory count of palette
colours that reach the scenes (never a gate). The brand must not change wording,
facts, or editorial tone, and the video must not look like an official company
publication.

Selection chain: **reference analysis (optional style context) → source
verification → primary company detection → brand profile selection →
subject assets → visual story → script → visual motion plan → audio cue plan (only if requested) → asset plan → cost gate
(+ human approval) → paid generation → word-level timing (voice) → build → audio
synchronization → validation → final mix → render.**

## Integrated flow and the two human gates

**Standard path (default):**

```
context / brief → subject assets → visual story (SEE / DOES / READ) → script → build
  → validate + trace → render → QA → human review
```

No critic or inspiration stage sits on this path. The full flow below
adds stages that apply only when a project uses them (paid generation, voice,
the optional AI review):

```
Brief + brand profile + manifest                       ← §Context scope and brand
  → Reference Analyzer (optional, project-scoped)
  → Subject assets → Visual story (storyboard) → Script   ← §Visual-first rule, CONTENT_RULES.md
  → Cost Gate ─────────────►   GATE 1: human cost approval   ← before paid generation
  → Paid Generation
  → Composition
  → Word-level Sync
  → Preview Render
  → Deterministic Analysis → AI Review → Proposed Fixes
  →  GATE 2: human creative/technical approval              ← before applying proposals
  → Apply approved changes to a new revision
  → Final Render
  → Quality Gate
```

The two gates are distinct. Gate 1 exists only when something paid is planned;
Gate 2 is the human review of the render (AI-proposed fixes are optional):

- **Gate 1 — cost approval, before paid generation.** Nothing paid runs until the
  human approves the estimate; if the estimate exceeds the approved limit it
  stops. Unknown pricing is surfaced, never invented (`COST_GATE.md`).
- **Gate 2 — creative/technical approval, after the preview.** Only proposals a
  human approves are applied, and applying writes a **new revision** — never the
  source project, never an existing render (`AI_REVIEW.md`).

Stages stay independently rerunnable: reference analysis needs no render, the
cost gate needs no generation, caption restyling and review need no TTS, and
applying a proposal never overwrites the previous revision.

Read-only status across all four subsystems and both gates:

```bash
python3 studio/cli.py status <project_dir> [--reference <id>] [--plan <plan.json>] [--pricing <p.json>]
```

It performs no paid calls, no rendering, and no project writes; it exits non-zero
with `--require-cost-approval` while Gate 1 is unresolved.

## Visual inspiration (optional)

Not part of standard production and never a gate: the storyboard does not wait
for it. The default visual direction is the starter plus the selected brand
profile. Gather references only when:

- the video establishes a genuinely new visual direction;
- the user explicitly asks for references; or
- the existing visual system cannot represent the subject well.

Then keep it small: a few references that each solve a real design problem,
recorded in an optional `visual_inspiration.md` (reference · what is useful ·
what not to copy · the selected direction). References are inspiration only —
never a factual source, never an asset source, never copied one-to-one
(`ASSET_POLICY.md`) — and are project-scoped (`CONTEXT_SCOPE.md` §2). They never
override typography, safe zones, Arabic RTL, or validation rules.

## Steps

### 0. Prerequisites
Note the run's `started_at` (local time with UTC offset) now, before any other
work; the run record needs it (`RUN_METRICS.md` §Required for new runs).
```bash
npx hyperframes@0.8.35 doctor        # Node >=22, FFmpeg, Chrome must be ✓
```
macOS GPU renders: `export PRODUCER_BROWSER_GPU_MODE=hardware`.

### 1. Verify the source
Read the supplied text and confirm every claim against primary sources. Record
each source URL in `sources.md`. Do not proceed on unverified claims. See
`CONTENT_RULES.md` (no invented facts).

### 2. Initialize the project
```bash
mkdir -p videos && npx hyperframes@0.8.35 init videos/<slug> \
  --non-interactive --example=blank --skill=motion-graphics --resolution=landscape
T=templates/tech-news-ar
cp $T/starter/standard.html videos/<slug>/index.html      # technical foundation, 1920x1080
cp $T/sources.md $T/script.md $T/storyboard.md videos/<slug>/
mkdir -p videos/<slug>/assets/fonts videos/<slug>/tools
cp $T/tools/check-tashkeel.py videos/<slug>/tools/
cp -R $T/lib videos/<slug>/lib                             # type + motion primitives + optional grammar
cp $T/assets/fonts/* videos/<slug>/assets/fonts/           # Alexandria (required)
```
Explicit 9:16 request only: `--resolution=portrait`, copy `$T/index.html`
(portrait starter) instead, and set `"format": "portrait"` in `meta.json`.

### 3. Resolve the brand and select a profile
Record the project manifest in `DESIGN.md` and `meta.json` (§Context scope and
brand). Determine the primary company from the verified sources and select its
profile from `templates/tech-news-ar/brands/` (rules in `brands/README.md`);
apply the tokens by replacing the `/* brand:start … brand:end */` block (or run
`tools/apply-brand.py`) and record `"brand"` in `meta.json`. No profile for a
named company/product → resolve a project identity from official sources or get
an explicit neutral approval before any composition (`brands/README.md` rule
10); unbranded subject → `generic`. The profile's `identity` block (palette, shapes, motifs,
surface, motion) is used **inside the scenes**, not only in the chrome; it never
changes wording, facts, or editorial tone.

### 4. Discover subject assets (before the storyboard)
Inspect the primary source (announcement, product page, docs, press kit) for
official product imagery, screenshots, diagrams, interface captures,
model/product artwork and other useful source visuals. This is not visual
inspiration and needs no Pinterest or Behance.

- Use official/source imagery where it materially improves the story. Source
  key art and product imagery **may** be used with a clear on-screen credit and
  a `sources.md` row (`ASSET_POLICY.md`).
- Do not reproduce a whole campaign composition, and do not make the video look
  like an official publication.
- Record the result at the top of `storyboard.md` under `## Source assets`:
  what was found and what will be used, or **`none usable`** with the reason.
  With none usable, continue with constructed visual objects.

### 5. Write the visual story (`storyboard.md`)
Before any caption and before choosing any grammar, write for **every** beat:

- **SEE** — what the viewer actually sees: the object, asset, interface,
  diagram, environment or visual system. Name it.
- **DOES** — what happens visually: motion that communicates the idea, not a
  decorative entrance.
- **READ** — the minimum text the viewer must read.

Also note the transition out and what survives into the next beat, and name 2–3
signature transformations (one object becoming the next explanation). Then map
each beat to a `.clip` `data-start`/`data-duration`. A grammar may be noted last,
if one fits; a custom scene is equally valid.

### 6. Write `script.md`
The final captions, taken from the READ lines. Story arc: **Hook → What
happened → Why it matters → One key detail → Takeaway**. See `CONTENT_RULES.md`
for wording (§Writing quality), the permanent no-tashkeel rule, and caption
style. `script.md` holds the final copy only.

### 7. Build `index.html`
Build each scene from its SEE / DOES / READ. Keep the foundation from
`starter/standard.html` and replace its placeholder scene:
- one paused GSAP timeline registered on `window.__timelines["main"]`;
- `fromTo` tweens with explicit from-states and absolute position parameters;
- typography classes, safe zones and chrome from `lib/`;
- on every scene `data-visual="<role>"` (`source-image`, `screenshot`,
  `interface`, `object`, `diagram`, `data`, `footage`, `text`, or another
  lower-case token); mark constructed visual elements with `data-object`.

`python3 design/cli.py visual videos/<slug>` (also part of the build stage of
`production`) fails on a missing visual-story block, a scene without a role, a
non-text role with nothing but text in the scene, or more than one text-only
scene. It checks that the decision was made, not how good it is.

### 8. Validate
Preferred: the pipeline (`PRODUCTION.md`) runs steps 8–10 in order and stops at
the first blocking gate — validation (incl. `hyperframes check` and the numeric
trace), render, QA. Then a human reviews the render. Critics are optional tools,
never part of the default run (`PRODUCTION.md` §Critics):
```bash
python3 studio/cli.py production videos/<slug>
```
The manual equivalent:
```bash
cd videos/<slug>
npx hyperframes@0.8.35 lint .
npx hyperframes@0.8.35 check . --at <beat-midpoints> --snapshots
```
Clear all lint errors before trusting layout/contrast numbers, then inspect
every snapshot. Fix RTL, typography, clipping, contrast, timing, layout.

### 9. Render
```bash
npx hyperframes@0.8.35 render . --skill=motion-graphics -q high -f 30 -o ./renders/video.mp4
```

### 10. Verify output
```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate,nb_frames,pix_fmt \
  -show_entries format=duration,size -of default=noprint_wrappers=1 renders/video.mp4
```
Confirm: H.264, 1920×1080 (or the explicitly declared format), 30 fps, intended frame count/duration, non-empty.

## AI review & approval layer

An optional, measured review pass runs after the preview render and before the
quality gate. The reviewer only inspects, measures, reports, and proposes; a
human must approve before anything is applied, and approved changes are written
to a **new project version** — never to the source project or an existing
render. See `AI_REVIEW.md` and `review/` (run `python3 review/cli.py review
videos/<project>`). The reviewer must not run paid APIs, add external assets, or
alter factual wording, RTL, no-tashkeel, brand profile, or `sources.md`.

### Optional visual critic

After the preview render, one read-only critic can review a prepared pack
(`python3 review/cli.py critic-pack`), and a blind pairwise pass can compare a
significant revision with its predecessor. Advisory only: no scores, no gate,
no automatic fixes or loops; the human approves. Triggers and skips:
`AI_REVIEW.md` §Advisory diagnostics and the optional visual critic.

## Run closure (every production run ends here)

A run is not finished until all four steps are done, in order.

1. **Validation** — `lint`, `check --snapshots`, and `ffprobe` all pass;
   snapshots inspected.
2. **Quality score** — score the six measured categories in `QUALITY_SCORE.md`,
   check the hard-fail list, and take visual quality only from an independent
   review — on the standard path, the human's 0–15 score at the render review —
   never self-scored (`review/quality.py`).
3. **Cost / usage record** — write `runs/<YYYY-MM-DD>-<slug>.json` per
   `RUN_METRICS.md` (start from
   `templates/tech-news-ar/run-metrics.example.json`). Never invent usage or
   cost: record measured values, or `null` with `cost_status: "unknown"`.
   `started_at`, `ended_at`, `total_production_seconds`, `quality_score`,
   `render_retries` and `manual_interventions` are never `null`:
   `python3 tools/check-run-record.py runs/<run-id>.json` must print `ok`.
4. **Publish decision** — set `ready_to_publish` per `QUALITY_SCORE.md`: `true`
   only for 90–100 with no hard fail; 80–89 requires minor review; below 80 or
   any hard fail → do not publish.

The final handoff names the score breakdown, the decision, and the run-record
path.

## Typography system

- **Font:** **Alexandria** is the required Arabic family (variable 100–900,
  Arabic + Latin subsets, SIL OFL 1.1), bundled in `assets/fonts/` with
  `OFL-Alexandria.txt`; `--ms-font` resolves to it. Declare the two
  `@font-face` rules **inline in `index.html`** with `url("assets/fonts/…")`
  (HyperFrames lint requires project-root paths; a linked stylesheet would
  resolve them relative to `lib/`). Never use system-only faces
  (`SF Arabic`, `Geeza Pro`): headless Chrome silently falls back.
- **Scale:** `lib/type.css` (classes `t-display`, `t-headline`, `t-secondary`,
  `t-caption`, `t-credit`, `t-handle`, `t-stat`, `t-stat-label`), values in
  `lib/type-scale.json`. Set `data-format="portrait|landscape"` on the root.
- **Check:** `python3 design/cli.py fonts <project> --render` verifies the chain
  required family (`lib/type-scale.json`, or `meta.json` →
  `production.typography` as an explicit override) → declared primary family →
  bundled file → loaded in the render browser, and fails on any break. The
  production build check raises `font_required_mismatch` (ERROR) when the
  primary family is not the required one. `python3 design/cli.py readability <project>` reports phone-scale
  sizes (390px-wide phone).

| Role (px) | Portrait 1080×1920 | Landscape 1920×1080 | Min at phone scale (P / L) |
|-----------|-------------------:|--------------------:|---------------------------:|
| display | 120 | 132 | — |
| headline | 92 | 96 | — |
| secondary | 50 | 54 | 14 / 10 |
| caption | 40 | 42 | 12 / 8 |
| credit | 30 | 32 | 9 / 6 |
| handle | 32 | 30 | — |
| stat / stat label | 260 / 46 | 240 / 48 | — |

Secondary text uses `--ms-secondary` (brand text mixed 80% with brand muted),
brighter than the old muted token; weight 500.

**Caption-specific readability policy (intentional, not a global relaxation):**
timed subtitles use the `subtitle` role (class `subtitle`) with a lower
phone-scale floor (landscape 8px, portrait 12px) than general secondary UI text
(10px / 14px). The exception applies **only** to timed subtitles; headline,
labels, statistics, cards, and all other secondary text keep the existing
secondary floor. Rationale and source: `lib/type-scale.json` →
`readability_policy`. Do not lower the secondary floor itself.

## Safe zones and frame usage

| Zone | Portrait | Landscape |
|------|----------|-----------|
| Chrome inset (topbar/footer) | 64px | 56px |
| Text-safe padding (top / side / bottom) | 200 / 72 / 320 | 150 / 120 / 130 |
| Full-bleed media | edge to edge; text band 360px from bottom | edge to edge; text band 150px from bottom, max 1180px wide |
| Split | media stacked on top, 46% height | text column right, media 55% left, 80px gutter |
| Large headline | max 936px | max 1600px |
| Card / screenshot | max 936 wide | 580–640px tall, max 1480 wide |

Landscape content should use the width (split, full-bleed, columns) instead of
a centered column in the middle third.

## Frame-0 rule

The first frame must show meaningful content — media, the hook headline, or a
visual hook — not an empty or near-black frame, and no long fade from black.
Starting a hook already partly revealed (`MS.enter.maskReveal(..., {start: 0.65})`)
or with media visible and pushing in both satisfy it; the rule is about content,
not a treatment. Measured on the render: content coverage ≥ 0.01 at 0s or by
0.5s (`lib/type-scale.json` → `frame_zero`); review reports `frame_zero`.

## Scene grammar

Optional layout helpers, chosen after the visual concept (§Visual-first rule).
Registry `lib/grammars.json`, layout `lib/grammar.css`, motion `lib/motion.js`.
A scene that uses one is annotated:

```html
<section class="clip g-scene" data-grammar="big_number" data-variant="center"
         data-beat-kind="statistic" data-start="29" data-duration="5">
  <div class="g"> … </div>
</section>
```

| Grammar | Use for (beat kinds) | Avoid for | Variants |
|---------|----------------------|-----------|----------|
| `full_bleed_media` | hook, product_visual, context | statistic, feature_list, ui_detail, comparison | bottom_band, top_band |
| `split_media_text` | claim, context, product_visual, process | statistic, quote, comparison | media_left, media_right |
| `big_number` | statistic, hook | process, ui_detail, feature_list, quote | center, offset |
| `kinetic_word` | hook, takeaway, claim | statistic, ui_detail, comparison, feature_list | line, stack |
| `screenshot_detail` | ui_detail, product_visual, feature_list | quote, takeaway, statistic | framed, full |
| `progressive_list` | process, feature_list | hook, quote, statistic, product_visual | numbered, plain |
| `comparison` | comparison | hook, quote, statistic, ui_detail | columns, stacked |
| `quote_or_statement` | quote, takeaway, claim | statistic, ui_detail, feature_list, process | attributed, center |

When a grammar is used, pick it from what the scene shows
(`python3 design/cli.py validate` flags an unsuitable pairing). Five of the
eight are text layouts; a video built only from those fails the visual-first check. Each grammar entry in the registry also
lists its layout, media treatment, typography, RTL behavior, allowed entry /
exit / camera motions and callouts. RTL: `.g` is `direction: rtl`; builds start
on the right; real screenshots keep `direction: ltr` inside `.g-shot`.

## Motion grammar

Ten motions, each grammar allows at most three entries and two exits:

| Motion | Role | Behavior |
|--------|------|----------|
| `fade_scale` | entry | opacity + scale 0.96→1 |
| `rtl_slide` | entry | enters from the right (+x) |
| `mask_reveal` | entry | clip-path wipe right→left; may start partly revealed |
| `stagger_build` | entry | items in DOM (reading) order |
| `line_draw` | entry | rules draw from the right / top |
| `hard_cut` | entry/exit | clip boundary is the cut |
| `push_in` | camera | slow linear scale on media |
| `zoom_to_detail` | camera | move to one region of a real screenshot |
| `fade_out` / `mask_out` | exit | short fade / wipe continuing right→left |

`lib/motion.js` adds these to the one paused timeline (`MS.enter.*`, `MS.exit.*`,
`MS.camera.pushIn`). It is deterministic (no random, clocks, async) and never
contains a closing script tag (HyperFrames inlines the file).

## Screenshot choreography

Visual treatments of **real** official imagery only — never fabricated UI.
Frame: `.g-shot` (style `--shot-ar: <w> / <h>` = the image's native ratio) with a
`.g-canvas` holding the image and overlays. Regions are fractions `x,y,w,h`.

| Treatment | Call |
|-----------|------|
| push-in | `MS.camera.pushIn(tl, "#img", at, dur, {scale})` |
| crop to region | `MS.shot.cropTo(tl, "#shot", region, at)` |
| zoom to detail | `MS.shot.zoomToDetail(tl, "#shot", region, at, dur)` |
| pan between regions | `MS.shot.panBetween(tl, "#shot", a, b, at, dur)` |
| highlight box | `.g-box[data-region]` + `MS.shot.highlightBox` |
| spotlight (dim outside) | `.g-spot[data-region]` + `MS.shot.spotlight` |
| callout line/arrow | `.g-line[data-from][data-to]` + `MS.shot.calloutLine` |

Call `MS.shot.place("#shot")` once to position overlays. Source files are never
modified; overlays travel with zooms because they live inside `.g-canvas`.

## Layout signature and novelty (advisory)

`python3 design/cli.py signature <project>` returns the ordered grammar ids
(unannotated legacy scenes read as `legacy_card`). Record it in the run record
as `layout_signature` (with `format`). Before building,
`python3 design/cli.py novelty <project>` compares it with the last 3 comparable
runs (same format, different story): exact repeats, ≥75% ordered similarity,
and a repeated opening grammar are reported with content-suitable alternatives.
Advisory only — never a hard fail.

## GSAP timeline structure
- Register `window.__timelines["main"]` **once**, at the end of the script.
- All positions are absolute seconds (`tl.fromTo(target, from, to, at)`).
- Entrances: headline `y:46 + blur(12px) → 0`, sub `y:26 → 0`,
  card `y:44 + scale 0.98 → 1`, logo `y:-18 + scale 0.96 → 1`.
- Eases: `power3.out` for text, `power2.out` for chrome, `back.out(1.6)` for a
  spark; `none` for progress fills.
- Finite repeats only. Never `repeat: -1`.
- One timeline for the whole piece; do not add paused child scene timelines.
- Scene-grammar projects build the timeline through `lib/motion.js` helpers and
  call `MS.applyReviewAttributes(tl)` just before registering it (turns approved
  review attributes such as `data-push-in` into tweens). The entrance values
  above describe the legacy 5-beat template.

## Validation gates
| Gate | Command | Pass condition |
|------|---------|----------------|
| Environment | `npx hyperframes@0.8.35 doctor` | Node/FFmpeg/Chrome ✓ |
| Context scope | `python3 design/cli.py preflight .` | `ok: true` — manifest complete, `reference_scope: project-only` |
| Static | `npx hyperframes@0.8.35 lint .` | 0 errors / 0 warnings |
| Full | `npx hyperframes@0.8.35 check . --at ... --snapshots` | 0 errors / 0 warnings / 0 layout issues |
| Visual | inspect `snapshots/*.png` | correct RTL, no clipping, hierarchy holds |
| Fonts | `python3 design/cli.py fonts . --render` | `"status": "loaded"`: required family (Alexandria) is primary, bundled and loaded |
| Visual-first | `python3 design/cli.py visual .` | 0 errors: visual-story block present, every scene has `data-visual`, ≤ 1 text-only scene |
| Format | build stage of `studio/cli.py validate` | composition = declared format (default 1920×1080) |
| Grammar | `python3 design/cli.py validate .` | 0 errors (advisories reviewed) |
| Novelty | `python3 design/cli.py novelty .` | advisories reviewed (never blocking) |
| Diagnostics | `python3 review/cli.py review videos/<slug>` | advisory `empty_frame` / `long_hold` / `boundary_dip` findings reviewed (never blocking) |
| Pre-render | `python3 studio/cli.py validate videos/<slug>` | 0 ERROR (one-frame outliers, malformed tracks, nondeterminism, impossible ranges); `Numeric trace` line states PASS or why SKIPPED (`PRODUCTION.md`) |
| Output | `ffprobe` (or `python3 studio/cli.py qa videos/<slug>`) | codec/res/fps/duration as specified |

## Definition of done
- [ ] Project manifest recorded in `DESIGN.md` and mirrored in `meta.json`; `python3 design/cli.py preflight` passes (§Context scope and brand).
- [ ] Brand profile selected per `brands/README.md` and recorded in `meta.json` (`generic` only for an unbranded subject, no dominant company, or an approved neutral treatment).
- [ ] Visual identity is inspired-by, not a look-alike of official company communications.
- [ ] `sources.md` lists every claim source and every asset with URL + license note.
- [ ] Output is 1920×1080, or the explicitly requested and declared format.
- [ ] Alexandria is the primary Arabic family (`fonts --render` → `loaded`).
- [ ] `storyboard.md` records `Source assets` and SEE / DOES / READ for every beat; every scene declares `data-visual`; at most one text-only scene.
- [ ] `script.md` and `storyboard.md` match the rendered video.
- [ ] No tashkeel in any visible Arabic text (see `CONTENT_RULES.md`).
- [ ] `lint` and `check --snapshots` clean; snapshots inspected.
- [ ] `@your_handle` present per the global preference (`CONTEXT_SCOPE.md` §6) or an explicit opt-out recorded in the manifest; source attribution present.
- [ ] Final MP4 verified with `ffprobe`.
- [ ] Quality score computed and decision applied (`QUALITY_SCORE.md`).
- [ ] Silent unless the brief requests audio: 0 audio streams in the final MP4 (`AUDIO_DESIGN.md` §0).
- [ ] Audio (only if requested) planned in `storyboard.md`, licensed, synchronized, mixed without clipping, and documented in `sources.md`; audio stream and duration verified.
- [ ] Run record written to `runs/<run-id>.json` and `tools/check-run-record.py` prints `ok` (time, quality score, retries, interventions recorded); usage/cost/audio counts marked unknown where not measurable.
- [ ] `ready_to_publish` set; publishing only when it is `true`.
- [ ] On publication, `status`/`published_at`/`final_master` set in `meta.json` (never automatically); the project then falls under the published retention policy (`WORKFLOW_REFERENCE.md`).
