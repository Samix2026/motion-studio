# asset-checkpoint.md — asset quality gate

Copy this into a project as `asset-checkpoint.md` and fill one row per
candidate asset before writing `narrative.md` or a scene map. Gate:
`TEMPLATE_RULES.md` §1 — **8–18 passing assets, story decides the count
inside that range. Quality over quantity: never pad past what the story
needs. Fewer than 8, or the story's beats not covered, stops the
project.**

An asset "passes" only if every column is filled with a real answer (not
"TBD") and `cinematic quality` is not `weak`.

| Asset name | Source | License | Resolution | Type | Saudi authenticity | Cinematic quality | Recommended duration | Why it earns a place |
|---|---|---|---|---|---|---|---|---|
| e.g. `edge-of-world-wide-01` | official tourism board footage / licensed stock provider, direct URL | licensed premium stock — usage terms recorded in `sources.md` | 4K, 3840×2160 | video | specific, recognizable place — no caption needed | strong / medium / weak | 3.5s | establishes place in one shot, no filler |

## Column definitions

- **Asset name** — kebab-case, descriptive, matches the eventual file in
  `assets/` (`../../ASSET_POLICY.md` §Asset organization).
- **Source** — the primary/official origin: institutional archive, licensed
  stock provider, official press kit. Never "found online."
- **License** — the specific usage basis (CC0, licensed stock license,
  editorial-with-attribution, owned/original). If unclear, this asset does
  not pass — `../../ASSET_POLICY.md` §Licensing.
- **Resolution** — actual pixel dimensions of the source file, not the
  delivery resolution.
- **Type** — `video` or `still`.
- **Saudi authenticity** — what makes this specifically and recognizably
  Saudi without a caption (a named place, a specific craft, a specific
  institution) — not "desert" or "skyline" alone.
- **Cinematic quality** — `strong` / `medium` / `weak`, judged against
  `TEMPLATE_RULES.md` §1 accept/reject lists. `weak` does not pass.
- **Recommended duration** — how long this asset earns on screen, in
  seconds, informed by its content and motion headroom (a still needs at
  least its Ken Burns duration, `components/ken-burns-still.md`).
- **Why it earns a place in the cut** — one sentence, tied to a narrative
  beat (past/identity/people/transformation/present/future/closing). No
  narrative purpose, no place in the cut.

## Gate summary (fill last)

- Total assets logged: **\_\_**
- Total assets passing: **\_\_**
- Do every narrative beat (past/identity/people/transformation/present/
  future/closing) have a passing asset? **yes / no**
- If passing < 8, or a beat has no passing asset: **STOP — do not build a
  scene map or narrative from this set.** Log what's missing and go back to
  sourcing.
- If passing > 18, or extra assets exist beyond what the story needs: cut
  them from the project, not from this log — a passing asset the story
  doesn't use does not belong in the cut.
