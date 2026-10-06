# Motion Studio

The workflow is `VIDEO_WORKFLOW.md`; it lists what else to read and when. This
file sets instruction precedence and the rules that apply to every task.

## Precedence

When instructions disagree, the higher one wins:

1. Motion Studio rules: `VIDEO_WORKFLOW.md` and the documents it points to.
2. The current project's brand profile and design rules (`meta.json`, `DESIGN.md`).
3. HyperFrames skills and defaults, including the `CLAUDE.md` / `AGENTS.md`
   that `hyperframes init` writes into each `videos/<slug>/`.

## Producing a video

- `VIDEO_WORKFLOW.md` is the entry point. Do not run the `/hyperframes` intent
  interview, routing, `skills update`, design-spec or audio offers; use
  HyperFrames skills only as technical reference for composition, animation
  and CLI.
- Each video is a project under `videos/<slug>/` (Git-ignored). Never write
  project state anywhere else.
- Render only through `python3 studio/cli.py production` (or `render`). Do not
  bypass a blocking gate; fix the cause and re-validate.
- Arabic output: Alexandria is the required family, no tashkeel
  (`tools/check-tashkeel.py`), RTL layout, bidi rules in `CONTENT_RULES.md`.
- Never invent facts or asset URLs. Record every claim source and every asset
  with its licence note in the project's `sources.md` (`ASSET_POLICY.md`).
- The handle in templates is the placeholder `@your_handle`. Use the project
  owner's handle from `user_identity.x_handle`, or remove it when
  `show_handle` is `false` (`CONTEXT_SCOPE.md` §6).
- Stop for the two human gates the workflow defines. A passing check is not an
  approval.

## Changing the toolkit

- Python is standard library only. Do not add dependencies.
- Keep the package layout (`studio/`, `design/`, `review/`, `timing/`,
  `narration/`, `costgate/`, `reference/`, `tools/`).
- Every behaviour change needs a test. Run all suites before finishing:

  ```bash
  for d in studio design timing narration review costgate reference tools templates/tech-news-ar/tools; do
    python3 -m unittest discover -s $d/tests || break
  done
  ```

- Tests must not depend on `videos/`, on network access, or on files outside
  the repository. Use tracked fixtures.
- `lib/` and `assets/fonts/` in the examples and starters are byte-identical
  copies of the template's; change them together (a test checks this).
- Never commit secrets, rendered media, or third-party media you cannot
  redistribute. See `CONTRIBUTING.md`.
