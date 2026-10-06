# PRODUCTION.md — gated production pipeline

```
default:  BRIEF → SPEC → BUILD → VALIDATE (+ trace) → RENDER → QA → AUDIO → human review
strict:   … VALIDATE → STILLS → CRITICS → RENDER → QA → AUDIO      (opt-in: --critics)
```

One rule: **an expensive stage never runs while an earlier stage has a blocking
problem.** Validation is cheap (seconds) and runs on composition data plus a
numeric browser trace; the full render waits for validation.

**Critics are optional.** The default `production` run does not build stills or
critic packs, never waits for a critic and never enters a fix loop; a human
reviews the render. The motion, design and visual critics remain available as
manual tools (`stills`, `critics`, `critic-record`; `AI_REVIEW.md` for the visual
critic). Their verdicts are advisory unless strict mode is on
(`production --critics`, or `policy.require_review: true` in the brief).

The brief is read from `meta.json`, the spec from the `<section class="clip">`
scenes. Three things are **declared, never inferred from the composition**, and
checked at the brief/build stage (ERROR on mismatch):

- **Format** — `production.resolution`, `outputs.master.resolution` or
  `"format": "portrait" | "landscape"`; default **1920x1080**. The composition
  and, in QA, the render must match it.
- **Font** — the required family from `lib/type-scale.json` (Alexandria in the
  standard template) or `production.typography`; the composition's primary
  family must be that family (`font_required_mismatch`).
- **Visual story** — `storyboard.md` carries `Source assets` and SEE / DOES /
  READ per scene, every scene declares `data-visual`, and at most
  `policy.max_text_only_scenes` (1) are text-only. Legacy projects with a
  storyboard but no such block set `policy.visual_story: false`.

The build stage also fails while `index.html` still contains the starter's
placeholder handle `@your_handle` (`handle_placeholder`): set your own handle,
or delete the handle element for a video without one (`CONTEXT_SCOPE.md` §6).

An advisory `brand_palette_reach` (INFO, never a gate) notes when few brand
palette colours reach the scene content. State is
written only to `<project>/production/` (and the render output).

## Commands

All are `python3 studio/cli.py <command> <project_dir>`.

| Command | Does | Cost |
|---|---|---|
| `brief` | print the machine-readable brief and where each value came from | instant |
| `validate` | brief + spec + build + pre-render validation (no render) | ~3–20 s |
| `trace [--install] [--refresh]` | numeric browser trace only (cached) | ~2–20 s |
| `stills` | optional: 4–6 representative stills + motion strips around boundaries | ~15 s |
| `critics` | optional: build motion + design critic packs, print the agent prompts | instant |
| `critic-record --critic motion\|design --file v.json` | record a critic agent's verdict | instant |
| `render [--override REASON] [--overwrite]` | full render **behind the render gate** | the expensive one |
| `qa [--render path]` | post-render QA + audio checks | ~1–5 s |
| `production` | every allowed stage in order; stops at the first blocking gate | — |
| `report` | the production report (also written to `production/report.md`) | instant |

`production` flags: `--no-trace`, `--refresh-trace`, `--no-check`,
`--rerun` (ignore fresh results), `--no-render` (stop before the render),
`--critics` (strict mode), `--skip-critics REASON` (force the default path even
when the policy requires review), `--override REASON`, `--overwrite`.
Exit codes: `0` done, `1` blocked/failed, `3` escalate to a human (strict mode),
`4` awaiting critics (strict mode).

## Stages and statuses

Each stage records `PASS`, `WARN`, `FAIL` or `SKIPPED`; the critics are `PENDING`
until a verdict is recorded. The report also shows `STALE` (recorded for an
older version) and `NOT RUN`.

- **FAIL blocks** every downstream stage.
- **WARN does not block** unless `policy.warnings_block` is true.
- Every result is bound to the **production hash**: `index.html`,
  `hyperframes.json`, `package.json`, everything under `lib/` and
  `compositions/`, referenced local scripts/styles, `meta.json` and
  `spec.json`. Any edit makes earlier results `STALE`, so a fix always goes back
  through validation (and, in strict mode, stills and both critics). It can
  never inherit an approval. Media assets are outside the hash, so the render gate
  re-checks that they exist every time.
- `production` reuses fresh `PASS`/`WARN` results for the current hash; `--rerun` forces them.

| Stage | Checks | FAIL when |
|---|---|---|
| Brief | fps, resolution and duration agree with the composition; audio policy is valid | mismatch / invalid value |
| Spec | `spec.json` is well-formed (absent = inferred) | malformed |
| Build | `index.html` exists, every local `src`/`href`/`url()` exists (CSS `url()` resolves from the project root, as HyperFrames does), fonts bundled, `required_text` present, `forbidden_text` absent | any of these |
| Validation | `hyperframes check` (lint, runtime, layout/overflow, motion sidecar, contrast), structure, determinism scan, numeric tracks | any ERROR |
| Stills | snapshots rendered | snapshot failed |
| Motion / Design critic (optional) | verdict recorded by the critic agent | strict mode only: verdict FAIL |
| Render | render gate, then `hyperframes render -q high -f <fps>` | gate blocked or render failed |
| Post-render QA | output against the brief | any ERROR |
| Audio | per audio policy | missing stream, clipping |

## The brief (`meta.json` → `production`, all optional)

```json
"production": {
  "objective": "…", "audience": "…", "core_message": "…",
  "duration_s": 29, "aspect_ratio": "16:9", "resolution": "1920x1080", "fps": 30,
  "language": "ar", "direction": "rtl",
  "brand_constraints": "…", "typography": "…",
  "assets": [], "required_text": ["…"], "forbidden": ["free-text constraints for the critics"],
  "forbidden_text": ["literal strings that must not appear"],
  "audio": "none | sfx | music | music+sfx", "loudness_lufs": -14,
  "delivery": { "file": "renders/video.mp4", "codec": "h264" },
  "policy": { "warnings_block": false, "require_numeric_validation": false,
              "require_review": false, "max_fix_iterations": 3, "stills": 6 }
}
```

Missing values fall back to `outputs.master`, `audio`, `design_manifest` and
the composition. `brief` prints each value's source. Audio defaults to `none`
unless `meta.audio.requested` is true (`AUDIO_DESIGN.md` §0).

## The spec (`spec.json`, optional)

```json
{
  "scenes": [
    { "id": "reveal", "frame_start": 300, "frame_end": 600,
      "entrance": "mask_reveal", "hold": "1.2s", "exit": "fade_out", "transition": "hard_cut",
      "depends_on": ["intro"], "review_frames": [420] }
  ],
  "tracks": {
    "camera.x": [[300, 0], [418, 82], [480, 82]],
    "hero.scale": [[300, 0.96], [330, 1.0]]
  },
  "discontinuities": [
    { "kind": "whip", "frames": [470, 478], "property": "camera.*" },
    { "kind": "intentional_jump", "time": 15.5, "property": "card.x" }
  ],
  "trace": { "selectors": { "camera": "#world .cam" } },
  "validator": { "thresholds": { "position": { "jump": 0.2 } } }
}
```

- **Scenes** describe intent at a high level: motion-grammar primitives
  (`VIDEO_WORKFLOW.md` §Motion grammar), not frame tables. Spec ranges are
  checked against the composition's clips.
- **Tracks** are deterministic keyframes, `{"<element>.<prop>": [[frame, value], …]}`,
  linearly interpolated. They are authoritative where declared. When the
  browser trace has the same track, a disagreeing runtime value is reported
  (`runtime_differs_from_spec`).
- **`trace.selectors`** names important elements for the trace (`camera` → `camera.x`, …).
- Template: `templates/tech-news-ar/spec.example.json`.

## Pre-render validation

```
spec.json tracks ─┐
                  ├─► normalized tracks ─► validator (studio/prerender.py)
browser trace  ───┘
```

The validator never knows where a track came from.

**Numeric checks** (per track, per frame):

| Code | Severity | Meaning |
|---|---|---|
| `one_frame_outlier` | ERROR | value leaves and returns within one frame (spike) |
| `suspicious_jump` | WARNING | one-frame step that stays, far above local motion |
| `non_finite_value` | ERROR | NaN / Infinity |
| `malformed_keyframe`, `duplicate_frame`, `unsorted_keyframes`, `frame_out_of_range`, `invalid_value` | ERROR | malformed track data (e.g. opacity outside 0..1) |
| `seek_order_dependent` | ERROR (visible) / INFO (invisible) | value differs when the frame is reached by a backward seek |
| `empty_opening` | ERROR | nothing visible in the first 0.5 s (Frame-0 rule) |
| `empty_review_frame` | ERROR | nothing visible on a declared review frame |
| `empty_frames` | WARNING | ≥ 2 frames with no visible traced content |
| `always_offstage` | WARNING | element visible but never inside the stage |
| `runtime_differs_from_spec` | WARNING | trace disagrees with a declared keyframe |

Thresholds per property kind: position as a fraction of the stage's shorter
edge, scale, rotation, opacity, size relative. Override them in
`spec.json → validator.thresholds`.

These are **not** errors:
- changes while the element is invisible;
- jumps within ±1 frame of a scene boundary (implicit hard cut);
- evenly spaced alternating steps, such as a caret blink.

All three are reported as INFO.

**Intentional discontinuities** (`spec.json → discontinuities`). Scope each one
with `property` (a glob over track names) and `frame` / `frames` / `time` / `times`:

| Kind | Suppresses | Default window |
|---|---|---|
| `hard_cut` | jumps (a spike at a cut is still an error) | ±1 frame |
| `intentional_jump` | jumps | ±1 |
| `whip` | jumps and spikes | ±6 |
| `impact` | jumps and spikes (shake) | ±4 |
| `allow_outlier` | jumps and spikes | ±1 |

Suppressed findings stay visible as INFO. An unknown kind is an ERROR.

**Determinism scan** (static, over `index.html` and the local scripts/styles it
references; `*.min.js` and vendored gsap/three/lottie/anime are skipped):
- ERROR: `Math.random()`, `Date.now()` / `performance.now()` / `new Date()`,
  `requestAnimationFrame`, `repeat: -1`, infinite CSS animation.
- WARNING: `setTimeout` / `setInterval`, CSS `transition`.
- Finite CSS `@keyframes` are allowed (HyperFrames seeks them). So is a seeded
  PRNG.
- A line marked `ms:allow-nondeterminism` becomes INFO: an explicit, reviewed
  exception.

**Structure:** `impossible_frame_range`, `duplicate_scene`, `invalid_duration`
(ERROR); spec/composition range mismatch (WARNING); frames outside every scene
(INFO).

Output format:

```
ERROR
  scene: reveal
  frame: 418
  property: camera.x
  change: 82 → 1682 → 82
  reason: one-frame outlier with no intentional annotation [trace/one_frame_outlier]
```

Full findings: `production/validation.json`.

## Numeric browser trace (opt-in)

The trace seeks the composition's deterministic timeline **frame by frame** and
samples numeric state only. Per element it reads translate x/y, scaleX/Y,
rotation, own opacity, effective alpha (the parent chain) and the stage box
x/y/w/h. It takes no screenshots, does no encoding and calls no critics.

- **Elements traced:** declared `trace.selectors`, scene roots, GSAP tween
  targets, and CSS/WAAPI-animated elements. Not the whole DOM. Visible
  canvas/video/img/svg count toward "is anything on stage".
- **Adapter:** `studio/hf_trace.mjs` is the only HyperFrames/browser contact
  point. It uses the public `@hyperframes/producer` exports
  (`createFileServer`, `createCaptureSession`, `initializeSession`,
  `getCompositionDuration`), `@hyperframes/core/compiler` `bundleToSingleHtml`,
  and `window.__hf.seek` (the same seek the official hyperframes-animation
  sampler uses). A HyperFrames change should only touch this file.
- **Install** (explicit, out of tree, pinned to the project's `hyperframes@x.y.z`):
  `python3 studio/cli.py trace <project> --install`. It goes to
  `~/.cache/motion-studio/hf-trace/<version>/` (override with
  `MOTION_STUDIO_TRACE_CACHE`). Nothing is added to the repository or the project.
- **Cache:** `production/trace.json` is keyed to the composition hash plus fps,
  size and selectors. Holds are compressed to their endpoints, which is lossless
  under interpolation. A changed composition re-traces automatically; a stale
  trace is never used.
- **Seek-order check:** after the forward pass, every 7th frame is re-seeked in
  reverse. Any visible difference is `seek_order_dependent`.
- **Three.js and other canvas worlds:** expose `window.__msTrace = (t) => ({camX: …})`
  to add `probe.*` tracks.
- **Failure is explicit.** If the tracer is missing or the browser fails, the
  report says `Numeric trace: SKIPPED — reason: …`. Validation never claims
  numeric PASS without a trace or spec tracks. With
  `policy.require_numeric_validation: true` it is a FAIL.

### Measured overhead (2026-10-02, Apple Silicon, cold runs)

| Project | Frames | Elements / tracks | Trace (wall) | `trace.json` | Validator |
|---|---|---|---|---|---|
| ai-decision-design-ar-rev3 (DOM, 1920×1080) | 870 @30 | 171 / 1881 sampled, 978 kept | 2.8–3.2 s | 247 KB | 0.16 s |
| time-management-priorities-ar (DOM, 1080×1920) | 1275 @30 | 79 / 869, 404 kept | 2.1 s | 327 KB | 0.10 s |
| deepseek-v41-flash-code-world-ar (Three.js) | 2100 @60 | 9 / 99, 42 kept | 18.6 s | 100 KB | 0.02 s |

For comparison, the full render of ai-decision-design-ar-rev3 took 15.1 s and
its stills 14.3 s. WebGL scenes re-render on every seek, so their trace costs
more. A cache hit costs about 3 ms.

## Stills

`stills` picks 4–6 frames, at least 0.75 s apart, in this priority order:
1. explicit `review_frames`;
2. the final state;
3. the opening hook;
4. the busiest transition (by trace motion energy);
5. validator hot spots;
6. each scene's settled hero frame (first frame after the entrance with motion below threshold), ranked by text and density.

It also captures 5-frame strips (b-2..b+2) around up to five scene boundaries.
Both sets come from `hyperframes snapshot` in one browser session each; its
contact sheets are reused. Output: `production/stills/<hash12>/`.

## Critics (optional; builder ≠ judge)

Not part of the default run. Use them when you want a second opinion, or run
`production --critics` to make them a gate.

`critics` writes two packs to `production/critics/<hash12>/{motion,design}/`:
- **Motion pack:** boundary strips, the key frames, and measured motion facts
  per scene from the trace (settle time, still time, longest hold, peak motion).
- **Design pack:** the stills plus the brief (objective, audience, typography,
  brand constraints, forbidden, required text).

Both include the pre-render validator facts.

Run the two read-only agents (`.claude/agents/motion-critic.md`,
`design-critic.md`) on their packs. Each returns JSON:

```json
{"critic": "motion", "reviewer": "motion-critic", "pack": "<pack id>", "verdict": "FAIL",
 "findings": [{"severity": "BLOCKING|MAJOR|MINOR", "scene": "s2", "frame": 120, "time": 4.0,
               "issue": "…", "evidence": "…", "correction": "…"}]}
```

Then run `critic-record`. It refuses a record when:
- `reviewer` is not the critic agent;
- the pack is not the current one (a stale review);
- a finding lacks scene/frame/time, issue, evidence or correction.

The stricter of the stated and implied verdict wins: BLOCKING → FAIL,
MAJOR or MINOR → WARN. A WARN never blocks.

**Strict mode only:** a critic FAIL blocks the render. `max_fix_iterations`
defaults to 1, so the first FAIL round exits 3 (ESCALATE) and a human decides;
there is no automatic repeated fix loop. History (issue → fix → result per hash)
stays in `production/state.json` and is listed in the report.

## Render gate

`render` refuses to run (`DO NOT RENDER — …` with every reason) when:
- a local asset or font file is missing (re-checked live);
- `brief`, `spec` or `validation` is FAIL, STALE or NOT RUN;
- any pre-render stage is FAIL;
- in strict mode (`--critics` / `policy.require_review`), stills and both critics are not PASS/WARN;
- with `policy.warnings_block`, a required stage is WARN.

It also refuses to overwrite an existing render it did not produce (`--overwrite`).

`--override "<reason>"` bypasses the gate. The reason and the bypassed gates are
stored in the stage history and printed in every report. Nothing is bypassed
silently.

## Post-render QA and audio

QA uses the existing review tooling (`review/process.py`, `review/pixels.py`):
- ERROR: output missing; resolution, fps, duration (±1 frame), frame count
  (±1) or codec off brief; first frame empty or near-black; an audio stream in
  a silent project.
- WARNING: last frame empty; non-yuv420p; near-empty spans and scene-boundary
  coverage dips (thresholds `review/rules/defaults.json → pixels.diagnostics`).

Pre-render validation checks composition data. QA checks the encoded file.

Audio follows the brief:
- `none` → `SKIPPED` (QA verifies 0 audio streams).
- Otherwise:
  - a stream is required (FAIL);
  - audio and video durations must agree within 0.1 s + 1 frame (WARN);
  - EBU R128 true peak above 0 dBTP is clipping (FAIL), above −1 dBTP is a WARN;
  - integrated loudness more than 2 LU off `loudness_lufs` is a WARN.
- A/V sync is not measured automatically; the report says so.

## Production report

```
PRODUCTION REPORT — adr3 (hash 7849a79679db)

Brief ..............  PASS
Spec ...............  PASS
Build ..............  PASS
Validation .........  WARN
Stills .............  PASS
Motion Critic ......  FAIL  — 8 finding(s): 1 blocking, 5 major, 2 minor
Design Critic ......  FAIL  — 8 finding(s): 1 blocking, 5 major, 2 minor
Render .............  NOT RUN
Post-render QA .....  NOT RUN
Audio ..............  NOT RUN

Numeric trace: PASS (trace; 870 frames, 171 elements, 978 tracks kept, 1.95s)
Warnings: 6
Blocking errors: 12
Fix iterations (critic FAIL rounds): 1

Timing: validation 3.0s, stills 14.3s
```

## Limitations

- Critic agents run outside Python. The pipeline waits for their recorded
  verdict and never fabricates one.
- The trace sees DOM state. Pixel-level emptiness (faint content on a matching
  background) is caught by post-render QA and the critics, not by the trace.
  Canvas/WebGL internals need the `window.__msTrace` probe.
- Text overflow and contrast come from `hyperframes check`. `--no-check` is
  reported as a WARNING.
- A/V sync is not measured.
