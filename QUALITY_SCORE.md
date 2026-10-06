# QUALITY_SCORE.md — publish gate for Arabic tech-news videos

A deterministic quality gate for every production run. It produces a single
score (0–100) plus a publish decision. The score and decision are recorded in
that run's `runs/<run-id>.json` (see `RUN_METRICS.md`).

Scoring is not a substitute for the automated gates: `lint`, `check
--snapshots`, and `ffprobe` must pass first (see `VIDEO_WORKFLOW.md`).

## Hard fail conditions

**Any** hard fail forces **Do not publish**, regardless of the numeric score.

- Unverified factual claim.
- Missing source attribution.
- Untracked external asset (a file in `assets/` not recorded in `sources.md`).
- Unnecessary Arabic tashkeel (see `CONTENT_RULES.md`).
- Broken RTL rendering (wrong bidi order, mirrored layout, unshaped Arabic).
- Clipped or overflowing text.
- Incorrect company / product / person / place name.
- Failed HyperFrames validation (`lint` or `check` not clean).
- Final output not matching the required resolution / fps / codec.
- Audio the brief did not request: any audio stream, `<audio>` element, music,
  SFX, ambience, or narration in a project whose brief does not request it
  (`AUDIO_DESIGN.md` §0).

A hard fail is recorded as `"hard_fail_triggered": true` with the reason in
`notes`, even if the arithmetic score would otherwise pass.

## Scoring (total 100)

| # | Category | Max | What it measures |
|---|----------|-----|------------------|
| 1 | Accuracy & sourcing | 30 | Every claim verified against primary sources; every asset tracked; no invented fact/number/quote/date. |
| 2 | Hook & editorial clarity | 20 | Strongest fact first; 5-beat structure; no filler; measured tone; clear takeaway. |
| 3 | Visual quality | 15 | Hierarchy, composition, hook, repetition, screenshot treatment, phone readability. **Independent source only** (see below). |
| 4 | Asset quality | 10 | Official/primary media, correct crops, no fabricated data visible, legible. |
| 5 | Brand identity fit | 10 | Profile matches primary company; inspired-by, not a look-alike; restrained. |
| 6 | Arabic / RTL quality | 10 | Correct RTL, no tashkeel, clean Arabic typography, bidi-safe Latin mixing. |
| 7 | Technical validation | 5 | Lint/check clean, snapshots inspected, ffprobe matches spec, and 0 audio streams unless the brief requests audio, and audio checks pass when it does. |

### Category bands
Score each category proportionally to its share:

- **90–100%** — no material issue.
- **75–89%** — minor issues that do not mislead or break rendering.
- **50–74%** — a real defect a reviewer must fix before publish.
- **< 50%** — category failed.

### Evidence required per category
- **Accuracy & sourcing** — `sources.md` claim table + asset table; spot-check.
- **Hook & editorial clarity** — `script.md` beats; does the opening carry the
  strongest verified fact.
- **Visual quality** — a multimodal visual review (`review/cli.py vision`,
  score = mean judgment / 5 × 15) or a human reviewer at Gate 2. Never the
  producing agent.
- **Asset quality** — `assets/` review + on-screen credits.
- **Brand identity fit** — selected `brands/<id>.json` vs the story's subject.
- **Arabic / RTL quality** — tashkeel guard clean + frame inspection.
- **Technical validation** — recorded command results.

## Scorecard (copy into the run record)

| Category | Max | Score | Evidence |
|----------|-----|-------|----------|
| Accuracy & sourcing | 30 | | |
| Hook & editorial clarity | 20 | | |
| Visual quality | 15 | | |
| Asset quality | 10 | | |
| Brand identity fit | 10 | | |
| Arabic / RTL quality | 10 | | |
| Technical validation | 5 | | |
| **Total** | **100** | | |

## Audio quality checks

Silent is the default (`AUDIO_DESIGN.md` §0). A silent video can score full
marks; its only audio check is **0 audio streams** in the final MP4. When the
brief requests audio, also verify:

- Sound matches a visible action; no unrelated or random sounds.
- No unnecessary SFX; no repetitive effects.
- Timing is synchronized with the motion.
- Music is not too loud and does not reduce readability (ducked under cues).
- No clipping (true peak ≤ −1 dBTP); no abrupt cuts or dropouts.
- No missing audio assets.
- Every external audio source is documented in `sources.md`.
- The final MP4 contains the expected audio stream (AAC, 48 kHz preferred).
- Audio duration matches video duration.

These checks sit inside the **Technical validation** category. A missing audio
stream is a defect only when the brief requested audio; an audio stream the
brief did not request is a hard fail (above).

## Visual quality source (no self-grading)

Earlier runs self-scored visual quality at 14–15/15 every time. Now:

- The six **measured** categories (85 points) are scored as before, with the
  same evidence and hard fails.
- **Visual quality (15)** is recorded with `visual_quality_source`:
  `multimodal_review` or `human_review`. The producing agent may not score it;
  `review/quality.py` rejects a self-score.
- Until the independent review happens, the run is **not closed**: the interim
  result has `visual_quality_status: not_independently_reviewed`, no total, and
  a decision from the measured score normalized to 100, capped at **Minor review
  required** (`ready_to_publish: false`). A new run record is never written in
  this state: get the visual score at the human review of the render, then
  record a non-null `quality_score` (`RUN_METRICS.md` §Required for new runs).
  Only records from before 2026-10-04 carry `quality_score: null`.
- Multimodal findings are AI judgment: they inform the visual score and
  proposals but **never** trigger a hard fail.
- Deterministic rendered checks (frame 0, frozen holds, duplicate frames, text
  density, phone readability) are measured facts that feed Technical validation
  and the reviewer's proposals.

```python
from review import quality
quality.score(measured_breakdown, visual={"score": 12.6, "source": "multimodal_review"}, hard_fails=[])
```

## Decision

| Total score | Decision |
|-------------|----------|
| 90–100 | **Ready to publish** |
| 80–89 | **Minor review required** |
| below 80 | **Do not publish** |
| any hard fail | **Do not publish**, regardless of score |

`ready_to_publish` is `true` only for **Ready to publish**. For
**Minor review required**, it is `false` until the review is done and the score
is re-run.

## Procedure

1. Confirm the automated gates passed: `lint`, `check --snapshots`, `ffprobe`.
2. Check the hard-fail list against the project; record any hit.
3. Score the six measured categories, citing evidence.
4. Take visual quality from an independent review. On the standard path that is
   the human review of the render: ask for the 0–15 visual score there, so
   `quality_score` is never left `null` (`RUN_METRICS.md` §Required for new runs).
5. Compute with `review/quality.py` (the sum; the normalized figure is only the
   interim result before the visual score is in).
6. Apply the decision table, overridden by any hard fail.
7. Write `quality_score`, `quality_breakdown`, `visual_quality_source`,
   `visual_quality_status`, `hard_fail_triggered`, and `ready_to_publish`
   into the run's `runs/<run-id>.json`.
8. If not **Ready to publish**, fix and re-run the gate; do not publish.
