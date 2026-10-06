#!/usr/bin/env python3
"""cleanup-published.py — retention + cleanup for published video projects.

Policy (see VIDEO_WORKFLOW.md → "Published Project Retention Policy"):
  - Never archive projects.
  - A published project keeps its full directory for --days (default 7) after
    `published_at`.
  - After that, only the final master (meta.json → "final_master") is retained:
    it is copied to ~/Videos/Published/<project-name>.mp4 and the project
    directory is deleted.
  - Unpublished projects are never touched.
  - A project is never deleted without a SHA-256-verified final master.
  - Dry-run by default; deletion happens only with --execute.

Usage:
  python3 tools/cleanup-published.py                     # dry-run (all projects)
  python3 tools/cleanup-published.py --project <name>    # dry-run (one project)
  python3 tools/cleanup-published.py --execute           # perform cleanup
  python3 tools/cleanup-published.py --project <name> --execute
  python3 tools/cleanup-published.py --days 7

No network, no paid calls. The only writes are ~/Videos/Published/<name>.mp4
and logs/published-cleanup.jsonl (append-only, on successful cleanup).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
VIDEOS_DIR = WORKSPACE_ROOT / "videos"
PUBLISHED_DIR = Path.home() / "Videos" / "Published"
LOG_PATH = WORKSPACE_ROOT / "logs" / "published-cleanup.jsonl"
DEFAULT_DAYS = 7
_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_USAGE = 2


# --------------------------------------------------------------------------- helpers
def human_bytes(n: int) -> str:
    """1024-based, trimmed to <=2 decimals (e.g. 6271943 -> '5.98 MB')."""
    if n < 1024:
        return "%d B" % n
    value = float(n)
    units = ["KB", "MB", "GB", "TB"]
    idx = -1
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    text = ("%.2f" % value).rstrip("0").rstrip(".")
    return "%s %s" % (text, units[idx])


def display_path(path: Path) -> str:
    """Render a path with '~' when it lives under the home directory."""
    try:
        home = Path.home().resolve()
        resolved = Path(path).resolve()
        if resolved == home:
            return "~"
        if resolved.is_relative_to(home):
            return "~/" + str(resolved.relative_to(home))
    except (OSError, ValueError):
        pass
    return str(path)


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def directory_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def parse_published_at(raw) -> Optional[datetime.datetime]:
    """Parse an ISO-8601 timestamp; naive values are treated as UTC."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _validate_project_name(name: str) -> Optional[str]:
    """Return an error string when a --project value is unsafe."""
    if not name or not name.strip():
        return "empty project name"
    if os.path.isabs(name):
        return "project name must not be an absolute path"
    if "/" in name or "\\" in name or ".." in Path(name).parts:
        return "project name must not contain path separators or traversal"
    return None


def is_safe_deletion_target(project_dir: Path, videos_dir: Path,
                            workspace_root: Path, home: Path) -> tuple[bool, str]:
    """Guard against deleting anything other than a project under videos/."""
    raw = Path(project_dir)
    if str(raw) in ("", "."):
        return False, "empty path"
    if any(part == ".." for part in raw.parts):
        return False, "path traversal in project path"
    try:
        resolved = raw.resolve()
        videos = Path(videos_dir).resolve()
        workspace = Path(workspace_root).resolve()
        home_resolved = Path(home).resolve()
    except (OSError, ValueError) as exc:
        return False, "unresolvable path: %s" % exc

    if resolved == Path("/"):
        return False, "refusing to delete filesystem root"
    if resolved == home_resolved:
        return False, "refusing to delete the home directory"
    if resolved == workspace:
        return False, "refusing to delete the workspace root"
    if resolved == videos:
        return False, "refusing to delete videos/ itself"
    if not resolved.is_relative_to(videos):
        return False, "path is not inside videos/"
    if resolved == videos.parent:
        return False, "refusing to delete the workspace root"
    return True, ""


# --------------------------------------------------------------------------- scanning
@dataclass
class ProjectStatus:
    name: str
    path: Path
    eligible: bool
    reason: str = ""
    published_at: Optional[datetime.datetime] = None
    age_days: int = 0
    project_size: int = 0
    master_path: Optional[Path] = None
    master_size: int = 0
    destination: Optional[Path] = None
    meta: dict = field(default_factory=dict)


def evaluate_project(project_dir: Path, videos_dir: Path, workspace_root: Path,
                     home: Path, days: int,
                     now: datetime.datetime) -> ProjectStatus:
    name = project_dir.name
    status = ProjectStatus(name=name, path=project_dir, eligible=False)

    # 9. symlink handling: a project symlink must resolve inside videos/
    if project_dir.is_symlink():
        try:
            target = project_dir.resolve()
        except OSError as exc:
            status.reason = "unresolvable symlink: %s" % exc
            return status
        if not target.is_relative_to(Path(videos_dir).resolve()):
            status.reason = "project symlink points outside videos/"
            return status

    # 1. meta.json exists and is valid
    meta_path = project_dir / "meta.json"
    if not meta_path.is_file():
        status.reason = "no meta.json"
        return status
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        status.reason = "meta.json is not valid JSON (%s)" % exc
        return status
    if not isinstance(meta, dict):
        status.reason = "meta.json is not a JSON object"
        return status
    status.meta = meta

    # 2. status == published
    meta_status = meta.get("status")
    if meta_status != "published":
        status.reason = "not published (status=%s)" % (
            json.dumps(meta_status) if meta_status is not None else "missing")
        return status

    # 3. published_at parses
    published_at = parse_published_at(meta.get("published_at"))
    if published_at is None:
        status.reason = "published_at missing or unparsable"
        return status
    status.published_at = published_at

    # 4. age >= days full days
    age = now - published_at
    full_days = int(age.total_seconds() // 86400)
    status.age_days = full_days
    if age.total_seconds() < 0:
        status.reason = "published_at is in the future"
        return status
    if full_days < days:
        status.reason = "published %d day(s) ago (< %d)" % (full_days, days)
        return status

    # 5. final_master exists, stays inside the project
    master_rel = meta.get("final_master")
    if not isinstance(master_rel, str) or not master_rel.strip():
        status.reason = "final_master missing from meta.json"
        return status
    master_path = (project_dir / master_rel)
    try:
        resolved_master = master_path.resolve()
        resolved_project = project_dir.resolve()
    except OSError as exc:
        status.reason = "unresolvable final_master: %s" % exc
        return status
    if not resolved_master.is_relative_to(resolved_project):
        status.reason = "final_master escapes the project directory"
        return status
    if not resolved_master.is_file():
        status.reason = "final_master not found: %s" % master_rel
        return status

    # 6. readable
    if not os.access(resolved_master, os.R_OK):
        status.reason = "final_master not readable"
        return status

    # 7. non-zero size
    size = resolved_master.stat().st_size
    if size <= 0:
        status.reason = "final_master is zero bytes"
        return status

    status.master_path = resolved_master
    status.master_size = size

    # 8. project path inside videos/ (and deletion guarded)
    safe, why = is_safe_deletion_target(project_dir, videos_dir, workspace_root, home)
    if not safe:
        status.reason = why
        return status

    status.project_size = directory_size(project_dir)
    status.eligible = True
    return status


def scan(videos_dir: Path, workspace_root: Path, home: Path, days: int,
         now: datetime.datetime, project: Optional[str] = None
         ) -> tuple[list[ProjectStatus], list[ProjectStatus]]:
    """Return (eligible, skipped)."""
    if project is not None:
        candidates = [videos_dir / project]
    else:
        candidates = sorted(
            (child for child in videos_dir.iterdir()),
            key=lambda p: p.name) if videos_dir.is_dir() else []

    eligible: list[ProjectStatus] = []
    skipped: list[ProjectStatus] = []
    for candidate in candidates:
        if not candidate.is_dir() and not candidate.is_symlink():
            if project is not None:
                skipped.append(ProjectStatus(
                    name=candidate.name, path=candidate,
                    reason="project directory not found"))
            continue
        status = evaluate_project(candidate, videos_dir, workspace_root, home,
                                  days, now)
        if status.eligible:
            eligible.append(status)
        else:
            skipped.append(status)
    return eligible, skipped


# --------------------------------------------------------------------------- report
def render_dry_run(eligible: list[ProjectStatus], skipped: list[ProjectStatus],
                   published_dir: Path, days: int) -> str:
    lines: list[str] = []
    lines.append("Published projects eligible for cleanup:")
    lines.append("")
    if not eligible:
        lines.append("(none)")
        lines.append("")
    total_project = 0
    total_master = 0
    for status in eligible:
        destination = published_dir / ("%s.mp4" % status.name)
        status.destination = destination
        total_project += status.project_size
        total_master += status.master_size
        lines.append(status.name)
        lines.append("Published: %s" % status.published_at.date().isoformat())
        lines.append("Age: %d days" % status.age_days)
        lines.append("Project size: %s" % human_bytes(status.project_size))
        lines.append("Final master: %s" % human_bytes(status.master_size))
        lines.append("Destination:")
        lines.append(display_path(destination))
        lines.append("")
        lines.append("Would keep:")
        lines.append(human_bytes(status.master_size))
        lines.append("")
        lines.append("Would delete:")
        lines.append(human_bytes(status.project_size - status.master_size))
        lines.append("")
        lines.append("Status:")
        lines.append("READY")
        lines.append("")

    lines.append("Eligible projects: %d" % len(eligible))
    lines.append("Total project size: %s" % human_bytes(total_project))
    lines.append("Final videos retained: %s" % human_bytes(total_master))
    lines.append("Potential space recovered: %s" % human_bytes(
        max(0, total_project - total_master)))
    lines.append("")
    lines.append("Retention window: %d days" % days)
    lines.append("")

    if skipped:
        lines.append("Skipped projects:")
        for status in skipped:
            lines.append("- %s: %s" % (status.name, status.reason))
        lines.append("")

    lines.append("No files changed.")
    lines.append("Use --execute to perform cleanup.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- execution
def _fsync_file(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def execute_one(status: ProjectStatus, videos_dir: Path, published_dir: Path,
                workspace_root: Path, home: Path, log_path: Path) -> dict:
    """Copy+verify the final master, then delete the project.

    Returns a result dict with 'ok', 'reused', 'sha256', 'dest', 'error'.
    Never deletes unless the copy is verified.
    """
    result = {"ok": False, "reused": False, "sha256": "", "dest": None,
              "error": "", "recovered": 0}
    source = status.master_path
    published_dir.mkdir(parents=True, exist_ok=True)
    destination = published_dir / ("%s.mp4" % status.name)
    result["dest"] = destination

    source_sha = sha256_file(source)

    if destination.exists():
        dest_sha = sha256_file(destination)
        if dest_sha == source_sha:
            result["reused"] = True
            result["sha256"] = source_sha
        else:
            result["error"] = (
                "destination conflict: %s exists with a different SHA-256 "
                "(existing %s, master %s)" % (
                    display_path(destination), dest_sha[:12], source_sha[:12]))
            return result
    else:
        shutil.copy2(source, destination)
        _fsync_file(destination)
        dest_sha = sha256_file(destination)
        if dest_sha != source_sha:
            result["error"] = (
                "hash mismatch after copy (source %s, destination %s)" % (
                    source_sha[:12], dest_sha[:12]))
            return result
        result["sha256"] = source_sha

    if destination.stat().st_size != source.stat().st_size:
        result["error"] = "destination size does not match source size"
        return result

    # re-verify source hash (paranoid) before deletion
    if sha256_file(source) != source_sha:
        result["error"] = "source changed during copy; refusing to delete"
        return result

    safe, why = is_safe_deletion_target(status.path, videos_dir,
                                        workspace_root, home)
    if not safe:
        result["error"] = "unsafe deletion target: %s" % why
        return result

    target = status.path.resolve()
    shutil.rmtree(target)
    result["ok"] = True
    result["recovered"] = max(0, status.project_size - status.master_size)

    record = {
        "timestamp": datetime.datetime.now(
            datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "project": status.name,
        "published_at": status.published_at.isoformat(),
        "project_path": str(status.path),
        "final_destination": str(destination),
        "sha256": result["sha256"],
        "original_project_size": status.project_size,
        "retained_file_size": status.master_size,
        "recovered_bytes": result["recovered"],
        "reused_existing_destination": result["reused"],
    }
    append_log(log_path, record)
    return result


def append_log(log_path: Path, record: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def render_cleaned(status: ProjectStatus, result: dict) -> str:
    lines = [
        "CLEANED:",
        "Project:",
        status.name,
        "Published:",
        status.published_at.date().isoformat(),
        "Age:",
        "%d days" % status.age_days,
        "Final master:",
        human_bytes(status.master_size),
        "Final destination:",
        display_path(result["dest"]),
        "Source SHA-256:",
        result["sha256"],
        "Destination SHA-256:",
        result["sha256"],
        "Project size before:",
        human_bytes(status.project_size),
        "Final retained size:",
        human_bytes(status.master_size),
        "Space recovered:",
        human_bytes(result["recovered"]),
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- run
def run(videos_dir: Path, published_dir: Path, log_path: Path, days: int,
        now: datetime.datetime, project: Optional[str] = None,
        execute: bool = False, home: Optional[Path] = None,
        workspace_root: Optional[Path] = None, out=None) -> int:
    out = out if out is not None else sys.stdout
    videos_dir = Path(videos_dir)
    published_dir = Path(published_dir)
    home = Path(home) if home is not None else Path.home()
    workspace_root = Path(workspace_root) if workspace_root is not None \
        else WORKSPACE_ROOT

    eligible, skipped = scan(videos_dir, workspace_root, home, days, now,
                             project=project)

    print(render_dry_run(eligible, skipped, published_dir, days), file=out)

    if not execute:
        return _EXIT_OK

    if not eligible:
        print("\nNothing to execute.", file=out)
        return _EXIT_OK

    print("\n" + "=" * 64, file=out)
    print("EXECUTING CLEANUP (verified copy, then delete)", file=out)
    print("=" * 64, file=out)

    exit_code = _EXIT_OK
    for status in eligible:
        result = execute_one(status, videos_dir, published_dir, workspace_root,
                             home, log_path)
        if result["ok"]:
            print("\n" + render_cleaned(status, result), file=out)
            if result["reused"]:
                print("Destination reused (identical SHA-256).", file=out)
        else:
            exit_code = _EXIT_ERROR
            print("\nERROR:", file=out)
            print("Project:", status.name, file=out)
            print("Reason:", result["error"], file=out)
            print("Project left untouched.", file=out)

    remaining = [s for s in eligible
                 if (published_dir / ("%s.mp4" % s.name)).exists()]
    print("\nExecuted projects: %d" % len(eligible), file=out)
    print("Log: %s" % display_path(log_path), file=out)
    return exit_code


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Retention cleanup for published video projects "
                    "(dry-run by default; delete only with --execute).")
    parser.add_argument("--project", help="limit to one project name")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help="retention window in days (default 7, min 1)")
    parser.add_argument("--execute", action="store_true",
                        help="perform the cleanup (copy + verify + delete)")
    parser.add_argument("--videos-dir", default=str(VIDEOS_DIR),
                        help=argparse.SUPPRESS)
    parser.add_argument("--published-dir", default=str(PUBLISHED_DIR),
                        help=argparse.SUPPRESS)
    parser.add_argument("--log-path", default=str(LOG_PATH),
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.days < 1:
        print("ERROR: --days must be >= 1 (got %d)" % args.days, file=sys.stderr)
        return _EXIT_USAGE

    if args.project is not None:
        error = _validate_project_name(args.project)
        if error:
            print("ERROR: invalid --project: %s" % error, file=sys.stderr)
            return _EXIT_USAGE

    videos_dir = Path(args.videos_dir)
    if args.project is not None:
        candidate = videos_dir / args.project
        if not candidate.exists() or not candidate.is_dir():
            print("ERROR: no such project: %s" % args.project, file=sys.stderr)
            return _EXIT_USAGE
        safe, why = is_safe_deletion_target(candidate, videos_dir,
                                            WORKSPACE_ROOT, Path.home())
        if not safe:
            print("ERROR: unsafe project path: %s" % why, file=sys.stderr)
            return _EXIT_USAGE

    return run(
        videos_dir=videos_dir,
        published_dir=Path(args.published_dir),
        log_path=Path(args.log_path),
        days=args.days,
        now=datetime.datetime.now(datetime.timezone.utc),
        project=args.project,
        execute=args.execute,
    )


if __name__ == "__main__":
    sys.exit(main())
