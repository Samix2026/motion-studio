"""Phase 1 recording contracts: schemas, validators, and errors.

Additive and standard-library only. A record written under ``runs/projects/``
or ``runs/manifests/`` asserts only what was explicitly recorded. Nothing here
implies generation, reported execution success, validation success, creative
approval, cost approval, publication approval, or final readiness.
"""

from __future__ import annotations

import math
import os
import re
from typing import Any, Dict, List, Optional

PROJECT_SCHEMA_VERSION = 1
RUN_SCHEMA_VERSION = 1
ATTEMPT_SCHEMA_VERSION = 1
ARTIFACT_SCHEMA_VERSION = 1
VALIDATION_SCHEMA_VERSION = 1

WORKFLOW_CONTRACT_VERSION = "workflow-contract-1"
STAGE_CONTRACT_VERSION = "stage-contract-1"

SUPPORTED_WORKFLOW_CONTRACT_VERSIONS = frozenset({WORKFLOW_CONTRACT_VERSION})
SUPPORTED_STAGE_CONTRACT_VERSIONS = frozenset({STAGE_CONTRACT_VERSION})

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ARTIFACT_KINDS = frozenset({
    "generated_asset", "composition", "render", "narration", "audio",
    "timing", "caption", "script", "validation_evidence", "legacy_run_summary",
    "other",
})
ARTIFACT_ROOTS = frozenset({"workspace", "project"})
ATTEMPT_ORIGINS = frozenset({"external", "human", "imported"})
ATTEMPT_OUTCOMES = frozenset({"started", "succeeded", "failed", "cancelled", "unknown"})
NON_TERMINAL_OUTCOMES = frozenset({"started"})
VALIDATION_RESULTS = frozenset({"passed", "failed", "unknown", "not_run"})

STAGE_CONTRACTS = {
    "generation": {
        "stage_id": "generation",
        "stage_contract_version": STAGE_CONTRACT_VERSION,
        "required_input_kinds": (),
        "required_input_when_narrated": (),
        "required_output_kinds": ("generated_asset",),
    },
    "narration": {
        "stage_id": "narration",
        "stage_contract_version": STAGE_CONTRACT_VERSION,
        "required_input_kinds": (),
        "required_input_when_narrated": (),
        "required_output_kinds": ("narration",),
    },
    "audio": {
        "stage_id": "audio",
        "stage_contract_version": STAGE_CONTRACT_VERSION,
        "required_input_kinds": (),
        "required_input_when_narrated": (),
        "required_output_kinds": ("audio",),
    },
    "composition": {
        "stage_id": "composition",
        "stage_contract_version": STAGE_CONTRACT_VERSION,
        "required_input_kinds": (),
        "required_input_when_narrated": ("narration",),
        "required_output_kinds": ("composition",),
    },
    "timing": {
        "stage_id": "timing",
        "stage_contract_version": STAGE_CONTRACT_VERSION,
        "required_input_kinds": ("narration",),
        "required_input_when_narrated": (),
        "required_output_kinds": ("timing",),
    },
    "render": {
        "stage_id": "render",
        "stage_contract_version": STAGE_CONTRACT_VERSION,
        "required_input_kinds": ("composition",),
        "required_input_when_narrated": (),
        "required_output_kinds": ("render",),
    },
    "validation": {
        "stage_id": "validation",
        "stage_contract_version": STAGE_CONTRACT_VERSION,
        "required_input_kinds": (),
        "required_input_when_narrated": (),
        "required_output_kinds": ("validation_evidence",),
    },
}

ACCOUNTING_FIELDS = (
    "input_units", "output_units", "characters", "seconds", "requests",
    "currency", "estimated_cost", "billed_cost", "cost_provenance",
)
_INT_ACCOUNTING_FIELDS = frozenset({"input_units", "output_units", "characters", "requests"})
_NUM_ACCOUNTING_FIELDS = frozenset({"seconds", "estimated_cost", "billed_cost"})
_STR_ACCOUNTING_FIELDS = frozenset({"currency", "cost_provenance"})
_COST_ACCOUNTING_FIELDS = ("estimated_cost", "billed_cost")
_CREDENTIAL_KEYS = frozenset({
    "authorization", "api_key", "apikey", "api-key", "access_key", "accesskey",
    "secret", "secret_key", "client_secret", "token", "access_token", "refresh_token",
    "auth", "authentication", "bearer", "password", "passwd", "headers", "header",
    "cookie", "cookies", "set-cookie",
})


class ContractError(Exception):
    """Base class for every Phase 1 contract failure."""


class SchemaVersionError(ContractError):
    """A record declares a schema or contract version the recorder does not support."""


class MalformedRecordError(ContractError):
    """A record is missing, non-JSON, or missing required structure."""


class DuplicateIdentityError(ContractError):
    """A record identity already exists and cannot be reused."""


class UnknownReferenceError(ContractError):
    """A record points at an identity that is not registered."""


class PathSafetyError(ContractError):
    """A path escapes its explicit workspace/project root or is refused."""


class ConcurrentWriterError(ContractError):
    """Another writer holds the run/project lock."""


class ImmutabilityError(ContractError):
    """A recorded attempt would be modified, replaced, or deleted."""


def _fail(message: str) -> None:
    raise MalformedRecordError(message)


def _need_key(doc: Dict, key: str, kind: str) -> Any:
    if key not in doc:
        _fail("%s record is missing required key %r" % (kind, key))
    return doc[key]


def _need_str(value: Any, label: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail("%s must be a string" % label)
    if not allow_empty and value == "":
        _fail("%s must not be empty" % label)
    return value


def _need_id(value: Any, label: str) -> str:
    text = _need_str(value, label)
    if not _ID_RE.match(text):
        _fail("%s %r is not a valid identifier" % (label, text))
    return text


def validate_fs_id(value: Any, label: str) -> str:
    """Validate an identifier used to construct filesystem paths."""
    text = _need_str(value, label)
    if os.path.isabs(text) or text in (".", "..") or "/" in text or "\\" in text:
        _fail("%s %r is not a safe filesystem identifier" % (label, text))
    if not _ID_RE.match(text):
        _fail("%s %r is not a valid identifier" % (label, text))
    return text


def _need_optional_str(value: Any, label: str) -> Optional[str]:
    if value is None:
        return None
    return _need_str(value, label)


def check_schema_version(doc: Any, expected: int, kind: str) -> int:
    if not isinstance(doc, dict):
        _fail("%s record must be a JSON object" % kind)
    version = _need_key(doc, "schema_version", kind)
    if isinstance(version, bool) or not isinstance(version, int):
        _fail("%s schema_version must be an integer" % kind)
    if version != expected:
        raise SchemaVersionError(
            "unsupported %s schema_version %r (supported: %d)" % (kind, version, expected))
    return version


def stage_contract(stage_id: str) -> Dict:
    if stage_id not in STAGE_CONTRACTS:
        raise ContractError("unknown stage_id %r has no stage contract" % stage_id)
    return STAGE_CONTRACTS[stage_id]


def required_input_kinds(stage_id: str, narration_enabled: bool = False) -> List[str]:
    contract = stage_contract(stage_id)
    required = list(contract["required_input_kinds"])
    if narration_enabled:
        required.extend(contract["required_input_when_narrated"])
    return required


def required_output_kinds(stage_id: str) -> List[str]:
    return list(stage_contract(stage_id)["required_output_kinds"])


def _check_accounting_field(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in _INT_ACCOUNTING_FIELDS:
        if isinstance(value, bool) or not isinstance(value, int):
            _fail("usage %s must be an integer or null" % key)
        if value < 0:
            _fail("usage %s must be non-negative" % key)
        return value
    if key in _NUM_ACCOUNTING_FIELDS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail("usage %s must be a finite number or null" % key)
        number = float(value)
        if not math.isfinite(number):
            _fail("usage %s must be a finite number or null" % key)
        if number < 0:
            _fail("usage %s must be non-negative" % key)
        return number
    if key in _STR_ACCOUNTING_FIELDS:
        return _need_str(value, "usage %s" % key)
    raise ContractError("unsupported usage field %r" % key)


def validate_usage(usage: Any) -> Optional[Dict]:
    if usage is None:
        return None
    if not isinstance(usage, dict):
        raise ContractError("usage must be an object or null")
    for key in usage:
        if not isinstance(key, str):
            _fail("usage keys must be strings")
        if key.lower() in _CREDENTIAL_KEYS:
            raise ContractError("usage contains a credential-shaped field and was rejected")
    unknown = sorted(k for k in usage if k not in ACCOUNTING_FIELDS)
    if unknown:
        raise ContractError("unsupported usage field(s): %s" % ", ".join(unknown))
    result = {field: _check_accounting_field(field, usage.get(field)) for field in ACCOUNTING_FIELDS}
    if any(result[field] is not None for field in _COST_ACCOUNTING_FIELDS) and not result["cost_provenance"]:
        raise ContractError("usage cost requires cost_provenance; unknown cost must stay null")
    return result


def normalize_usage(usage: Any) -> Optional[Dict]:
    return validate_usage(usage)


def validate_project(doc: Any) -> Dict:
    check_schema_version(doc, PROJECT_SCHEMA_VERSION, "project")
    _need_id(_need_key(doc, "project_id", "project"), "project_id")
    project_dir = _need_str(_need_key(doc, "project_dir", "project"), "project_dir")
    if project_dir.startswith("/") or project_dir.startswith("../") or "/../" in project_dir:
        _fail("project_dir must be a workspace-relative path")
    _need_optional_str(doc.get("revision"), "revision")
    _need_optional_str(doc.get("parent_revision"), "parent_revision")
    _need_str(_need_key(doc, "created_at", "project"), "created_at")
    return doc


def validate_artifact(doc: Any) -> Dict:
    check_schema_version(doc, ARTIFACT_SCHEMA_VERSION, "artifact")
    _need_id(_need_key(doc, "artifact_id", "artifact"), "artifact_id")
    kind = _need_str(_need_key(doc, "kind", "artifact"), "kind")
    if kind not in ARTIFACT_KINDS:
        raise ContractError("artifact kind %r is not registered" % kind)
    root = _need_str(_need_key(doc, "root", "artifact"), "root")
    if root not in ARTIFACT_ROOTS:
        raise ContractError("artifact root %r is not one of %s" % (root, sorted(ARTIFACT_ROOTS)))
    path = _need_str(_need_key(doc, "path", "artifact"), "path")
    if path.startswith("/") or ".." in path.split("/"):
        _fail("artifact path must stay within its root")
    sha = _need_str(_need_key(doc, "sha256", "artifact"), "sha256")
    if not _SHA256_RE.match(sha):
        _fail("artifact sha256 must be 64 lowercase hex characters")
    size = _need_key(doc, "size_bytes", "artifact")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        _fail("artifact size_bytes must be a non-negative integer")
    producer = doc.get("producer_attempt_id")
    if producer is not None:
        _need_id(producer, "producer_attempt_id")
    legacy = doc.get("legacy_external")
    if not isinstance(legacy, bool):
        _fail("artifact legacy_external must be a boolean")
    if legacy and producer is not None:
        _fail("artifact cannot be both legacy_external and produced by an attempt")
    if not legacy and producer is None:
        _fail("artifact requires a producer_attempt_id or legacy_external origin")
    _need_str(_need_key(doc, "created_at", "artifact"), "created_at")
    return doc


def validate_attempt(doc: Any) -> Dict:
    check_schema_version(doc, ATTEMPT_SCHEMA_VERSION, "attempt")
    _need_id(_need_key(doc, "attempt_id", "attempt"), "attempt_id")
    stage_id = _need_str(_need_key(doc, "stage_id", "attempt"), "stage_id")
    stage_contract(stage_id)
    version = _need_str(_need_key(doc, "stage_contract_version", "attempt"), "stage_contract_version")
    if version not in SUPPORTED_STAGE_CONTRACT_VERSIONS:
        raise SchemaVersionError("unsupported stage contract version %r" % version)
    origin = _need_str(_need_key(doc, "origin", "attempt"), "origin")
    if origin not in ATTEMPT_ORIGINS:
        raise ContractError("attempt origin %r is not registered" % origin)
    outcome = _need_str(_need_key(doc, "reported_execution_outcome", "attempt"),
                        "reported_execution_outcome")
    if outcome not in ATTEMPT_OUTCOMES:
        raise ContractError("attempt outcome %r is not registered" % outcome)
    for key in ("input_artifact_ids", "output_artifact_ids"):
        value = _need_key(doc, key, "attempt")
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            _fail("attempt %s must be a list of artifact ids" % key)
    for key in ("started_at", "ended_at", "error", "provider", "tool", "model", "supersedes"):
        _need_optional_str(doc.get(key), key)
    validate_usage(doc.get("usage"))
    return doc


def validate_historical_reference(doc: Any) -> Dict:
    if not isinstance(doc, dict):
        _fail("historical reference must be a JSON object")
    _need_id(doc.get("reference_id"), "reference_id")
    kind = _need_str(doc.get("kind"), "historical reference kind")
    if kind not in ARTIFACT_KINDS:
        raise ContractError("historical reference kind %r is not registered" % kind)
    root = _need_str(doc.get("root"), "historical reference root")
    if root not in ARTIFACT_ROOTS:
        raise ContractError("historical reference root %r is not registered" % root)
    path = _need_str(doc.get("path"), "historical reference path")
    if path.startswith("/") or ".." in path.split("/"):
        _fail("historical reference path must stay within its root")
    sha = _need_str(doc.get("sha256"), "historical reference sha256")
    if not _SHA256_RE.match(sha):
        _fail("historical reference sha256 must be 64 lowercase hex characters")
    note = doc.get("note")
    if note is not None:
        _need_str(note, "historical reference note")
    _need_str(doc.get("recorded_at"), "historical reference recorded_at")
    return doc


def validate_validation(doc: Any) -> Dict:
    check_schema_version(doc, VALIDATION_SCHEMA_VERSION, "validation")
    _need_id(_need_key(doc, "validation_id", "validation"), "validation_id")
    _need_str(_need_key(doc, "validator", "validation"), "validator")
    _need_str(_need_key(doc, "validator_version", "validation"), "validator_version")
    _need_str(_need_key(doc, "evidence_ref", "validation"), "evidence_ref")
    _need_id(_need_key(doc, "evidence_artifact_id", "validation"), "evidence_artifact_id")
    result = _need_str(_need_key(doc, "result", "validation"), "result")
    if result not in VALIDATION_RESULTS:
        raise ContractError("validation result %r is not registered" % result)
    _need_str(_need_key(doc, "scope", "validation"), "scope")
    subjects = doc.get("subject_artifact_ids", [])
    if not isinstance(subjects, list) or any(not isinstance(v, str) for v in subjects):
        _fail("validation subject_artifact_ids must be a list of artifact ids")
    _need_str(_need_key(doc, "created_at", "validation"), "created_at")
    return doc


def validate_run(doc: Any) -> Dict:
    check_schema_version(doc, RUN_SCHEMA_VERSION, "run")
    _need_id(_need_key(doc, "run_id", "run"), "run_id")
    _need_id(_need_key(doc, "project_id", "run"), "project_id")
    _need_str(_need_key(doc, "revision", "run"), "revision")
    revision_dir = _need_str(_need_key(doc, "revision_dir", "run"), "revision_dir")
    if revision_dir.startswith("/") or revision_dir.startswith("../") or "/../" in revision_dir:
        _fail("revision_dir must be a workspace-relative path")
    _need_str(_need_key(doc, "created_at", "run"), "created_at")
    workflow_version = _need_str(
        _need_key(doc, "workflow_contract_version", "run"), "workflow_contract_version")
    if workflow_version not in SUPPORTED_WORKFLOW_CONTRACT_VERSIONS:
        raise SchemaVersionError("unsupported workflow contract version %r" % workflow_version)
    narration = _need_key(doc, "narration_enabled", "run")
    if not isinstance(narration, bool):
        _fail("run narration_enabled must be a boolean")
    for key in ("attempts", "artifacts", "validations"):
        if not isinstance(doc.get(key), dict):
            _fail("run %s must be an object keyed by id" % key)
    if not isinstance(doc.get("historical_references"), list):
        _fail("run historical_references must be a list")
    return doc


def enforce_stage_contract(attempt: Dict, artifacts: Dict, narration_enabled: bool) -> None:
    if attempt["reported_execution_outcome"] != "succeeded":
        return
    required_inputs = required_input_kinds(attempt["stage_id"], narration_enabled)
    required_outputs = required_output_kinds(attempt["stage_id"])
    input_kinds = set()
    for artifact_id in attempt["input_artifact_ids"]:
        artifact = artifacts.get(artifact_id)
        if artifact is not None:
            input_kinds.add(artifact["kind"])
    output_kinds = set()
    for artifact_id in attempt["output_artifact_ids"]:
        artifact = artifacts.get(artifact_id)
        if artifact is not None:
            output_kinds.add(artifact["kind"])
    missing_inputs = [kind for kind in required_inputs if kind not in input_kinds]
    missing_outputs = [kind for kind in required_outputs if kind not in output_kinds]
    if missing_inputs:
        raise ContractError(
            "attempt %r (stage %r) is missing required input kinds %s"
            % (attempt["attempt_id"], attempt["stage_id"], missing_inputs))
    if missing_outputs:
        raise ContractError(
            "attempt %r (stage %r) is missing required output kinds %s"
            % (attempt["attempt_id"], attempt["stage_id"], missing_outputs))
