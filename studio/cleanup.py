"""Safe retention + cleanup for reproducible Motion Studio production artifacts.

Video production leaves many *regenerable* artifacts (stills, contact sheets,
motion boundary strips, critic packs, a stale trace cache, scratch) that can be
recomputed from the source composition.  This module removes only those, and
only when it is provably safe to do so.

Safety model (read this before changing it):

* **Allowlist, not denylist.** A path is deleted only if it matches an explicit
  cleanable *category* and pattern.  Everything else is KEEP.  An unknown file
  is never disposable.
* **The current production hash is always preserved**, regardless of age.  Only
  artifacts keyed to *older* production hashes may be cleaned.
* **Fails safe.**  If a project's ``production/state.json`` is missing or
  malformed, no artifact in that project is proposed for deletion.
* **Protected roots** (repository root, ``videos/``, each project root) and
  ``renders/video.mp4`` can never be deleted.
* **No symlink escape.**  A candidate that is a symlink, or whose real path
  leaves the repository, is refused.  Symlinked directories are never walked.
* **No recursive delete of an unknown directory.**  Only whitelisted category
  directories are removed with ``rmtree``.
* **Dry-run is read-only.**  ``plan()`` performs zero filesystem mutations;
  ``apply_report()`` is the only function that deletes.

Cleanable categories
--------------------
1. ``<project>/production/stills/<hash12>/``  old stills + contact sheets + strips
2. ``<project>/production/critics/<hash12>/`` stale critic packs
3. ``<project>/production/trace.json``        stale trace cache only
4. ``<project>/production/{qa,tmp}/``         temporary production scratch
5. ``<project>/snapshots/``                   regenerable check snapshots
6. ``<project>/renders/exports/``             derived exports (only if the
                                              final ``renders/video.mp4`` exists)

Everything else is permanent or unknown and is kept.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import sys
from typing import Dict, List, Optional, Tuple

# ------------------------------------------------------------------ constants

DEFAULT_RETENTION = "3d"
DEFAULT_RETENTION_S = 3 * 24 * 3600

# Mirror tools/cleanup-published.py logging convention.
LOG_REL = os.path.join("logs", "cleanup.jsonl")

CATEGORY_STILLS = "old production stills / contact sheets / motion strips"
CATEGORY_CRITICS = "stale critic packs"
CATEGORY_TRACE = "stale trace cache"
CATEGORY_SCRATCH = "temporary production scratch"
CATEGORY_SNAPSHOTS = "regenerable check snapshots"
CATEGORY_EXPORTS = "derived platform exports"

_DIR_CATEGORIES = {CATEGORY_STILLS, CATEGORY_CRITICS, CATEGORY_SCRATCH,
                   CATEGORY_SNAPSHOTS, CATEGORY_EXPORTS}

# Top-level entries of a project that are always permanent.  Any other
# unrecognised entry is reported as unclassified and kept.
_PERMANENT_TOP = {
    "index.html", "hyperframes.json", "package.json", "meta.json", "spec.json",
    "lib", "assets", "tools", "renders", "production",
    "BRIEF.md", "DESIGN.md", "script.md", "storyboard.md", "sources.md",
    "visual_inspiration.md",
}
_PERMANENT_PRODUCTION = {"state.json", "report.md", "validation.json"}

_HASH_RE = re.compile(r"^[0-9a-f]{12}$")
_DUR_RE = re.compile(r"^(\d+)\s*([smhd])?$", re.IGNORECASE)

EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2


# ------------------------------------------------------------------ helpers

def parse_duration(text: str) -> int:
    """``3d`` / ``12h`` / ``90m`` / ``45s`` / bare seconds -> seconds."""
    m = _DUR_RE.match((text or "").strip())
    if not m:
        raise ValueError("invalid duration %r (use e.g. 3d, 12h, 90m, 45s)" % text)
    value = int(m.group(1))
    unit = (m.group(2) or "s").lower()
    return value * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def human_bytes(n: int) -> str:
    if n < 1024:
        return "%d B" % n
    value = float(n)
    units = ["KB", "MB", "GB", "TB"]
    idx = -1
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    return ("%.2f" % value).rstrip("0").rstrip(".") + " " + units[idx]


def human_age(seconds: float) -> str:
    s = max(0, int(seconds))
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    if d:
        return "%dd %dh" % (d, h)
    if h:
        return "%dh %dm" % (h, m)
    if m:
        return "%dm" % m
    return "%ds" % s


def _is_under(child: str, parent: str) -> bool:
    """True when ``child`` is ``parent`` or strictly inside it (real paths)."""
    try:
        child_r = os.path.realpath(child)
        parent_r = os.path.realpath(parent)
    except OSError:
        return False
    if child_r == parent_r:
        return True
    try:
        return os.path.commonpath([child_r, parent_r]) == parent_r
    except ValueError:
        return False


def _prune(dirs: List[str], root: str) -> None:
    dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]


def _tree_mtime(path: str) -> float:
    """Newest mtime in the tree (conservative: any recent file keeps it young)."""
    if os.path.islink(path):
        return 0.0
    try:
        newest = os.path.getmtime(path)
    except OSError:
        return 0.0
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path, followlinks=False):
            _prune(dirs, root)
            for name in files:
                p = os.path.join(root, name)
                if os.path.islink(p):
                    continue
                try:
                    newest = max(newest, os.path.getmtime(p))
                except OSError:
                    pass
    return newest


def _tree_size(path: str) -> int:
    """Total bytes of regular files (symlinks are never followed or counted)."""
    if os.path.islink(path):
        return 0
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        _prune(dirs, root)
        for name in files:
            p = os.path.join(root, name)
            if os.path.islink(p):
                continue
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
    return total


# ------------------------------------------------------------- current hash

def _current_hash(project: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """(state_ok, hash12, note) from ``production/state.json``.

    Missing, unreadable, non-object or hash-less state -> ``(False, None, note)``
    so the project fails safe.
    """
    path = os.path.join(project, "production", "state.json")
    if os.path.islink(path) or not os.path.isfile(path):
        return False, None, "production/state.json missing"
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        return False, None, "production/state.json malformed: %s" % str(exc)[:120]
    if not isinstance(doc, dict):
        return False, None, "production/state.json is not an object"
    found: List[Tuple[str, str]] = []
    for key in ("stages", "history"):
        container = doc.get(key)
        if isinstance(container, dict):
            entries = container.values()
        elif isinstance(container, list):
            entries = container
        else:
            continue
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get("hash"), str) and e["hash"]:
                found.append((str(e.get("at") or ""), e["hash"]))
    if not found:
        return False, None, "production/state.json records no production hash"
    found.sort()
    return True, found[-1][1][:12], None


def _trace_is_stale(project: str) -> bool:
    """True only when the cached trace's composition hash differs from the
    composition on disk.  Unreadable trace/current -> not stale (keep)."""
    path = os.path.join(project, "production", "trace.json")
    if not os.path.isfile(path) or os.path.islink(path):
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        recorded = doc.get("composition_hash")
    except (OSError, ValueError):
        return False
    if not isinstance(recorded, str) or not recorded:
        return False
    try:
        from studio import trace as T
        return T.composition_hash(project) != recorded
    except Exception:  # noqa: BLE001 - any failure keeps the cache
        return False


# ------------------------------------------------------------------ planning

def _candidate(project: str, rel_project: str, path: str, category: str, *,
               eligible: bool, preserve_reason: str, state_ok: bool,
               older_than_s: int, now: float) -> Dict:
    age = max(0.0, now - _tree_mtime(path))
    size = _tree_size(path)
    is_link = os.path.islink(path)
    if is_link:
        action, reason = "PRESERVE", "symlink (never followed)"
    elif not state_ok:
        action, reason = "PRESERVE", "production state unavailable — failing safe"
    elif not eligible:
        action, reason = "PRESERVE", preserve_reason or "not eligible"
    elif age <= older_than_s:
        action, reason = "PRESERVE", "newer than retention"
    else:
        action, reason = "DELETE", ""
    return {
        "path": path,
        "rel": os.path.relpath(path, project),
        "project": rel_project,
        "category": category,
        "age_s": int(age),
        "age": human_age(age),
        "size": size,
        "size_h": human_bytes(size),
        "action": action,
        "reason": reason,
    }


def plan(repo_root: str, videos_dir: Optional[str] = None, older_than_s: int = DEFAULT_RETENTION_S,
         *, now: Optional[float] = None) -> Dict:
    """Read-only cleanup plan.  Performs no filesystem mutations."""
    repo_root = os.path.abspath(repo_root)
    videos_dir = os.path.abspath(videos_dir or os.path.join(repo_root, "videos"))
    now = _dt.datetime.now().timestamp() if now is None else float(now)

    report: Dict = {
        "generated_at": _dt.datetime.fromtimestamp(now).isoformat(timespec="seconds"),
        "repo_root": repo_root,
        "videos_dir": videos_dir,
        "older_than_s": int(older_than_s),
        "projects": [],
        "candidates": [],
        "unclassified": [],
        "errors": [],
        "summary": {},
    }

    if not os.path.isdir(videos_dir):
        report["errors"].append("videos directory not found: %s" % videos_dir)
        _finalize(report)
        return report

    try:
        names = sorted(os.listdir(videos_dir))
    except OSError as exc:
        report["errors"].append("cannot list videos directory: %s" % exc)
        _finalize(report)
        return report

    for name in names:
        project = os.path.join(videos_dir, name)
        if os.path.islink(project) or not os.path.isdir(project):
            if os.path.islink(project):
                report["errors"].append("skipped symlinked project: videos/%s" % name)
            continue
        _plan_project(report, repo_root, videos_dir, project, older_than_s, now)

    _finalize(report)
    return report


def _plan_project(report: Dict, repo_root: str, videos_dir: str, project: str,
                  older_than_s: int, now: float) -> None:
    rel_project = os.path.relpath(project, repo_root)
    state_ok, cur12, note = _current_hash(project)
    report["projects"].append({
        "project": rel_project,
        "current_hash12": cur12,
        "state_ok": state_ok,
        "note": note,
    })

    def add(path: str, category: str, *, eligible: bool, preserve_reason: str = "") -> None:
        if not os.path.lexists(path):
            return
        report["candidates"].append(_candidate(
            project, rel_project, path, category, eligible=eligible,
            preserve_reason=preserve_reason, state_ok=state_ok,
            older_than_s=older_than_s, now=now))

    # ---- production/ --------------------------------------------------------
    prod = os.path.join(project, "production")
    if os.path.isdir(prod) and not os.path.islink(prod):
        for sub in ("stills", "critics"):
            container = os.path.join(prod, sub)
            if not os.path.isdir(container) or os.path.islink(container):
                continue
            category = CATEGORY_STILLS if sub == "stills" else CATEGORY_CRITICS
            try:
                children = sorted(os.listdir(container))
            except OSError:
                continue
            for pid in children:
                p = os.path.join(container, pid)
                if os.path.islink(p):
                    add(p, category, eligible=False, preserve_reason="symlink")
                    continue
                if not os.path.isdir(p) or not _HASH_RE.match(pid):
                    report["unclassified"].append({
                        "project": rel_project, "rel": os.path.join("production", sub, pid),
                        "reason": "production/%s entry is not a <hash12> directory" % sub})
                    continue
                is_current = state_ok and cur12 is not None and pid == cur12
                add(p, category, eligible=not is_current,
                    preserve_reason="current production hash")

        trace = os.path.join(prod, "trace.json")
        if os.path.lexists(trace):
            add(trace, CATEGORY_TRACE, eligible=state_ok and _trace_is_stale(project),
                preserve_reason="not stale (matches the current composition)")

        for scratch in ("qa", "tmp"):
            add(os.path.join(prod, scratch), CATEGORY_SCRATCH, eligible=True)

        for sub in sorted(os.listdir(prod)):
            if sub in ("stills", "critics", "trace.json", "qa", "tmp"):
                continue
            if sub in _PERMANENT_PRODUCTION:
                continue
            report["unclassified"].append({
                "project": rel_project, "rel": os.path.join("production", sub),
                "reason": "unknown production entry (kept)"})

    # ---- renders/ -----------------------------------------------------------
    renders = os.path.join(project, "renders")
    master = os.path.join(renders, "video.mp4")
    exports = os.path.join(renders, "exports")
    if os.path.isdir(exports) and not os.path.islink(exports):
        add(exports, CATEGORY_EXPORTS, eligible=os.path.isfile(master),
            preserve_reason="no final master to rebuild exports from")

    # ---- snapshots/ ---------------------------------------------------------
    add(os.path.join(project, "snapshots"), CATEGORY_SNAPSHOTS, eligible=True)

    # ---- everything else: protected or unclassified -------------------------
    try:
        tops = sorted(os.listdir(project))
    except OSError:
        return
    protected: List[str] = []
    for name in tops:
        if name in ("production", "renders", "snapshots"):
            continue
        if name in _PERMANENT_TOP or name.endswith(".md"):
            protected.append(name)
        else:
            report["unclassified"].append({
                "project": rel_project, "rel": name,
                "reason": "unknown top-level entry (kept)"})
    always = sorted(set(protected) | {
        "renders/", "index.html", "meta.json", "spec.json", "hyperframes.json",
        "package.json", "lib/", "assets/", "tools/", "*.md",
    } | {"production/" + n for n in _PERMANENT_PRODUCTION})
    report.setdefault("protected", []).append({
        "project": rel_project,
        "always_permanent": always,
    })


def _finalize(report: Dict) -> None:
    cands = report["candidates"]
    delete = [c for c in cands if c["action"] == "DELETE"]
    preserve = [c for c in cands if c["action"] != "DELETE"]
    reclaim = sum(c["size"] for c in delete)
    categories: Dict[str, int] = {}
    for c in delete:
        categories[c["category"]] = categories.get(c["category"], 0) + c["size"]
    report["summary"] = {
        "candidates": len(cands),
        "would_delete": len(delete),
        "would_preserve": len(preserve),
        "reclaimable_bytes": reclaim,
        "reclaimable": human_bytes(reclaim),
        "by_category": {k: {"bytes": v, "h": human_bytes(v)}
                        for k, v in sorted(categories.items(), key=lambda kv: -kv[1])},
        "projects": len(report["projects"]),
        "unclassified": len(report["unclassified"]),
    }


# ------------------------------------------------------------------- guards

def guard_delete(path: str, repo_root: str, videos_dir: str, project: str,
                 category: str) -> Tuple[bool, str]:
    """Last-line check before any deletion.  Returns ``(ok, reason)``."""
    if not path or os.path.islink(path):
        return False, "symlink or empty path"
    real = os.path.realpath(path)
    repo_r = os.path.realpath(repo_root)
    videos_r = os.path.realpath(videos_dir)
    proj_r = os.path.realpath(project)
    if real in (repo_r, videos_r, proj_r):
        return False, "protected root"
    if not (_is_under(real, proj_r) and real != proj_r):
        return False, "outside the project"
    if not (_is_under(real, videos_r) and real != videos_r):
        return False, "outside videos/"
    if not (_is_under(real, repo_r) and real != repo_r):
        return False, "outside the repository"
    if _is_under(os.path.realpath(proj_r), os.path.realpath(real)):
        return False, "would remove a parent of the project"

    rel = os.path.relpath(real, proj_r).split(os.sep)
    if category in (CATEGORY_STILLS, CATEGORY_CRITICS):
        want = "stills" if category == CATEGORY_STILLS else "critics"
        if len(rel) != 3 or rel[0] != "production" or rel[1] != want or not _HASH_RE.match(rel[2]):
            return False, "unexpected %s pattern" % want
    elif category == CATEGORY_TRACE:
        if rel != ["production", "trace.json"]:
            return False, "unexpected trace path"
    elif category == CATEGORY_SCRATCH:
        if rel not in (["production", "qa"], ["production", "tmp"]):
            return False, "unexpected scratch path"
    elif category == CATEGORY_SNAPSHOTS:
        if rel != ["snapshots"]:
            return False, "unexpected snapshots path"
    elif category == CATEGORY_EXPORTS:
        if len(rel) < 2 or rel[0] != "renders" or rel[1] != "exports":
            return False, "unexpected exports path"
    else:
        return False, "unknown category"
    return True, ""


def apply_report(report: Dict, repo_root: str, log_path: Optional[str] = None) -> Dict:
    """Delete the plan's DELETE candidates.  Returns the mutated report."""
    videos_dir = report["videos_dir"]
    deleted: List[Dict] = []
    errors: List[str] = list(report.get("errors", []))
    for cand in report["candidates"]:
        if cand["action"] != "DELETE":
            continue
        path = cand["path"]
        project = os.path.join(repo_root, cand["project"])
        ok, why = guard_delete(path, repo_root, videos_dir, project, cand["category"])
        if not ok:
            cand["action"] = "PRESERVE"
            cand["reason"] = "blocked: %s" % why
            errors.append("refused %s: %s" % (cand["rel"], why))
            continue
        size = _tree_size(path)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        except OSError as exc:
            errors.append("failed to remove %s: %s" % (cand["rel"], exc))
            continue
        rec = {"project": cand["project"], "rel": cand["rel"], "category": cand["category"],
               "bytes": size, "at": _dt.datetime.now().isoformat(timespec="seconds")}
        deleted.append(rec)
        if log_path:
            _log(log_path, rec)
    report["deleted"] = deleted
    report["errors"] = errors
    reclaimed = sum(d["bytes"] for d in deleted)
    report["summary"]["deleted"] = len(deleted)
    report["summary"]["deleted_bytes"] = reclaimed
    report["summary"]["deleted_h"] = human_bytes(reclaimed)
    return report


def _log(log_path: str, record: Dict) -> None:
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ------------------------------------------------------------------ render

def render_human(report: Dict, dry_run: bool) -> str:
    out: List[str] = []
    out.append("Motion Studio cleanup — %s" % ("DRY RUN (no changes)" if dry_run else "APPLIED"))
    out.append("Repo:       %s" % report["repo_root"])
    out.append("Videos:     %s" % report["videos_dir"])
    out.append("Retention:  older than %s (%ds)   Now: %s"
               % (human_age(report["older_than_s"]), report["older_than_s"], report["generated_at"]))
    out.append("")

    by_project: Dict[str, List[Dict]] = {}
    for c in report["candidates"]:
        by_project.setdefault(c["project"], []).append(c)
    for proj in report["projects"]:
        name = proj["project"]
        head = "PROJECT %s" % name
        if proj["state_ok"]:
            head += "  (current hash %s)" % proj["current_hash12"]
        else:
            head += "  [%s]" % (proj["note"] or "state unavailable")
        out.append(head)
        rows = by_project.get(name, [])
        if not rows:
            out.append("  (no cleanable artifacts)")
        for c in sorted(rows, key=lambda x: (x["category"], x["path"])):
            flag = "DELETE  " if c["action"] == "DELETE" else "PRESERVE"
            why = ("  (%s)" % c["reason"]) if c["reason"] else ""
            out.append("  %s %-46s %-9s %-10s %s%s"
                       % (flag, os.path.join(name, c["rel"]), c["age"], c["size_h"], c["category"], why))
        for p in [x for x in report.get("protected", []) if x["project"] == name]:
            out.append("  PROTECTED (always permanent): %s" % ", ".join(p["always_permanent"]))
        for u in [x for x in report["unclassified"] if x["project"] == name]:
            out.append("  UNCLASSIFIED (kept, not deletable): %s — %s" % (u["rel"], u["reason"]))
        out.append("")

    s = report["summary"]
    out.append("SUMMARY")
    out.append("  projects scanned ......  %d" % s["projects"])
    out.append("  candidates considered ..  %d" % s["candidates"])
    out.append("  would delete ..........  %d" % s["would_delete"])
    out.append("  would preserve ........  %d" % s["would_preserve"])
    out.append("  reclaimable ...........  %s (%d bytes)" % (s["reclaimable"], s["reclaimable_bytes"]))
    if s.get("by_category"):
        out.append("  by category:")
        for cat, v in s["by_category"].items():
            out.append("    %-46s %s" % (cat, v["h"]))
    if not dry_run:
        out.append("  deleted ...............  %d (%s)" % (s.get("deleted", 0), s.get("deleted_h", "0 B")))
    if report.get("errors"):
        out.append("  notes/errors:")
        for e in report["errors"]:
            out.append("    - %s" % e)
    if s["unclassified"]:
        out.append("  unclassified entries ..  %d (all kept)" % s["unclassified"])
    return "\n".join(out)


# ------------------------------------------------------------------ CLI

def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cmd_cleanup(args) -> int:
    repo = _root()
    videos = args.videos_dir or os.path.join(repo, "videos")
    try:
        older = parse_duration(args.older_than)
    except ValueError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    dry_run = bool(args.dry_run)
    report = plan(repo, videos, older)
    report["dry_run"] = dry_run
    if not dry_run:
        apply_report(report, repo, log_path=os.path.join(repo, LOG_REL))
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_human(report, dry_run))
    return EXIT_OK


def register_subcommands(sub) -> None:
    p = sub.add_parser("cleanup", help="safe retention/cleanup of reproducible production artifacts")
    p.add_argument("--dry-run", action="store_true",
                   help="report candidates only; make no filesystem changes")
    p.add_argument("--older-than", default=DEFAULT_RETENTION, metavar="DUR",
                   help="retention window (e.g. 3d, 12h, 90m); default %s" % DEFAULT_RETENTION)
    p.add_argument("--json", action="store_true", help="machine-readable plan/report")
    p.add_argument("--videos-dir", default=None,
                   help="videos directory to scan (default <repo>/videos)")
    p.set_defaults(func=cmd_cleanup)
