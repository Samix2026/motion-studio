# WORKFLOW_REFERENCE.md — read-on-demand production reference

Specialized sections moved out of `VIDEO_WORKFLOW.md` unchanged. None of this is
required reading for a standard video; open a section only when its trigger in
`VIDEO_WORKFLOW.md` §Read on demand applies.

## Optional project metadata (backward compatible)

`meta.json` may additionally record cross-subsystem references. All are
optional; older projects without them keep working:

```json
{
  "brand": "microsoft",
  "reference_profile_id": null,
  "cost_gate_id": null,
  "cost_gate_status": null,
  "word_timing_file": null,
  "review_revision": null,
  "proposal_status": null,
  "status": null,
  "published_at": null,
  "final_master": null
}
```

- `reference_profile_id` — an optional `reference/profiles/<id>.json` used as
  planning context only (never auto-applied, never a defect).
- `cost_gate_id` / `cost_gate_status` — the gate in `costgate/state/`.
- `word_timing_file` — the canonical `*.word-timings.json` (usually next to the
  voice asset).
- `review_revision` / `proposal_status` — the last review revision and the
  proposal decision state.
- `status` / `published_at` / `final_master` — publication metadata used by the
  retention cleanup (`tools/cleanup-published.py`). `status` is `"published"`
  only after a human publishes; `published_at` is an ISO-8601 timestamp;
  `final_master` is the project-relative final MP4 (e.g.
  `renders/video-final.mp4`). These are never set automatically.

`meta.json` is not a duplicate manifest: it stays the small project marker and
only gains optional pointers.

## Platform outputs (optional `meta.json` → `outputs`)

One master serves every platform, rendered once to `renders/video.mp4`:
**16:9, 1920×1080** by default, or 9:16, 1080×1920 when the project explicitly
declares portrait (`VIDEO_WORKFLOW.md` §Output format). Platforms are profiles on top of that
master, not separate compositions. A platform gets its own export file only
when it needs a different cut (trim); otherwise the master is uploaded as is.

```json
"outputs": {
  "master": { "aspect_ratio": "16:9", "resolution": "1920x1080", "file": "renders/video.mp4" },
  "cover":   { "time_s": 1.0, "file": null, "text": null },
  "caption": { "text": null, "hashtags": [] },
  "cta":     { "text": null, "url": null },
  "platforms": {
    "tiktok":          { "enabled": true },
    "instagram_reels": { "enabled": true },
    "youtube_shorts":  { "enabled": true },
    "x":               { "enabled": true }
  }
}
```

- `master` must agree with `format` (default `landscape` ↔ `16:9` / `1920x1080`; `portrait` ↔ `9:16` / `1080x1920` only when explicitly requested).
  Without `outputs`, a project is master-only, as before.
- `cover` — thumbnail frame (`time_s` in the master) or a still `file`, plus
  optional overlay `text`. `cta` — the call to action written in the post.
- `caption` — social-post text, hashtags, and post metadata. It is **not**
  on-screen subtitle text or a narration transcript.
- Each platform entry may override `cover`, `caption`, or `cta`, and may add:
  - `export` — output file, default `renders/exports/<slug>-<platform>.mp4`;
    set only when the platform needs its own cut.
  - `trim` — `{ "start_s": …, "end_s": …, "note": "…" }` for that export.
  - `duration` — `{ "preferred_s": [min, max], "max_s": … }`, overriding the
    table below.
  - `safe_zone` — `{ "top": px, "side": px, "bottom": px }`, used only when the
    platform's UI needs more than the portrait text-safe padding
    (§Safe zones: 200 / 72 / 320). The master is designed to that padding, so
    most platforms need no override.
- No credentials, account IDs, endpoints, schedules, or publishing automation
  in `outputs`. Publishing stays manual (`tools/mark-published.py` records it
  afterward).
- Platform exports are derived files: the retention cleanup keeps only
  `final_master`.

Duration follows the project brief (standard videos: 25–35 s); there is no
per-platform duration preference. Platform maximums: verify before relying.

#### Platform facts

- Remembered platform limits are not permanent truth. Maximum duration,
  safe-zone UI behavior, and upload constraints change.
- Verify any such fact from a current official source before relying on it
  operationally, and record it in the project (`duration.max_s`,
  `safe_zone`) with the source in the project's `sources.md`.
- Unverified platform facts stay descriptive and non-binding in this repo;
  never hard-code a speculative limit.

## Run manifest recording (Phase 1, opt-in)

An additive, opt-in recording layer answers which project / revision / run /
stage attempt produced which artifacts, without changing existing behavior. It
records only what an external process reports: it never runs providers,
renderers, or shells, never approves anything, and never infers success or
finality from file existence.

- **Projects** — `runs/projects/<project_id>.json`: an explicit id plus a
  workspace-relative project directory and optional `revision` /
  `parent_revision`. Ancestry is never inferred from directory names.
- **Runs** — `runs/manifests/<project_id>/<run_id>.json`: schema version,
  revision, an immutable workspace-relative `revision_dir` binding, `created_at`,
  workflow contract version, attempts, artifacts, validations, and historical
  references. Project-rooted artifacts resolve against the run's
  `revision_dir`, so two creative revisions under one logical project resolve
  independently; ancestry is never inferred from `rev2`/`v2`/`final` names.
  After creation, the run interpretation context is frozen: `revision`,
  `revision_dir`, `workflow_contract_version`, and `narration_enabled` cannot be
  changed by mutation — a different revision or workflow context requires a new
  run. Only artifacts, attempts, validations, and historical references may be
  appended.
- **Artifacts** are explicitly selected revision-root-relative paths with a
  streaming SHA-256 and byte size. Each is either produced by a recorded attempt
  or marked `legacy_external` (a genuine legacy artifact needs no producer). No
  final/master artifact is guessed.
- **Attempts** record `reported_execution_outcome`, required input kinds, and
  required output kinds (a narrated composition consumes narration and produces
  a composition; a render consumes a composition and produces a render).
  Successfully reported stages must satisfy their input/output kinds; failed or
  unknown attempts may preserve partial evidence. Attempts are immutable at the
  persistence boundary — they cannot be edited, replaced, or deleted, and a
  correction is a new superseding attempt. A started attempt is resolved by a
  new attempt that explicitly supersedes it, never by mutation. Reported
  execution success and validation success are separate, and neither implies
  creative, cost, or publication approval.
- **Validation evidence** is content-addressed: `evidence_artifact_id` must
  reference a registered artifact, and full validation detects missing or
  changed evidence.
- **Provider accounting** (`provider`, `tool`, `model`, `usage`) is nullable.
  `usage` is a small normalized object (`input_units`, `output_units`,
  `characters`, `seconds`, `requests`, `currency`, `estimated_cost`,
  `billed_cost`, `cost_provenance`); unknown values stay `null`, cost requires a
  provenance, and non-finite numbers or credential-shaped fields are rejected
  without being echoed. Credentials are never stored.

```bash
python3 studio/cli.py project-register --project-id <id> --project-dir videos/<slug> [--revision <r>] [--parent-revision <p>]
python3 studio/cli.py run-create --project-id <id> --run-id <run> --revision <r> --revision-dir videos/<rev-dir> [--narration]
python3 studio/cli.py artifact-register --project-id <id> --run-id <run> --artifact-id <a> --kind <k> --root project|workspace --path <p> (--producer-attempt <t> | --legacy-external) [--historical]
python3 studio/cli.py attempt-record --project-id <id> --run-id <run> --attempt-id <a> --stage <s> --origin external --outcome <o> [--input <id>]... [--output <id>]... [--usage <json>|--input-units N --billed-cost N --cost-provenance <p>]
python3 studio/cli.py validation-record --project-id <id> --run-id <run> --validation-id <v> --validator <n> --validator-version <v> --evidence-ref <ref> --evidence-artifact <a> --result passed|failed|unknown|not_run --scope <s>
python3 studio/cli.py historical-reference --project-id <id> --run-id <run> --reference-id <a> --root workspace --path runs/<legacy>.json
python3 studio/cli.py manifest-validate --project-id <id> --run-id <run>
python3 studio/cli.py run-status --project-id <id> --run-id <run>   # read-only
python3 studio/cli.py run-history [--project-id <id>]              # read-only
```

Persistence is standard-library and atomic (temporary file + replacement) with a
per-run single-writer lock (collision-free hashed identity) that is never stolen
and no automatic crash recovery; a stale lock may be removed manually only after
confirming the writer is no longer active. Recorder storage is confined to the
exact designated directories `runs/projects/`, `runs/manifests/`, and
`runs/.locks/`: symlinked recorder storage components, aliases into other
workspace areas (including legacy `runs/*.json`), and outside-workspace escapes
are rejected before any create, replace, remove, enumerate, or lock action.
Writes reject malformed records (a stored record must be a JSON object; stored
historical references are structurally validated), unsupported schema and
contract versions, duplicate identities, and inconsistent relationships:
attempt outputs must agree with artifact producers and the reverse (an artifact
producer must list it among that attempt's outputs), supersession must not be
self-referential or cyclic, historical references must match their artifact, and
references must be registered. Genuine `legacy_external` artifacts remain
producer-free.

`run-status` is read-only and exposes distinct, non-final states (it is not final
QC):

- `structural_validity` — stored records are well-formed.
- `reference_resolution` / `reference_validity` — every referenced ID exists.
- `relationship_validity` — producer/output, supersession, and historical
  relationships are consistent.
- `stage_contract_validity` — successfully reported stages satisfy their required
  input/output kinds.
- `unresolved_reference_ids` — IDs referenced but not yet registered.
- `complete` — true only when references resolve, relationships and stage
  contracts are valid, and every attempt is terminal and resolved. Deferred
  registration stays allowed, and `complete` is never true while a successful
  terminal attempt points at an unregistered output.

`manifest-validate` performs the full structural, reference, relationship, and
stage-contract check plus validation-evidence content integrity, and its output
states each checked scope plus `production_artifact_integrity: "not_checked"`:
broader production artifact content integrity (for example a changed render) is
reported by `run-status` per artifact (`ok`/`missing`/`changed`) and is not
implied by `valid`. Paths must resolve within the explicit
workspace/revision roots; traversal, symlink escapes, and refused targets such as
`.env`/`.git` are rejected before any outside read or write. The legacy
`runs/<YYYY-MM-DD>-<slug>.json` summaries are never modified; they can be
associated as `legacy_external` historical references, which inspection labels
`historical_reference_only`. Add `--workspace <dir>` to target a non-default
workspace root.

## Reference style analysis (optional, before planning)

An optional reference pass extracts abstract style context (pacing, cut
density, duration bands) for planning only:

```bash
python3 reference/cli.py analyze <local-video-or-image-dir> [--id ID]
python3 reference/cli.py analyze --manual <observations.json>
```

- Output is **style metadata only**: observed vs inferred are separate, and
  unknown measurements stay `unavailable`.
- It never copies scripts, wording, scene order, logos, branding, or assets.
- It does **not** modify brand profiles, does **not** auto-apply to a project,
  and never overrides factual accuracy, source attribution, RTL, no-tashkeel, or
  brand rules. It is not a review defect source.

Full detail: `REFERENCE_ANALYZER.md`.

## Word-level timing (when there is voice)

If the piece has a voiceover, normalize the provider's **real** timestamps once
into the canonical word-timing format and cache them with the voice asset:

```bash
python3 timing/cli.py normalize <provider-response.json> --provider elevenlabs \
  --out assets/audio/voice/<name>.word-timings.json
python3 timing/cli.py phrases <name>.word-timings.json --out captions.json
```

- Visual rerenders, caption restyles, and review runs read the cache; they must
  not call TTS again.
- Missing timestamps stay unavailable — never estimate or derive them from
  character counts.
- Review consumes the timings read-only for caption/audio sync findings.

Full detail: `WORD_SYNC.md`.

## Cost gate (before any paid generation)

No paid generation starts silently. After the script/storyboard + asset plan +
provider selection, and before any paid video/image/TTS/SFX/music/external call,
run the cost gate:

```bash
python3 costgate/cli.py build   <project> --plan <plan.json> [--pricing <p.json>]
python3 costgate/cli.py check   <project>     # non-zero while not approved
python3 costgate/cli.py approve <project> --limit <usd>
```

- Estimates use only explicit, sourced prices; anything unverified is `UNKNOWN`
  (never invented).
- Paid generation is **blocked** until a human approves the estimate, and it
  **stops** if the estimate exceeds the approved limit.
- The cost gate is separate from the post-preview AI review gate: cost approval
  is before generation, creative/technical approval is after the preview.
- Record the gate's numbers in the run record (`RUN_METRICS.md`).

Full detail: `COST_GATE.md`.

## Audio design and mix

Videos are **silent by default**: no music, SFX, ambience, narration, or audio
stream unless the brief requests audio (`AUDIO_DESIGN.md` §0). A silent project
writes `Audio cue: none` in `storyboard.md`, adds no `<audio>` element, and
verifies 0 audio streams in the render.

The rest of this section applies **only** when the brief requests audio:

- Plan audio in `storyboard.md`: every beat gets an **Audio cue** block (type,
  trigger, timestamp, duration, purpose, intensity, source). Use `none` when a
  beat should stay silent.
- Cue types: `keyboard`, `click`, `whoosh`, `impact`, `digital`, `ambient`,
  `tick`, `music`, or a justified combination (e.g. `keyboard + low music`).
- Source audio only with a clear license; track every external file in
  `sources.md` (filename, URL, creator, license, scene) per `ASSET_POLICY.md`.
  If licensing is unclear, use no music.
- Wire cues with standard HyperFrames `<audio>` elements (muted video + separate
  `<audio id=...>`, `data-start`/`data-duration`/`data-volume`, no `crossorigin`).
  Duck/animate `volume` on the one paused GSAP timeline (`AUDIO_DESIGN.md` §7).
- Final mix with FFmpeg when normalization/ducking/limiting is needed: AAC audio,
  48 kHz, stereo, true peak ≤ −1 dBTP, no clipping, `-shortest` so audio matches
  the video (`AUDIO_DESIGN.md` §8). Keep `-c:v copy` unless the video also
  changes.
- Verify the audio stream and duration with the `ffprobe` command in
  `AUDIO_DESIGN.md` §8.

Audio checks feed the Technical validation category in `QUALITY_SCORE.md`;
unrequested audio is a hard fail there.

## Narration mode

Narration is a per-project mode in `meta.json`: `"narration": "off" | "optional" | "required"`
(default `off`). Enable it only when the brief requests narration (`AUDIO_DESIGN.md` §0). It is read-only to inspect:

```bash
python3 narration/cli.py mode   <project>
python3 narration/cli.py status <project>
python3 narration/cli.py plan   <project>   # --json for machine output
```

When enabled, the ten-step pipeline runs: Alice TTS with provider timestamps in
the same call → normalize to `timing/` → phrase groups → mark narrated scenes
`data-narration-locked="true"` → kinetic captions → set each scene duration from
`max(narration end, final caption end, visual minimum duration) + tail padding`
→ caption/audio sync review → preview render → Human Gate 2.

- `off`: the pipeline is inactive (`n/a`).
- `optional`: narration may be used; missing assets are non-blocking.
- `required`: missing narration blocks the pipeline.

Step 1-2 (voice generation) is paid and stays behind Gate 1 (the cost gate); the
mode layer never calls a provider, never renders, and never writes to a project.
Narration-locked scenes cannot be shortened (see `review/` narration-lock rules).

## Review input integrity (Phase 2, Unit A)

Managed review callers select inputs explicitly instead of discovering them:

- The exact render is named (`--render`), plus the composition `index.html`, any
  selected local CSS, explicit timing/caption files (or declared absence),
  selected snapshots, and declared local dependencies. The explicit path
  **never** auto-selects `renders/video.mp4`, the first sorted MP4, `preview.mp4`,
  or an inferred "final"; a missing explicit render fails clearly. Legacy
  commands keep the existing discovery behavior.
- Declarations define what is consumed. In explicit mode the analyzer validates
  that its project context matches the `ReviewInputs` object, that the CSS
  typography actually consumes exactly equals the declared CSS, that snapshots
  come only from the declared selection, and that every required literal local
  dependency (`<script src>`/`<link href>`) is declared; an undeclared required
  literal fails clearly before findings can change. Selected timing/caption
  inputs propagate through analysis and proposal generation; explicit mode never
  reloads legacy-discovered timing/captions.
- Every selected input is content-hashed into a versioned **review-input
  descriptor** (render, composition, CSS, timing/caption with validity recorded
  separately from content identity, dependencies, snapshots, the normalized
  **effective** rules actually used, typography scale, analyzer/parser/pixel/
  timing-validator implementation identity, and FFmpeg/FFprobe identity). The
  **review fingerprint** is computed from the current descriptor — never from a
  saved `content_hash` — so same-size replacement changes it, equivalent rule key
  ordering and unordered inventories do not, and unrelated file changes and
  inactive configuration do not. Runtime/JS dependency coverage is reported as
  `partial_local_only`/`unsupported` rather than implied complete.
- Saved reports/proposals carry the full descriptor and fingerprint. Freshness
  reconstructs the exact saved selection (not legacy discovery) and re-hashes
  current content; changed render/timing/caption/CSS/dependency invalidates,
  extra unselected MP4 files do not. Older records without a reconstructable
  descriptor stay readable but are `unverified`; stale/unverifiable evidence is
  never used to infer caption review completion, and `review report` labels saved
  proposal evidence `current`/`stale`/`unverified` instead of presenting it as
  current.
- Read paths are side-effect-free: `analyze`, `narration.plan`, `review status`,
  `review report`, and `studio status` use a read-only state accessor and create
  no state, report, or version directories. Only explicit mutation commands
  (review/approve/apply/vision) initialize or save state.
- Measurements publish availability/coverage metadata separately from findings:
  each family is `complete`, `partial`, or `unavailable`. A failed silence probe,
  a failed deadline frame (never substituted with frame 0), or missing midpoint
  frame samples cannot be read as a clean completed measurement, and narration
  planning treats unavailable/partial caption-sync evidence as re-review
  required.
- Media probing goes through a narrow local boundary (`review/process.py`):
  a fixed allowlist of known operations (probe, silence/freeze detection,
  one-frame decode, tool identity) rather than a generic command runner; fixed
  FFmpeg/FFprobe executables; explicit argv lists; `shell=False`; explicit
  working directory; a minimal explicit child environment (no provider keys,
  proxies, auth tokens, or Python/package-manager hooks inherited); a finite
  positive timeout; and bounded stdout/stderr (raw-frame output is separately
  bounded). Local-only media inputs are enforced before launch — URLs, network
  paths, pseudo-protocols, playlists, and unsupported containers are rejected,
  and remote composition references are never fetched. A failed or missing tool
  raises and is never reported as an empty-success measurement. Only literal
  local dependency references are validated (no JavaScript resolver or browser
  execution).

## Managed timing execution (Phase 2, Unit B — Increment 1)

An opt-in, **local-only** managed execution lifecycle for the offline `timing`
stage. It is the first executor built on the Phase 1 recorder; it does not
render, use a browser, call a provider, run TTS, or touch the network.

- **Explicit request** — names the workspace/project/run, an explicit new
  `attempt_id`, explicit **registered input artifact IDs** (at least one of kind
  `narration`, per the frozen timing stage contract, plus a registered artifact
  holding the raw provider timing response), explicit output paths and artifact
  IDs, a finite positive timeout, and `--confirm`. Nothing is discovered.
- **Pre-execution validation** (no side effects): run/project existence,
  structural manifest validity, input artifact resolution, timing stage-contract
  input kinds, path containment, immutable run/revision context, output
  destinations (not already present on disk or registered), unsupported stage
  rejection, and remote/network/pseudo input rejection. Validation failure
  creates no attempt, artifact, lock, or output.
- **Execution lock** — an execution-scoped run-level lock reusing Phase 1
  `FileLock` semantics (`O_CREAT|O_EXCL`, never stolen, no stale-lock recovery,
  no crash recovery), held for the whole execution.
- **Bounded local execution** — only the existing offline timing operations are
  reused (`timing.adapter.normalize` → `timing.schema.validate`, then
  `timing.phrases.to_captions → validate_captions`) through a narrow
  allowlisted function boundary. No subprocess, no shell, no network.
- **Append-only receipt** — one terminal Phase 1 attempt (`succeeded`, or
  `failed` with a concise error on execution failure), written atomically
  together with the registered output artifacts (kind `timing`, optional
  `caption`), each with SHA-256 and `producer_attempt_id`. Prior attempts are
  never mutated or deleted; failures are never retried automatically.
- **Overwrite safety** — an existing output file, artifact ID, or attempt ID is
  refused. A rerun/correction is a new explicit request producing a new attempt;
  it never silently overwrites.
- **Read paths unchanged** — `studio status`, `run-status`, `manifest-validate`,
  `narration plan`, and review status/report remain side-effect-free.

```bash
python3 studio/cli.py timing-execute \
  --project-id <id> --run-id <run> --attempt-id <new-attempt> \
  --input <narration-artifact> --input <provider-response-artifact> \
  --provider-response-artifact <provider-response-artifact> --provider elevenlabs \
  --output-timing-artifact <timing-artifact> --output-timing-path <rel-path> \
  [--output-captions-artifact <caption-artifact> --output-captions-path <rel-path>] \
  --timeout 60 --confirm
```

## Published project retention policy

Video projects must not accumulate forever. Retention is driven by the
publication metadata in `meta.json` (`status`, `published_at`, `final_master`)
and enforced by `tools/cleanup-published.py`.

- **Full project retained for 7 days after publication.** The default window is
  7 days (`--days`, min 1).
- **After 7 days, only `video-final.mp4` is retained**, copied to
  `~/Videos/Published/<project-name>.mp4`.
- **The entire project directory is then deleted.** Projects are never
  archived.
- **Unpublished projects are never deleted** (`status` must be `"published"`).
- **A project is never deleted without a verified final master** — a readable,
  non-zero-size `final_master` whose SHA-256 matches the retained copy.
- **Cleanup is dry-run by default.** Running the tool with no flags only prints
  a report; deletion requires the explicit `--execute` flag, and never happens
  automatically.
- Publication metadata is **never set automatically**.

```bash
python3 tools/cleanup-published.py                      # dry-run, all projects
python3 tools/cleanup-published.py --project <name>     # dry-run, one project
python3 tools/cleanup-published.py --execute            # perform cleanup
python3 tools/cleanup-published.py --project <name> --execute
python3 tools/cleanup-published.py --days 7
```

Eligibility requires all of: `meta.json` present; `status == "published"`;
`published_at` present and parseable; age ≥ `--days` full days; `final_master`
present, readable and non-zero; the project inside `videos/`; and no symlink
escape. Anything else is skipped with the reason reported. Successful cleanups
append to `logs/published-cleanup.jsonl`. The destination conflict rule: an
existing `~/Videos/Published/<name>.mp4` is reused when its SHA-256 is
identical, and cleanup stops (no deletion) when it differs.

### Marking a publication

Publication metadata is set by hand *after* the video is posted. Never mark a
project published automatically.

```bash
# 1. After manual publication, record it (shows a preview, then asks y/N):
python3 tools/mark-published.py <project-name>

# 2. Seven days later, review the cleanup dry-run:
python3 tools/cleanup-published.py

# 3. If the dry-run is correct, execute it:
python3 tools/cleanup-published.py --execute
```

`mark-published.py` writes `status`, `published_at` (local ISO-8601 with
offset) and `final_master` into `meta.json`, preserving all other fields. It
requires `renders/video-final.mp4` to exist, be readable and non-zero; it never
deletes files, never runs cleanup, never creates a master, and never overwrites
an existing timestamp (an already-published project is reported and left
unchanged). To record the real posting time after the fact, pass
`--published-at "2026-09-15T18:30:00+03:00"`. `--list` shows every project's
status read-only.
