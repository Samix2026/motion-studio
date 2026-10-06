# TEMPLATE_RULES.md — Business Learning (Arabic) standard

Editorial and presentation rules for short educational business videos built
from a lesson in `../../learning/`. Extends `../../CONTENT_RULES.md`,
`../../CONTEXT_SCOPE.md`, `../../ASSET_POLICY.md` and `../../AUDIO_DESIGN.md`;
where this file is silent, those govern. This file only narrows them.

Replaced for this template: the 5-beat news structure in `CONTENT_RULES.md`
(§Structure) is replaced by §2 below. Every other `CONTENT_RULES.md` rule
applies: Arabic language rules, no tashkeel, the banned word, RTL/bidi,
attribution of borrowed media, and accuracy.

## 1. Source of content

- Every video starts from one lesson file (`../../learning/README.md` owns the
  schema). The project's `meta.json` records it as `"lesson"`. The step order
  and gates are in `../../LEARNING_WORKFLOW.md`; `script.md` is written only
  after the lesson's `research.md` and `lesson.json`.
- The lesson holds meaning; the video's `script.md` holds the final on-screen
  copy, cut to that format's length. A video never edits the lesson to fit a
  scene; if the lesson is wrong, fix the lesson.
- One clear problem per video, at most two hotspots.
- On-screen claims come only from `lesson.json`, which is backed by the
  lesson's primary sources. A conflict listed in the lesson's `research.md` is
  shown as a conflict or left out, never merged. An `inference` stays worded
  as inference; content listed in the lesson's `illustrative` is labelled as
  an example on screen.
- `script.md` belongs to the video. Different outputs may adapt the same lesson
  differently (length, emphasis, order) without changing the lesson.

## 2. Narrative flow (guidance, not a validator rule)

Preferred default:

```text
Hook → Problem / tension → Mechanism / explanation → Concept / finding
     → Application / implication → Takeaway
```

**Show first, then name the concept** where appropriate. The viewer sees the operation fail and
sees why (Mechanism) before the concept's term appears (Concept). The concept is
the name for something already on screen, not an opening definition.

- Required roles: Hook, Problem, Concept, Takeaway.
- Mechanism and Application are optional; a short cut may merge them.
- Concept may come before Mechanism when the audience already knows the term.
- A role may span two scenes; a scene carries one role.

## 3. Roles → existing beat kinds

No new beat kinds. A scene's educational role comes from the lesson field it
uses; its `data-beat-kind` describes the visual/rhetorical kind, from the
existing registry (`../tech-news-ar/lib/grammars.json`).

| Role | Lesson fields | Beat kind | Typical existing grammar |
|---|---|---|---|
| Hook | `hook` | `hook` | `kinetic_word`, `big_number` |
| Problem | `problem.situation`, `model` (if any), `metrics` | `process` or `statistic` | `process_flow`; `big_number` |
| Mechanism | `model.hotspots`, `problem.misbelief` | `process` | `process_flow` |
| Concept | `concept.*`, `terms` | `claim` | `quote_or_statement`, `kinetic_word` |
| Application | `change`, `metrics.*.after` | `comparison` | `process_flow` (problem → after); `comparison` |
| Takeaway | `takeaway` | `takeaway` | `kinetic_word`, `quote_or_statement` |

## 4. Copy

All copy passes the writing-quality gate (`../../CONTENT_RULES.md`
§Writing-quality gate) before the storyboard; the rules below only narrow it.

- Open with concrete operational tension: a place, a symptom, a cost.
  Never open with «ما هو Lean؟», «تعريف Lean هو...», or a classroom introduction.
- Overturn the misbelief when the lesson has one (for example: the staff are
  not slow, the layout is).
- One idea per scene; headline about two lines, secondary line one or two.
- Method names and established terms stay in Latin inside the Arabic RTL run
  (`في Lean يسمى هذا هدرا`); never start a line with a Latin token
  (`CONTENT_RULES.md` §RTL).
- No generic motivational lines. Every sentence refers to the operation.
- The concept wording must stay faithful to the lesson's cited definition.
- Do not copy source wording verbatim when a clearer visual explanation
  exists, and do not simplify past what the sources support.
- A «ما هو ...؟» opening is allowed only when the question itself is the
  tension for this audience.

## 5. Numbers

- Lesson numbers with `basis: "illustrative"` are shown with a visible tag,
  default «أرقام افتراضية للتوضيح», in every scene where they appear.
- "After" values are possible outcomes of the change, phrased as such; never
  present them as measured results.
- Cited numbers show their source credit per `CONTENT_RULES.md` §Attribution.

## 6. Visual explanation

- Each storyboard scene names its lesson field, its `research.md` evidence,
  and its visual purpose: what the scene proves. Its visual answers at least
  one question: what changed? what caused it? where is the problem? how does
  the system work? what is being compared? what should the viewer notice?
- Not every scene needs a diagram; use the smallest grammar that answers the
  scene's question.

- Motion must explain the operation: work moving, piling up, travelling,
  waiting, changing state. No decorative motion behind text.
- Prefer one diagram that carries Problem → Mechanism → Application, changing
  state, over separate slides.
- Hotspots are labelled with the source's term (e.g. «انتظار», «حركة زائدة»).
- Scene layouts come from the shared grammar registry; this template does not
  define its own scene system.
- `process_flow` direction: in `line`, work follows the reading direction (RTL:
  right to left) because nodes are laid out by the RTL container, never by
  reversing markup. In `floor`, positions are physical (storage is where it
  is); the layout is never mirrored, only the text follows RTL.
- A queue or customer delay is an operational consequence (counter, queue); a
  source's category (e.g. a Lean waste) is labelled only where the stage shows it.

## 7. Typography

- **Alexandria** is the primary Arabic font for the Business Learning series
  (global preference, `../../CONTEXT_SCOPE.md` §1.1). Technical Latin runs may
  use IBM Plex Mono.
- The shared `lib/type.css` defaults `--ms-font` to IBM Plex Sans Arabic; a
  Business Learning project overrides `--ms-font` with Alexandria, declares its
  `@font-face` inline, and bundles the font files locally with the OFL license
  (see `starter/index.html`). Never rely on a system font.
- Verify with `design/cli.py fonts <project> --render` (primary family
  Alexandria, `loaded`) and `design/cli.py readability <project>`: Alexandria
  is wider than the face the type scale was tuned on.

## 8. Audio

Silent by default (`../../AUDIO_DESIGN.md` §0).

## 9. Series identity and context scope

The series reuses this template's composition language on purpose. Each project
manifest records it (`../../CONTEXT_SCOPE.md` §2.2):

```yaml
composition_language: inherited
inherited_from: templates/business-learning-ar
inheritance_authorized: true
```

Only the series identity is inherited. Palettes, layouts or references from a
previous lesson video are not.

## 10. Formats

The master is 9:16 (1080×1920), rendered once and used for TikTok, Instagram
Reels, YouTube Shorts, and X through platform profiles in `meta.json` →
`outputs` (`../../VIDEO_WORKFLOW.md` §Platform outputs). A platform gets its own
export only when it needs a different cut. A 16:9 version is a separate project
from the same lesson. Format and platform live in the project, never in the
lesson package.
