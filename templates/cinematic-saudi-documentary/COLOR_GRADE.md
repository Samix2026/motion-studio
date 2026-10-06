# COLOR_GRADE.md — two-stage color pipeline

Implementation: `starter/components/color-grade.css` (Stage B) and `starter/components/cinematic-frame.css` (Stage A).

Mixed sources (archival stills, licensed stock, institutional footage) never
start in the same range. One global filter alone bakes in whatever each
source's own exposure/white-balance/saturation happened to be — so the
pipeline is **two stages**: a small per-shot correction first, then one
global grade applied once. Never rely on the global filter alone to fix a
mismatched source, and never apply the same correction values blindly to
every shot — each shot gets its own numbers, chosen by eye against the
reference frame below.

## Direction

- Dark green / neutral cinematic look.
- Restrained contrast — no crushed blacks, no blown highlights.
- Warm skin tones preserved — the grade tilts shadows/midtones, not skin;
  see §Skin tone protection.
- Natural greens (vegetation, palm fronds, oases) stay believable, not
  teal-and-orange stylized.
- Avoid oversaturation.
- **Protect Saudi flag colors** — the flag's green (`#006C35` official) and
  white must not shift hue or desaturate. See §Flag protection.
- **Protect archival images** — old photographs already carry their own
  color cast (sepia, faded, low-contrast). Correct toward legibility, not
  toward looking like modern footage. See §Archival protection.

## Stage A — per-shot correction

Purpose: bring heterogeneous source footage/stills into the same starting
range **before** the global grade sees them. This is corrective, not
stylistic — small values, chosen per shot against how far that shot's raw
exposure/white-balance/saturation/contrast sit from the reference.

Applied per media element (inside `components/cinematic-media-frame.md`'s
`.cine-frame img`/`.cine-frame video`), not at the root:

```css
.cine-frame img,
.cine-frame video {
  filter:
    brightness(var(--corr-exposure, 1))
    contrast(var(--corr-contrast, 1))
    saturate(var(--corr-saturation, 1))
    var(--corr-white-balance, none); /* sepia()/hue-rotate() pair, see below */
}
```

```html
<figure class="cine-frame" id="s3frame"
        style="--corr-exposure:1.05; --corr-contrast:1.02; --corr-saturation:0.97;
               --corr-white-balance: sepia(0.04) hue-rotate(-3deg);">
  <img src="assets/<file>" alt="" />
</figure>
```

| Correction | CSS lever | Typical range | Notes |
|---|---|---|---|
| Exposure | `brightness()` | 0.9–1.12 | lift underexposed archival/low-light shots, pull down blown highlights |
| White balance | `sepia()` + `hue-rotate()` pair | sepia 0–0.08, hue-rotate ±6deg | neutralize a cool/warm cast toward the reference, not toward orange/teal |
| Saturation | `saturate()` | 0.9–1.05 | mainly pulls down an oversaturated stock clip; rarely pushes up |
| Contrast | `contrast()` | 0.95–1.08 | flat archival footage needs a small lift; already-contrasty footage needs none |

Rules:
- Set these per shot in the asset checkpoint / scene map, not once globally
  — `TEMPLATE_RULES.md` §1's checkpoint row is where the values get decided,
  the scene map is where they're recorded (`scene-map-example.md` §per-shot
  correction column).
- **Do not apply identical correction values to every source.** A shot that
  needs no correction gets all four levers left at their neutral default
  (`1`, `1`, `1`, `none`) — leaving a shot uncorrected is a valid choice, not
  an omission.
- Keep every value inside the ranges above. A value outside that range means
  the source asset itself is too far off — fix upstream (re-export, pick a
  different shot) rather than stack heavier correction.
- Correction happens once per shot, at the frame, and is invisible as a
  "look" — if a correction is noticeable as its own effect, it's too strong.

## Stage B — global cinematic grade

Applied **once, at the composition root**, after every shot has already
been corrected in Stage A — this stage gives the whole piece its unified
look, it does not fix individual shots.

```css
:root {
  --grade-shadow-tint: #10241a;   /* dark green shadow tint */
  --grade-contrast: 1.04;         /* restrained: keep near 1.0 */
  --grade-saturation: 0.94;       /* slightly desaturated, never > 1 */
  --grade-brightness: 1.0;
  --grade-warmth: 0.03;           /* subtle warm bias, skin-safe */
}

.grade-cinematic-sd {
  filter:
    saturate(var(--grade-saturation))
    contrast(var(--grade-contrast))
    brightness(var(--grade-brightness))
    sepia(var(--grade-warmth));
  position: relative;
}

/* dark-green shadow tint via a soft multiply overlay, not a hue shift */
.grade-cinematic-sd::after {
  content: "";
  position: absolute;
  inset: 0;
  background: var(--grade-shadow-tint);
  mix-blend-mode: multiply;
  opacity: 0.06;
  pointer-events: none;
  z-index: 40;
}
```

```html
<div id="root" class="grade-cinematic-sd">
  <!-- all .clip scenes, each already corrected per Stage A -->
</div>
```

Rules:
- Apply this wrapper exactly once. Do not add per-scene `filter` overrides
  at this stage — per-shot differences are Stage A's job, already resolved
  by the time Stage B runs.
- Keep `--grade-contrast` and `--grade-saturation` inside the ranges shown;
  values further from 1.0 read as "heavy effects," which §Do not is against.
- The multiply overlay opacity (0.06) is deliberately light — this is a
  restrained grade, not a stylized LUT.

## Skin tone protection

- Stage A white-balance correction on a shot with visible faces must not
  push warmth or a hue-rotate far enough to discolor skin — keep
  `hue-rotate` inside ±6deg on any people shot, and check skin before
  committing the value.
- Stage B's `--grade-warmth` is deliberately small (0.03) precisely so it
  never tips a corrected skin tone toward orange or green. If a corrected
  shot's skin reads green or sallow after Stage B, the fix is Stage A's
  saturation/white-balance on that shot, never loosening Stage B for
  everyone.

## Flag protection

When a Saudi flag (or the Kalima/sword emblem) is in frame:
- Stage A: do not white-balance-correct a flag-forward shot beyond neutral
  unless the flag itself reads off-color uncorrected — the flag's green is
  the reference, not the thing being corrected toward something else.
- Stage B: exclude that region from the shadow-tint overlay
  (`mix-blend-mode: multiply` on a full-bleed div can dull a small bright
  green flag against a dark background — mask the overlay with a
  `clip-path` cutout on flag-forward shots, or prefer a shot where the flag
  isn't full-bleed under the tint).
- Never apply `hue-rotate()` beyond the ranges above, or any duotone/
  split-tone treatment, to a flag-forward shot at either stage.
- Verify visually at both stages: the flag's green must still read as
  green, not teal or olive.

## Archival protection

- Stage A on an archival still corrects toward **legibility** (recoverable
  detail in faded highlights/shadows), not toward matching modern footage's
  contrast or saturation — an archival image that's been corrected to look
  like it was shot yesterday has lost what made it archival.
- Do not fully neutralize an archival image's own sepia/fade in Stage A;
  reduce it only enough that Stage B's warmth doesn't stack into an
  oversaturated brown. A light residual cast is expected and fine.
- Stage B's multiply overlay is safe on archival images at its documented
  opacity (0.06) — do not raise it specifically for archival shots to "age"
  them further; that is a stylized effect this template avoids.

## Heavier looks (LUT-based)

If a project needs a more specific photographic look than this two-stage
pipeline gives (film emulation, print grain), that is asset-level color
treatment, not this template's job — see `/media-use` →
`media-treatments.md` for applying a LUT to source footage before it enters
Stage A. The two-stage pipeline above is what ships with every project from
this template regardless of whether a LUT was also used upstream.

## Do not

- Do not skip Stage A and rely on the global grade alone to unify mixed
  sources.
- Do not apply identical Stage A correction values to every shot blindly —
  each shot's values come from that shot's own starting point.
- Do not bake a per-scene grade at Stage B — one wrapper, one grade.
- Do not oversaturate or crush blacks at either stage.
- Do not use aggressive hue-rotate stylization (teal/orange, duotone) at
  either stage.
- Do not let green skin or crushed blacks pass uncaught — check both after
  Stage A and after Stage B, not just the final composite.
- Do not let the pipeline reduce lower-third text readability — if it does,
  fix the text scrim (`components/lower-third.md`), not the grade.
