# RUN_METRICS.md — per-run usage, cost, and quality record

One JSON file per production run, written at the end of the run (see the run
closure in `VIDEO_WORKFLOW.md`). Schema example:
`templates/tech-news-ar/run-metrics.example.json`.

Location and naming: `runs/<YYYY-MM-DD>-<slug>.json`
(e.g. `runs/2026-09-12-claude-computer-use-ar.json`). Details: `runs/README.md`.

A separate, opt-in Phase 1 recording layer writes structured run manifests under
`runs/manifests/` and project registrations under `runs/projects/` (see the
"Run manifest recording" section in `VIDEO_WORKFLOW.md`). Those records are
additive and do not replace this per-run summary. Existing
`runs/<YYYY-MM-DD>-<slug>.json` files stay valid; they may be linked as
`legacy_external` historical references without being modified.

## Fields

| Key | Type | Required | Meaning |
|-----|------|----------|---------|
| `run_id` | string | yes | Stable id; match the filename stem. |
| `topic` | string | yes | One line: what the video is about. |
| `primary_company` | string \| null | yes | Company the story is mainly about; `null` if none. |
| `brand_profile` | string | yes | Selected profile id (`brands/<id>.json`), or `generic`. |
| `model_provider` | string \| null | yes | Provider of the producing model (e.g. an API/agent provider); `null` if unknown. |
| `model_name` | string \| null | yes | Exact model id/name; `null` if unknown. |
| `started_at` | string (ISO 8601 offset) | yes | Run start, e.g. `2026-09-12T10:30:00+03:00`. |
| `ended_at` | string (ISO 8601 offset) | yes | Run end. |
| `total_production_seconds` | number | yes | Wall-clock `ended_at − started_at`, in seconds. Never `null` for a new run. |
| `input_tokens` | number \| null | yes | Measured input tokens; `null` if not measurable. |
| `output_tokens` | number \| null | yes | Measured output tokens; `null` if not measurable. |
| `cached_tokens` | number \| null | yes | Cached/prompt-cache read tokens if the provider reports them; else `null`. |
| `usage_source` | string \| null | yes | Where the token numbers came from (provider response `usage`, console export, …); `null` if none. |
| `model_api_cost` | number \| null | yes | Producing-model cost in `currency`; `null` if unknown. |
| `external_api_cost` | number \| null | yes | Sum of other paid API/cloud costs; `null` if unknown. |
| `total_production_cost` | number \| null | yes | `model_api_cost + external_api_cost`; `null` unless both are known. |
| `currency` | string | yes | ISO 4217 code, e.g. `USD`. |
| `cost_status` | string | yes | `known`, `partial`, or `unknown`. |
| `pricing_source` | string \| null | yes | Reference to the explicit price data used; `null` if none. |
| `estimated_cost_usd` | number \| null | no | Cost-gate estimate from verified pricing, before generation; `null` if not gated. |
| `approved_cost_limit_usd` | number \| null | no | Budget limit the human approved at the cost gate; `null` if none. |
| `provider_billed_cost_usd` | number \| null | no | Actual provider-billed amount, when the provider reports it. |
| `session_reported_cost_usd` | number \| null | no | Cost reported by the agent session/console. |
| `cost_variance_usd` | number \| null | no | `provider_billed_cost_usd − estimated_cost_usd`; `null` unless both are known. |
| `pricing_checked_at` | string \| null | no | When the pricing catalog used by the gate was last checked. |
| `render_duration_seconds` | number \| null | yes | Render wall time from `hyperframes render` output. |
| `render_retries` | number | yes | Count of re-renders after a failure. |
| `manual_interventions` | number \| null | yes | Count of human corrections/re-asks during the run. |
| `asset_quality_score` | number \| null | yes | 0–10; the Asset quality category scaled from `QUALITY_SCORE.md`. |
| `rtl_text_issues_found` | array of strings | yes | RTL/text/tashkeel issues found (empty array if none). |
| `audio_assets_count` | number \| null | yes | Total audio assets used (SFX + music + ambient); `0` if none. |
| `sfx_count` | number \| null | yes | Number of SFX cues used. |
| `music_used` | boolean \| null | yes | Whether a music bed was used (silent by default, `AUDIO_DESIGN.md` §0). |
| `ambient_used` | boolean \| null | yes | Whether an ambient bed was used. |
| `audio_source_count` | number \| null | yes | Number of external audio sources documented in `sources.md`. |
| `audio_mix_retries` | number \| null | yes | Audio re-mix attempts after a defect (clipping, cutoffs, wrong level). |
| `audio_validation_passed` | boolean \| null | yes | Audio quality checks passed; `true`/`null` when no audio was planned. |
| `quality_score` | number | yes | 0–100 total from `QUALITY_SCORE.md`, with the visual score from the human review. Never `null` for a new run. |
| `quality_breakdown` | object | yes | The seven category scores (see below). |
| `hard_fail_triggered` | boolean | yes | `true` if any hard-fail condition was hit. |
| `ready_to_publish` | boolean \| null | yes | `true` only for "Ready to publish"; `false` otherwise; `null` only if scoring is incomplete. |
| `notes` | string | yes | Free text: blockers, assumptions, cost caveats. |
| `format` | string \| null | no | `portrait` or `landscape`. |
| `content_type` | string \| null | no | e.g. `tech_news`, `business_development`; groups comparable runs. |
| `layout_signature` | array of strings \| null | no | Ordered scene grammar ids from `python3 design/cli.py signature`; `legacy_card` for unannotated scenes. |
| `novelty_advisories` | array of strings | no | Messages from `design/cli.py novelty` (advisory, never blocking). |
| `visual_quality_source` | string \| null | no | `multimodal_review` or `human_review`; `null` when not independently reviewed. Never self-scored. |
| `visual_quality_status` | string | no | `independently_reviewed` or `not_independently_reviewed`. |
| `diagnostics` | object \| null | no | Advisory pixel diagnostics from `review/cli.py review`: `near_still_seconds`, `longest_hold_s`, `empty_frames` (spans), `boundary_dips` (times). Context only; never a score or gate. |
| `critic_run` | string \| null | no | `diagnostic`, `diagnostic+pairwise`, or `null` when the optional visual critic was skipped. |
| `critic_trigger` | string \| null | no | Why it ran (see `AI_REVIEW.md` §Optional visual critic) or why it was skipped. |
| `critic_tokens` / `critic_wall_seconds` | integer \| null | no | Measured from the critic run (`claude -p --output-format json` usage); `null` if not measured. |
| `critic_findings` / `critic_findings_accepted` / `critic_findings_wrong` | integer \| null | no | Findings returned, accepted by the human, and judged wrong by the human. |
| `pairwise_result` | string \| null | no | Blind pairwise outcome for a significant revision, e.g. `revision preferred 9/10, 1 tie`; mapping revealed only after the verdict. |

Older run records without these fields stay valid; novelty checks derive a
signature from `videos/<slug>/index.html` when `layout_signature` is absent.

`quality_breakdown` keys (maxima): `accuracy_sourcing` (30),
`hook_editorial_clarity` (20), `visual_quality` (15), `asset_quality` (10),
`brand_identity_fit` (10), `arabic_rtl_quality` (10), `technical_validation` (5).

## Cost Gate (pre-generation) — two separate human gates

Cost approval happens **before** paid generation; creative/technical review
approval happens **after** the preview render. They are different gates.

- The cost gate lives in `costgate/` and is documented in `COST_GATE.md`. It
  never contacts a provider and never invents pricing: prices come only from an
  explicit catalog with a recorded source, and anything unverified is `UNKNOWN`.
- Record the gate's numbers here: `estimated_cost_usd`,
  `approved_cost_limit_usd`, `provider_billed_cost_usd`,
  `session_reported_cost_usd`, `cost_variance_usd`, `pricing_checked_at`.
- Keep the existing distinctions: estimated vs provider-billed vs
  session-reported, and never write an unmeasured number.

## Cost and usage rules — never invent

- **Do not invent token usage or cost.** If a number is not measurable, write
  `null` — never an estimate, average, or remembered figure.
- Record **usage** whenever the provider exposes it, even when price is
  unknown. Token counts come from the producing model/agent provider's `usage`
  metadata, a session/console export, or another measured source; put that
  source in `usage_source`.
- If exact provider cost is unavailable, set the cost field(s) to `null` and
  `cost_status` to `unknown`. Do not guess.
- If price data is **supplied externally**, calculate from that explicit price
  only, and record `pricing_source`. Formula (per-token pricing, per 1M tokens):

  ```text
  model_api_cost = (input_tokens  / 1_000_000) * input_price
                 + (output_tokens / 1_000_000) * output_price
                 - cached_discount   # only if the supplied price defines one

  total_production_cost = model_api_cost + external_api_cost
  ```

  Apply only the exact prices and rules you were given. If the price table does
  not define cached pricing, leave the cached adjustment out and note it.
- `cost_status`:
  - `known` — every cost component is known; `total_production_cost` is set.
  - `partial` — some components known, some not; set `total_production_cost`
    to `null` and explain in `notes`.
  - `unknown` — no reliable cost data; all cost fields `null`.
- `external_api_cost` covers other paid services (search, cloud render, TTS,
  storage, etc.) and comes from their own console/invoice; otherwise `null`.
- Currency is `USD` unless the supplied prices state another currency.

## How to measure actual cost in future runs

1. Capture usage during the run: read the provider's `usage` object
   (`input_tokens`, `output_tokens`, cached tokens) or export it from the
   session/console; write the numbers and `usage_source`.
2. Capture non-model spend from each external provider's console/invoice.
3. Obtain an explicit price table (price per 1M input/output tokens and any
   cache rules) from the user or provider price page. Put its reference in
   `pricing_source`.
4. Compute `model_api_cost` with the formula above using **only** those prices.
5. Sum to `total_production_cost`; set `cost_status` accordingly.
6. If any step is unavailable, record usage where possible and leave cost
   `null` with `cost_status: "unknown"`.

## Audio fields

Runs are silent by default (`AUDIO_DESIGN.md` §0). When a run uses no audio, set `audio_assets_count` and
`sfx_count` to `0`, `music_used`/`ambient_used` to `false`, and
`audio_validation_passed` to `true`. When a run uses audio, record the counts
and whether the mix passed the checks in `AUDIO_DESIGN.md` §10.

**Do not invent audio counts.** If a value was not measured, use `null`. Audio
mixing is done in HyperFrames and/or FFmpeg (see `AUDIO_DESIGN.md` §7–§8); a
re-mix forced by clipping, an abrupt cut, or a wrong level counts as an
`audio_mix_retries` attempt.

## Timing
Use local time with an explicit UTC offset for `started_at` / `ended_at`.
`total_production_seconds = (ended_at − started_at)` in seconds.

## Required for new runs
Every run closed from 2026-10-04 on records measured values, never `null`, for
`started_at`, `ended_at`, `total_production_seconds`, `quality_score`,
`render_retries` and `manual_interventions` (both integers, not prose; put the
explanation in `notes`).

- Note `started_at` when the brief is accepted, before any other work, and
  `ended_at` when the human review of the render ends.
- `quality_score` needs the visual score, which the human gives at that review
  (`visual_quality_source: human_review`). Ask for it; a run without it is not
  closed.
- Check: `python3 tools/check-run-record.py runs/<run-id>.json` → `ok`.

Older records are unchanged.

## Validation
The file must parse as JSON and contain every `required` key above. Quick check:

```bash
python3 -c "import json,sys; json.load(open(sys.argv[1])); print('ok')" runs/<run-id>.json
```
