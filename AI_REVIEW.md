# AI_REVIEW.md — AI Video Review & Approval Layer (V1)

A measured, non-destructive review layer on top of the existing motion-studio
system. It inspects a HyperFrames project, reports **evidence-backed findings**,
proposes fixes as **separate structured proposals**, and can apply **only what a
human explicitly approves** — to a **new project version**, never to the source.

The AI reviewer **never** edits a video project. It may only inspect, measure,
report, and propose.

## Pipeline position

```
Script → Assets → Composition → Preview Render → Deterministic Analysis
  → AI Review → Proposed Fixes → Human Approve/Reject
  → Apply approved changes only → Render V2 → Quality Gate
```

This layer implements the boxed middle: analysis → review → proposals →
approval → apply-to-new-version. Rendering continues to use the existing
HyperFrames/GSAP/FFmpeg pipeline, unchanged.

## Architecture

```
review/
  cli.py               # review | report | approve | reject | apply | status
  htmlmodel.py         # deterministic parse of index.html (scenes, audio, GSAP, CSS)
  analyzer.py          # measurements -> findings (+ unavailable checks)
  reviewer.py          # findings -> proposals (measured vs judgment kept separate)
  proposal_schema.py   # strict validation; operation whitelist
  proposal_engine.py   # simulate an operation; before/after + warnings (no writes)
  apply_proposal.py    # apply approved ops to a NEW version dir only
  revision.py          # content hash + revision state + stale detection
  rules/defaults.json  # thresholds
  state/               # <state_key>.json  (revision, content_hash, history)
  proposals/           # <state_key>-rev<N>.json
  reports/             # <state_key>-rev<N>.md / .json
  tests/               # unittest suite + synthetic fixture
```

Language: **stdlib Python** (matches `templates/tech-news-ar/tools/`). No new
framework, no new runtime dependency.

## What the analyzer measures

Everything is read from the project's own files; when a measurement is not
available the check is reported under `unavailable` instead of being invented.

- **scene pacing** — scene durations, per-scene **static hold** (scene end −
  last timeline event end inside the scene), duration outliers vs the median.
- **sfx timing** — each `<audio>` SFX start vs the nearest GSAP event start
  (signed offset in ms).
- **music / silence gaps** — music lead/tail vs composition duration, missing
  music ducking while SFX exist, and `ffmpeg silencedetect` regions on the
  rendered audio (when a render exists).
- **text readability** — CSS font sizes and WCAG contrast for secondary classes
  (`.sub`, `.note`, `.shotcap`, `.wcap`, `.src`).
- **caption / audio sync** — real, when a canonical `word-timings.json` exists
  (see `WORD_SYNC.md`): measures captions that begin before speech or end before
  the spoken phrase, in milliseconds, with a 150 ms tolerance. Without word
  timings it stays **unavailable** — never inferred from character counts.

Rendered-output and layout checks (deterministic, FFmpeg + stdlib; thresholds in
`rules/defaults.json` → `pixels`, calibrated on existing renders):

- **frame_zero** — content coverage of frame 0 and of the 0.5s frame (pixels
  differing from the dominant background luma); near-empty openings are `high`.
- **rendered_freeze** — FFmpeg `freezedetect` on the content area (top 10% and
  bottom 14% cropped so a filling progress bar cannot hide a frozen scene);
  holds ≥ 2.5s are reported, ≥ 4s `high`. Complements the timeline static hold.
- **shot_diversity** — 256-bit difference hash of each scene's midpoint frame;
  pairs within 28 bits (≈89% similar) are reported.
- **text_density** — visible words per scene from the DOM; > 4 words/s or
  > 26 words per scene.
- **mobile_readability** — CSS size (px or `var(--ts-*)`) scaled to a 390px
  phone, against the per-format minimums in `lib/type-scale.json`. Px classes get
  a `change_text_size` proposal; type-scale classes are layout knobs.

Without a render, the three pixel checks are `unavailable`. All are MEASURED FACT.

Optional read-only inputs: `ffprobe` metadata, snapshot filenames, current
quality docs.

## Findings (strict schema)

```json
{
  "id": "finding-001",
  "category": "scene_pacing",
  "severity": "low | medium | high",
  "scene": 2,
  "evidence": { "measured_value": 1.1, "unit": "seconds", "source": "timeline" },
  "description": "Final visual state remains static for 1.1 seconds.",
  "confidence": 0.91
}
```

`category` ∈ {scene_pacing, text_readability, caption_audio_sync, sfx_timing,
music_silence_gaps, frame_zero, rendered_freeze, shot_diversity, text_density,
mobile_readability, long_hold, empty_frame, boundary_dip, visual_judgment}. Every finding is evidence-backed.

`basis` is `MEASURED_FACT` (default; numeric `measured_value`) or `AI_JUDGMENT`
(only `visual_judgment`; `measured: false`, `measured_value: null`, a `judgment`
object with dimension, score 1–5 and rationale; never `hard_fail`). The schema
rejects any mix of the two.

## Proposals (separate, never auto-applied)

```json
{
  "id": "proposal-001",
  "project_revision": 7,
  "project_hash": "<sha256 of review-relevant files>",
  "finding_id": "finding-001",
  "title": "Tighten scene 2",
  "rationale": "The final state remains static longer than required.",
  "operation": { "type": "adjust_scene_duration", "scene": 2, "from": 5.2, "to": 4.4, "ripple": true },
  "duration_before": 34.0,
  "duration_after": 33.2,
  "warnings": [],
  "confidence": 0.91,
  "status": "awaiting_review",
  "basis": { "measured_facts": ["static hold = 1.1s (timeline)"], "judgment": "trim 0.7s" }
}
```

`basis` keeps **MEASURED FACT** and **AI JUDGMENT** separate: the analyzer
measures, the reviewer interprets.

### Supported operations (V1 whitelist)

`adjust_scene_duration` (ripple), `move_caption`, `adjust_caption_end`,
`shift_sfx`, `adjust_music_ducking`, `remove_silence`, `change_text_size`,
`change_text_contrast`, `adjust_animation_start`, `adjust_animation_duration`.

Layout operations (V2), attribute / custom-property edits on scene-grammar
scenes only — legacy scenes without `data-grammar` are rejected at simulation:

| Operation | Edit | Bounds |
|-----------|------|--------|
| `swap_layout_variant` | `data-variant` on the scene | variant must exist in `grammars.json` |
| `add_push_in` | `data-push-in` on an img/video/figure id in the scene | scale 1.02–1.12; grammar must allow `push_in` |
| `enlarge_secondary_text` | `--secondary-scale` on the scene | 1.05–1.3 |
| `increase_media_scale` | `--media-scale` on the scene | 1.05–1.25 |
| `reduce_empty_space` | `data-density="tight"` | — |

Multimodal proposals (`origin: "multimodal"`) may use **only** these five.
Arbitrary shell commands and arbitrary source-code edits are **rejected by the
schema**. An operation with no target in a project (e.g. captions when none
exist) is rejected at simulation time.

## Multimodal visual review (V2, interface + offline fixtures)

```
Preview render → deterministic review → rendered-frame visual review
  → AI_JUDGMENT findings → existing proposals file → Gate 2
```

- `review/vision.py` `build_inputs()` extracts, into `review/vision_inputs/`
  (never the project): a contact sheet of beat midpoints, each midpoint frame,
  hook frames at 0/0.5/1.0/1.5s, and 3-frame strips across every transition,
  plus metadata (brand, format, layout signature, scene grammars and text).
- A `VisionProvider` returns judgments on nine dimensions: hook_strength,
  visual_hierarchy, composition_balance, empty_space, visual_repetition,
  screenshot_treatment, brand_consistency, transition_quality,
  mobile_readability. Only `FixtureProvider` (recorded JSON) ships; no provider
  is called in implementation or tests.
- Findings are `AI_JUDGMENT`. A `hard_fail` in a judgment is ignored and noted.
  Suggested operations outside the layout whitelist are dropped with a note;
  valid ones are simulated and saved as `awaiting_review` proposals.
- **Cost Gate hook:** a provider with `requires_payment=True` raises
  `CostGateBlocked` until the project's Cost Gate is approved.
  `cost_plan_items()` produces the plan item (`external_api`, `unit_basis:
  image`); its price stays UNKNOWN until `costgate/pricing.json` has a verified
  entry.
- Visual quality for `QUALITY_SCORE.md` = mean judgment score / 5 × 15, source
  `multimodal_review`.

Deterministic vs multimodal: timing, sync, contrast, font loading, frame 0,
freezes, near-duplicate frames, text density and phone-scale size stay
deterministic. Hook strength, hierarchy, balance, empty space, repetition feel,
screenshot treatment, brand consistency and transition quality are judgment.

```bash
python3 review/cli.py vision videos/<project>                          # inputs + cost plan item only
python3 review/cli.py vision videos/<project> --fixture judgments.json # offline review, merges proposals
```

## Revision locking

- State lives in `review/state/<state_key>.json` (key = slug + short hash of the
  absolute path). The project itself is never written.
- `content_hash` = sha256 of `index.html`, `script.md`, `storyboard.md`,
  `sources.md`, `meta.json`, plus the audio asset inventory.
- Each proposal records `project_revision` and `project_hash`.
- On apply, if the project's current hash differs → **STALE**:

```
STALE — proposal cannot be applied: proposal-001 targets revision 7 but the project has changed
```

## Approval workflow

```bash
python3 review/cli.py review  videos/<project>              # analyze + propose (read-only)
python3 review/cli.py report  videos/<project>              # print the latest report
python3 review/cli.py approve videos/<project> --index 1 3  # approve 1 and 3
python3 review/cli.py reject  videos/<project> --index 2    # reject 2
python3 review/cli.py apply   videos/<project>              # apply approved -> new version
python3 review/cli.py apply   videos/<project> --preview     # dry run, writes nothing
python3 review/cli.py status  videos/<project>
```

`approve`/`reject` only change proposal status. `apply`:

- takes **only approved** proposals,
- copies the project to a **new sibling directory** `<slug>-rev<N>`,
- applies whitelisted edits there, re-parses the result and verifies the
  resulting duration matches the simulation,
- runs the project's `check-tashkeel.py` guard on the new version,
- bumps the revision and writes an audit entry,
- **never overwrites the source project or an existing render** (the new version
  deliberately carries no `renders/`).

## Before/after simulation

Every proposal is simulated before saving: timing validity, `duration_before` /
`duration_after`, and side-effect warnings (e.g. "music bed may no longer cover
the new timeline", "duck depth outside a safe range"). The simulation mutates
only an in-memory model — the real project is untouched.

## Preview mode

Interface is in place (`apply --preview`): it prints the exact edit plan and the
local render command, and writes nothing. **Rendering the preview is deferred to
V2** (the CLI prints the command instead of running it).

## Example report

```
AI VIDEO REVIEW

Project: <project-slug>
Revision: 1

Findings: 4

[1] Scene Pacing
Severity: medium
Scene 2
Measured: final hold 1.1s (timeline)
Proposal: Tighten scene 2
Operation: {"type": "adjust_scene_duration", "scene": 2, "from": 5.2, "to": 4.4, "ripple": true}
Impact: 34.0s -> 33.2s
Confidence: 0.91
Status: awaiting_review

[2] Sfx Timing
Severity: medium
Measured: offset 0.32 seconds (audio+timeline)
Proposal: Align SFX 'au-click' with the visible event
Status: awaiting_review

Unavailable checks:
- caption_audio_sync: no transcript.json and no caption elements; timing unavailable

No changes have been applied.
```

A machine-readable copy is saved next to it as `reports/<state_key>-rev<N>.json`.

## Style metadata (reference) is context, never a defect

Reference style profiles (`REFERENCE_ANALYZER.md`) are optional planning
context. The analyzer does **not** read them and differences from a reference
must **never** become automatic findings, proposals, or failures. If a future
Review V2 surfaces style context, it must be non-scoring and clearly separated
from measured facts.

## Running the tests

```bash
python3 -m unittest discover -s review/tests -v
# or: pytest review/tests -q
```

Coverage: proposal creation does not alter the project; approved proposal creates
a new revision; rejected proposal changes nothing; stale proposal cannot be
applied; duration_before/after correct; unsupported operation rejected; missing
evidence does not become a finding; existing render untouched; RTL/no-tashkeel
checks still pass; apply refuses an existing target. Tests use a synthetic
fixture (`tests/fixtures/mini_project`) and never touch a real video project.

## Advisory diagnostics and the optional visual critic

Validated in the 2026-09-30 critic pilot (DeepSeek v1 → rev2: preferred by a
blind pairwise critic in both label positions and by the human in a blind A/B).

**Advisory diagnostics** (deterministic, part of `review`; thresholds in
`rules/defaults.json` → `pixels.diagnostics`):

| Check | Measures | Finding |
|---|---|---|
| near-still | seconds whose 10 fps frame difference (content crop) stays below 0.05 | none — context only |
| `long_hold` | a near-still hold longer than 2 s | low, "Advisory:" |
| `empty_frame` | frames after 0.5 s with content coverage below 0.01 | medium, "Advisory:" |
| `boundary_dip` | coverage around a scene boundary below 35% of the nearby median | low, "Advisory:" |

They are MEASURED FACT, never a hard fail, never a proposal. Any pixel change
counts as motion, so footage, grain or drifting particles read as moving:
near-still time is context, not a quality verdict.

**Optional visual critic.** One independent read-only agent
(`.claude/agents/visual-critic.md`) reviews a prepared pack; it never browses
the project.

```bash
python3 review/cli.py critic-pack videos/<project> --render <render.mp4>
python3 review/cli.py critic-pack videos/<project> --render <old.mp4> --pair <new.mp4>   # blind pairwise
```

The command prints a one-turn prompt (`Pack: … · Read in one turn: …`) for the
`visual-critic` agent. The diagnostic pack is exactly three composite images
(1 fps sheet, frame 0 + beat midpoints, 5-frame strips around each boundary)
plus `pack.md` (format, video type and viewer job, beat table, series
constraints, the diagnostics as facts). The brief and storyboard are not
included. The critic returns at most 6 DEFECT/OPPORTUNITY findings with
severity, confidence, timestamp, evidence and direction. The pairwise pack
holds one sheet and six key frames per render with random A/B labels; the
mapping is sealed in `<pack>.mapping.json` and revealed only after the verdict.

Invariants: no visual scores, no publish gate, no automatic fixes, no automatic
critic loops (at most one diagnostic pass and one pairwise pass per video unless
the human asks). Findings are addressed, if at all, by the builder in a new
revision; human creative approval (Gate 2) stays final.

**When to run.** Run the diagnostic critic when: any `empty_frame` finding or a
`long_hold` over 2 s; a human judges the preview "basic"; a flagship or
model-showcase video; ambitious Three.js/WebGL work; the first use of a new
visual system. Near-still time alone never triggers it. Run pairwise only when a
significant revision exists (scenes restructured, not text edits). Skip for fast
news on a proven template with clean diagnostics, text/fact/caption/audio-only
re-renders, and minor changes to an approved video.

**Cost (measured in the pilot).** Diagnostic run ≈ 33k tokens, ≈ 21 s; pairwise
≈ 36k tokens, ≈ 23 s (headless `claude -p --agent visual-critic`). Every extra
agent turn re-sends ≈ 11–13k tokens of base context, so the critic reads all
pack files in one turn. Pack build ≈ 6 s; diagnostics ≈ 2–3 s per 30 s render.

## Safety rules (invariants)

- Never overwrite the source project.
- Never modify an existing published render.
- Never auto-approve; never apply during review.
- Never invent transcript/audio timing; missing data → `unavailable`.
- Preserve Arabic RTL, no-tashkeel, brand profile, factual wording, and
  `sources.md` provenance.
- No new external assets and no paid API calls during review.

## V1 limitations

- Static holds and SFX offsets come from parsing the GSAP timeline text pattern;
  unusual/nested timelines may be reported as unavailable rather than guessed.
- Text overflow and safe-zone violations are estimated from CSS; exact pixel
  geometry remains HyperFrames' `check` job.
- Caption/voiceover sync is `unavailable` until a transcript exists (no V1
  analysis of word timings).
- `adjust_scene_duration` uses ripple semantics; in-scene motion is preserved
  and only later scenes/audio/timeline shift.
- Preview rendering is not implemented (interface only).
- Revision state is a local file (no multi-user locking).

## V2 limitations

- No live multimodal provider: the interface, schema, Cost Gate hook and
  fixtures exist; wiring a real model needs verified pricing and approval.
- dHash similarity is weak on flat, dark frames (few edges): legacy dark
  videos can look diverse to it. It is a signal, not a verdict.
- Freeze detection crops fixed chrome bands; chrome placed elsewhere can still
  mask a hold. Text density counts DOM words per scene, not per visible moment.
- Phone readability is computed from CSS size, not measured glyph height.
- `cmd_status` in `review/cli.py` references an undefined `slug` (pre-existing).

## Future ideas

- Live multimodal provider behind the Cost Gate; side-by-side V1/V2 previews.
- Asset-quality review (resolution, provenance completeness).
- Cross-video pixel similarity for novelty (today novelty uses layout signatures).
- Undo/history UI over the audit trail.
