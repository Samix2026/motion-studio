"""Explicit artifact registration, streaming hashing, and integrity checks.

Standard-library only. Paths resolve within an explicit workspace root and,
for project-rooted artifacts, within ``<workspace>/<revision_dir>``. Refused
files (credential stores, ``.env``, ``.git``) and escaping symlink aliases are
rejected both before and after canonical resolution. Nothing here reads
credentials, scans the workspace, or infers success from file existence.
"""

from __future__ import annotations

import hashlib
import os
from typing import Dict, Optional

from studio import contracts

HASH_CHUNK = 1 << 20
_REFUSED_BASENAMES = frozenset({".env", ".netrc", "credentials", "credentials.json"})
_REFUSED_PREFIXES = (".env.",)
_REFUSED_SEGMENTS = frozenset({".git", ".ssh", ".aws"})


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def assert_within(root: str, candidate: str) -> None:
    if candidate != root and not candidate.startswith(root + os.sep):
        raise contracts.PathSafetyError(
            "path %r escapes root %r" % (candidate, root))


_assert_within = assert_within


def assert_allowed_path(canonical: str, base: str) -> None:
    relative = os.path.relpath(canonical, base).replace(os.sep, "/")
    for segment in relative.split("/"):
        if segment in ("", "."):
            continue
        if (segment in _REFUSED_SEGMENTS or segment in _REFUSED_BASENAMES
                or segment.startswith(_REFUSED_PREFIXES)):
            raise contracts.PathSafetyError(
                "refusing to access a refused path")  # never echo the refused target


def _check_relative_input(rel_path: str) -> None:
    if not isinstance(rel_path, str) or rel_path == "":
        raise contracts.PathSafetyError("artifact path must be a non-empty string")
    if os.path.isabs(rel_path):
        raise contracts.PathSafetyError("artifact path must be relative")
    parts = rel_path.split("/")
    if ".." in parts or "." in parts:
        raise contracts.PathSafetyError("artifact path must not traverse")
    for segment in parts:
        if segment in _REFUSED_SEGMENTS:
            raise contracts.PathSafetyError("refusing to access a refused path")
    basename = os.path.basename(rel_path)
    if basename in _REFUSED_BASENAMES or basename.startswith(_REFUSED_PREFIXES):
        raise contracts.PathSafetyError("refusing to access a refused path")


def normalize_project_dir(workspace: str, project_dir: str,
                          must_exist: bool = True) -> str:
    ws = os.path.realpath(workspace)
    if os.path.isabs(project_dir):
        candidate = os.path.realpath(project_dir)
    else:
        candidate = os.path.realpath(os.path.join(ws, project_dir))
    assert_within(ws, candidate)
    assert_allowed_path(candidate, ws)
    if must_exist and not os.path.isdir(candidate):
        raise contracts.PathSafetyError("project dir does not exist: %s" % project_dir)
    rel = os.path.relpath(candidate, ws)
    return rel.replace(os.sep, "/")


def project_root(workspace: str, project_dir: str) -> str:
    ws = os.path.realpath(workspace)
    root = os.path.realpath(os.path.join(ws, project_dir))
    assert_within(ws, root)
    assert_allowed_path(root, ws)
    return root


def resolve_artifact_path(root: str, rel_path: str, workspace: str,
                          project_dir: Optional[str]) -> str:
    if root not in contracts.ARTIFACT_ROOTS:
        raise contracts.ContractError("artifact root %r is not registered" % root)
    ws = os.path.realpath(workspace)
    _check_relative_input(rel_path)
    if root == "workspace":
        base = ws
    else:
        if not project_dir:
            raise contracts.PathSafetyError("project-rooted artifact needs a revision_dir")
        base = project_root(ws, project_dir)
    candidate = os.path.realpath(os.path.join(base, rel_path))
    assert_within(base, candidate)
    assert_allowed_path(candidate, base)
    return candidate


def build_artifact(artifact_id: str, kind: str, root: str, rel_path: str,
                   workspace: str, project_dir: Optional[str],
                   producer_attempt_id: Optional[str], legacy_external: bool,
                   created_at: str) -> Dict:
    if kind not in contracts.ARTIFACT_KINDS:
        raise contracts.ContractError("artifact kind %r is not registered" % kind)
    full = resolve_artifact_path(root, rel_path, workspace, project_dir)
    if not os.path.isfile(full):
        raise contracts.PathSafetyError("artifact file not found: %s" % rel_path)
    if root == "workspace":
        base = os.path.realpath(workspace)
    else:
        base = project_root(workspace, project_dir)
    canonical = os.path.relpath(full, base).replace(os.sep, "/")
    assert_allowed_path(full, base)
    return {
        "schema_version": contracts.ARTIFACT_SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "kind": kind,
        "root": root,
        "path": canonical,
        "sha256": sha256_file(full),
        "size_bytes": os.path.getsize(full),
        "producer_attempt_id": producer_attempt_id,
        "legacy_external": legacy_external,
        "created_at": created_at,
    }


def check_artifact(artifact: Dict, workspace: str, project_dir: Optional[str]) -> Dict:
    report = {
        "artifact_id": artifact["artifact_id"],
        "kind": artifact["kind"],
        "root": artifact["root"],
        "path": artifact["path"],
        "expected_sha256": artifact["sha256"],
        "producer_attempt_id": artifact.get("producer_attempt_id"),
        "legacy_external": artifact.get("legacy_external", False),
        "state": "ok",
        "actual_sha256": None,
        "detail": None,
    }
    try:
        full = resolve_artifact_path(artifact["root"], artifact["path"], workspace, project_dir)
    except contracts.ContractError:
        report["state"] = "unsafe"
        report["detail"] = "registered artifact path is not allowed"
        return report
    if not os.path.isfile(full):
        report["state"] = "missing"
        report["detail"] = "registered artifact is not present"
        return report
    actual = sha256_file(full)
    report["actual_sha256"] = actual
    if actual != artifact["sha256"]:
        report["state"] = "changed"
        report["detail"] = "content differs from the registered SHA-256"
    return report
