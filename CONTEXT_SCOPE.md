# CONTEXT_SCOPE.md — context scopes, brand resolution, and reference isolation

Normative framework rule for Motion Studio. It fixes two systemic failures:

1. **Missing brand resolution** — a video about a recognizable product (e.g.
   Claude Code / Opus 5.5) inherited the visual language of an unrelated
   Motion Studio demo instead of the subject's own identity.
2. **Reference-scope leakage** — a design reference supplied for **one** video
   was allowed to influence **later unrelated** videos.

`VIDEO_WORKFLOW.md`, `CONTENT_RULES.md`, and
`templates/tech-news-ar/brands/README.md` implement this rule. This file is the
source of truth when they disagree.

---

## 1. The three context scopes

Every piece of direction applied to a video belongs to **exactly one** scope.
Scopes never blend, and a value is never promoted from one scope to another
without an explicit user instruction.

### 1.1 Global user preferences — persist across projects

Durable defaults for this workspace. They apply to every new video unless the
user overrides them for a single project.

- Arabic-first when the audience and subject warrant it.
- **Alexandria** for Arabic.
- **No Arabic tashkeel** (see `CONTENT_RULES.md`).
- Technical/Latin runs may use **IBM Plex Mono**.
- The project owner's social handle (`user_identity.x_handle`) normally
  appears subtly in social-video output (see §6).
- **Silent by default** — no music, SFX, ambience, narration, or audio stream
  unless the brief requests audio (`AUDIO_DESIGN.md` §0).
- The quality/review requirements (`AI_REVIEW.md`, `QUALITY_SCORE.md`).

Global preferences are the **only** thing that carries forward by default.
Everything visual about a finished video is *not* global.

### 1.2 Project-specific context — this video only

Valid **only** for the current video/project. It must never become a default
for a future project.

- A design reference or inspiration image supplied for this project.
- A screenshot supplied as visual inspiration.
- A color palette requested for one video.
- Temporary layout/style directions.
- **Composition language**: scene layout, card/panel geometry, dashboard
  patterns, navigation rails, radial diagrams, metric blocks, scene framing,
  motion grammar, and information hierarchy.
- Source footage specific to this story.
- The subject's brand profile chosen for this story.

Project-specific context is recorded in the project manifest (§5) and expires
with the project.

### 1.3 System defaults — neutral fallback

Used **only** when neither explicit project direction nor subject branding
determines the visual direction.

- The neutral Motion Studio default palette and type scale
  (`templates/tech-news-ar/`), with the `generic` brand profile when no single
  subject company is dominant.
- System defaults are neutral. They are **not** the style of the most recently
  produced video.

---

## 2. Design reference rule (hard rule)

> **User-supplied visual references are project-scoped by default.**

A reference image, palette, layout, motif, or animation language supplied for
one project must never influence another project unless the user explicitly
says something equivalent to:

- "make this our default style"
- "use this style going forward"
- "save this as a template"
- "apply this to future videos"

Only then may a reference be **promoted** (record
`visual_reference.promoted_to_template: true` with the authorizing instruction).
Silence is not authorization.

When a new project begins, **reset** all of the previous project's:

- reference images
- palettes
- layouts
- visual motifs
- scene structures
- art direction
- animation language

**Do not infer persistence merely because the previous project used it.**

### 2.1 Reusable foundation and composition language

The Motion Studio **technical foundation is reusable by default** and is not "a
previous project's style": the typography system, spacing, safe zones, the
timeline structure, motion primitives (`lib/`), chrome and handle placement, and
brand handling. Building on it needs no authorization and no justification.

- **The foundation does not own the visual concept.** What the viewer sees in
  each scene is derived from the subject for every video
  (`VIDEO_WORKFLOW.md` §Visual-first rule). Scene grammars are optional layout
  helpers, not the concept. The technical system is never redesigned per video,
  and novelty for its own sake is not a requirement.
- **What must not carry over** is another project's *project-specific* look
  (§2): a user-supplied reference, or a one-off art direction built for one
  subject, reused on an unrelated subject without the user asking for it.
  Recoloring such a layout does not make it the new subject's identity.

### 2.2 `composition_language` in the manifest

```yaml
brand:
  composition_language: foundation | fresh | inherited
  inherited_from: null            # a project id, only when inherited
  inheritance_authorized: false   # true only with an explicit user instruction
```

- `foundation` (the default) — built on the starter, brand profile and shared
  grammar. `inherited_from: null`.
- `fresh` — a new direction designed for this subject. `inherited_from: null`.
- `inherited` — reuses a specific earlier project's one-off look. Requires a
  non-null `inherited_from` **and** `inheritance_authorized: true`
  ("reuse previous layout", "continue that series").

The preflight (`design/cli.py preflight`) fails only when `inherited_from` is
set without explicit authorization, or `composition_language` is missing.

---

## 3. Brand Resolution Gate (applies before `DESIGN.md` is written)

A standard video resolves its brand from the summary in `VIDEO_WORKFLOW.md`
§Context scope and brand; this section is the full rule, for when this document
is opened (a supplied reference, a style reuse or promotion, a handle opt-out).

Before any visual design is authored for a new video, resolve and record:

| Field | Question |
|-------|----------|
| **SUBJECT** | What is this video about? |
| **PRODUCT / COMPANY** | Which product/company owns the identity? |
| **CONTENT TYPE** | Launch, explainer, tip, demo, comparison, … |
| **OFFICIAL VISUAL IDENTITY AVAILABLE?** | Is there a public, sourceable identity? |
| **USER-SUPPLIED REFERENCE FOR THIS PROJECT?** | Was a reference given *for this project*? |
| **USER EXPLICITLY REQUESTED AN ALTERNATE STYLE?** | Did the user ask for a different look? |
| **COMPOSITION LANGUAGE** | `foundation` (default), a `fresh` direction, or `inherited` from a named prior project (needs authorization)? |

Apply this **priority order** and take the first that resolves:

1. Explicit **current-project** user instructions.
2. **Current-project** supplied reference.
3. **Official subject/product visual identity** (source it — see
   `ASSET_POLICY.md`).
4. Motion Studio **neutral default** (`generic`) — only when the subject has
   no applicable brand identity (`product: none`), or the user explicitly asked
   for a neutral / unbranded treatment (record `neutral_approval`).

A named product/company never reaches step 4 by default. With no supported
profile, resolve a project identity from official sources and record
`project_identity` (§5). With no official evidence, **stop before composition**
and ask for an explicit decision.

Never use:

5. The **previous project's design language** — unless the user explicitly
   requested it.

For branded products (Claude / Claude Code, OpenAI, Google, Gemini, NVIDIA,
Typesafe, Ceer, …), inspect the current official visual identity and available
official assets **before** designing. Do not invent a generic "AI" identity
when a recognizable product identity exists. Using a product's identity must
stay **inspired-by**, never a look-alike of official communications
(`brands/README.md`, legal/design rule).

Record the outcome in the project manifest (§5) as
`brand.identity_mode: official | user-reference | neutral`.

---

## 4. Start-of-project reset check

Run this before writing `DESIGN.md` when the project brings its own reference
or follows a project that had one.

```
NEW PROJECT CONTEXT CHECK
- [ ] No prior project's supplied visual reference or one-off art direction
      carried over without authorization (the shared foundation, §2.1, is fine)
- [ ] Current subject/product identified
- [ ] Brand identity resolved (Brand Resolution Gate, §3)
- [ ] Current-project references identified (project-scoped only)
- [ ] Persistent user preferences applied separately (global, §1.1)
- [ ] @your_handle decision made (§6)
```

**Fail the design preflight** if a previous project's style is being reused
without explicit authorization.

Enforce it (read-only, exits non-zero while the manifest is missing, incomplete,
a scope is not `project-only`, or a reference is promoted without a recorded
authorization):

```bash
python3 design/cli.py preflight videos/<slug>
```

---

## 5. Project manifest

Every new video records a small manifest in the project's `DESIGN.md`
(canonical, human-readable) and mirrors the machine-readable fields in
`meta.json`. At project initialization `promoted_to_template` **must** default
to `false`.

```yaml
brand:
  subject: "<what the video is about>"
  product: "<product / company that owns the identity>"
  source: "<verified source(s) for the identity, or 'none'>"
  identity_mode: official | user-reference | neutral
  reference_scope: project-only
  composition_language: foundation | fresh | inherited
  inherited_from: null
  inheritance_authorized: false
  # named product without a supported profile — one of:
  project_identity:            # identity resolved for this project only
    source: "<official URL / approved source>"
    status: verified | user-approved
    primary: "#…"
    accent: "#…"
    background: "#…"
    text: "#…"
  neutral_approval: "<the user's explicit request for a neutral treatment>"

user_identity:
  x_handle: "@your_handle"
  show_handle: true

visual_reference:
  supplied: true | false
  scope: project-only
  promoted_to_template: false
```

Rules:

- **No previous project's manifest is inherited automatically.** Start from the
  template defaults (this section) and fill it from the current project only.
- `reference_scope` is `project-only` unless the user promoted it (§2).
- `show_handle` follows the user's instruction for this project; the global
  default is `true` (§6).
- `product` is `none` for an unbranded subject. Any other value is a named
  product/company: the preflight fails unless `meta.json` `"brand"` is a
  supported profile, `identity_mode` is `user-reference`, or
  `project_identity` / `neutral_approval` is recorded.
- `composition_language` defaults to `foundation` (§2.1). Building on the
  starter and a brand profile is a complete brand resolution.

---

## 6. Social identity / user credit

Global user preference, applied unless the user explicitly opts out:

> Social videos include the project owner's handle, recorded as
> `user_identity.x_handle`.

Starters ship the literal placeholder `@your_handle`. Replace it with the
owner's real handle, or — for a video without a handle — delete the handle
element and set `show_handle: false` (`x_handle` may then be omitted). A
handle is never required. The build stage blocks a composition that still
contains the placeholder (`handle_placeholder`), and `preflight` rejects it as
`x_handle`. Never credit someone other than the project owner.

- Placement: **subtle**, visually integrated, normally at the **bottom edge**
  throughout or clearly in the **closing scene**.
- It must **not** compete with primary content.
- It must **never** appear inside a GitHub / product demo when the user
  explicitly requests a neutral repository asset.

This is a **global** preference (§1.1), unlike design references (§1.2).
Record the per-project decision as `user_identity.show_handle` in the manifest.
