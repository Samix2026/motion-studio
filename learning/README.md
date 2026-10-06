# learning/ — source-driven lessons

A lesson is the reusable knowledge behind educational videos, built from 1–2
sources the user supplies. It describes what the sources support, never how a
video presents it. One lesson can feed several outputs (a 9:16 cut, a 16:9 cut,
an English version, later a carousel or quiz). Each output is its own project
in `videos/<slug>/` and records the lesson in `meta.json` as
`"lesson": "learning/lessons/<lesson-id>/lesson.json"`.

Topics are not predefined. There are no topic or methodology folders; a lesson
may come from an article, research paper, book excerpt, company or government
report, technical article, credible thread, or case study.

**The step-by-step workflow and its gates are in
[`../LEARNING_WORKFLOW.md`](../LEARNING_WORKFLOW.md).** This file owns the
package formats and the research, claim, and source rules.

## Package

```text
learning/lessons/<lesson-id>/
  brief.json    # the request: topic, audience, goal, language, primary sources, research policy
  sources.md    # source register: every source opened, role, tier, verified or not
  research.md   # the research gate: evidence, classified claims, conflicts, chosen angle
  lesson.json   # final lesson content (schema below)
  sources/      # optional: local copies of supplied files (PDF, excerpt, screenshot of a thread)
```

`<lesson-id>` is kebab-case and stable. Platform, format, duration, caption,
CTA, cover, and rendering choices never live here; they belong to the video
project (`meta.json` → `outputs`, `BRIEF.md`).

## Primary sources

- The user's 1–2 sources are the starting point and the **primary** basis of
  the lesson.
- **Supplementary** research exists only to verify, clarify, fill important
  gaps, find authoritative definitions, check numbers, improve examples, and
  identify misconceptions. It runs only when `brief.json` → `research`
  permits it.
- It stays on the user's topic and answers the gaps and research questions; it
  is not broad research into neighbouring subjects.
- It never silently replaces or rewords what a primary source says. A
  disagreement is a conflict (§Conflicts), not a correction.

## Claim classification

Every important claim considered for the lesson is labelled in `research.md`
with one class:

| Class | Meaning | May enter `lesson.json`? |
|---|---|---|
| `primary` | Supported by a user-supplied source (quoted/located). | Yes. |
| `supplementary` | Verified in an opened supplementary source. | Yes, cited with `role: "supplementary"`. |
| `inference` | Strong inference from supported facts, not stated by a source. | Only worded as inference ("this suggests…"), never as confirmed fact. |
| `illustrative` | Hypothetical scenario, example, or number made up to teach. | Yes, listed in `illustrative` (and `metrics.basis: "illustrative"` for numbers) so every output labels it. |
| `unsupported` | No opened source supports it. | **No.** Listed under §Avoid claiming. |

No scores or weights; one label per claim.

## Conflicts

When two sources disagree, never merge them into one statement. Record in
`research.md` §Conflicts:

| Field | Content |
|---|---|
| Claim | The claim or question in dispute. |
| A | Source A's position, with its source number. |
| B | Source B's position, with its source number. |
| Context | Authority, date, scope, or definition differences that explain it. |
| Status | `unresolved`, `shown-both`, `primary-kept`, or `supplementary-kept-with-reason`. |

- `unresolved` — the disputed point stays out of `lesson.json`.
- `shown-both` — the lesson states both positions with their sources.
- `primary-kept` — the lesson follows the primary source; the conflict stays
  recorded.
- `supplementary-kept-with-reason` — the supplementary source is followed; the
  reason is written in Context (e.g. primary source is outdated). Tell the user.
- A conflict that materially affects the chosen angle stops the workflow
  before `script.md` until the user resolves it.

## Source quality

Guidance, not a hard ranking. Preferred order (the `tier` in `sources.md`):

1. Primary / official source
2. Standards body / methodology owner
3. Government / university / research institution
4. Credible industry publication
5. Expert commentary
6. Community discussion — signal only

Important definitions, numbers, and claims use the strongest practical source.
Tiers 5–6 may still supply examples, reactions, common misconceptions, and
questions worth verifying. The user's primary sources stay primary whatever
their tier; a weak primary source is a reason to verify, not to replace it.

## brief.json (version 1)

| Field | Req. | Meaning |
|---|---|---|
| `schema` | R | `1`. |
| `id` | R | Same as the folder name. |
| `topic` | R | Short statement of the subject. |
| `language` | R | Lesson language, e.g. `ar`. |
| `audience` | R | Who it is for and what they already know. |
| `goal` | R | What the viewer should understand or do afterward. |
| `output_intent` | O | Kind of output in words (e.g. "short silent explainer"). No platform, aspect ratio, or duration. |
| `primary_sources[]` | R | 1–2 entries: `ref` (URL or `sources/<file>` path), optional `note`. |
| `research` | R | `none`, `allowed`, or `required`. |
| `research_questions[]` | O | Questions supplementary research must answer. |

## sources.md

One table row per source opened: `#` (used everywhere as `[n]`), `role`
(`primary` / `supplementary`), `tier` (1–6), source (publisher, title, URL or
`sources/` path), date opened, verified (`yes` / `partly` / `no`), used for.

## research.md

Concise and production-oriented — notes for building the lesson, not an
academic report. Sections, in order (write "None." when empty):

1. **Primary sources** — two or three lines per primary source: what it says
   that matters here.
2. **Core concept** — the verified definition, quoted, with source.
3. **Supported facts** — bullet list, each with its class and `[n]`.
4. **Numbers** — each number with class, unit, date/scope, and `[n]`.
5. **Supplementary findings** — what research added or corrected, with `[n]`.
6. **Example candidates** — practical examples; mark each `primary`,
   `supplementary`, or `illustrative`.
7. **Misconception** — the common wrong belief, when relevant, with evidence.
8. **Conflicts** — table per §Conflicts.
9. **Avoid claiming** — `unsupported` claims and tempting overstatements.
10. **Angle** — the one educational angle and a one-line reason (e.g. explain
    a mechanism, challenge a misconception, show cause and effect, explain a
    decision, a framework through one case, one finding from a report).
11. **Sources** — `[n]` short titles; full entries in `sources.md`.

## lesson.json (schema version 2)

JSON, UTF-8. Text is a language map: `{ "ar": "...", "en": "..." }` — `ar` is
required, `en` is optional. Written from `research.md` only.

| Field | Req. | Why it exists |
|---|---|---|
| `schema` | R | Format version (`2`). |
| `id` | R | Same as the folder name; used by videos and run records. |
| `tags[]` | O | Free-form topic tags for search. Not a folder, not a track. |
| `level` | O | `beginner` / `intermediate` / `advanced`. |
| `illustrative[]` | O | Field paths whose content is illustrative (e.g. `["problem", "model"]`). Outputs label these as examples. |
| `concept.name` | R | The concept's name (text). |
| `concept.definition` | R | Definition (text); must be backed by a `sources` entry. |
| `concept.method` | O | Framework the concept belongs to, if any (text). |
| `hook` | R | The tension that opens the lesson (text). A situation, not "what is X". |
| `problem.situation` | R | The concrete failure, question, or tension (text). |
| `problem.setting` | O | Industry, operation, or context, e.g. `restaurant`. |
| `problem.misbelief` | O | The wrong explanation the lesson overturns (text). |
| `model` | O | Mechanism, when the source describes one. `kind`: `flow` for now; add a kind only when a lesson needs it. |
| `model.nodes[]` | R if `model` | `id`, `label` (text). |
| `model.links[]` | R if `model` | `from`, `to`, optional `kind` (e.g. `trip`). |
| `model.hotspots[]` | R if `model` | 1–2 places where the concept shows up: `kind` (the source's own term), `at` (node id or `[from, to]`), `label` (text), optional `detail` (text). |
| `change` | O | The practical application (text). |
| `metrics.basis` | R if `metrics` | `illustrative` or `cited`. |
| `metrics.items[]` | R if `metrics` | `id`, `label` (text), `unit`, `before`, optional `after`. |
| `takeaway` | R | The one action or insight for the viewer (text). |
| `terms[]` | O | Bilingual terminology: `{ "en": ..., "ar": ... }`. |
| `sources[]` | R | Citations: `role` (`primary` / `supplementary`), `for` (field paths), `publisher`, `title`, `url`, `quote`, `accessed` (ISO date). |

## Rules

- **No presentation.** No durations, aspect ratios, platforms, grammar or beat
  names, coordinates, colors, fonts, animation instructions, post captions, or
  final on-screen copy. Final copy is written per video in `script.md`.
- **Claims follow their class** (§Claim classification); `unsupported` never
  enters the lesson.
- **Primary first.** A field the primary sources cover is supported by them;
  a supplementary source supports only what they do not cover, or a recorded
  conflict decision.
- **Numbers are honest.** `basis: "illustrative"` means hypothetical: every
  output labels them as such, and `after` values are possible outcomes, never
  measured results. `basis: "cited"` requires a `sources` entry whose `for`
  includes `metrics`.
- **Sources are real.** Only cite a page that was opened and checked; `quote`
  is copied from it. If the source does not support a wording, change the
  wording.
- **Hotspot kinds use the source's own terms** and match its meaning (for
  example, Lean "waiting" is people standing idle).
- Arabic text follows `CONTENT_RULES.md` (no tashkeel, no banned words).

## Check

```bash
python3 -c "import json,glob; [json.load(open(p, encoding='utf-8')) for p in glob.glob('learning/**/*.json', recursive=True)]"
python3 templates/tech-news-ar/tools/check-tashkeel.py learning
```

A schema checker is deferred until at least two lessons exist.
