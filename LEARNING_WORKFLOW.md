# LEARNING_WORKFLOW.md — source-driven educational video, end to end

The single authoritative production workflow for educational videos: from the
sources a user supplies to a verified vertical master and optional platform
outputs. Any capable coding/research agent follows it as written; it assumes
only file editing, a shell, and web access.

This file owns the **sequence and the gates**. Rules for each step live with
their owner and are linked, not repeated:

| Owner | Owns |
|---|---|
| `learning/README.md` | Lesson package, `brief.json` / `research.md` / `lesson.json` formats, claim classification, conflicts, source quality |
| `templates/business-learning-ar/TEMPLATE_RULES.md` | Narrative flow, copy, numbers on screen, storyboard and visual rules, typography |
| `VIDEO_WORKFLOW.md` | Global production mechanics: project layout, `meta.json` and `outputs`, validation, render, safe zones, grammar registry |
| `CONTENT_RULES.md`, `CONTEXT_SCOPE.md`, `AUDIO_DESIGN.md`, `ASSET_POLICY.md` | Language, brand/context, audio, asset provenance |
| `AI_REVIEW.md`, `QUALITY_SCORE.md` | Review layer and publish gate |

## Stage A — Sources and research (`learning/lessons/<lesson-id>/`)

1. **Receive the source(s).** The user supplies 1–2 primary sources. They stay
   the primary basis of the lesson (`learning/README.md` §Primary sources).
2. **Create or update `brief.json`**: topic, audience, goal, language, primary
   sources, research policy, research questions.
3. **Open and inspect every primary source.** Never work from a title, summary,
   or memory of it. Save a local copy in `sources/` when the source is a file.
4. **Record them in `sources.md`.**
5. **Extract the supported claims** — what the primary sources actually say.
6. **Identify gaps**: missing definitions, unchecked numbers, a missing
   practical example, likely misconceptions.
7. **Supplementary research — only if `brief.json` → `research` is `allowed`
   or `required`.** Limit it to the gaps and research questions; stay on the
   user's topic. Register every source opened in `sources.md`.
8. **Verify** important definitions, numbers, and claims against opened
   sources. Classify every claim (`learning/README.md` §Claim classification).
9. **Record uncertainty and conflicts** (`learning/README.md` §Conflicts).
10. **Write `research.md`** in the required structure (`learning/README.md`
    §research.md).
11. **Select one educational angle** and record it with a one-line reason in
    `research.md` §Angle. One short video explains one thing; it never
    summarizes a whole source.
12. **Create or update `lesson.json`** from `research.md` only.

**Research gate.** `script.md` is never written from source material directly:

```text
source(s) → research.md → lesson.json → script.md
```

Before Stage B, `research.md` has an angle, no `unsupported` claim is in
`lesson.json`, and no conflict that materially affects the angle is
`unresolved`. If one is, **stop and surface it to the user** before scripting.

## Stage B — Video project (`videos/<slug>/`)

Create the project per `VIDEO_WORKFLOW.md` §Project convention, record
`"lesson"` in `meta.json`, and copy the template starter
(`templates/business-learning-ar/README.md`).

13. **Write `script.md`.** It belongs to the video, not the lesson; different
    outputs may adapt the same lesson differently. Flow and copy rules:
    `TEMPLATE_RULES.md` §2, §4, §5. Draft first, then pass the writing-quality
    gate (`CONTENT_RULES.md` §Writing-quality gate); `script.md` keeps the
    final copy only.
    **Visual inspiration gate.** After the final script and before step 14, gather references, write
    `visual_inspiration.md`, and select one style direction
    (`VIDEO_WORKFLOW.md` §Visual inspiration and style direction).
14. **Write `storyboard.md`.** Every scene names its lesson field, its
    `research.md` evidence, and the question its visual answers
    (`TEMPLATE_RULES.md` §6).
15. **Build the composition** (`VIDEO_WORKFLOW.md` §Steps 6–7, §Scene grammar).
16. **Validate**: `npx hyperframes@0.8.35 lint .` and `npx hyperframes@0.8.35 check .`
    (`VIDEO_WORKFLOW.md` §Step 8); `python3 design/cli.py validate <project>`,
    `fonts <project> --render`, `readability <project>`; the tashkeel check
    (`templates/business-learning-ar/README.md` §Check). Clear errors before
    previewing.

## Stage C — Preview gate

17. **Generate preview frames** at every scene's key state
    (`npx hyperframes@0.8.35 check . --at <times> --snapshots`), not only scene
    midpoints when a scene changes state. Review each frame for:
    - hierarchy and mobile readability at 1080×1920;
    - text density (one idea per scene);
    - whether the visual explains the idea, not only decorates the text;
    - motion that is functional, not decorative;
    - source and number accuracy against `lesson.json` / `research.md`;
    - illustrative labels wherever illustrative content appears;
    - safe zones (`VIDEO_WORKFLOW.md` §Safe zones);
    - continuity between scenes;
    - whether it reads as content, not a slide deck.
18. **Wait for user approval.** Validation passing is not approval. Never
    render the final output before the user approves the preview.

## Stage D — Master and platform outputs

19. **Render the vertical master** — 9:16, 1080×1920 — to `renders/video.mp4`
    (`VIDEO_WORKFLOW.md` §Step 9).
20. **Verify the file** with `ffprobe`: duration, resolution, fps, codec
    (H.264), pixel format, and audio stream count (0 unless the brief asked for
    audio). Then run a final visual review of frames from the render.
21. **Platform outputs — only when requested.** Read `meta.json` → `outputs`
    (`VIDEO_WORKFLOW.md` §Platform outputs):
    - every enabled platform uses the master file by default;
    - create a separate export only when a platform has a real override that
      changes the file (e.g. `trim`); never four identical files for four
      platforms;
    - caption, CTA, and cover are post metadata, written in `outputs`, never in
      the lesson;
    - verify any platform limit you rely on from a current official source
      first (`VIDEO_WORKFLOW.md` §Platform outputs → Platform facts).

No publishing, uploading, or scheduling is part of this workflow. After the
user publishes, `tools/mark-published.py` records it.
