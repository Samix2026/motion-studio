"""Project/run manifest store: explicit registration and atomic persistence.

Standard-library only. Every write is atomic (temporary file + replacement) and
guarded by a per-record lock created with ``O_CREAT | O_EXCL``. Locks are never
stolen and no crash recovery is attempted. Inspecting a manifest never writes.
Recorded attempts are immutable at the persistence boundary: corrections append
a new (optionally superseding) attempt. Nothing here runs a provider, renderer,
shell, or network call.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from studio import artifacts, contracts

DEFAULT_WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIRNAME = "runs"
PROJECTS_DIRNAME = "projects"
MANIFESTS_DIRNAME = "manifests"
LOCKS_DIRNAME = ".locks"
_RUN_CONTEXT_FIELDS = (
    "run_id", "project_id", "revision", "revision_dir",
    "workflow_contract_version", "narration_enabled",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _workspace(workspace: str) -> str:
    ws = os.path.realpath(workspace)
    if not os.path.isdir(ws):
        raise contracts.PathSafetyError("workspace does not exist: %s" % workspace)
    return ws


def _reject_symlink_components(base: str, target: str) -> None:
    if os.path.islink(base):
        raise contracts.PathSafetyError("refusing symlinked recorder storage")
    relative = os.path.relpath(target, base)
    if relative == ".":
        return
    current = base
    for part in relative.split(os.sep):
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise contracts.PathSafetyError("refusing symlinked recorder storage")


def _storage_path(workspace: str, *parts: str) -> str:
    if not parts:
        raise contracts.PathSafetyError("recorder storage path requires a root component")
    ws = _workspace(workspace)
    runs_dir = os.path.join(ws, RUNS_DIRNAME)
    lexical = os.path.join(runs_dir, *parts)
    _reject_symlink_components(runs_dir, lexical)
    root_dir = os.path.join(runs_dir, parts[0])
    real_root = os.path.realpath(root_dir)
    candidate = os.path.realpath(lexical)
    artifacts.assert_within(real_root, candidate)
    artifacts.assert_within(ws, candidate)
    artifacts.assert_allowed_path(candidate, ws)
    return candidate


def _lock_name(*parts: str) -> str:
    digest = hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()
    return "%s.lock" % digest[:32]


def projects_dir(workspace: str) -> str:
    return _storage_path(workspace, PROJECTS_DIRNAME)


def manifests_dir(workspace: str) -> str:
    return _storage_path(workspace, MANIFESTS_DIRNAME)


def locks_dir(workspace: str) -> str:
    return _storage_path(workspace, LOCKS_DIRNAME)


def project_path(workspace: str, project_id: str) -> str:
    contracts.validate_fs_id(project_id, "project_id")
    return _storage_path(workspace, PROJECTS_DIRNAME, "%s.json" % project_id)


def manifest_path(workspace: str, project_id: str, run_id: str) -> str:
    contracts.validate_fs_id(project_id, "project_id")
    contracts.validate_fs_id(run_id, "run_id")
    return _storage_path(workspace, MANIFESTS_DIRNAME, project_id, "%s.json" % run_id)


def run_lock_path(workspace: str, project_id: str, run_id: str) -> str:
    contracts.validate_fs_id(project_id, "project_id")
    contracts.validate_fs_id(run_id, "run_id")
    return _storage_path(workspace, LOCKS_DIRNAME, _lock_name("run", project_id, run_id))


def registry_lock_path(workspace: str) -> str:
    return _storage_path(workspace, LOCKS_DIRNAME, _lock_name("registry"))


def load_json_strict(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        raise contracts.MalformedRecordError("%s is not valid JSON" % path)
    if not isinstance(parsed, dict):
        raise contracts.MalformedRecordError("%s must contain a JSON object" % path)
    return parsed


def atomic_write_json(path: str, doc: Dict) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            try:
                json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            except ValueError:
                raise contracts.MalformedRecordError(
                    "record contains a non-finite number and was not written")
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class FileLock:
    """Single-writer lock. Existing locks are never stolen or aged out."""

    def __init__(self, path: str):
        self.path = path
        self._held = False

    def acquire(self) -> "FileLock":
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raise contracts.ConcurrentWriterError(
                "another writer holds the lock; confirm the writer is inactive before manual removal")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "acquired_at": _now()}, fh)
        self._held = True
        return self

    def release(self) -> None:
        if not self._held:
            return
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        self._held = False

    def __enter__(self) -> "FileLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def load_project(workspace: str, project_id: str) -> Optional[Dict]:
    contracts.validate_fs_id(project_id, "project_id")
    path = project_path(workspace, project_id)
    if not os.path.isfile(path):
        return None
    doc = load_json_strict(path)
    contracts.validate_project(doc)
    if doc["project_id"] != project_id:
        raise contracts.MalformedRecordError(
            "project record identity does not match its storage path")
    return doc


def _iter_projects(workspace: str) -> List[Dict]:
    ws = _workspace(workspace)
    directory = projects_dir(ws)
    if not os.path.isdir(directory):
        return []
    found = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        stem = name[:-5]
        contracts.validate_fs_id(stem, "project_id")
        doc = load_project(ws, stem)
        if doc is not None:
            found.append(doc)
    return found


def register_project(workspace: str, project_id: str, project_dir: str,
                     revision: Optional[str] = None,
                     parent_revision: Optional[str] = None,
                     created_at: Optional[str] = None, must_exist: bool = True) -> Dict:
    ws = _workspace(workspace)
    contracts.validate_fs_id(project_id, "project_id")
    revision = _optional_id(revision, "revision")
    parent_revision = _optional_id(parent_revision, "parent_revision")
    rel_dir = artifacts.normalize_project_dir(ws, project_dir, must_exist=must_exist)
    projects_dir(ws)
    project_path(ws, project_id)
    with FileLock(registry_lock_path(ws)):
        existing = load_project(ws, project_id)
        if existing is not None:
            raise contracts.DuplicateIdentityError(
                "project_id %r is already registered at %r"
                % (project_id, existing["project_dir"]))
        for other in _iter_projects(ws):
            if other["project_dir"] == rel_dir and other["project_id"] != project_id:
                raise contracts.DuplicateIdentityError(
                    "project dir %r is already registered as %r"
                    % (rel_dir, other["project_id"]))
        doc = {
            "schema_version": contracts.PROJECT_SCHEMA_VERSION,
            "project_id": project_id,
            "project_dir": rel_dir,
            "revision": revision,
            "parent_revision": parent_revision,
            "created_at": created_at or _now(),
        }
        contracts.validate_project(doc)
        atomic_write_json(project_path(ws, project_id), doc)
    return doc


def load_run(workspace: str, project_id: str, run_id: str) -> Dict:
    contracts.validate_fs_id(project_id, "project_id")
    contracts.validate_fs_id(run_id, "run_id")
    path = manifest_path(workspace, project_id, run_id)
    if not os.path.isfile(path):
        raise contracts.UnknownReferenceError(
            "run manifest not found: %s/%s" % (project_id, run_id))
    doc = load_json_strict(path)
    if doc.get("project_id") != project_id or doc.get("run_id") != run_id:
        raise contracts.MalformedRecordError(
            "run record identity does not match its storage path")
    contracts.validate_run(doc)
    validate_run_structure(doc)
    return doc


def create_run(workspace: str, project_id: str, run_id: str, revision: str,
               revision_dir: str,
               workflow_contract_version: str = contracts.WORKFLOW_CONTRACT_VERSION,
               narration_enabled: bool = False,
               created_at: Optional[str] = None) -> Dict:
    ws = _workspace(workspace)
    contracts.validate_fs_id(project_id, "project_id")
    contracts.validate_fs_id(run_id, "run_id")
    if not isinstance(revision, str) or not revision:
        raise contracts.MalformedRecordError("run revision must be a non-empty string")
    if workflow_contract_version not in contracts.SUPPORTED_WORKFLOW_CONTRACT_VERSIONS:
        raise contracts.SchemaVersionError(
            "unsupported workflow contract version %r" % workflow_contract_version)
    if load_project(ws, project_id) is None:
        raise contracts.UnknownReferenceError("project %r is not registered" % project_id)
    rel_rev = artifacts.normalize_project_dir(ws, revision_dir, must_exist=True)
    path = manifest_path(ws, project_id, run_id)
    with FileLock(run_lock_path(ws, project_id, run_id)):
        if os.path.exists(path):
            raise contracts.DuplicateIdentityError(
                "run_id %r already exists for project %r" % (run_id, project_id))
        doc = {
            "schema_version": contracts.RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "project_id": project_id,
            "revision": revision,
            "revision_dir": rel_rev,
            "created_at": created_at or _now(),
            "workflow_contract_version": workflow_contract_version,
            "narration_enabled": bool(narration_enabled),
            "attempts": {},
            "artifacts": {},
            "validations": {},
            "historical_references": [],
        }
        validate_run_structure(doc)
        atomic_write_json(path, doc)
    return doc


def _enforce_attempt_immutability(prior_attempts: Dict, result_attempts: Dict) -> None:
    for attempt_id, prior in prior_attempts.items():
        if attempt_id not in result_attempts:
            raise contracts.ImmutabilityError(
                "attempt %r cannot be deleted; append a superseding attempt" % attempt_id)
        if result_attempts[attempt_id] != prior:
            raise contracts.ImmutabilityError(
                "attempt %r cannot be modified; append a superseding attempt" % attempt_id)


def _enforce_run_context_immutability(prior_context: Dict, result: Dict) -> None:
    for field in _RUN_CONTEXT_FIELDS:
        if result.get(field) != prior_context[field]:
            raise contracts.ImmutabilityError(
                "run context field %r is immutable after creation; create a new run" % field)


def mutate_run(workspace: str, project_id: str, run_id: str,
               mutate: Callable[[Dict], Dict]) -> Dict:
    ws = _workspace(workspace)
    path = manifest_path(ws, project_id, run_id)
    with FileLock(run_lock_path(ws, project_id, run_id)):
        prior = load_run(ws, project_id, run_id)
        prior_attempts = json.loads(json.dumps(prior["attempts"]))
        prior_context = {field: prior.get(field) for field in _RUN_CONTEXT_FIELDS}
        result = mutate(prior)
        if not isinstance(result, dict):
            raise contracts.MalformedRecordError("mutation returned a non-object record")
        _enforce_run_context_immutability(prior_context, result)
        _enforce_attempt_immutability(prior_attempts, result.get("attempts", {}))
        validate_run_structure(result)
        atomic_write_json(path, result)
    return result


def register_artifact(workspace: str, project_id: str, run_id: str, artifact_id: str,
                      kind: str, root: str, rel_path: str,
                      producer_attempt_id: Optional[str] = None,
                      legacy_external: bool = False,
                      historical: bool = False,
                      historical_note: Optional[str] = None,
                      created_at: Optional[str] = None) -> Dict:
    ws = _workspace(workspace)
    contracts.validate_fs_id(artifact_id, "artifact_id")
    stamp = created_at or _now()

    def _mutate(run: Dict) -> Dict:
        if load_project(ws, project_id) is None:
            raise contracts.UnknownReferenceError("project %r is not registered" % project_id)
        if artifact_id in run["artifacts"]:
            raise contracts.DuplicateIdentityError("artifact_id %r already registered" % artifact_id)
        if legacy_external and producer_attempt_id:
            raise contracts.ContractError(
                "legacy artifact %r cannot name a producer attempt" % artifact_id)
        if not legacy_external and not producer_attempt_id:
            raise contracts.ContractError(
                "artifact %r requires a producer_attempt_id or legacy_external" % artifact_id)
        if producer_attempt_id and producer_attempt_id not in run["attempts"]:
            raise contracts.UnknownReferenceError(
                "producer attempt %r is not recorded" % producer_attempt_id)
        if producer_attempt_id and artifact_id not in run["attempts"][producer_attempt_id]["output_artifact_ids"]:
            raise contracts.ContractError(
                "artifact %r is not listed as an output of producer attempt %r"
                % (artifact_id, producer_attempt_id))
        artifact = artifacts.build_artifact(
            artifact_id, kind, root, rel_path, ws, run["revision_dir"],
            producer_attempt_id, legacy_external, stamp)
        for other in run["artifacts"].values():
            if other["root"] == artifact["root"] and other["path"] == artifact["path"]:
                raise contracts.DuplicateIdentityError(
                    "artifact path %r/%r already registered as %r"
                    % (artifact["root"], artifact["path"], other["artifact_id"]))
        run["artifacts"][artifact_id] = artifact
        if historical:
            run["historical_references"].append({
                "reference_id": artifact_id,
                "kind": kind,
                "root": artifact["root"],
                "path": artifact["path"],
                "sha256": artifact["sha256"],
                "note": historical_note,
                "recorded_at": stamp,
            })
        return run

    return mutate_run(ws, project_id, run_id, _mutate)


def record_attempt(workspace: str, project_id: str, run_id: str, attempt_id: str,
                   stage_id: str, origin: str, reported_execution_outcome: str,
                   input_artifact_ids: Optional[List[str]] = None,
                   output_artifact_ids: Optional[List[str]] = None,
                   started_at: Optional[str] = None, ended_at: Optional[str] = None,
                   error: Optional[str] = None, provider: Optional[str] = None,
                   tool: Optional[str] = None, model: Optional[str] = None,
                   usage: Optional[Dict] = None,
                   supersedes: Optional[str] = None,
                   stage_contract_version: Optional[str] = None,
                   created_at: Optional[str] = None) -> Dict:
    ws = _workspace(workspace)
    contracts.validate_fs_id(attempt_id, "attempt_id")
    contracts.stage_contract(stage_id)
    version = stage_contract_version or contracts.STAGE_CONTRACT_VERSION
    if version not in contracts.SUPPORTED_STAGE_CONTRACT_VERSIONS:
        raise contracts.SchemaVersionError("unsupported stage contract version %r" % version)
    normalized_usage = contracts.normalize_usage(usage)

    def _mutate(run: Dict) -> Dict:
        if attempt_id in run["attempts"]:
            raise contracts.DuplicateIdentityError("attempt_id %r already recorded" % attempt_id)
        if supersedes is not None:
            if supersedes == attempt_id:
                raise contracts.ContractError("attempt %r cannot supersede itself" % attempt_id)
            if supersedes not in run["attempts"]:
                raise contracts.UnknownReferenceError("superseded attempt %r is not recorded" % supersedes)
        inputs = list(input_artifact_ids or [])
        outputs = list(output_artifact_ids or [])
        for ref in inputs:
            if ref not in run["artifacts"]:
                raise contracts.UnknownReferenceError("input artifact %r is not registered" % ref)
        attempt = {
            "schema_version": contracts.ATTEMPT_SCHEMA_VERSION,
            "attempt_id": attempt_id,
            "stage_id": stage_id,
            "stage_contract_version": version,
            "origin": origin,
            "reported_execution_outcome": reported_execution_outcome,
            "input_artifact_ids": inputs,
            "output_artifact_ids": outputs,
            "started_at": started_at,
            "ended_at": ended_at,
            "error": error,
            "provider": provider,
            "tool": tool,
            "model": model,
            "usage": normalized_usage,
            "supersedes": supersedes,
            "recorded_at": created_at or _now(),
        }
        contracts.validate_attempt(attempt)
        run["attempts"][attempt_id] = attempt
        return run

    return mutate_run(ws, project_id, run_id, _mutate)


def record_validation(workspace: str, project_id: str, run_id: str, validation_id: str,
                      validator: str, validator_version: str, evidence_ref: str,
                      evidence_artifact_id: str, result: str, scope: str,
                      subject_artifact_ids: Optional[List[str]] = None,
                      created_at: Optional[str] = None) -> Dict:
    ws = _workspace(workspace)
    contracts.validate_fs_id(validation_id, "validation_id")
    contracts.validate_fs_id(evidence_artifact_id, "evidence_artifact_id")

    def _mutate(run: Dict) -> Dict:
        if validation_id in run["validations"]:
            raise contracts.DuplicateIdentityError("validation_id %r already recorded" % validation_id)
        if evidence_artifact_id not in run["artifacts"]:
            raise contracts.UnknownReferenceError(
                "validation evidence artifact %r is not registered" % evidence_artifact_id)
        subjects = list(subject_artifact_ids or [])
        for ref in subjects:
            if ref not in run["artifacts"]:
                raise contracts.UnknownReferenceError("validation subject %r is not registered" % ref)
        validation = {
            "schema_version": contracts.VALIDATION_SCHEMA_VERSION,
            "validation_id": validation_id,
            "validator": validator,
            "validator_version": validator_version,
            "evidence_ref": evidence_ref,
            "evidence_artifact_id": evidence_artifact_id,
            "result": result,
            "scope": scope,
            "subject_artifact_ids": subjects,
            "created_at": created_at or _now(),
        }
        contracts.validate_validation(validation)
        run["validations"][validation_id] = validation
        return run

    return mutate_run(ws, project_id, run_id, _mutate)


def historical_reference(workspace: str, project_id: str, run_id: str, reference_id: str,
                         root: str, rel_path: str, note: Optional[str] = None,
                         created_at: Optional[str] = None) -> Dict:
    return register_artifact(
        workspace, project_id, run_id, reference_id, "legacy_run_summary", root, rel_path,
        producer_attempt_id=None, legacy_external=True, historical=True,
        historical_note=note, created_at=created_at)


def validate_run_structure(run: Dict) -> Dict:
    contracts.validate_run(run)
    for key, artifact in run["artifacts"].items():
        contracts.validate_artifact(artifact)
        if artifact["artifact_id"] != key:
            raise contracts.MalformedRecordError(
                "artifact key %r does not match artifact_id %r" % (key, artifact["artifact_id"]))
    for key, attempt in run["attempts"].items():
        contracts.validate_attempt(attempt)
        if attempt["attempt_id"] != key:
            raise contracts.MalformedRecordError(
                "attempt key %r does not match attempt_id %r" % (key, attempt["attempt_id"]))
    for key, validation in run["validations"].items():
        contracts.validate_validation(validation)
        if validation["validation_id"] != key:
            raise contracts.MalformedRecordError(
                "validation key %r does not match validation_id %r"
                % (key, validation["validation_id"]))
    for reference in run["historical_references"]:
        contracts.validate_historical_reference(reference)
    return run


def _supersession_cycle(attempts: Dict) -> List[str]:
    color: Dict[str, int] = {}

    def visit(node: str) -> Optional[List[str]]:
        color[node] = 1
        target = attempts[node].get("supersedes")
        if target in attempts and target != node:
            if color.get(target) == 1:
                return [target, node]
            if color.get(target, 0) == 0:
                found = visit(target)
                if found:
                    return found
        color[node] = 2
        return None

    for node in attempts:
        if color.get(node, 0) == 0:
            found = visit(node)
            if found:
                return found
    return []


def validate_run_manifest(run: Dict, narration_enabled: Optional[bool] = None,
                          workspace: Optional[str] = None) -> Dict:
    validate_run_structure(run)
    narration = run["narration_enabled"] if narration_enabled is None else narration_enabled
    attempts = run["attempts"]
    artifacts = run["artifacts"]
    for key, artifact in artifacts.items():
        producer = artifact["producer_attempt_id"]
        if producer and producer not in attempts:
            raise contracts.UnknownReferenceError(
                "artifact %r names producer attempt %r that is not recorded" % (key, producer))
        if producer and key not in attempts[producer]["output_artifact_ids"]:
            raise contracts.ContractError(
                "artifact %r declares producer %r but is not among its outputs" % (key, producer))
    for key, attempt in attempts.items():
        supersedes = attempt.get("supersedes")
        if supersedes == key:
            raise contracts.ContractError("attempt %r supersedes itself" % key)
        if supersedes is not None and supersedes not in attempts:
            raise contracts.UnknownReferenceError(
                "attempt %r supersedes attempt %r that is not recorded" % (key, supersedes))
        for ref in attempt["input_artifact_ids"]:
            if ref not in artifacts:
                raise contracts.UnknownReferenceError(
                    "attempt %r references input artifact %r that is not registered" % (key, ref))
        for ref in attempt["output_artifact_ids"]:
            if ref not in artifacts:
                raise contracts.UnknownReferenceError(
                    "attempt %r references output artifact %r that is not registered" % (key, ref))
            output = artifacts[ref]
            if output["producer_attempt_id"] != key:
                raise contracts.ContractError(
                    "attempt %r claims output %r whose producer reference disagrees" % (key, ref))
        contracts.enforce_stage_contract(attempt, artifacts, narration)
    cycle = _supersession_cycle(attempts)
    if cycle:
        raise contracts.ContractError("supersession cycle detected: %s" % ", ".join(cycle))
    for key, validation in run["validations"].items():
        evidence_id = validation["evidence_artifact_id"]
        if evidence_id not in artifacts:
            raise contracts.UnknownReferenceError(
                "validation %r evidence artifact %r is not registered" % (key, evidence_id))
        for ref in validation.get("subject_artifact_ids", []):
            if ref not in artifacts:
                raise contracts.UnknownReferenceError(
                    "validation %r references artifact %r that is not registered" % (key, ref))
    for reference in run["historical_references"]:
        ref_id = reference.get("reference_id")
        artifact = artifacts.get(ref_id)
        if artifact is None:
            raise contracts.UnknownReferenceError(
                "historical reference %r is not a registered artifact" % ref_id)
        if not artifact.get("legacy_external"):
            raise contracts.ContractError(
                "historical reference %r must be a legacy_external artifact" % ref_id)
        for field in ("kind", "root", "path", "sha256"):
            if reference.get(field) != artifact.get(field):
                raise contracts.ContractError(
                    "historical reference %r disagrees with its artifact on %r" % (ref_id, field))
    if workspace is not None:
        _verify_validation_evidence(workspace, run)
    return run


def _verify_validation_evidence(workspace: str, run: Dict) -> None:
    for key, validation in run["validations"].items():
        artifact = run["artifacts"][validation["evidence_artifact_id"]]
        report = artifacts.check_artifact(artifact, workspace, run["revision_dir"])
        if report["state"] != "ok":
            raise contracts.ContractError(
                "validation %r evidence %r is %s" % (key, artifact["artifact_id"], report["state"]))


def _unresolved_reference_ids(run: Dict) -> List[str]:
    attempts = run["attempts"]
    artifacts = run["artifacts"]
    unresolved = set()
    for attempt in attempts.values():
        for ref in attempt["input_artifact_ids"] + attempt["output_artifact_ids"]:
            if ref not in artifacts:
                unresolved.add(ref)
        supersedes = attempt.get("supersedes")
        if supersedes is not None and supersedes not in attempts:
            unresolved.add(supersedes)
    for artifact in artifacts.values():
        producer = artifact["producer_attempt_id"]
        if producer and producer not in attempts:
            unresolved.add(producer)
    for validation in run["validations"].values():
        evidence_id = validation.get("evidence_artifact_id")
        if evidence_id and evidence_id not in artifacts:
            unresolved.add(evidence_id)
        for ref in validation.get("subject_artifact_ids", []):
            if ref not in artifacts:
                unresolved.add(ref)
    for reference in run["historical_references"]:
        ref_id = reference.get("reference_id")
        if ref_id not in artifacts:
            unresolved.add(ref_id)
    return sorted(unresolved)


def _relationship_issues(run: Dict) -> List[Tuple[frozenset, str]]:
    attempts = run["attempts"]
    artifacts = run["artifacts"]
    issues: List[Tuple[frozenset, str]] = []
    for key, attempt in attempts.items():
        for out_id in attempt["output_artifact_ids"]:
            output = artifacts.get(out_id)
            if output is None:
                continue
            if output["producer_attempt_id"] != key:
                issues.append((frozenset({key, out_id}),
                               "attempt %s claims output %s whose producer reference disagrees"
                               % (key, out_id)))
    for key, artifact in artifacts.items():
        producer = artifact["producer_attempt_id"]
        if producer is None or producer not in attempts:
            continue
        if key not in attempts[producer]["output_artifact_ids"]:
            issues.append((frozenset({producer, key}),
                           "artifact %s declares producer %s but is not among its outputs"
                           % (key, producer)))
    for key, attempt in attempts.items():
        supersedes = attempt.get("supersedes")
        if supersedes == key:
            issues.append((frozenset({key}), "attempt %s supersedes itself" % key))
    cycle = _supersession_cycle(attempts)
    if cycle:
        issues.append((frozenset(cycle), "supersession cycle detected: %s" % ", ".join(cycle)))
    for reference in run["historical_references"]:
        if not isinstance(reference, dict):
            issues.append((frozenset(), "historical reference is not an object"))
            continue
        ref_id = reference.get("reference_id")
        artifact = artifacts.get(ref_id)
        if artifact is None:
            continue
        if not artifact.get("legacy_external"):
            issues.append((frozenset(), "historical reference %s must be legacy_external" % ref_id))
            continue
        for field in ("kind", "root", "path", "sha256"):
            if reference.get(field) != artifact.get(field):
                issues.append((frozenset(),
                               "historical reference %s disagrees with its artifact on %s"
                               % (ref_id, field)))
    return issues


def _stage_contract_issues(run: Dict) -> List[Tuple[frozenset, str]]:
    issues: List[Tuple[frozenset, str]] = []
    for key, attempt in run["attempts"].items():
        try:
            contracts.enforce_stage_contract(attempt, run["artifacts"], run["narration_enabled"])
        except contracts.ContractError as exc:
            issues.append((frozenset({key}), str(exc)))
    return issues


def inspect_run(workspace: str, project_id: str, run_id: str) -> Dict:
    ws = _workspace(workspace)
    run = load_run(ws, project_id, run_id)
    unresolved = _unresolved_reference_ids(run)
    relationship_issues = _relationship_issues(run)
    contract_issues = _stage_contract_issues(run)
    related_bad = set()
    for ids, _message in relationship_issues:
        related_bad |= set(ids)
    contract_bad = set()
    for ids, _message in contract_issues:
        contract_bad |= set(ids)
    artifact_reports = {
        artifact["artifact_id"]: artifacts.check_artifact(artifact, ws, run["revision_dir"])
        for artifact in run["artifacts"].values()
    }
    attempts = []
    for attempt in run["attempts"].values():
        attempt_id = attempt["attempt_id"]
        unresolved_inputs = [r for r in attempt["input_artifact_ids"] if r not in run["artifacts"]]
        unresolved_outputs = [r for r in attempt["output_artifact_ids"] if r not in run["artifacts"]]
        terminal = attempt["reported_execution_outcome"] not in contracts.NON_TERMINAL_OUTCOMES
        resolved = not unresolved_inputs and not unresolved_outputs
        relationship_ok = attempt_id not in related_bad
        contract_ok = attempt_id not in contract_bad
        attempts.append({
            "attempt_id": attempt_id,
            "stage_id": attempt["stage_id"],
            "origin": attempt["origin"],
            "reported_execution_outcome": attempt["reported_execution_outcome"],
            "terminal": terminal,
            "resolved": resolved,
            "relationship_ok": relationship_ok,
            "stage_contract_ok": contract_ok,
            "complete": terminal and resolved and relationship_ok and contract_ok,
            "supersedes": attempt.get("supersedes"),
            "unresolved_input_ids": unresolved_inputs,
            "unresolved_output_ids": unresolved_outputs,
            "provider": attempt.get("provider"),
            "tool": attempt.get("tool"),
            "model": attempt.get("model"),
            "usage": attempt.get("usage"),
        })
    validations = []
    for validation in run["validations"].values():
        evidence_id = validation["evidence_artifact_id"]
        evidence = artifact_reports.get(evidence_id)
        validations.append({
            "validation_id": validation["validation_id"],
            "validator": validation["validator"],
            "validator_version": validation["validator_version"],
            "result": validation["result"],
            "scope": validation["scope"],
            "evidence_ref": validation["evidence_ref"],
            "evidence_artifact_id": evidence_id,
            "evidence_state": evidence["state"] if evidence else "unregistered",
        })
    historical = [
        dict(reference, verification_state="historical_reference_only")
        for reference in run["historical_references"]
    ]
    reference_resolution = not unresolved
    relationship_validity = not relationship_issues
    stage_contract_validity = not contract_issues
    complete = (reference_resolution and relationship_validity and stage_contract_validity
                and all(a["complete"] for a in attempts))
    return {
        "run_id": run["run_id"],
        "project_id": run["project_id"],
        "revision": run["revision"],
        "revision_dir": run["revision_dir"],
        "created_at": run["created_at"],
        "workflow_contract_version": run["workflow_contract_version"],
        "narration_enabled": run["narration_enabled"],
        "structural_validity": True,
        "reference_resolution": reference_resolution,
        "reference_validity": reference_resolution,
        "relationship_validity": relationship_validity,
        "stage_contract_validity": stage_contract_validity,
        "unresolved_reference_ids": unresolved,
        "relationship_issues": [message for _ids, message in relationship_issues],
        "stage_contract_issues": [message for _ids, message in contract_issues],
        "complete": complete,
        "attempts": attempts,
        "artifacts": list(artifact_reports.values()),
        "validations": validations,
        "historical_references": historical,
        "totals": {
            "attempts": len(attempts),
            "artifacts": len(artifact_reports),
            "artifacts_ok": sum(1 for a in artifact_reports.values() if a["state"] == "ok"),
            "artifacts_missing": sum(1 for a in artifact_reports.values() if a["state"] == "missing"),
            "artifacts_changed": sum(1 for a in artifact_reports.values() if a["state"] == "changed"),
            "validations": len(validations),
            "unresolved_references": len(unresolved),
        },
    }


def list_runs(workspace: str, project_id: Optional[str] = None) -> List[Dict]:
    ws = _workspace(workspace)
    base = manifests_dir(ws)
    if not os.path.isdir(base):
        return []
    if project_id is not None:
        contracts.validate_fs_id(project_id, "project_id")
        projects = [project_id]
    else:
        projects = sorted(name for name in os.listdir(base)
                          if os.path.isdir(os.path.join(base, name)))
    summaries = []
    for pid in projects:
        contracts.validate_fs_id(pid, "project_id")
        directory = _storage_path(ws, MANIFESTS_DIRNAME, pid)
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".json"):
                continue
            rid = name[:-5]
            contracts.validate_fs_id(rid, "run_id")
            run = load_run(ws, pid, rid)
            summaries.append({
                "project_id": run["project_id"],
                "run_id": run["run_id"],
                "revision": run["revision"],
                "revision_dir": run["revision_dir"],
                "created_at": run["created_at"],
                "attempts": len(run["attempts"]),
                "artifacts": len(run["artifacts"]),
                "validations": len(run["validations"]),
            })
    return summaries


def _optional_id(value: Optional[str], label: str) -> Optional[str]:
    if value is None:
        return None
    return contracts.validate_fs_id(value, label)
