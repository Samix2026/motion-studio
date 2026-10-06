# Motion Studio

An AI-native motion graphics production toolkit: workflow rules, templates and
quality gates that let an AI coding agent turn a brief into a structured,
validated, renderable [HyperFrames](https://github.com/heygen-com/hyperframes)
video project. Arabic/RTL-first.

Status: early, pre-1.0, single maintainer. It works end to end today for one
kind of video (short Arabic explainer / tech-news motion graphics) and is
published so others can use, adapt and extend it.

## What it is

Each video is one HTML composition (GSAP timeline, deterministic, seek-safe)
rendered to MP4 by HyperFrames. Writing that composition well is the hard part.
Motion Studio gives a coding agent — and the human reviewing it — three things:

1. **A workflow to follow.** `VIDEO_WORKFLOW.md` takes a brief through source
   verification, storyboard, script, composition, validation, render and review,
   with two human gates: cost approval before anything paid, and review of the
   render.
2. **Starting points.** Templates with a type system, motion primitives, a
   scene-grammar library, brand profiles and bundled Arabic fonts.
3. **Gates that run as code.** A Python CLI that validates a project before the
   expensive render, blocks the render while a blocking problem exists, checks
   the result afterwards and records what happened.

## What problem it solves

An agent asked to "make a video" tends to produce text-heavy slides, skip
verification, render too early and call the result done. Motion Studio makes the
process explicit and checkable: declared format and font, a visual story per
scene, layout/contrast/motion checks, a render gate, post-render QA, and a run
record with time and quality score.

## What it can do today

- Run a gated pipeline on a project: brief → spec → build → validation → render
  → QA (`studio/cli.py production`).
- Validate without rendering, in seconds (`studio/cli.py validate`).
- Check typography, mobile readability, scene grammar, brand resolution and
  layout novelty (`design/cli.py`).
- Analyse a rendered video and propose fixes; build packs for optional
  motion/design/visual critic agents (`review/cli.py`, `.claude/agents/`).
- Plan narration and group word timings into captions (`narration/cli.py`,
  `timing/cli.py`).
- Clean up reproducible artifacts safely (`studio/cli.py cleanup`).

## Who it is for

Developers and motion designers who already work with an AI coding agent
(developed with Claude Code) and want repeatable, reviewable video production
rather than one-off prompts — especially for Arabic content.

## What it is not

- Not a render engine. HyperFrames renders; Motion Studio wraps it.
- Not autonomous. An agent writes the composition by following the workflow, and
  a human reviews the result. No code here turns a brief into a video by itself.
- Not a hosted service, SaaS or GUI. It is a repository you clone and run locally.
- Not a general video editor, and not yet tuned for non-Arabic content.

## Prerequisites

| Need | Notes |
|---|---|
| Python 3.9+ | Standard library only; no `pip install`. Tested on 3.9, 3.11 and 3.14. |
| Node.js 22+ | Required by HyperFrames (`engines: node >=22` in the pinned package). Motion Studio itself was run on Node 26 only. |
| FFmpeg + FFprobe | Rendering, QA, and some tests. |
| Chrome | Used by HyperFrames to render. |
| An AI coding agent | Needed to author videos, not to run the quick start. |

Check the HyperFrames side with:

```bash
npx --yes hyperframes@0.8.35 doctor
```

FFmpeg, FFprobe and Chrome must show ✓. Docker, TTS and music entries are
optional and may show ✗.

No environment variables or API keys are needed for the basic workflow. See
[`.env.example`](.env.example) for the optional ones.

## Install

```bash
git clone https://github.com/Samix2026/motion-studio.git motion-studio
cd motion-studio
```

There is nothing to build. To author videos with an agent, also install the
HyperFrames agent skills (they go to the Git-ignored `.agents/`):

```bash
npx --yes skills experimental_install --yes   # the 12 skills listed in skills-lock.json
# or choose skills from upstream:
npx --yes skills add heygen-com/hyperframes
```

The skills are reference material for the agent. The Python tooling does not
import them, and the quick start below works without them. Installing may
rewrite `skills-lock.json`, because it is not a pin to a fixed upstream revision.

## 5-minute quick start

Render the bundled example through the full pipeline:

```bash
mkdir -p videos
cp -R templates/tech-news-ar/examples/grammar-demo-landscape videos/hello
python3 studio/cli.py production videos/hello
```

This validates the project, renders it and runs QA. The first run downloads the
pinned HyperFrames CLI; after that it takes about a minute. The output is
`videos/hello/renders/video.mp4`, and the report ends like this:

```
Brief ..............  PASS
Spec ...............  PASS
Build ..............  WARN
Validation .........  PASS
Render .............  PASS
Post-render QA .....  WARN
```

Warnings do not block; a `FAIL` does. The example uses placeholder images and
carries no social handle.

## Create your first project

Each video is a project under `videos/<slug>/` (Git-ignored).

```bash
npx --yes hyperframes@0.8.35 init videos/my-video \
  --non-interactive --example=blank --skill=motion-graphics --resolution=landscape
T=templates/tech-news-ar
cp $T/starter/standard.html videos/my-video/index.html
cp $T/sources.md $T/script.md $T/storyboard.md videos/my-video/
mkdir -p videos/my-video/assets/fonts videos/my-video/tools
cp $T/tools/check-tashkeel.py videos/my-video/tools/
cp -R $T/lib videos/my-video/lib
cp $T/assets/fonts/* videos/my-video/assets/fonts/
```

Then open the repository in your agent and ask it to produce the video,
following `VIDEO_WORKFLOW.md`. The agent fills `sources.md`, `storyboard.md`,
`script.md`, the project manifest in `meta.json`, and the scenes in `index.html`.

A freshly created project is expected to be **blocked**. Validation fails until:

- the storyboard describes what the viewer sees in every scene, and
- the starter's placeholder handle `@your_handle` is resolved: replace it in
  `index.html` with your own handle, or delete the handle element for a video
  without one. A handle is optional; the placeholder is never rendered.
  The choice is recorded in `meta.json` as
  `design_manifest.user_identity.show_handle` (`false` for no handle). A fresh
  `meta.json` has no `design_manifest` block until the project manifest is
  written (`CONTEXT_SCOPE.md` §5).

That is the gate working.

## Validate and render

```bash
python3 studio/cli.py validate videos/my-video     # brief + spec + build + pre-render checks, no render
python3 design/cli.py preflight videos/my-video    # project manifest and brand resolution
python3 studio/cli.py production videos/my-video   # every stage in order; stops at the first blocking gate
python3 studio/cli.py report videos/my-video       # the production report
```

`python3 studio/cli.py production <project>` is the supported way to render: it
runs the gates first. Calling HyperFrames' own render directly skips them.
Full reference: [`PRODUCTION.md`](PRODUCTION.md).

Optional: `python3 studio/cli.py trace <project> --install` installs a numeric
browser tracer outside the repository; without it the trace stage reports
`SKIPPED` and the pipeline continues.

## How HyperFrames fits in

HyperFrames (HeyGen, Apache-2.0) is the composition format, CLI and renderer.
Motion Studio calls it through `npx hyperframes@<version>`. It is not vendored
here. Templates load GSAP from the jsDelivr CDN, so rendering needs network
access.

### HyperFrames version policy

**Runtime.** The known-good HyperFrames version is **0.8.35**. It is defined
once, as `HYPERFRAMES_VERSION` in `studio/trace.py`. Every template, starter and
example pins it in `package.json`, the commands in the documentation name it,
and tests fail if any of them disagree. A project's own pin wins; a project
with no pin gets the known-good version. Nothing resolves to "latest"
implicitly. `studio/cli.py` reads the pin from the project's `package.json`.

Newer versions are not supported until someone upgrades deliberately:

1. Change `HYPERFRAMES_VERSION`, then replace the old version in every
   `package.json` under `templates/` and in the `*.md` files.
2. Run the test suites, plus `MS_RENDER_TESTS=1 python3 -m unittest discover -s design/tests`.
3. Run `npm run check` in `templates/tech-news-ar`, both
   `examples/grammar-demo-*`, and the two other templates' `starter/`.
4. Run the quick start and watch the rendered video.

**Agent skills** are separate from the runtime. `skills-lock.json` records
which 12 upstream skills to install, not a fixed revision of them:
`npx skills experimental_install` fetches their current upstream versions, so
skill text can describe CLI features newer than the pinned runtime. When they
disagree, the pinned runtime and this repository's documents win.

## Arabic / RTL support

- **Alexandria** is bundled and enforced as the required family, declared in
  the project's `lib/type-scale.json` (copied from
  `templates/tech-news-ar/lib/`); a different primary font is an error.
- Compositions are `lang="ar"` with `direction: rtl` scoped to the scene
  containers; scene grammars carry RTL layout notes.
- **No tashkeel** in on-screen text; `check-tashkeel.py` checks it. It ships in
  `templates/tech-news-ar/tools/` and is copied into each project's `tools/`
  (it is not in the repository-root `tools/`).
- Type scale and mobile-readability checks are sized for Arabic script
  (`python3 design/cli.py readability <project>`).
- Latin product names inside Arabic lines follow the RTL / bidi rules in
  [`CONTENT_RULES.md`](CONTENT_RULES.md).

## Repository structure

| Path | Contents |
|---|---|
| `VIDEO_WORKFLOW.md` | The workflow and entry point for agents |
| `CLAUDE.md`, `.claude/agents/` | Agent instructions; optional critic subagents |
| `studio/` | Gated production pipeline, manifests, validation, trace, cleanup |
| `design/` | Typography, scene grammar, brand and manifest checks |
| `review/` | Post-render analysis, proposals, critic packs |
| `timing/`, `narration/` | Word timings, captions, narration planning |
| `costgate/` | Cost estimate/approval gate |
| `reference/` | Reference image/video analyzer |
| `tools/` | Run-record check, publish marking, published cleanup |
| `templates/` | `tech-news-ar` (main), `business-learning-ar`, `cinematic-saudi-documentary`. Template directories are sources to copy from; your projects live in `videos/` |
| `tests/word-sync/` | A fixture project used by tests |
| `runs/`, `learning/` | Formats for run records and lessons (no data included) |

Topic documents: [`PRODUCTION.md`](PRODUCTION.md),
[`CONTEXT_SCOPE.md`](CONTEXT_SCOPE.md), [`CONTENT_RULES.md`](CONTENT_RULES.md),
[`ASSET_POLICY.md`](ASSET_POLICY.md), [`AUDIO_DESIGN.md`](AUDIO_DESIGN.md),
[`AI_REVIEW.md`](AI_REVIEW.md), [`QUALITY_SCORE.md`](QUALITY_SCORE.md),
[`RUN_METRICS.md`](RUN_METRICS.md), [`CLEANUP.md`](CLEANUP.md),
[`WORKFLOW_REFERENCE.md`](WORKFLOW_REFERENCE.md).

## Stable vs experimental

| Area | State |
|---|---|
| `studio/` pipeline, `design/` checks, `templates/tech-news-ar` | Most used; the main path |
| `review/` analysis and proposals | Used regularly; advisory |
| Critic agents (`.claude/agents/`, `studio/cli.py critics`) | Optional; Claude Code format |
| `timing/`, `narration/` (word sync, narration) | Proof of concept; one provider adapter |
| `templates/business-learning-ar`, `LEARNING_WORKFLOW.md` | v1 |
| `templates/cinematic-saudi-documentary` | Validated on one internal pilot |
| `costgate/` | Works, but `costgate/pricing.json` ships empty; you supply prices |
| `reference/`, `review/ffmpeg_skill.py` | Experimental |

## Known limitations

- Documentation and templates assume Arabic output and a tech-news/explainer format.
- No demo video is published yet.
- Developed on macOS. Linux is configured in CI but unverified until the first
  GitHub Actions run succeeds. Windows is untested.
- Rendering needs network access (npx, GSAP CDN).
- Run from a clone; there is no installable package.
- Cost tracking depends on usage data the agent or provider reports.
- Brand profiles are colour and naming references for editorial use. You are
  responsible for the rights to any media and logos you add
  ([`ASSET_POLICY.md`](ASSET_POLICY.md)).

## Tests

```bash
for d in studio design timing narration review costgate reference tools templates/tech-news-ar/tools; do
  python3 -m unittest discover -s $d/tests || break
done
```

Some tests skip when a tool is missing: FFmpeg/FFprobe, Node, or the optional
browser tracer. Two typography tests run only with `MS_RENDER_TESTS=1` (they
need `npx hyperframes` and Chrome).

## Contributing and security

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md).

## License

Licensed under the Apache License 2.0 — see [`LICENSE`](LICENSE).

Third-party components, including HyperFrames, fonts, and GSAP, remain subject
to their own licenses. Company and product names referenced in brand profiles
are trademarks of their respective owners — see [`NOTICE`](NOTICE).

Created and maintained by Sami Al Mohaimeed
([@SamiBizConsult](https://x.com/SamiBizConsult)).
