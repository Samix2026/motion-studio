#!/usr/bin/env python3
"""mark-published.py — record a manual publication so retention can run.

After a video is published by hand, this command writes the publication
metadata into the project's meta.json so that tools/cleanup-published.py can
retain the final master and delete the full project after 7 days.

It never deletes or moves anything, never runs cleanup, never creates a final
master, and never changes an existing published_at.

Usage:
  python3 tools/mark-published.py <project-name>
  python3 tools/mark-published.py <project-name> --published-at "2026-09-15T18:30:00+03:00"
  python3 tools/mark-published.py --list

See WORKFLOW_REFERENCE.md → "Published project retention policy".
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
VIDEOS_DIR = WORKSPACE_ROOT / "videos"
MASTER_REL = "renders/video-final.mp4"
RETENTION_DAYS = 7
_EXIT_OK = 0
_EXIT_ERROR = 1
_EXIT_USAGE = 2
_WIDTH_PROJECT = 38
_WIDTH_STATUS = 13
_WIDTH_DATE = 26


# --------------------------------------------------------------------------- helpers
def local_now() -> datetime.datetime:
    return datetime.datetime.now().astimezone().replace(microsecond=0)


def parse_timestamp(raw: str) -> Optional[datetime.datetime]:
    """Parse an ISO-8601 timestamp; naive input is treated as local time."""
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
        parsed = parsed.astimezone()
    return parsed.replace(microsecond=0)


def format_timestamp(value: datetime.datetime) -> str:
    return value.isoformat()


def is_safe_project_path(project_dir: Path, videos_dir: Path,
                         workspace_root: Path, home: Path) -> tuple[bool, str]:
    """The project must be a real directory inside videos/ (no escapes)."""
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
        return False, "refusing to use the filesystem root"
    if resolved == home_resolved:
        return False, "refusing to use the home directory"
    if resolved == workspace:
        return False, "refusing to use the workspace root"
    if resolved == videos:
        return False, "refusing to use videos/ itself"
    if not resolved.is_relative_to(videos):
        return False, "path is not inside videos/"
    return True, ""


def _validate_project_name(name: str) -> Optional[str]:
    if not name or not name.strip():
        return "empty project name"
    if os.path.isabs(name):
        return "project name must not be an absolute path"
    if "/" in name or "\\" in name or ".." in Path(name).parts:
        return "project name must not contain path separators or traversal"
    return None


def _load_meta(meta_path: Path) -> tuple[Optional[dict], str]:
    if not meta_path.is_file():
        return None, "meta.json not found"
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, "meta.json is not valid JSON (%s)" % exc
    if not isinstance(data, dict):
        return None, "meta.json is not a JSON object"
    return data, ""


def _write_meta_atomic(meta_path: Path, meta: dict) -> None:
    directory = meta_path.parent
    fd, tmp_name = tempfile.mkstemp(dir=str(directory), prefix=".meta-",
                                    suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(meta, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, meta_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def evaluate(project_dir: Path, videos_dir: Path, workspace_root: Path,
             home: Path) -> dict:
    """Return {ok, reason, meta, meta_path, master_path, master_size}."""
    result = {"ok": False, "reason": "", "meta": None, "meta_path": None,
              "master_path": None, "master_size": 0}

    if not project_dir.exists() or not project_dir.is_dir():
        result["reason"] = "project not found"
        return result

    if project_dir.is_symlink():
        target = project_dir.resolve()
        if not target.is_relative_to(Path(videos_dir).resolve()):
            result["reason"] = "project symlink points outside videos/"
            return result

    safe, why = is_safe_project_path(project_dir, videos_dir, workspace_root,
                                     home)
    if not safe:
        result["reason"] = why
        return result

    meta_path = project_dir / "meta.json"
    meta, why = _load_meta(meta_path)
    if meta is None:
        result["reason"] = why
        return result
    result["meta"] = meta
    result["meta_path"] = meta_path

    master_path = project_dir / MASTER_REL
    try:
        resolved_master = master_path.resolve()
        resolved_project = project_dir.resolve()
    except OSError as exc:
        result["reason"] = "unresolvable final master: %s" % exc
        return result
    if not resolved_master.is_relative_to(resolved_project):
        result["reason"] = "final master escapes the project directory"
        return result
    if not resolved_master.is_file():
        result["reason"] = "final master not found: %s" % MASTER_REL
        return result
    if not os.access(resolved_master, os.R_OK):
        result["reason"] = "final master is not readable"
        return result
    size = resolved_master.stat().st_size
    if size <= 0:
        result["reason"] = "final master is zero bytes"
        return result

    result["master_path"] = resolved_master
    result["master_size"] = size
    result["ok"] = True
    return result


def default_confirm(prompt: str) -> bool:
    try:
        answer = input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer.strip().lower() in ("y", "yes")


# --------------------------------------------------------------------------- actions
def mark_project(project_dir: Path, videos_dir: Path, workspace_root: Path,
                 home: Path, days: int = RETENTION_DAYS,
                 published_at: Optional[datetime.datetime] = None,
                 confirm=None, now: Optional[datetime.datetime] = None,
                 out=None) -> int:
    out = out if out is not None else sys.stdout
    confirm = confirm if confirm is not None else default_confirm
    now = now if now is not None else local_now()

    state = evaluate(project_dir, videos_dir, workspace_root, home)
    if not state["ok"]:
        print("ERROR:", state["reason"], file=out)
        return _EXIT_ERROR

    meta = state["meta"]
    current_status = meta.get("status")

    if current_status == "published":
        recorded = parse_timestamp(meta.get("published_at")) \
            if meta.get("published_at") else None
        print("ALREADY PUBLISHED", file=out)
        print("", file=out)
        print("Project:", file=out)
        print(project_dir.name, file=out)
        print("", file=out)
        print("Published at:", file=out)
        print(format_timestamp(recorded) if recorded else "—", file=out)
        print("", file=out)
        print("Cleanup eligible:", file=out)
        print(format_timestamp(recorded + datetime.timedelta(days=days))
              if recorded else "—", file=out)
        return _EXIT_OK

    new_published_at = published_at if published_at is not None else now
    eligible_after = new_published_at + datetime.timedelta(days=days)

    # confirmation preview (nothing written yet)
    print("Project:", file=out)
    print(project_dir.name, file=out)
    print("", file=out)
    print("Final master:", file=out)
    print(MASTER_REL, file=out)
    print("", file=out)
    print("Current status:", file=out)
    print(current_status if current_status is not None else "—", file=out)
    print("", file=out)
    print("New status:", file=out)
    print("published", file=out)
    print("", file=out)
    print("Published at:", file=out)
    print(format_timestamp(new_published_at), file=out)
    print("", file=out)
    print("Cleanup eligible after:", file=out)
    print(format_timestamp(eligible_after), file=out)
    print("", file=out)

    if not confirm("Mark this project as published? [y/N] "):
        print("Aborted. No changes made.", file=out)
        return _EXIT_OK

    meta["status"] = "published"
    meta["published_at"] = format_timestamp(new_published_at)
    meta["final_master"] = MASTER_REL
    _write_meta_atomic(state["meta_path"], meta)

    print("Marked as published.", file=out)
    print("Project:", project_dir.name, file=out)
    print("Published at:", format_timestamp(new_published_at), file=out)
    print("Cleanup eligible after:", format_timestamp(eligible_after), file=out)
    return _EXIT_OK


def list_projects(videos_dir: Path, days: int = RETENTION_DAYS, out=None) -> int:
    out = out if out is not None else sys.stdout
    header = ("%-*s%-*s%-*s%s" % (_WIDTH_PROJECT, "PROJECT", _WIDTH_STATUS,
                                  "STATUS", _WIDTH_DATE, "PUBLISHED AT",
                                  "CLEANUP"))
    print(header, file=out)
    if not videos_dir.is_dir():
        return _EXIT_OK
    for child in sorted(videos_dir.iterdir(), key=lambda p: p.name):
        if not (child.is_dir() or child.is_symlink()):
            continue
        meta, _err = _load_meta(child / "meta.json")
        status = (meta or {}).get("status")
        raw_date = (meta or {}).get("published_at")
        parsed = parse_timestamp(raw_date) if isinstance(raw_date, str) else None
        status_text = status if isinstance(status, str) else "—"
        date_text = parsed.strftime("%Y-%m-%d %H:%M") if parsed else "—"
        cleanup_text = ("%d days" % days) if status == "published" else "—"
        print("%-*s%-*s%-*s%s" % (_WIDTH_PROJECT, child.name, _WIDTH_STATUS,
                                  status_text, _WIDTH_DATE, date_text,
                                  cleanup_text), file=out)
    return _EXIT_OK


# --------------------------------------------------------------------------- cli
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mark a published video project so retention cleanup can "
                    "run after 7 days.")
    parser.add_argument("project", nargs="?",
                        help="project directory name under videos/")
    parser.add_argument("--published-at", dest="published_at",
                        help="record a real posting time (ISO-8601 with offset)")
    parser.add_argument("--list", action="store_true",
                        help="list projects and their publication status")
    parser.add_argument("--days", type=int, default=RETENTION_DAYS,
                        help="retention window shown for cleanup (default 7)")
    parser.add_argument("--videos-dir", default=str(VIDEOS_DIR),
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    videos_dir = Path(args.videos_dir)

    if args.list:
        if args.project is not None or args.published_at is not None:
            print("ERROR: --list cannot be combined with a project or "
                  "--published-at", file=sys.stderr)
            return _EXIT_USAGE
        if args.days < 1:
            print("ERROR: --days must be >= 1", file=sys.stderr)
            return _EXIT_USAGE
        return list_projects(videos_dir, days=args.days)

    if args.project is None:
        print("ERROR: provide a project name (or --list)", file=sys.stderr)
        return _EXIT_USAGE

    error = _validate_project_name(args.project)
    if error:
        print("ERROR: invalid project name: %s" % error, file=sys.stderr)
        return _EXIT_USAGE

    if args.days < 1:
        print("ERROR: --days must be >= 1", file=sys.stderr)
        return _EXIT_USAGE

    parsed_at = None
    if args.published_at is not None:
        parsed_at = parse_timestamp(args.published_at)
        if parsed_at is None:
            print("ERROR: invalid --published-at (expected ISO-8601 with "
                  "timezone, e.g. 2026-09-15T18:30:00+03:00)", file=sys.stderr)
            return _EXIT_USAGE

    project_dir = videos_dir / args.project
    if not project_dir.exists() or not project_dir.is_dir():
        print("ERROR: project not found: %s" % args.project, file=sys.stderr)
        return _EXIT_ERROR

    return mark_project(
        project_dir=project_dir,
        videos_dir=videos_dir,
        workspace_root=WORKSPACE_ROOT,
        home=Path.home(),
        days=args.days,
        published_at=parsed_at,
        now=local_now(),
    )


if __name__ == "__main__":
    sys.exit(main())
