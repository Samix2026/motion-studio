# runs/ — per-production-run records

One JSON file per production run, written at the end of the run. This is the
audit trail that ties each video to its measured usage, cost, and quality
decision.

## Layout

```
runs/
  README.md
  <YYYY-MM-DD>-<slug>.json            # legacy per-run metric summary (one per run)
  projects/<project_id>.json          # opt-in Phase 1 project registration
  manifests/<project_id>/<run_id>.json  # opt-in Phase 1 run manifest
  .locks/                             # transient single-writer locks (never content)
```

- Filename stem equals the record's `run_id`.
- Use the project slug from `videos/<slug>/` where possible.

## Phase 1 recording layer (opt-in)

The `projects/` and `manifests/` directories belong to the additive Phase 1
recording layer described in `../WORKFLOW_REFERENCE.md` ("Run manifest recording").
They are created only when the corresponding CLI command is run; nothing here is
generated automatically and the legacy `runs/*.json` summaries are never
modified. These records distinguish reported execution outcome from validation
result and never imply generation, approval, or publication readiness. Each run
binds an immutable workspace-relative `revision_dir` and resolves project-rooted
artifacts against it. A run may temporarily list an unregistered output
(deferred registration); `run-status` surfaces `structural_validity`,
`reference_validity`, and `unresolved_reference_ids` rather than hiding it.

`.locks/` holds transient single-writer lock files with collision-free hashed
names. Locks are never stolen and no crash recovery is automatic; a stale lock
may be deleted by hand only after confirming the writer process is no longer
active. Lock files are not records and carry no run content.

## Review evidence freshness (Phase 2, Unit A)

Saved review reports and proposals carry a versioned, content-based
**review-input descriptor** and **review fingerprint** (render, composition,
selected CSS, timing/caption inputs with validity recorded separately, declared
dependencies, selected snapshots, the **effective** rules actually used,
typography, implementation identity, and local tool identity). The fingerprint
means the exact declared/current semantic review context: same-size replacement
invalidates it, while equivalent rule ordering, unordered inventories, inactive
configuration, and extra unselected MP4 files do not. Freshness is reconstructed
from the saved selection itself (not legacy discovery); older records without a
reconstructable descriptor stay readable but are `unverified` and are never
rewritten or assigned fabricated hashes. Caption-sync completion is only credited
when the saved evidence is current, the caption-sync measurement actually
completed (`complete`, not `unavailable`/`partial`), and no finding was produced.
Runtime/JS dependency coverage may be partial/unknown (`partial_local_only`,
`runtime_dynamic: unsupported`). Read paths (including `studio status`, review
`status`/`report`, and narration planning) never initialize review state or write
reports. See `../WORKFLOW_REFERENCE.md` ("Review input integrity").

## Managed timing execution (Phase 2, Unit B — Increment 1)

An opt-in, local-only executor for the offline `timing` stage writes **Phase 1
receipts** into the run manifest: one terminal attempt (`succeeded`, or `failed`
with an error on execution failure) plus the registered output artifacts (kind
`timing`, optional `caption`) with SHA-256 and `producer_attempt_id`. It uses an
execution-scoped run-level lock with the same `.locks/` semantics as the
recorder, refuses to overwrite an existing output/artifact/attempt, performs no
automatic retry, and never calls a provider, TTS, browser, subprocess, or
network. Read paths (`run-status`, `manifest-validate`, `studio status`, review
status/report, narration plan) are unchanged. See `../VIDEO_WORKFLOW.md`
("Managed timing execution").

## Create a record

```bash
cp ../templates/tech-news-ar/run-metrics.example.json \
   runs/$(date +%F)-<slug>.json
```

Then fill it during and after the run. The schema and every field are defined in
`../RUN_METRICS.md`; the score comes from `../QUALITY_SCORE.md`.

## Rules

- **Never invent token usage or cost.** If a value is not measurable, use
  `null` and set `cost_status` accordingly (`unknown` / `partial`).
- Record usage whenever the provider exposes it, even if price is unknown.
- Compute cost only from explicit, externally supplied prices; record the
  reference in `pricing_source`.
- One file per run; do not overwrite a published run's record. If a run is
  re-done, create a new dated record (optionally add a suffix).
- **No secrets or private data**: no API keys, credentials, customer data, or
  full prompts containing private material. Reference them, do not paste them.

## Validate

```bash
python3 -c "import json,sys; json.load(open(sys.argv[1])); print('ok')" runs/<run-id>.json
```

Confirm it contains every required key listed in `../RUN_METRICS.md`.

## Relationship to the workflow

The run closure in `../VIDEO_WORKFLOW.md` ends with:

1. validation (lint / check / ffprobe)
2. quality score (`QUALITY_SCORE.md`)
3. this cost/usage record
4. publish decision

`ready_to_publish` must be `true` only for a "Ready to publish" score with no
hard fail.
