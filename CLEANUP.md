# CLEANUP.md — safe retention of reproducible production artifacts

```
python3 studio/cli.py cleanup --dry-run
python3 studio/cli.py cleanup --older-than 3d
python3 studio/cli.py cleanup --dry-run --older-than 3d
python3 studio/cli.py cleanup --dry-run --older-than 3d --json
```

Producing a video leaves many **regenerable** artifacts — stills, contact
sheets, motion boundary strips, critic packs, a stale trace cache, scratch —
that can be recomputed from the source composition. `studio/cli.py cleanup`
removes only those. **Safety is the primary requirement**, so cleanup is an
allowlist: a file is deleted only if it matches an explicit cleanable category
*and* passes every guard. Everything else is kept.

Default retention is **3 days** (`--older-than` accepts `3d`, `12h`, `90m`,
`45s`, or bare seconds).

## What is NEVER deleted

**Permanent** (sources, configuration, state, output) and **unknown** (anything
not explicitly classified) are always preserved:

- source composition (`index.html`), `hyperframes.json`, `package.json`,
  `meta.json`, `spec.json`;
- brief / spec / source documents (`BRIEF.md`, `DESIGN.md`, `script.md`,
  `storyboard.md`, `sources.md`, `visual_inspiration.md` and any `*.md`);
- source assets (`assets/`, including fonts), shared code (`lib/`), rebuild
  scripts (`tools/`);
- the final render **`renders/video.mp4`** — never deleted, ever;
- the current production state/report: `production/state.json`,
  `production/report.md`, `production/validation.json`;
- the repository root, `videos/`, and every individual project root;
- **anything that is not explicitly classified** (UNKNOWN = KEEP).

## Cleanable categories

Only inside `videos/<project>/`, and only for a project whose
`production/state.json` is present and readable:

| Category | Path | Rule |
|---|---|---|
| old production stills / contact sheets / motion strips | `production/stills/<hash12>/` | hash ≠ current |
| stale critic packs | `production/critics/<hash12>/` | hash ≠ current |
| stale trace cache | `production/trace.json` | only when its recorded composition hash ≠ the current composition |
| temporary production scratch | `production/qa/`, `production/tmp/` | any age past retention |
| regenerable check snapshots | `snapshots/` | any age past retention |
| derived platform exports | `renders/exports/` | only when `renders/video.mp4` exists |

### Always preserve the current production hash

Artifacts keyed to the **current production hash** (read from
`production/state.json`) are preserved **regardless of age**. Only artifacts
from *older* production hashes are eligible.

### Fail safe

If `production/state.json` is missing, malformed, or records no hash, **no
artifact in that project is proposed for deletion**. Because older projects
predate the gated pipeline and have no production state, they are fully
protected.

## Safety guarantees

- **Allowlist, not denylist.** Unknown paths are never deleted.
- **No symlink escape.** A candidate that is a symlink, or whose real path
  leaves the repository, is refused; symlinked directories are never walked.
- **Protected roots.** The repo root, `videos/`, and each project root are never
  deletable. A candidate must resolve strictly inside its project *and* inside
  `videos/` *and* inside the repo.
- **No recursive delete of an unknown directory.** Only whitelisted category
  paths are removed with `rmtree`.
- **Dry-run is read-only.** `plan()` performs zero filesystem mutations;
  `apply_report()` is the only function that deletes, and it re-validates every
  path immediately before removal.
- **Every deletion is logged** to `logs/cleanup.jsonl` (append-only).

## Dry-run output

`--dry-run` prints, for every considered candidate: path, category/reason, age,
size, whether it would be **deleted or preserved** (and why), the per-category
totals, and the total reclaimable space. It makes no changes. `--json` emits the
same plan as a machine-readable object.

## Retention log

Real deletions append one JSON line per artifact to `logs/cleanup.jsonl`
(`project`, `rel`, `category`, `bytes`, `at`).

## Tests

`python3 studio/tests/test_cleanup.py` — 17 tests over temporary fixtures only
(the real `videos/` tree is never touched): dry-run purity, retention age,
old-vs-current hash handling, final render/source/unknown protection, symlink
containment, protected roots, malformed/missing state, idempotency, and byte
accounting.

## Not yet configured

No `launchd` job is installed. This document and the command define the policy;
scheduling is a separate, explicit step.
