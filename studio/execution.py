"""Unit B (Increment 1): opt-in, local-only managed execution of the timing stage.

Lifecycle: explicit request -> pre-execution validation (no side effects) ->
execution-scoped run lock -> bounded local timing operation -> append-only
Phase 1 receipt (attempt) + registered output artifacts.

There is no render, browser, provider, TTS, or network execution here. Only the
offline timing operations are exposed, through the narrow boundary in
``studio/execution_process.py``. Phase 1 schemas, stage vocabulary, and
``ATTEMPT_ORIGINS`` are unchanged; read paths stay side-effect-free.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from studio import artifacts, contracts, execution_process, manifest

SUPPORTED_STAGES = ("timing",)
DEFAULT_PROVIDER = "elevenlabs"
DEFAULT_TOOL = "studio.execution.timing"
_ERROR_LIMIT = 600


class ExecutionError(contracts.ContractError):
    """A managed execution request is invalid or cannot proceed."""


@dataclass(frozen=True)
class TimingExecutionRequest:
    """Explicit request to execute the timing stage for one run.

    Every input is an explicitly registered artifact ID; nothing is discovered.
    """
    workspace: str
    project_id: str
    run_id: str
    attempt_id: str
    input_artifact_ids: Tuple[str, ...]
    provider_response_artifact_id: str
    output_timing_artifact_id: str
    output_timing_path: str
    provider: str = DEFAULT_PROVIDER
    stage_id: str = "timing"
    output_captions_artifact_id: Optional[str] = None
    output_captions_path: Optional[str] = None
    audio_duration_ms: Optional[int] = None
    timeout_seconds: float = 60.0
    origin: str = "human"
    confirm: bool = False
    created_at: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short(value: object) -> str:
    text = str(value)
    return text if len(text) <= _ERROR_LIMIT else text[:_ERROR_LIMIT] + "...[truncated]"


def execution_lock_path(workspace: str, project_id: str, run_id: str) -> str:
    """Execution-scoped run-level lock path (Phase 1 lock semantics)."""
    contracts.validate_fs_id(project_id, "project_id")
    contracts.validate_fs_id(run_id, "run_id")
    digest = hashlib.sha256(
        "\x00".join(("execution", project_id, run_id)).encode("utf-8")).hexdigest()
    return os.path.join(manifest.locks_dir(workspace), "%s.lock" % digest[:32])


def _resolve_registered_artifact(run: Dict, artifact_id: str, workspace: str,
                                 revision_dir: str) -> Tuple[Dict, str]:
    artifact = run["artifacts"].get(artifact_id)
    if artifact is None:
        raise contracts.UnknownReferenceError("input artifact %r is not registered" % artifact_id)
    path = artifacts.resolve_artifact_path(
        artifact["root"], artifact["path"], workspace, revision_dir)
    return artifact, path


def _prepare(request: TimingExecutionRequest) -> Dict:
    """Validate the request completely before any side effect."""
    if request.stage_id != "timing":
        raise ExecutionError("unsupported stage_id %r; Unit B Increment 1 supports timing only"
                             % request.stage_id)
    if not request.confirm:
        raise ExecutionError("execution writes outputs and a receipt; pass --confirm")
    try:
        timeout = execution_process.validate_timeout(request.timeout_seconds)
    except execution_process.ExecutionProcessError as exc:
        raise ExecutionError(str(exc))
    if request.origin not in contracts.ATTEMPT_ORIGINS:
        raise ExecutionError("origin %r is not a registered attempt origin" % request.origin)
    contracts.validate_fs_id(request.attempt_id, "attempt_id")
    contracts.validate_fs_id(request.provider_response_artifact_id,
                             "provider_response_artifact_id")
    contracts.validate_fs_id(request.output_timing_artifact_id, "output_timing_artifact_id")
    if (request.output_captions_artifact_id is None) != (request.output_captions_path is None):
        raise ExecutionError("caption output requires both an artifact id and a path")
    if request.output_captions_artifact_id is not None:
        contracts.validate_fs_id(request.output_captions_artifact_id,
                                 "output_captions_artifact_id")
    if request.provider not in execution_process.supported_providers():
        raise ExecutionError("unsupported timing provider %r" % request.provider)
    if request.audio_duration_ms is not None and (
            isinstance(request.audio_duration_ms, bool)
            or not isinstance(request.audio_duration_ms, int)
            or request.audio_duration_ms <= 0):
        raise ExecutionError("audio_duration_ms must be a positive integer or null")

    manifest.locks_dir(request.workspace)  # validates workspace + recorder containment
    ws = os.path.realpath(request.workspace)
    if manifest.load_project(ws, request.project_id) is None:
        raise contracts.UnknownReferenceError("project %r is not registered" % request.project_id)
    run = manifest.load_run(ws, request.project_id, request.run_id)
    revision_dir = run["revision_dir"]

    input_ids = list(request.input_artifact_ids)
    if len(set(input_ids)) != len(input_ids):
        raise ExecutionError("input_artifact_ids must be unique")
    if request.provider_response_artifact_id not in input_ids:
        raise ExecutionError("provider_response_artifact_id must be one of the input artifacts")
    for ref in input_ids:
        contracts.validate_fs_id(ref, "input_artifact_id")
        if ref not in run["artifacts"]:
            raise contracts.UnknownReferenceError("input artifact %r is not registered" % ref)
    required = contracts.required_input_kinds("timing", run["narration_enabled"])
    kinds = {run["artifacts"][ref]["kind"] for ref in input_ids}
    missing = [kind for kind in required if kind not in kinds]
    if missing:
        raise ExecutionError("timing stage is missing required input kinds: %s" % missing)

    _provider_artifact, provider_response_path = _resolve_registered_artifact(
        run, request.provider_response_artifact_id, ws, revision_dir)
    try:
        provider_response_path = execution_process.ensure_local_file(
            provider_response_path, "provider response")
    except execution_process.ExecutionProcessError as exc:
        raise ExecutionError(str(exc))

    if request.attempt_id in run["attempts"]:
        raise contracts.DuplicateIdentityError("attempt_id %r already recorded" % request.attempt_id)
    for aid in (request.output_timing_artifact_id, request.output_captions_artifact_id):
        if aid is not None and aid in run["artifacts"]:
            raise contracts.DuplicateIdentityError("artifact_id %r already registered" % aid)

    timing_dest = artifacts.resolve_artifact_path(
        "project", request.output_timing_path, ws, revision_dir)
    captions_dest = None
    if request.output_captions_path is not None:
        captions_dest = artifacts.resolve_artifact_path(
            "project", request.output_captions_path, ws, revision_dir)
    if captions_dest is not None and captions_dest == timing_dest:
        raise ExecutionError("timing and caption outputs must be different files")
    for dest in (timing_dest, captions_dest):
        if dest is not None and os.path.exists(dest):
            raise ExecutionError("refusing to overwrite existing output: %s" % dest)
    for existing in run["artifacts"].values():
        resolved = artifacts.resolve_artifact_path(
            existing["root"], existing["path"], ws, revision_dir)
        if resolved in (timing_dest, captions_dest):
            raise contracts.DuplicateIdentityError(
                "output path is already registered as artifact %r" % existing["artifact_id"])

    return {
        "ws": ws,
        "project_id": request.project_id,
        "run_id": request.run_id,
        "revision_dir": revision_dir,
        "provider_response_path": provider_response_path,
        "timing_dest": timing_dest,
        "captions_dest": captions_dest,
        "timing_artifact_id": request.output_timing_artifact_id,
        "captions_artifact_id": request.output_captions_artifact_id,
        "timing_rel_path": request.output_timing_path,
        "captions_rel_path": request.output_captions_path,
        "input_ids": input_ids,
        "timeout": timeout,
    }


def _mutate_success(plan: Dict, request: TimingExecutionRequest,
                    started_at: str, ended_at: str) -> Callable[[Dict], Dict]:
    output_ids: List[str] = [plan["timing_artifact_id"]]
    produced: List[Tuple[str, str, str]] = [
        (plan["timing_artifact_id"], "timing", plan["timing_rel_path"])]
    if plan["captions_artifact_id"] is not None:
        output_ids.append(plan["captions_artifact_id"])
        produced.append((plan["captions_artifact_id"], "caption", plan["captions_rel_path"]))
    stamp = request.created_at or ended_at

    def mutate(run: Dict) -> Dict:
        if request.attempt_id in run["attempts"]:
            raise contracts.DuplicateIdentityError(
                "attempt_id %r already recorded" % request.attempt_id)
        for aid, _kind, _rel in produced:
            if aid in run["artifacts"]:
                raise contracts.DuplicateIdentityError("artifact_id %r already registered" % aid)
        for ref in plan["input_ids"]:
            if ref not in run["artifacts"]:
                raise contracts.UnknownReferenceError("input artifact %r is not registered" % ref)
        attempt = {
            "schema_version": contracts.ATTEMPT_SCHEMA_VERSION,
            "attempt_id": request.attempt_id,
            "stage_id": "timing",
            "stage_contract_version": contracts.STAGE_CONTRACT_VERSION,
            "origin": request.origin,
            "reported_execution_outcome": "succeeded",
            "input_artifact_ids": list(plan["input_ids"]),
            "output_artifact_ids": list(output_ids),
            "started_at": started_at,
            "ended_at": ended_at,
            "error": None,
            "provider": request.provider,
            "tool": DEFAULT_TOOL,
            "model": None,
            "usage": None,
            "supersedes": None,
            "recorded_at": stamp,
        }
        contracts.validate_attempt(attempt)
        for aid, kind, rel in produced:
            artifact = artifacts.build_artifact(
                aid, kind, "project", rel, plan["ws"], run["revision_dir"],
                request.attempt_id, False, stamp)
            for other in run["artifacts"].values():
                if other["root"] == artifact["root"] and other["path"] == artifact["path"]:
                    raise contracts.DuplicateIdentityError(
                        "artifact path %r/%r already registered as %r"
                        % (artifact["root"], artifact["path"], other["artifact_id"]))
            run["artifacts"][aid] = artifact
        run["attempts"][request.attempt_id] = attempt
        contracts.enforce_stage_contract(attempt, run["artifacts"], run["narration_enabled"])
        return run

    return mutate


def execute_timing(request: TimingExecutionRequest) -> Dict:
    """Execute the timing stage for an explicit request.

    Raises a contract error on validation/lock failure (no attempt/artifact
    written). Returns a result dict; on execution failure a terminal ``failed``
    receipt is recorded and ``status`` is ``"failed"``.
    """
    plan = _prepare(request)
    lock = manifest.FileLock(execution_lock_path(plan["ws"], request.project_id, request.run_id))
    with lock:
        # Re-verify uniqueness under the lock (TOCTOU-safe).
        run = manifest.load_run(plan["ws"], request.project_id, request.run_id)
        if request.attempt_id in run["attempts"]:
            raise contracts.DuplicateIdentityError(
                "attempt_id %r already recorded" % request.attempt_id)
        for aid in (plan["timing_artifact_id"], plan["captions_artifact_id"]):
            if aid is not None and aid in run["artifacts"]:
                raise contracts.DuplicateIdentityError("artifact_id %r already registered" % aid)
        for dest in (plan["timing_dest"], plan["captions_dest"]):
            if dest is not None and os.path.exists(dest):
                raise ExecutionError("refusing to overwrite existing output: %s" % dest)

        started_at = _now()
        started_mono = time.monotonic()
        written: List[str] = []
        try:
            timing_doc = execution_process.normalize_timing(
                request.provider, plan["provider_response_path"], request.audio_duration_ms)
            written.append(execution_process.write_json_atomic(plan["timing_dest"], timing_doc))
            if plan["captions_dest"] is not None:
                captions_doc = execution_process.phrase_captions(timing_doc)
                written.append(execution_process.write_json_atomic(plan["captions_dest"],
                                                                   captions_doc))
            execution_process.ensure_within_deadline(started_mono, plan["timeout"])
        except Exception as exc:  # execution failure -> failed receipt, no output artifacts
            for path in written:
                execution_process.remove_file(path)
            ended_at = _now()
            manifest.record_attempt(
                plan["ws"], request.project_id, request.run_id, request.attempt_id,
                "timing", request.origin, "failed",
                input_artifact_ids=list(plan["input_ids"]),
                output_artifact_ids=[],
                started_at=started_at, ended_at=ended_at,
                error=_short(exc), provider=request.provider, tool=DEFAULT_TOOL,
                model=None, usage=None, created_at=request.created_at or ended_at)
            return {
                "status": "failed",
                "stage_id": "timing",
                "attempt_id": request.attempt_id,
                "error": _short(exc),
                "output_artifacts": [],
            }

        ended_at = _now()
        try:
            manifest.mutate_run(plan["ws"], request.project_id, request.run_id,
                                _mutate_success(plan, request, started_at, ended_at))
        except BaseException:
            # Never leave output files without a receipt.
            for path in written:
                execution_process.remove_file(path)
            raise
        outputs = [{"artifact_id": plan["timing_artifact_id"], "kind": "timing",
                    "path": plan["timing_rel_path"]}]
        if plan["captions_artifact_id"] is not None:
            outputs.append({"artifact_id": plan["captions_artifact_id"], "kind": "caption",
                            "path": plan["captions_rel_path"]})
        return {
            "status": "succeeded",
            "stage_id": "timing",
            "attempt_id": request.attempt_id,
            "output_artifacts": outputs,
            "provider": request.provider,
        }


# ---------------------------------------------------------------- CLI wiring

def cmd_timing_execute(args) -> int:
    request = TimingExecutionRequest(
        workspace=args.workspace or manifest.DEFAULT_WORKSPACE,
        project_id=args.project_id,
        run_id=args.run_id,
        attempt_id=args.attempt_id,
        input_artifact_ids=tuple(args.input or ()),
        provider_response_artifact_id=args.provider_response_artifact,
        provider=args.provider,
        stage_id="timing",
        output_timing_artifact_id=args.output_timing_artifact,
        output_timing_path=args.output_timing_path,
        output_captions_artifact_id=args.output_captions_artifact,
        output_captions_path=args.output_captions_path,
        audio_duration_ms=args.audio_duration_ms,
        timeout_seconds=args.timeout,
        origin=args.origin,
        confirm=args.confirm,
        created_at=args.at,
    )
    result = execute_timing(request)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "succeeded" else 1


def register_subcommands(sub) -> None:
    p = sub.add_parser(
        "timing-execute",
        help="managed, local-only execution of the timing stage (Unit B, Increment 1)")
    p.add_argument("--project-id", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--attempt-id", required=True,
                   help="explicit new attempt id for the terminal receipt")
    p.add_argument("--input", action="append", default=None,
                   help="explicit registered input artifact id (repeatable)")
    p.add_argument("--provider-response-artifact", required=True,
                   help="registered artifact holding the raw provider timing response")
    p.add_argument("--provider", default=DEFAULT_PROVIDER)
    p.add_argument("--audio-duration-ms", type=int, default=None)
    p.add_argument("--output-timing-artifact", required=True)
    p.add_argument("--output-timing-path", required=True,
                   help="revision-relative path for the canonical word-timings file")
    p.add_argument("--output-captions-artifact", default=None)
    p.add_argument("--output-captions-path", default=None,
                   help="revision-relative path for the caption file (optional)")
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--origin", default="human", choices=sorted(contracts.ATTEMPT_ORIGINS))
    p.add_argument("--confirm", action="store_true",
                   help="required confirmation for a mutating execution")
    p.add_argument("--at", default=None, help="explicit recorded_at timestamp")
    p.add_argument("--workspace", default=None, help="workspace root (default: repository root)")
    p.set_defaults(func=cmd_timing_execute)
