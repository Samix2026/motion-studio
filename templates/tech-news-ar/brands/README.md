# Brand profiles

Data-only visual identities for `templates/tech-news-ar`. A profile adapts the
video's colors and surface treatment to the company the story is about, while
the HyperFrames composition structure, typography scale, safe zones, timeline,
footer, and Arabic rules stay unchanged.

No framework: each profile is JSON, and the template consumes it through CSS
custom properties (`--brand-*`) plus the existing GSAP timeline.

Selection is governed by the **Brand Resolution Gate** and the three context
scopes in `CONTEXT_SCOPE.md`; this section only adds the profile mechanics.

## Selection rules

1. Resolve the brand **before** `DESIGN.md` is written (Brand Resolution Gate,
   `CONTEXT_SCOPE.md` §3): current-project instruction → current-project
   reference → official subject identity → neutral default.
2. Determine the **primary company** from the verified source URLs and the
   subject of the news.
3. If one company is clearly dominant, use that company's profile.
4. If multiple companies are equally central, use **generic** — unless one is
   clearly the subject and the others are context.
5. **Never infer a brand from an unrelated asset.**
6. **Never carry a previous project's profile, palette, layout, or composition
   language forward.** A profile is project-scoped; re-resolve it for every
   story (`CONTEXT_SCOPE.md` §2). Brand isolation includes layout and
   composition, not only palette, and recoloring a prior layout is not brand
   resolution. Record `brand.identity_mode` (`official | user-reference |
   neutral`), `reference_scope: project-only`, and `composition_language`
   (`fresh | inherited`) in the project manifest (`DESIGN.md` / `meta.json`).
7. Record the selected profile id in the project's `meta.json` as `"brand"`.
8. The brand choice must **not** affect factual wording or editorial tone.
9. **generic** means "this subject has no applicable brand identity", never
   "the brand was not resolved". Use it only for an unbranded subject
   (`brand.product: none`), rule 4, or an explicit user request for a neutral
   treatment. It is achromatic on purpose.
10. A named product/company with no profile here must not silently use
    generic. Resolve its identity from official sources (product/company page,
    documentation, press/brand material, verified product UI), write those
    values into the `brand:start … brand:end` block, set `"brand": "project"`,
    and record `brand.project_identity` in the manifest (`CONTEXT_SCOPE.md`
    §5). Never infer a palette from taste. If no official evidence is
    available, stop before composition and ask; a neutral treatment needs the
    user's explicit approval, recorded as `brand.neutral_approval`.
    `design/cli.py preflight` enforces this.

Supported ids: `nvidia`, `anthropic`, `openai`, `google`, `microsoft`, `apple`,
`xai`, `deepseek`, `meta`, `higgsfield`, `generic`.

## Legal / design rule

The video should be **visually inspired by** a company's public identity but
must not imitate official communications closely enough that a viewer could
mistake it for a company publication.

- Do not reproduce a whole campaign composition, a proprietary layout, or an
  exact marketing template. Credited source imagery and key art may appear
  inside your own scenes (`ASSET_POLICY.md`).
- Do not reconstruct or recolor logos; use official logos only via
  `ASSET_POLICY.md`, and only in the placements the profile allows.
- Keep `@your_handle` and source attribution visible at all times.

## Confidence

Every profile states `colorConfidence`:

- `verified` — the key brand color(s) are traceable to an official published
  value (e.g. Anthropic press-kit SVG fills, Google logo SVG, Fluent tokens).
- `sampled-official` — values were sampled from the company's own site/CSS/
  theme metadata, not an official published spec.
- `approximate` — the company publishes no usable color spec (e.g. monochrome
  identity); the profile is an interpretation.
- `not-applicable` — generic.

`officialColors` lists the verified/sampled brand values. `tokens` holds the
full CSS-ready set, including derived dark-theme UI values (background, surface,
border, etc.) that are design choices, not official brand colors. When exact
official values are unavailable, the profile and `notes` say so.

## Token → CSS custom property map

`tools/apply-brand.py` maps each key in `tokens` to `--brand-<kebab-key>`:

| tokens key | CSS custom property | Purpose |
|------------|---------------------|---------|
| `primary` | `--brand-primary` | main accent |
| `secondary` | `--brand-secondary` | secondary accent |
| `background` | `--brand-background` | base background |
| `backgroundGradient` | `--brand-background-gradient` | root background |
| `surface` | `--brand-surface` | cards / panels |
| `text` | `--brand-text` | primary text |
| `muted` | `--brand-muted` | secondary text |
| `accentGradient` | `--brand-accent-gradient` | gradient accent |
| `borderColor` / `borderWidth` / `borderStyle` | `--brand-border-*` | card border |
| `radius` | `--brand-radius` | corner radius |
| `gap` | `--brand-gap` | scene spacing (density) |
| `imageFit` / `imagePosition` / `imageScale` | `--brand-image-*` | image treatment |
| `headlineWeight` / `headlineTracking` | `--brand-headline-*` | headline treatment |
| `highlightColor` | `--brand-highlight-color` | `<span class="hl">` |
| `creditColor` | `--brand-credit-color` | source credit |
| `progressFill` | `--brand-progress-fill` | progress bar fill (color or gradient) |

`traits` (density, imageTreatment, headlineTreatment, creditTreatment,
progressTreatment) and `logoRules` are descriptive: they guide the agent and the
asset step.

## Identity block (optional): beyond logo + accent colour

A profile may add an `identity` object describing how the brand looks in the
**scene content**, not only in the chrome:

| key | Meaning |
|---|---|
| `palette` | the full colour set; `apply-brand.py` emits `--brand-palette-1..n` |
| `paletteUse` | how the colours work together |
| `gradients` | characteristic gradients, where the brand has them |
| `shapes` | characteristic geometry (corners, circles, pills, grids) |
| `motifs` | recurring visual elements usable as scene objects |
| `surface` | surface treatment (flat, light, dark, texture) |
| `motion` | motion character, where the brand has one |
| `confidence` | what is verified and what is descriptive |

Use it when designing the scenes: objects, fills, data series, tracks and
shapes carry the identity. It stays inspired-by (see the legal/design rule) and
never changes wording or facts. `python3 design/cli.py brand <project>` reports,
as an advisory only, how many palette colours actually reach the scene content;
a low count is a prompt to look again, never a gate. `google.json` carries a
filled example; other profiles gain the block when they are next used.

## Applying a profile

In a new project, replace the `/* brand:start … brand:end */` block in
`index.html` with the selected profile's tokens, then set `"brand"` in
`meta.json`. The included script does both:

```bash
python3 tools/apply-brand.py brands/meta.json index.html
# or, from the project root, pointing at the template's brands dir:
python3 ../templates/tech-news-ar/tools/apply-brand.py \
  ../templates/tech-news-ar/brands/meta.json index.html
```

`apply-brand.py` is a plain JSON→CSS text transform (standard library only). It
is optional; you can copy the values by hand.
