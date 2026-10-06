# CONTENT_RULES.md — Arabic tech-news editorial standard

Rules for every Arabic technology-news video produced from
`templates/tech-news-ar/`. These are permanent unless explicitly changed.

## Language
- Modern Standard Arabic (فصحى), simple and direct.
- Product and company names stay in Latin script as they are officially written
  (`Claude`, `Claude Code`, `Cowork`, `computer use`).
- No dialect, no slang.
- Do not translate established technical terms that are used in Latin form in
  primary sources; keep the term and add Arabic context around it.
- **Banned word:** never use the standalone Arabic word «بل» in any generated <!-- check-tashkeel: allow -->
  content; rephrase instead. Longer words that contain the same letters (e.g.
  «قبل») are fine. Enforced by `templates/tech-news-ar/tools/check-tashkeel.py`.

## Writing quality — No-AI-Slop guidance

Guidance applied while drafting viewer-facing copy. It is not a gate, produces
no separate record and never blocks the storyboard. It is an editorial check
for natural, specific, source-grounded writing, not an authorship detector:
never claim that passing means a human wrote the text.

**Applies to** hooks, headlines, secondary lines, takeaways, on-screen labels,
post captions (`meta.json` → `outputs.caption`), and any article or thread copy
the project produces. **Does not apply mechanically to** `research.md`,
`sources.md`, source quotes, metadata, JSON keys, code, or filenames; those
keep formal/source language until they become audience-facing copy.

**Reference.** Adapted from `petergyang/no-ai-slop` (`SKILL.md`, `eval.md`, MIT).
If the agent has the `no-ai-slop` skill installed, run it on the draft copy,
then apply the Arabic and source-fidelity rules below, which take precedence.
If it is not installed, follow this section; production never blocks on the
external skill. Optional install, only when the user authorizes it:
`npx skills add petergyang/no-ai-slop --skill no-ai-slop --global --yes`.

### What to fix (judge in context; not a banned-phrase list)
- **Binary contrasts** ("not X, it is Y", «ليس ... إنما ...») and negative
  listings: state Y directly. One contrast is fine when the point itself is a
  correction; repeating the shape across scenes is not.
- **Throat-clearing openers and rhetorical setups:** start with the point.
- **Faux-insight setups** ("what nobody tells you"): make the claim stand alone.
- **Colon reveals and dramatic fragments:** use plain sentences; colons are for
  lists, labels, and quotes.
- **Superficial analysis and importance puffery:** replace "marks a pivotal
  moment"-style commentary with the fact, mechanism, or consequence.
- **Vague attribution** ("experts agree", «يرى الخبراء»): name the source or cut.
- **Synonym cycling:** repeat the clear term.
- **Fake-profound or motivational endings:** end on the concrete takeaway.
- **Abstract wording** where a concrete noun, number, or action exists; the
  portability test: a line that fits any topic is filler.
- **Passive or tangled sentences:** active voice when natural, one idea per line.
- **Robotic rhythm:** the same cadence, three-part list, or contrast shape in
  several scenes.
- **Copy that narrates the visual:** the text adds what the picture cannot say.

### Arabic adaptation
Flag and rewrite formulaic phrasing unless the source and context justify it:
«في عالم اليوم»، «في عصرنا الحالي»، «وهنا تكمن المشكلة»، «وهنا يأتي دور»،
«الأمر لا يتعلق بـ...»، «ليس الأمر مجرد...»، «ما لا يخبرك به أحد»،
«الحقيقة التي يتجاهلها الجميع»، «المستقبل ليس قادما...»، «نقلة نوعية»،
«تحول جذري»، «ثورة في»، «غير قواعد اللعبة». Also watch for repeated
three-part structures, stacked ellipses (…), colon-led reveals, artificial
pauses, generic motivational endings, inflated claims, polished corporate
prose, and the same rhetorical cadence across scenes. Natural Arabic
expressions stay; the aim is removing formula, not flattening voice. The
Language rules above (MSA, no dialect, no tashkeel, the banned word) still
apply and are enforced by the existing checker.

### Voice and editing
Preserve the intended meaning, personality, and cadence; make the minimum
effective edit and leave strong lines alone. Lead with the point, prefer
concrete words and active voice, cut filler, and shorten only when it reads
better; short is not automatically better. Prefer natural, Saudi-readable MSA
over stiff formal or corporate Arabic. Scripts must not all sound alike.

### Source fidelity (overrides style)
The pass may change style, never meaning. It must not strengthen a claim
beyond the source, turn an inference into fact, drop uncertainty that matters,
turn an illustrative example into a factual claim or drop its label, alter a
number, or change what a citation supports. If a better sentence would change
meaning, keep the original meaning.

### Self-check
1. No obvious AI-slop pattern remains.
2. The Arabic reads naturally aloud.
3. No formulaic opening.
4. No fake-profound or motivational ending.
5. No unsupported hype or superlative.
6. No rhetorical pattern repeated across scenes.
7. Copy does not merely narrate what the visual shows.
8. Source meaning, qualifiers, and numbers are unchanged.
9. Illustrative content is still labelled as illustrative.
10. `check-tashkeel.py` passes (tashkeel and banned word).

`script.md` holds the final copy only; no second script file and no editorial
record.

## Arabic tashkeel (diacritics) — permanent rule
**Do not use Arabic diacritics/tashkeel in headlines, captions, subtitles,
labels, or body text. Use plain Arabic letters by default.**

Forbidden combining marks include (non-exhaustive):
`U+064B–U+065F` (fathatan, dammatan, kasratan, fatha, damma, kasra, shadda,
sukun, and the hamza above/below marks), `U+0670` (superscript alef),
`U+0610–U+061A` (Arabic signs), and `U+06D6–U+06ED` (Quranic marks).

- This does **not** remove base letters such as `آ` (U+0622), `أ` (U+0623),
  `إ` (U+0625), `ئ` (U+0626), `ؤ` (U+0624) or `ء` (U+0621). These are letters,
  not tashkeel, and stay.
- **Only exception:** a diacritic may be used when it is absolutely necessary to
  prevent ambiguity in a proper noun or a pronunciation-sensitive term. Prefer
  rewording over adding a diacritic. Every exception must be justified in
  `sources.md` under a `## Notes` section.
- Apply this rule to `index.html` **and** to the written deliverables
  (`script.md`, `storyboard.md`, `sources.md`, `BRIEF.md`).
- Enforce with `templates/tech-news-ar/tools/check-tashkeel.py <project-dir>`
  (stdlib-only; exit 1 if any mark is found). Run it before render.

## Structure (5 beats, 25–35s)
1. **Hook** — the strongest fact or development, stated plainly.
2. **What happened** — the concrete change, no build-up.
3. **Why it matters** — the impact or context, without speculation.
4. **One key detail** — the most load-bearing verified nuance/limitation.
5. **Takeaway** — a measured closing line, framed as direction, not hype.

Assign time windows that sum to the target duration; each beat is one `.clip`.

## Attribution (required)
- The project owner's handle (`user_identity.x_handle`; templates carry the
  placeholder `@your_handle`) is present in social output: subtle, visually integrated,
  normally at the bottom edge or in the closing scene, never dominant. This is a
  **global user preference** (`CONTEXT_SCOPE.md` §6), not a per-project design
  choice. The only exception is a project where the user explicitly opts out —
  for example a neutral repository/GitHub demo — recorded as
  `user_identity.show_handle: false` in the project manifest.
- Every borrowed screenshot/media carries an adjacent on-screen credit:
  `المصدر: <publisher>`.
- The whole piece credits sources in `sources.md`.

## Captions
- The on-screen Arabic text **is** the caption — there is no separate voiceover
  or subtitle track.
- One idea per beat; keep a headline to roughly two lines and a subcaption to
  one or two lines.
- Subcaption expands the headline; it does not repeat it.
- Ensure text stays inside the safe zones (`VIDEO_WORKFLOW.md`).

## RTL / bidi
- Never put `dir="rtl"` on `<html>` — it blanks the rendered video. Scope
  `direction: rtl` to the text container (`.scene`).
- Start an Arabic sentence with an Arabic word. When mixing Latin terms inline,
  keep them inside the RTL run (e.g. `ميزة computer use لا تزال في ...`). Do not
  lead a headline with a Latin token — bidi places it wrong.
- Wrap inline highlight terms in a `<span class="hl">` rather than reordering
  words.

## Accuracy
- Verify every claim against the supplied source and primary sources.
- Do not invent facts, numbers, quotes, dates, screenshots, or implications.
- Do not exaggerate. Keep primary-source qualifiers (e.g. "research preview",
  "beta", "optional") on screen when they are material.
- No dates on screen unless directly verified in a primary source.
- Do not show marketing screenshots that contain fictional sample data
  (fake metrics, fake prices) — see `ASSET_POLICY.md`.

## Brand profiles & editorial independence
- A brand profile shapes the **visuals** (tokens, palette, shapes, motifs in
  the scene content). It must never change the factual wording or the
  editorial tone.
- Select the profile per `templates/tech-news-ar/brands/README.md`: one clearly
  dominant company → its profile; multiple equally-central companies or none →
  `generic`.
- Never infer a brand from an unrelated asset (e.g. a screenshot that merely
  mentions a company).
- Resolve the brand via the **Brand Resolution Gate** before `DESIGN.md` is
  written, and never carry a previous project's profile, palette, layout, or
  visual language into a new video (`CONTEXT_SCOPE.md` §2–§3).
- The visual identity must be **inspired by** the company's public identity, not
  an imitation of official communications. A viewer must not mistake the video
  for one published by that company.
- Use official logos only via `ASSET_POLICY.md` and only in placements the
  profile allows.
- All Arabic rules above — RTL scoped to scene containers, no tashkeel,
  `@your_handle` footer, visible source credit — are **unchanged** by the
  selected brand.

## Audio
- Videos are **silent by default**; audio is added only when the brief requests
  it. The rule and the requested-audio guidance live in `AUDIO_DESIGN.md` §0.
- When audio is requested, it must not change editorial facts or tone, and every
  Arabic rule above still applies.

## Forbidden
- AI-generated images or media.
- Any audio (music, SFX, ambience, narration) the brief did not request.
- Unlicensed or unclear music, or loud/dramatic music that fights the content.
- Unverified superlatives ("الأفضل", "الأول", "الأسرع") without a primary source.
- Reusing another video's branding as if it were the publisher's.
