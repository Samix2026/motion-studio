# templates/business-learning-ar

Starter for short Arabic educational videos built from a source-driven lesson
in `../../learning/lessons/`. Any topic; the lesson comes from the sources the
user supplies.
9:16 first, silent, Alexandria.

**Status: grammar and starter ready; no lesson video yet.** `starter/` is a
validated demo of the `process_flow` grammar (generic labels, not a lesson).

## Use it

Follow `../../LEARNING_WORKFLOW.md` from source to render. This template adds
only the project setup for Stage B:

- **Project.** Create `videos/<slug>/` per `../../VIDEO_WORKFLOW.md`
  §Project convention. In `meta.json` add
  `"lesson": "learning/lessons/<lesson-id>/lesson.json"`, the manifest from
  `TEMPLATE_RULES.md` §9, and `outputs` (copy it from `starter/meta.json`).
- **Brief.** `BRIEF.md` states duration and "silent" (unless audio is
  explicitly requested; `../../AUDIO_DESIGN.md` §0).
- **Visual inspiration.** Write `visual_inspiration.md` and pick one style
  direction before the storyboard (`../../VIDEO_WORKFLOW.md` §Visual
  inspiration and style direction).
- **Storyboard.** Copy `storyboard.md` and fill one block per scene.
- **Composition.** Copy `starter/` into `videos/<slug>/` (keep `lib/` and
  `assets/fonts/` byte-identical) and replace the demo scenes. Scene layouts
  come from the shared registry; operations use `process_flow`.

## Check

```bash
python3 templates/tech-news-ar/tools/check-tashkeel.py videos/<slug>   # tashkeel + banned word
python3 templates/tech-news-ar/tools/check-tashkeel.py learning
```

## Files

- `TEMPLATE_RULES.md` — narrative flow, role → beat-kind mapping, copy,
  numbers, visual explanation, typography, series identity.
- `storyboard.md` — storyboard template (Arabic).
- `starter/` — `index.html` (3-scene `process_flow` demo: line neutral, line
  problem with a queue, floor problem → after), `lib/` (copy of
  `../tech-news-ar/lib`), `assets/fonts/` (Alexandria + OFL).

Global rules stay in their owners: `../../CONTENT_RULES.md`,
`../../CONTEXT_SCOPE.md`, `../../AUDIO_DESIGN.md`, `../../ASSET_POLICY.md`,
`../../QUALITY_SCORE.md`.
