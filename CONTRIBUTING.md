# Contributing to Motion Studio

Thanks for your interest. Motion Studio is early and maintained by one person,
so small, focused changes are the easiest to review.

## Local setup

```bash
git clone https://github.com/Samix2026/motion-studio.git motion-studio
cd motion-studio
npx --yes hyperframes@0.8.35 doctor      # FFmpeg, FFprobe and Chrome must show ✓
```

You need Python 3.9+, Node.js 22+, FFmpeg and Chrome. There are no Python
dependencies to install. To author videos with an agent, install the HyperFrames
skills as described in the README.

## Tests

```bash
for d in studio design timing narration review costgate reference tools templates/tech-news-ar/tools; do
  python3 -m unittest discover -s $d/tests || break
done
```

All suites must pass before you open a pull request. Some tests skip when
FFmpeg, Node or the optional browser tracer is missing; two typography tests run
only with `MS_RENDER_TESTS=1`. CI runs the same command.

Rules for tests:

- Standard library `unittest` only.
- No network access, and no dependence on `videos/` or anything outside the
  repository. Use tracked fixtures.
- A behaviour change comes with a test.

## Project structure

See "Repository structure" in the README. Python packages are standard library
only; please do not add dependencies or restructure the packages.

## Workflow

1. Open an issue first for anything larger than a small fix.
2. Branch from `main`, keep the change focused, and update the documentation
   that describes the behaviour you changed.
3. Run the tests. If you changed a template or example, also run
   `npx hyperframes@0.8.35 check` in that directory.
4. Open a pull request describing what changed and how you verified it.

## Adding or changing templates and examples

- A template lives in `templates/<name>/` with a `README.md` (plus
  `TEMPLATE_RULES.md` when it has rules of its own); a runnable starter or example needs `index.html`,
  `hyperframes.json`, `package.json` (pinned to the known-good HyperFrames
  version; a test enforces it), `meta.json`
  and `sources.md`.
- `lib/` and `assets/fonts/` inside examples and starters are byte-identical
  copies of the template's. Change them together; a test enforces it.
- Example media must be project-owned placeholders named `placeholder-*.svg`
  (see `templates/tech-news-ar/examples/`). A test enforces this for the
  grammar demos.
- Starters carry the placeholder handle `@your_handle`, never a real account.
  Runnable examples carry no handle, because the build stage blocks the
  placeholder.
- Brand profiles (`templates/tech-news-ar/brands/`) hold colours and names with
  their sources. Do not add logos or brand imagery.

## Media, assets and licensing

By contributing you agree that your contribution is licensed under the
Apache License 2.0 (see `LICENSE`, section 5).

- Only submit media you created or that is under a licence allowing
  redistribution in an Apache-2.0 project. State the source and licence in the
  pull request and in the relevant `sources.md`.
- Fonts must be openly licensed (for example SIL OFL) and ship with their
  licence file.
- Do not commit third-party logos, screenshots, stock media, product imagery,
  generated voice recordings, or rendered videos.
- Do not commit secrets, API keys, `.env` files, personal paths, run records
  from private work, or anything under `videos/`.

A pull request that includes unlicensed media or a secret will be closed, and
the secret must be rotated by its owner.
