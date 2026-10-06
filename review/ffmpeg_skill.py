"""Optional, read-only ffmpeg-skill measurement/evidence layer (Phase 1).

This is a shadow integration, not a renderer and not a decision source.

- It invokes a pinned, local copy of ffmpeg-skill (1.25.0, contract 1.0)
  through the same narrow process boundary as ``review/process.py``:
  fixed argv lists, ``shell=False``, a minimal explicit child environment, a
  finite positive timeout, bounded stdout/stderr, and local script paths only.
- Exactly four operations are exposed: ``doctor``, ``probe``, ``check`` and
  ``look``. No caller may name an arbitrary tool.
- It produces measurement evidence only. It never creates findings, proposals,
  approvals, or Gate 2 decisions; it never writes under ``renders/`` and never
  mutates the artifacts it inspects.
- Evidence is written under ``review/reports/`` with deterministic names and is
  never overwritten silently.

Remove this module and its tests to revert the integration completely; nothing
else in the review or studio layers depends on it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

try:  # normal package import
    from . import inputs as review_inputs, process, revision
except ImportError:  # executed directly as a script
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from review import inputs as review_inputs, process, revision  # type: ignore

# ---------------------------------------------------------------- constants

SCHEMA_VERSION = 1
SKILL_VERSION = "1.25.0"
CONTRACT_VERSION = "1.0"

ENV_SKILL_ROOT = "MOTION_STUDIO_FFMPEG_SKILL"
_HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(_HERE, "reports")
_VISION_INPUTS_DIR = os.path.join(_HERE, "vision_inputs")
_DEFAULT_SKILL_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(_HERE)), "vendor", "ffmpeg-skill")

# Fixed script + argument templates. This is the entire tool surface; there is
# no generic runner and no way to reach any other ffmpeg-skill script.
_SCRIPTS = {
    "doctor": "scripts/_contract.py",
    "probe": "scripts/probe.py",
    "check": "scripts/check.py",
    "look": "scripts/look.py",
}

ALLOWED_OPERATIONS = ("doctor", "probe", "check", "look")

# Canonical platforms accepted by ``check.py``; aliases map onto them. Free text
# is never forwarded to the subprocess.
_PLATFORM_ALIASES = {
    "youtube": "youtube", "yt": "youtube",
    "shorts": "shorts", "youtube-shorts": "shorts", "yt-shorts": "shorts",
    "reels": "reels", "instagram": "reels", "ig": "reels",
    "tiktok": "tiktok",
    "x": "x", "twitter": "x",
    "linkedin": "linkedin",
    "facebook": "facebook", "fb": "facebook",
    "broadcast": "broadcast",
    "podcast": "podcast",
}
ALLOWED_PLATFORMS = tuple(sorted(set(_PLATFORM_ALIASES.values())))

_DOCTOR_TIMEOUT = 60
_PROBE_TIMEOUT = 120
_CHECK_TIMEOUT = 180
_LOOK_TIMEOUT = 300

STDOUT_LIMIT = 4 << 20
STDERR_LIMIT = 256 << 10

# Stderr markers that a look failure is an ffmpeg build capability gap rather
# than a generic tool error. doctor.tools.look.usable is not treated as proof.
_LOOK_CAPABILITY_TOKENS = (
    "no such filter", "unknown filter", "filter not found", "drawtext",
    "libass", "zscale", "not compiled", "unsupported codec",
)

# Error kinds: distinct failure classes reported as evidence, never as findings.
ERR_DEPENDENCY = "dependency_unavailable"
ERR_CAPABILITY = "capability_unavailable"
ERR_VERSION = "version_mismatch"
ERR_TIMEOUT = "timeout"
ERR_INVALID = "invalid_input"
ERR_TOOL = "tool_failure"
ERR_JSON = "malformed_json"
ERR_OVERFLOW = "output_overflow"


class SkillError(Exception):
    """A configuration or caller-input problem (before any subprocess runs)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class EvidenceExistsError(Exception):
    """Existing evidence would be replaced; overwrite was not requested."""


# ---------------------------------------------------------------- identity

def _reject_remote(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SkillError(ERR_INVALID, "%s must be a local path" % label)
    lowered = value.lower()
    if lowered.startswith("//") or "://" in value:
        raise SkillError(ERR_INVALID, "%s must be local, not a URL: %s" % (label, value))
    return value


def _read_skill_version(root: str) -> Optional[str]:
    """Read the pinned version from a local marker; never invokes npm."""
    pkg = os.path.join(root, "package.json")
    if os.path.isfile(pkg):
        try:
            with open(pkg, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            version = data.get("version")
            if isinstance(version, str) and version:
                return version
        except (OSError, ValueError):
            return None
    marker = os.path.join(root, ".ffmpeg-skill-version")
    if os.path.isfile(marker):
        try:
            with open(marker, "r", encoding="utf-8") as fh:
                return fh.read().strip() or None
        except OSError:
            return None
    return None


def resolve_skill_root(explicit: Optional[str] = None) -> str:
    """Locate and validate the pinned local ffmpeg-skill installation.

    Rejects remote paths, symlink escapes out of the root, a missing required
    script, and a version that does not match the pinned one.
    """
    candidate = explicit or os.environ.get(ENV_SKILL_ROOT) or _DEFAULT_SKILL_ROOT
    _reject_remote(candidate, "ffmpeg-skill root")
    root = os.path.abspath(candidate)
    if not os.path.isdir(root):
        raise SkillError(ERR_DEPENDENCY, "ffmpeg-skill root is not a local directory: %s"
                         % os.path.basename(candidate))
    real_root = os.path.realpath(root)
    for script in _SCRIPTS.values():
        path = os.path.join(root, script)
        real = os.path.realpath(path)
        if not (real == real_root or real.startswith(real_root + os.sep)):
            raise SkillError(ERR_DEPENDENCY, "ffmpeg-skill script escapes the root: %s" % script)
        if not os.path.isfile(path):
            raise SkillError(ERR_DEPENDENCY, "required ffmpeg-skill script is missing: %s" % script)
    version = _read_skill_version(root)
    if version is None:
        raise SkillError(ERR_DEPENDENCY, "ffmpeg-skill version marker is missing")
    if version != SKILL_VERSION:
        raise SkillError(ERR_VERSION, "ffmpeg-skill %s is not the pinned %s"
                         % (version, SKILL_VERSION))
    return root


def _script_path(root: str, name: str) -> str:
    if name not in _SCRIPTS:
        raise SkillError(ERR_INVALID, "unsupported ffmpeg-skill operation: %s" % name)
    return os.path.join(root, _SCRIPTS[name])


def _python_executable() -> str:
    exe = sys.executable or shutil.which("python3") or ""
    _reject_remote(exe, "python executable")
    if not os.path.isabs(exe) or not os.path.isfile(exe):
        raise SkillError(ERR_DEPENDENCY, "no local python executable available")
    return exe


# ---------------------------------------------------------------- helpers

def _iso(now=None) -> str:
    moment = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    return moment.isoformat(timespec="seconds")


def _display_path(project_dir: Optional[str], abspath: str) -> str:
    if project_dir:
        rel = os.path.relpath(abspath, project_dir)
        if not rel.startswith(".."):
            return rel.replace(os.sep, "/")
    return os.path.basename(abspath)


def _display_argv(argv: List[str], root: str, media_abs: Optional[str],
                  media_rel: Optional[str]) -> List[str]:
    disp = []
    for arg in argv:
        if arg == sys.executable:
            arg = "python3"
        if arg.startswith(root + os.sep):
            arg = os.path.relpath(arg, root).replace(os.sep, "/")
        if media_abs and arg == media_abs:
            arg = media_rel or os.path.basename(media_abs)
        disp.append(arg)
    return disp


def _classify(exc: Exception) -> str:
    message = str(exc).lower()
    if "timed out" in message:
        return ERR_TIMEOUT
    if "exceeded the bounded limit" in message:
        return ERR_OVERFLOW
    if "not installed" in message or "not on path" in message or "failed to launch" in message:
        return ERR_DEPENDENCY
    return ERR_TOOL


def _base_result(operation: str, *, arguments: List[str], media_rel: Optional[str],
                 media_sha: Optional[str], generated_at: str) -> Dict:
    return {
        "operation": operation,
        "input": ({"path": media_rel, "sha256": media_sha} if media_rel else None),
        "arguments": arguments,
        "measurement_status": "complete",
        "exit_status": None,
        "error": None,
        "diagnostic": None,
        "output": None,
        "timestamp": generated_at,
    }


def _failed_result(operation: str, kind: str, message: str, *,
                   arguments: Optional[List[str]] = None,
                   media_rel: Optional[str] = None,
                   media_sha: Optional[str] = None,
                   generated_at: Optional[str] = None,
                   diagnostic: Optional[str] = None,
                   exit_status: Optional[int] = None,
                   output: Optional[Dict] = None) -> Dict:
    status = "unavailable" if kind in (ERR_DEPENDENCY, ERR_CAPABILITY) else "failed"
    return {
        "operation": operation,
        "input": ({"path": media_rel, "sha256": media_sha} if media_rel else None),
        "arguments": arguments or [],
        "measurement_status": status,
        "exit_status": exit_status,
        "error": {"kind": kind, "message": process.bounded(message or "")},
        "diagnostic": process.bounded(diagnostic) if diagnostic else None,
        "output": output,
        "timestamp": generated_at or _iso(),
    }


# A tool can exit non-zero while printing a *valid* structured failure document
# (``{"status": "failed", "error": {"kind": ..., "code": ...}}``). Such a result
# is never a completed measurement; it is mapped to the module's own error kinds.
_STRUCTURED_CODE_KINDS = {
    "INPUT_INVALID": ERR_INVALID,
    "DEPENDENCY_MISSING": ERR_DEPENDENCY,
    "TIMEOUT": ERR_TIMEOUT,
    "OUTPUT_INVALID": ERR_TOOL,
    "FFMPEG_EXECUTION_FAILED": ERR_TOOL,
    "VERIFICATION_FAILED": ERR_TOOL,
    "INTERNAL_ERROR": ERR_TOOL,
}
_STRUCTURED_KIND_KINDS = {
    "input": ERR_INVALID,
    "missing_tool": ERR_DEPENDENCY,
    "timeout": ERR_TIMEOUT,
    "output": ERR_TOOL,
    "ffmpeg": ERR_TOOL,
    "verification": ERR_TOOL,
    "interrupted": ERR_TOOL,
}


def _structured_error_kind(doc: Dict) -> str:
    error = doc.get("error") if isinstance(doc.get("error"), dict) else {}
    code = str(error.get("code") or "").upper()
    if code in _STRUCTURED_CODE_KINDS:
        return _STRUCTURED_CODE_KINDS[code]
    kind = str(error.get("kind") or "").lower()
    return _STRUCTURED_KIND_KINDS.get(kind, ERR_TOOL)


def _structured_error_message(doc: Dict) -> str:
    error = doc.get("error") if isinstance(doc.get("error"), dict) else {}
    return str(error.get("message") or "ffmpeg-skill reported a failed result")


def _execute(operation: str, root: str, argv: List[str], *, timeout: int,
             parse_json: bool, media_abs: Optional[str] = None,
             media_rel: Optional[str] = None, media_sha: Optional[str] = None,
             generated_at: Optional[str] = None) -> Dict:
    stamp = generated_at or _iso()
    display = _display_argv(argv, root, media_abs, media_rel)
    try:
        process._validate_timeout(timeout)
    except process.ProcessError as exc:
        return _failed_result(operation, ERR_INVALID, str(exc), arguments=display,
                              media_rel=media_rel, media_sha=media_sha, generated_at=stamp)
    try:
        rc, out, err = process._run_bounded(
            argv, timeout=timeout, cwd=root,
            max_stdout=STDOUT_LIMIT, max_stderr=STDERR_LIMIT)
    except process.ProcessError as exc:
        return _failed_result(operation, _classify(exc), str(exc), arguments=display,
                              media_rel=media_rel, media_sha=media_sha, generated_at=stamp)
    diag = err.decode("utf-8", "replace").strip()
    if parse_json:
        try:
            doc = json.loads(out.decode("utf-8", "replace") or "")
        except ValueError:
            return _failed_result(operation, ERR_JSON,
                                  "ffmpeg-skill returned unparseable JSON",
                                  arguments=display, media_rel=media_rel, media_sha=media_sha,
                                  generated_at=stamp, diagnostic=diag, exit_status=rc)
        if isinstance(doc, dict) and doc.get("status") == "failed":
            return _failed_result(
                operation, _structured_error_kind(doc), _structured_error_message(doc),
                arguments=display, media_rel=media_rel, media_sha=media_sha,
                generated_at=stamp, diagnostic=diag, exit_status=rc, output=doc)
        result = _base_result(operation, arguments=display, media_rel=media_rel,
                              media_sha=media_sha, generated_at=stamp)
        result["exit_status"] = rc
        result["output"] = doc
        result["diagnostic"] = process.bounded(diag) if diag else None
        return result
    if rc != 0:
        return _failed_result(operation, ERR_TOOL, "ffmpeg-skill exited %d" % rc,
                              arguments=display, media_rel=media_rel, media_sha=media_sha,
                              generated_at=stamp, diagnostic=diag, exit_status=rc)
    result = _base_result(operation, arguments=display, media_rel=media_rel,
                          media_sha=media_sha, generated_at=stamp)
    result["exit_status"] = rc
    result["diagnostic"] = process.bounded(diag) if diag else None
    return result


def _prepare_media(media: str, project_dir: Optional[str]) -> Tuple[str, str, str]:
    """Return (abspath, project-relative display path, sha256). Local files only."""
    abspath = process.ensure_local(media, "ffmpeg-skill input")
    return abspath, _display_path(project_dir, abspath), review_inputs.sha256_file(abspath)


# ---------------------------------------------------------------- operations

def run_doctor(*, skill_root: Optional[str] = None, timeout: Optional[int] = None,
               now=None, reuse: Optional[Dict] = None) -> Dict:
    """Run ffmpeg-skill doctor once and capture capability/version evidence.

    ``reuse`` lets a caller pass a previous complete doctor result; when a
    matching one is supplied it is returned unchanged and no subprocess runs.
    """
    root = resolve_skill_root(skill_root)
    if isinstance(reuse, dict) and reuse.get("measurement_status") == "complete" \
            and reuse.get("output") is not None:
        return reuse
    argv = [_python_executable(), _script_path(root, "doctor"), "doctor", "--json"]
    result = _execute("doctor", root, argv, timeout=timeout or _DOCTOR_TIMEOUT,
                      parse_json=True, generated_at=_iso(now))
    if result.get("output") is not None:
        result["relevant"] = _doctor_relevant(result["output"])
        # doctor ran and produced structured data, but a missing required
        # capability means the environment is not fully usable. This is a
        # partial measurement, never a misleading "complete". The raw doctor
        # document stays in evidence.
        if result.get("measurement_status") == "complete" \
                and result["output"].get("ok") is False:
            result["measurement_status"] = "partial"
            result["error"] = {
                "kind": ERR_CAPABILITY,
                "message": "ffmpeg-skill doctor reports missing required capabilities",
            }
    return result


def _doctor_relevant(doc: Dict) -> Dict:
    doc = doc if isinstance(doc, dict) else {}
    fonts = doc.get("fonts") if isinstance(doc.get("fonts"), dict) else {}
    scripts = fonts.get("scripts") if isinstance(fonts.get("scripts"), dict) else {}
    tools = doc.get("tools") if isinstance(doc.get("tools"), dict) else {}
    return {
        "ok": doc.get("ok"),
        "missing": list(doc.get("missing") or []),
        "missing_optional": list(doc.get("missing_optional") or []),
        "unknown": list(doc.get("unknown") or []),
        "arabic_fonts": scripts.get("ar"),
        "caption_tool": tools.get("caption"),
    }


def run_probe(media: str, *, skill_root: Optional[str] = None,
              project_dir: Optional[str] = None, timeout: Optional[int] = None,
              now=None) -> Dict:
    """Supplementary facts from ``probe --json`` (VFR/HDR/DV/colour/streams)."""
    root = resolve_skill_root(skill_root)
    try:
        abspath, rel, sha = _prepare_media(media, project_dir)
    except process.ProcessError as exc:
        return _failed_result("probe", ERR_INVALID, str(exc), generated_at=_iso(now))
    argv = [_python_executable(), _script_path(root, "probe"), abspath, "--json"]
    result = _execute("probe", root, argv, timeout=timeout or _PROBE_TIMEOUT,
                      parse_json=True, media_abs=abspath, media_rel=rel, media_sha=sha,
                      generated_at=_iso(now))
    if result.get("output") is not None:
        result["supplementary"] = _probe_supplementary(result["output"])
    return result


def _probe_supplementary(doc) -> Dict:
    if isinstance(doc, list):
        doc = doc[0] if doc else {}
    if not isinstance(doc, dict):
        doc = {}
    video = doc.get("video") if isinstance(doc.get("video"), dict) else {}
    return {
        "variable_frame_rate_suspected": video.get("variable_frame_rate_suspected"),
        "hdr": video.get("hdr"),
        "hdr_format": video.get("hdr_format"),
        "hdr_signal": video.get("hdr_signal"),
        "dolby_vision": video.get("dolby_vision"),
        "bit_depth": video.get("bit_depth"),
        "rotation": video.get("rotation"),
        "color_space": video.get("color_space"),
        "color_primaries": video.get("color_primaries"),
        "color_transfer": video.get("color_transfer"),
        "color_range": video.get("color_range"),
        "subtitle_streams": doc.get("subtitle_streams"),
        "audio_streams": doc.get("audio_streams"),
    }


def normalize_platform(platform: str) -> str:
    if not isinstance(platform, str):
        raise SkillError(ERR_INVALID, "platform must be a string")
    canonical = _PLATFORM_ALIASES.get(platform.strip().lower())
    if canonical is None:
        raise SkillError(ERR_INVALID, "unsupported check platform: %s" % platform)
    return canonical


def run_check(media: str, *, platform: str, skill_root: Optional[str] = None,
              project_dir: Optional[str] = None, timeout: Optional[int] = None,
              now=None) -> Dict:
    """Delivery conformance from ``check --json --platform <allowlisted>``.

    PASS/WARN/FAIL rows are stored verbatim as evidence; they never become
    Motion Studio findings.
    """
    canonical = normalize_platform(platform)
    root = resolve_skill_root(skill_root)
    try:
        abspath, rel, sha = _prepare_media(media, project_dir)
    except process.ProcessError as exc:
        return _failed_result("check", ERR_INVALID, str(exc), generated_at=_iso(now))
    argv = [_python_executable(), _script_path(root, "check"), abspath,
            "--json", "--platform", canonical]
    result = _execute("check", root, argv, timeout=timeout or _CHECK_TIMEOUT,
                      parse_json=True, media_abs=abspath, media_rel=rel, media_sha=sha,
                      generated_at=_iso(now))
    if isinstance(result.get("output"), dict):
        result["platform"] = canonical
        result["summary"] = _check_summary(result["output"])
    return result


def _check_summary(doc: Dict) -> Dict:
    return {
        "platform": doc.get("platform"),
        "ok": doc.get("ok"),
        "failed": doc.get("failed"),
        "warnings": doc.get("warnings"),
        "checks": len(doc.get("checks") or []) if isinstance(doc.get("checks"), list) else None,
    }


def run_look(media: str, output_path: str, *, skill_root: Optional[str] = None,
             project_dir: Optional[str] = None, at_times: Optional[List[float]] = None,
             timeout: Optional[int] = None, now=None) -> Dict:
    """Render a contact sheet PNG via ``look`` into an evidence path."""
    stamp = _iso(now)
    root = resolve_skill_root(skill_root)
    out_abs = os.path.abspath(output_path)
    if not (out_abs == REPORTS_DIR or out_abs.startswith(REPORTS_DIR + os.sep)):
        raise SkillError(ERR_INVALID, "look output must stay under review/reports/")
    try:
        abspath, rel, sha = _prepare_media(media, project_dir)
    except process.ProcessError as exc:
        return _failed_result("look", ERR_INVALID, str(exc), generated_at=stamp)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    argv = [_python_executable(), _script_path(root, "look"), abspath, "-o", out_abs]
    for at in (at_times or []):
        argv += ["--at", "%.3f" % float(at)]
    result = _execute("look", root, argv, timeout=timeout or _LOOK_TIMEOUT,
                      parse_json=False, media_abs=abspath, media_rel=rel, media_sha=sha,
                      generated_at=stamp)
    result["output_image"] = os.path.basename(out_abs)
    if result["measurement_status"] == "complete" and not os.path.isfile(out_abs):
        result["measurement_status"] = "failed"
        result["error"] = {"kind": ERR_TOOL, "message": "look did not write the expected image"}
    # doctor's tools.look.usable is not proof that look runs on this ffmpeg
    # build (e.g. it needs the drawtext filter for timecodes). A runtime
    # capability failure is recorded as an unavailable measurement, never as a
    # completed one, and never surfaced as a review finding.
    runtime_error = result.get("error") or {}
    if result["measurement_status"] != "complete" and runtime_error.get("kind") == ERR_TOOL:
        diagnostic = (result.get("diagnostic") or "").lower()
        if any(token in diagnostic for token in _LOOK_CAPABILITY_TOKENS):
            result["measurement_status"] = "unavailable"
            result["error"] = {
                "kind": ERR_CAPABILITY,
                "message": "look failed: an ffmpeg runtime capability is unavailable",
            }
    return result


# ---------------------------------------------------------------- evidence paths

def _project_revision(project_dir: str) -> Tuple[str, int]:
    state = revision.load_state_view(project_dir)
    return revision.state_key(project_dir), int(state.get("revision", 1))


def evidence_path(project_dir: str) -> str:
    key, rev = _project_revision(project_dir)
    return os.path.join(REPORTS_DIR, "%s-rev%d.skill.json" % (key, rev))


def look_evidence_path(project_dir: str) -> str:
    key, rev = _project_revision(project_dir)
    return os.path.join(REPORTS_DIR, "%s-rev%d.skill-look.png" % (key, rev))


def existing_visual_evidence(project_dir: str, key: str, rev: int) -> Tuple[bool, str]:
    """Report whether existing review/snapshot evidence already covers visuals."""
    reasons: List[str] = []
    vision_sheet = os.path.join(_VISION_INPUTS_DIR, "%s-rev%d" % (key, rev), "contact-sheet.png")
    if os.path.isfile(vision_sheet):
        reasons.append("vision_contact_sheet")
    snap_dir = os.path.join(project_dir, "snapshots")
    if os.path.isdir(snap_dir):
        names = os.listdir(snap_dir)
        if any(n in ("contact-sheet.jpg", "contact-sheet.png") for n in names):
            reasons.append("snapshot_contact_sheet")
        pngs = [n for n in names if n.lower().endswith(".png")]
        if len(pngs) >= 3:
            reasons.append("snapshots:%d" % len(pngs))
    return (bool(reasons), ",".join(reasons))


def _write_json_atomic(path: str, data: Dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def save_evidence(project_dir: str, evidence: Dict, *, overwrite: bool = False) -> str:
    path = evidence_path(project_dir)
    if os.path.isfile(path) and not overwrite:
        raise EvidenceExistsError(
            "evidence already exists at %s; pass overwrite=True to replace it"
            % os.path.basename(path))
    _write_json_atomic(path, evidence)
    return path


# ---------------------------------------------------------------- aggregation

def _aggregate_status(results: List[Dict]) -> str:
    ran = [r for r in results if r.get("measurement_status") != "skipped"]
    if not ran:
        return "skipped"
    complete = [r for r in ran if r.get("measurement_status") == "complete"]
    if len(complete) == len(ran):
        return "complete"
    if complete:
        return "partial"
    if all(r.get("measurement_status") == "unavailable" for r in ran):
        return "unavailable"
    return "failed"


def collect_evidence(project_dir: str, *, render: Optional[str] = None,
                     platform: Optional[str] = None, look: bool = False,
                     skill_root: Optional[str] = None, overwrite: bool = False,
                     force_doctor: bool = False, now=None) -> Dict:
    """Run the requested shadow measurements and return an evidence document.

    Never raises for an unavailable/failed ffmpeg-skill (that is recorded in the
    evidence). It only raises for caller-input errors such as an unsupported
    platform, so a broken integration cannot break the base review pipeline.
    """
    project_dir = os.path.abspath(project_dir)
    key, rev = _project_revision(project_dir)
    stamp = _iso(now)
    notes: List[str] = []
    operations: Dict[str, Dict] = {}

    try:
        root = resolve_skill_root(skill_root)
        dependency = {"available": True, "ffmpeg_skill_version": _read_skill_version(root),
                      "contract_version": CONTRACT_VERSION}
    except SkillError as exc:
        root = None
        dependency = {"available": False, "ffmpeg_skill_version": None,
                      "contract_version": None,
                      "error": {"kind": exc.kind, "message": str(exc)}}

    tools = process.tool_identities()
    provenance = {
        "ffmpeg_skill_version": dependency.get("ffmpeg_skill_version"),
        "contract_version": dependency.get("contract_version"),
        "ffmpeg_version": (tools.get("ffmpeg") or {}).get("identity"),
        "ffprobe_version": (tools.get("ffprobe") or {}).get("identity"),
        "generated_at": stamp,
    }
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "kind": "ffmpeg-skill-measurement",
        "project": revision.slug_for(project_dir),
        "state_key": key,
        "revision": rev,
        "render": None,
        "dependency": dependency,
        "provenance": provenance,
        "operations": operations,
        "measurement_status": "unavailable",
        "notes": notes,
    }

    if root is None:
        notes.append("ffmpeg-skill unavailable: %s" % dependency["error"]["message"])
        return evidence

    render_abs = None
    render_rel = None
    render_sha = None
    render_path = render or review_inputs.discover_render(project_dir)
    if render_path:
        try:
            render_abs = process.ensure_local(render_path, "render")
            render_rel = _display_path(project_dir, render_abs)
            render_sha = review_inputs.sha256_file(render_abs)
            evidence["render"] = {"path": render_rel, "sha256": render_sha}
        except process.ProcessError as exc:
            notes.append("render is not a permitted local file: %s" % exc)
    if render_abs is None:
        notes.append("no local render found; probe/check/look skipped")

    # doctor: run once per collection, reusing prior complete evidence when
    # the pinned version is unchanged (never re-run per artifact review).
    reuse = None
    existing_path = evidence_path(project_dir)
    if os.path.isfile(existing_path) and not force_doctor:
        prior = _read_existing_json(existing_path)
        prior_doc = ((prior or {}).get("operations") or {}).get("doctor")
        prior_version = ((prior or {}).get("provenance") or {}).get("ffmpeg_skill_version")
        if prior_version == provenance["ffmpeg_skill_version"]:
            reuse = prior_doc
    try:
        operations["doctor"] = run_doctor(skill_root=root, now=now, reuse=reuse)
        if reuse is not None:
            notes.append("doctor reused from existing evidence")
    except SkillError as exc:
        operations["doctor"] = _failed_result("doctor", exc.kind, str(exc), generated_at=stamp)

    if render_abs is not None:
        operations["probe"] = run_probe(render_abs, skill_root=root,
                                        project_dir=project_dir, now=now)
    if platform is not None:
        if render_abs is None:
            notes.append("check skipped: no local render")
        else:
            operations["check"] = run_check(render_abs, platform=platform,
                                            skill_root=root, project_dir=project_dir, now=now)
    if look:
        if render_abs is None:
            notes.append("look skipped: no local render")
        else:
            sufficient, reason = existing_visual_evidence(project_dir, key, rev)
            out_path = look_evidence_path(project_dir)
            if sufficient:
                operations["look"] = {
                    "operation": "look", "measurement_status": "skipped",
                    "reason": "existing_visual_evidence:%s" % reason,
                    "input": {"path": render_rel, "sha256": render_sha},
                    "timestamp": stamp,
                }
                notes.append("look skipped: existing visual evidence (%s)" % reason)
            elif os.path.isfile(out_path) and not overwrite:
                operations["look"] = {
                    "operation": "look", "measurement_status": "skipped",
                    "reason": "existing_evidence_file",
                    "input": {"path": render_rel, "sha256": render_sha},
                    "timestamp": stamp,
                }
                notes.append("look skipped: evidence image already exists")
            else:
                operations["look"] = run_look(render_abs, out_path, skill_root=root,
                                              project_dir=project_dir, now=now)

    evidence["measurement_status"] = _aggregate_status(list(operations.values()))
    return evidence


def _read_existing_json(path: str) -> Optional[Dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- CLI

def _summary(evidence: Dict) -> str:
    lines = [
        "ffmpeg-skill measurement (shadow, read-only)",
        "project: %s" % evidence.get("project"),
        "revision: %s" % evidence.get("revision"),
        "measurement_status: %s" % evidence.get("measurement_status"),
        "ffmpeg-skill: %s (contract %s)"
        % ((evidence.get("provenance") or {}).get("ffmpeg_skill_version"),
           (evidence.get("provenance") or {}).get("contract_version")),
    ]
    for name, op in (evidence.get("operations") or {}).items():
        detail = op.get("error", {}).get("kind") if op.get("error") else op.get("reason", "")
        lines.append("- %s: %s%s" % (name, op.get("measurement_status"),
                                     (" (%s)" % detail) if detail else ""))
    for note in evidence.get("notes") or []:
        lines.append("note: %s" % note)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ffmpeg-skill-evidence",
        description="Shadow ffmpeg-skill measurements (never findings)")
    ap.add_argument("project", help="video project directory")
    ap.add_argument("--render", help="explicit render path (default: rendered video in renders/)")
    ap.add_argument("--platform", help="delivery platform for check (%s)"
                    % ", ".join(ALLOWED_PLATFORMS))
    ap.add_argument("--look", action="store_true",
                    help="also render a contact sheet when no existing visual evidence covers it")
    ap.add_argument("--skill-root", help="local ffmpeg-skill root (env %s)" % ENV_SKILL_ROOT)
    ap.add_argument("--overwrite", action="store_true", help="replace existing evidence")
    ap.add_argument("--force-doctor", action="store_true", help="ignore reused doctor evidence")
    ap.add_argument("--json", action="store_true", help="print the evidence document")
    ap.add_argument("--no-save", action="store_true", help="do not write evidence")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = collect_evidence(
            args.project, render=args.render, platform=args.platform, look=args.look,
            skill_root=args.skill_root, overwrite=args.overwrite,
            force_doctor=args.force_doctor)
    except SkillError as exc:
        print("Invalid input: %s" % exc)
        return 2
    if not args.no_save:
        try:
            path = save_evidence(args.project, evidence, overwrite=args.overwrite)
            evidence["saved_to"] = os.path.basename(path)
        except EvidenceExistsError as exc:
            print("Evidence not written: %s" % exc)
            return 3
    if args.json:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    else:
        print(_summary(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
