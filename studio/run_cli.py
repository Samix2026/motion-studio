"""Additive CLI for the Phase 1 project/run manifest recording layer.

These commands register explicitly selected records and perform atomic writes
under ``<workspace>/runs/``. They never run a provider, renderer, shell, or
network call, never modify a project directory, and never infer success,
approval, cost, or readiness.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from studio import contracts, execution, manifest  # noqa: E402

_ACCOUNTING_FLAGS = (
    "input_units", "output_units", "characters", "seconds", "requests",
    "currency", "estimated_cost", "billed_cost", "cost_provenance",
)


def _workspace(args) -> str:
    return args.workspace or manifest.DEFAULT_WORKSPACE


def _emit(doc) -> None:
    try:
        text = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    except ValueError:
        raise contracts.MalformedRecordError("record contains a non-finite number")
    print(text)


def _build_usage(args) -> dict:
    discrete = {key: getattr(args, key) for key in _ACCOUNTING_FLAGS
                if getattr(args, key, None) is not None}
    if args.usage is not None:
        if discrete:
            raise contracts.ContractError(
                "provide either --usage or the discrete accounting fields, not both")
        try:
            return json.loads(args.usage)
        except json.JSONDecodeError:
            raise contracts.MalformedRecordError("usage must be valid JSON")
    return discrete or None


def cmd_project_register(args) -> int:
    doc = manifest.register_project(
        _workspace(args), args.project_id, args.project_dir,
        revision=args.revision, parent_revision=args.parent_revision, created_at=args.at)
    _emit(doc)
    return 0


def cmd_run_create(args) -> int:
    doc = manifest.create_run(
        _workspace(args), args.project_id, args.run_id, args.revision, args.revision_dir,
        workflow_contract_version=args.workflow_contract_version,
        narration_enabled=args.narration, created_at=args.at)
    _emit(doc)
    return 0


def cmd_artifact_register(args) -> int:
    doc = manifest.register_artifact(
        _workspace(args), args.project_id, args.run_id, args.artifact_id,
        args.kind, args.root, args.path,
        producer_attempt_id=args.producer_attempt,
        legacy_external=args.legacy_external,
        historical=args.historical, historical_note=args.note, created_at=args.at)
    _emit(doc["artifacts"][args.artifact_id])
    return 0


def cmd_attempt_record(args) -> int:
    doc = manifest.record_attempt(
        _workspace(args), args.project_id, args.run_id, args.attempt_id,
        args.stage, args.origin, args.outcome,
        input_artifact_ids=args.input, output_artifact_ids=args.output,
        started_at=args.started_at, ended_at=args.ended_at, error=args.error,
        provider=args.provider, tool=args.tool, model=args.model,
        usage=_build_usage(args),
        supersedes=args.supersedes, created_at=args.at)
    _emit(doc["attempts"][args.attempt_id])
    return 0


def cmd_validation_record(args) -> int:
    doc = manifest.record_validation(
        _workspace(args), args.project_id, args.run_id, args.validation_id,
        args.validator, args.validator_version, args.evidence_ref,
        args.evidence_artifact, args.result, args.scope,
        subject_artifact_ids=args.subject, created_at=args.at)
    _emit(doc["validations"][args.validation_id])
    return 0


def cmd_historical_reference(args) -> int:
    doc = manifest.historical_reference(
        _workspace(args), args.project_id, args.run_id, args.reference_id,
        args.root, args.path, note=args.note, created_at=args.at)
    _emit(doc["artifacts"][args.reference_id])
    return 0


def cmd_manifest_validate(args) -> int:
    ws = _workspace(args)
    run = manifest.load_run(ws, args.project_id, args.run_id)
    narration = run["narration_enabled"] if args.narration is None else args.narration
    manifest.validate_run_manifest(run, narration_enabled=narration, workspace=ws)
    _emit({
        "valid": True,
        "structural_validity": True,
        "reference_validity": True,
        "relationship_validity": True,
        "stage_contract_validity": True,
        "validation_evidence_integrity": True,
        "production_artifact_integrity": "not_checked",
        "artifact_integrity_note": (
            "manifest-validate checks structure, references, relationships, stage "
            "contracts, and validation-evidence integrity. Production artifact "
            "content integrity (e.g. a render that changed) is not checked here; "
            "run-status reports per-artifact state (ok/missing/changed)."),
        "run_id": run["run_id"],
        "project_id": run["project_id"],
        "revision": run["revision"],
        "revision_dir": run["revision_dir"],
        "attempts": len(run["attempts"]),
        "artifacts": len(run["artifacts"]),
        "validations": len(run["validations"]),
        "historical_references": len(run["historical_references"]),
        "narration_enabled": narration,
    })
    return 0


def cmd_run_status(args) -> int:
    _emit(manifest.inspect_run(_workspace(args), args.project_id, args.run_id))
    return 0


def cmd_run_history(args) -> int:
    _emit(manifest.list_runs(_workspace(args), project_id=args.project_id))
    return 0


def register_subcommands(sub) -> None:
    p = sub.add_parser("project-register", help="register a project id under runs/projects/")
    p.add_argument("--project-id", required=True)
    p.add_argument("--project-dir", required=True, help="workspace-relative or absolute project directory")
    p.add_argument("--revision", default=None)
    p.add_argument("--parent-revision", default=None)
    p.add_argument("--at", default=None, help="explicit created_at timestamp")
    p.add_argument("--workspace", default=None, help="workspace root (default: repository root)")
    p.set_defaults(func=cmd_project_register)

    p = sub.add_parser("run-create", help="create a versioned run manifest under runs/manifests/")
    p.add_argument("--project-id", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--revision-dir", required=True,
                   help="immutable workspace-relative revision directory bound to this run")
    p.add_argument("--workflow-contract-version", default=contracts.WORKFLOW_CONTRACT_VERSION)
    p.add_argument("--narration", action="store_true", help="workflow narration explicitly enabled")
    p.add_argument("--at", default=None)
    p.add_argument("--workspace", default=None)
    p.set_defaults(func=cmd_run_create)

    p = sub.add_parser("artifact-register", help="register an explicitly selected existing artifact")
    p.add_argument("--project-id", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--artifact-id", required=True)
    p.add_argument("--kind", required=True, choices=sorted(contracts.ARTIFACT_KINDS))
    p.add_argument("--root", required=True, choices=sorted(contracts.ARTIFACT_ROOTS))
    p.add_argument("--path", required=True, help="revision-root-relative artifact path")
    p.add_argument("--producer-attempt", default=None)
    p.add_argument("--legacy-external", action="store_true")
    p.add_argument("--historical", action="store_true",
                   help="also associate this artifact as a historical reference")
    p.add_argument("--note", default=None)
    p.add_argument("--at", default=None)
    p.add_argument("--workspace", default=None)
    p.set_defaults(func=cmd_artifact_register)

    p = sub.add_parser("attempt-record", help="record an externally performed stage attempt")
    p.add_argument("--project-id", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--attempt-id", required=True)
    p.add_argument("--stage", required=True, choices=sorted(contracts.STAGE_CONTRACTS))
    p.add_argument("--origin", required=True, choices=sorted(contracts.ATTEMPT_ORIGINS))
    p.add_argument("--outcome", required=True, choices=sorted(contracts.ATTEMPT_OUTCOMES))
    p.add_argument("--input", action="append", default=None)
    p.add_argument("--output", action="append", default=None)
    p.add_argument("--started-at", default=None)
    p.add_argument("--ended-at", default=None)
    p.add_argument("--error", default=None)
    p.add_argument("--provider", default=None)
    p.add_argument("--tool", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--usage", default=None,
                   help="normalized accounting JSON object, or omit to leave unknown/null")
    p.add_argument("--input-units", type=int, default=None)
    p.add_argument("--output-units", type=int, default=None)
    p.add_argument("--characters", type=int, default=None)
    p.add_argument("--seconds", type=float, default=None)
    p.add_argument("--requests", type=int, default=None)
    p.add_argument("--currency", default=None)
    p.add_argument("--estimated-cost", type=float, default=None)
    p.add_argument("--billed-cost", type=float, default=None)
    p.add_argument("--cost-provenance", default=None)
    p.add_argument("--supersedes", default=None)
    p.add_argument("--at", default=None)
    p.add_argument("--workspace", default=None)
    p.set_defaults(func=cmd_attempt_record)

    p = sub.add_parser("validation-record", help="record a validation reference and result")
    p.add_argument("--project-id", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--validation-id", required=True)
    p.add_argument("--validator", required=True)
    p.add_argument("--validator-version", required=True)
    p.add_argument("--evidence-ref", required=True)
    p.add_argument("--evidence-artifact", required=True,
                   help="registered artifact id whose SHA-256 is the evidence content address")
    p.add_argument("--result", required=True, choices=sorted(contracts.VALIDATION_RESULTS))
    p.add_argument("--scope", required=True)
    p.add_argument("--subject", action="append", default=None)
    p.add_argument("--at", default=None)
    p.add_argument("--workspace", default=None)
    p.set_defaults(func=cmd_validation_record)

    p = sub.add_parser("historical-reference",
                       help="associate an existing legacy run summary without modifying it")
    p.add_argument("--project-id", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--reference-id", required=True)
    p.add_argument("--root", required=True, choices=sorted(contracts.ARTIFACT_ROOTS))
    p.add_argument("--path", required=True)
    p.add_argument("--note", default=None)
    p.add_argument("--at", default=None)
    p.add_argument("--workspace", default=None)
    p.set_defaults(func=cmd_historical_reference)

    p = sub.add_parser("manifest-validate", help="validate manifest structure and references")
    p.add_argument("--project-id", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--narration", action="store_true", default=None)
    p.add_argument("--workspace", default=None)
    p.set_defaults(func=cmd_manifest_validate)

    p = sub.add_parser("run-status", help="inspect a run manifest without writing")
    p.add_argument("--project-id", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--workspace", default=None)
    p.set_defaults(func=cmd_run_status)

    p = sub.add_parser("run-history", help="list recorded runs without writing")
    p.add_argument("--project-id", default=None)
    p.add_argument("--workspace", default=None)
    p.set_defaults(func=cmd_run_history)

    # Unit B (Increment 1): opt-in, local-only managed execution of the timing stage.
    execution.register_subcommands(sub)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="studio-run", description="Phase 1 run manifest recorder")
    sub = parser.add_subparsers(dest="cmd", required=True)
    register_subcommands(sub)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except contracts.ContractError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
