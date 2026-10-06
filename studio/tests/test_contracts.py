"""Phase 1 contract tests: schemas, versions, accounting, and stage handoffs."""

from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from studio import contracts as c  # noqa: E402


def project(**over):
    doc = {
        "schema_version": 1,
        "project_id": "proj",
        "project_dir": "videos/proj",
        "revision": None,
        "parent_revision": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    doc.update(over)
    return doc


def artifact(**over):
    doc = {
        "schema_version": 1,
        "artifact_id": "render-1",
        "kind": "render",
        "root": "project",
        "path": "renders/video.mp4",
        "sha256": "a" * 64,
        "size_bytes": 10,
        "producer_attempt_id": "att-1",
        "legacy_external": False,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    doc.update(over)
    return doc


def attempt(**over):
    doc = {
        "schema_version": 1,
        "attempt_id": "att-1",
        "stage_id": "render",
        "stage_contract_version": c.STAGE_CONTRACT_VERSION,
        "origin": "external",
        "reported_execution_outcome": "succeeded",
        "input_artifact_ids": [],
        "output_artifact_ids": [],
        "started_at": None,
        "ended_at": None,
        "error": None,
        "provider": None,
        "tool": None,
        "model": None,
        "usage": None,
        "supersedes": None,
        "recorded_at": "2026-01-01T00:00:00+00:00",
    }
    doc.update(over)
    return doc


def validation(**over):
    doc = {
        "schema_version": 1,
        "validation_id": "val-1",
        "validator": "ffprobe",
        "validator_version": "6.0",
        "evidence_ref": "reports/ffprobe.txt",
        "evidence_artifact_id": "ev-1",
        "result": "passed",
        "scope": "render-integrity",
        "subject_artifact_ids": [],
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    doc.update(over)
    return doc


def run(**over):
    doc = {
        "schema_version": 1,
        "run_id": "run-1",
        "project_id": "proj",
        "revision": "rev1",
        "revision_dir": "videos/proj",
        "created_at": "2026-01-01T00:00:00+00:00",
        "workflow_contract_version": c.WORKFLOW_CONTRACT_VERSION,
        "narration_enabled": False,
        "attempts": {},
        "artifacts": {},
        "validations": {},
        "historical_references": [],
    }
    doc.update(over)
    return doc


class TestSchemas(unittest.TestCase):
    def test_valid_records_pass(self):
        self.assertEqual(project(), c.validate_project(project()))
        self.assertEqual(artifact(), c.validate_artifact(artifact()))
        self.assertEqual(attempt(), c.validate_attempt(attempt()))
        self.assertEqual(validation(), c.validate_validation(validation()))
        self.assertEqual(run(), c.validate_run(run()))

    def test_missing_key_is_malformed(self):
        with self.assertRaises(c.MalformedRecordError):
            c.validate_project({k: v for k, v in project().items() if k != "project_id"})

    def test_unsupported_schema_version_fails_clearly(self):
        with self.assertRaises(c.SchemaVersionError):
            c.validate_project(project(schema_version=99))
        with self.assertRaises(c.SchemaVersionError):
            c.validate_artifact(artifact(schema_version=2))
        with self.assertRaises(c.SchemaVersionError):
            c.validate_attempt(attempt(schema_version=3))

    def test_missing_schema_version_is_malformed(self):
        doc = project()
        del doc["schema_version"]
        with self.assertRaises(c.MalformedRecordError):
            c.validate_project(doc)

    def test_invalid_identifier(self):
        with self.assertRaises(c.MalformedRecordError):
            c.validate_project(project(project_id="../escape"))

    def test_validate_fs_id_rejects_paths(self):
        self.assertEqual("ok-1", c.validate_fs_id("ok-1", "run_id"))
        for bad in ("../x", "/abs", "a/b", "..", ".", "a\\b", ""):
            with self.assertRaises(c.MalformedRecordError):
                c.validate_fs_id(bad, "run_id")

    def test_unknown_workflow_contract_version(self):
        with self.assertRaises(c.SchemaVersionError):
            c.validate_run(run(workflow_contract_version="bogus"))

    def test_unknown_stage_and_stage_version(self):
        with self.assertRaises(c.ContractError):
            c.validate_attempt(attempt(stage_id="not-a-stage"))
        with self.assertRaises(c.SchemaVersionError):
            c.validate_attempt(attempt(stage_contract_version="bogus"))

    def test_artifact_origin_exclusive(self):
        with self.assertRaises(c.MalformedRecordError):
            c.validate_artifact(artifact(legacy_external=True, producer_attempt_id="att-1"))
        with self.assertRaises(c.MalformedRecordError):
            c.validate_artifact(artifact(legacy_external=False, producer_attempt_id=None))
        legacy = c.validate_artifact(artifact(legacy_external=True, producer_attempt_id=None))
        self.assertTrue(legacy["legacy_external"])
        self.assertIsNone(legacy["producer_attempt_id"])

    def test_unknown_kind_and_bad_hash(self):
        with self.assertRaises(c.ContractError):
            c.validate_artifact(artifact(kind="not_a_kind"))
        with self.assertRaises(c.MalformedRecordError):
            c.validate_artifact(artifact(sha256="xyz"))

    def test_unknown_validation_result(self):
        with self.assertRaises(c.ContractError):
            c.validate_validation(validation(result="approved"))

    def test_validation_requires_evidence_artifact(self):
        doc = validation()
        del doc["evidence_artifact_id"]
        with self.assertRaises(c.MalformedRecordError):
            c.validate_validation(doc)

    def test_report_execution_and_validation_are_separate(self):
        self.assertNotIn("passed", c.ATTEMPT_OUTCOMES)
        self.assertNotIn("validated", c.ATTEMPT_OUTCOMES)
        self.assertNotIn("succeeded", c.VALIDATION_RESULTS)


class TestAccounting(unittest.TestCase):
    def test_unknown_stays_null(self):
        doc = c.validate_attempt(attempt(usage=None))
        self.assertIsNone(doc["usage"])
        normalized = c.normalize_usage(None)
        self.assertIsNone(normalized)

    def test_valid_measurements_round_trip(self):
        usage = {"input_units": 10, "output_units": 5, "characters": 120,
                 "seconds": 2.5, "requests": 1, "currency": "USD",
                 "billed_cost": 0.0, "cost_provenance": "invoice-42"}
        out = c.normalize_usage(usage)
        self.assertEqual(10, out["input_units"])
        self.assertEqual(2.5, out["seconds"])
        self.assertEqual(0.0, out["billed_cost"])
        self.assertEqual("invoice-42", out["cost_provenance"])
        self.assertIsNone(out["estimated_cost"])

    def test_null_values_round_trip(self):
        out = c.normalize_usage({"input_units": 7})
        self.assertEqual(7, out["input_units"])
        for field in ("output_units", "characters", "seconds", "requests",
                      "currency", "estimated_cost", "billed_cost", "cost_provenance"):
            self.assertIsNone(out[field])

    def test_credential_shaped_metadata_rejected_without_echo(self):
        for key in ("api_key", "authorization", "token", "secret", "headers", "cookie"):
            with self.assertRaises(c.ContractError) as ctx:
                c.validate_usage({key: "SUPER-SECRET-VALUE"})
            message = str(ctx.exception)
            self.assertNotIn("SUPER-SECRET-VALUE", message)
            self.assertNotIn(key, message)

    def test_arbitrary_payload_rejected(self):
        with self.assertRaises(c.ContractError):
            c.validate_usage({"prompt": "do things"})
        with self.assertRaises(c.ContractError):
            c.validate_usage({"seconds": {"nested": 1}})

    def test_nan_and_infinities_rejected(self):
        with self.assertRaises(c.ContractError):
            c.validate_usage({"seconds": float("nan")})
        with self.assertRaises(c.ContractError):
            c.validate_usage({"seconds": float("inf")})
        with self.assertRaises(c.ContractError):
            c.validate_usage({"seconds": float("-inf")})
        with self.assertRaises(c.ContractError):
            c.validate_usage({"billed_cost": float("inf"), "cost_provenance": "x"})

    def test_cost_requires_provenance(self):
        with self.assertRaises(c.ContractError):
            c.validate_usage({"estimated_cost": 0.0})
        with self.assertRaises(c.ContractError):
            c.validate_usage({"billed_cost": 1.25})
        out = c.validate_usage({"estimated_cost": 0.0, "cost_provenance": "provided"})
        self.assertEqual(0.0, out["estimated_cost"])

    def test_negative_measurements_rejected(self):
        with self.assertRaises(c.ContractError):
            c.validate_usage({"input_units": -1})
        with self.assertRaises(c.ContractError):
            c.validate_usage({"seconds": -0.1})


class TestStageContracts(unittest.TestCase):
    narration = {"n1": artifact(artifact_id="n1", kind="narration")}
    composition = {"c1": artifact(artifact_id="c1", kind="composition")}
    render = {"r1": artifact(artifact_id="r1", kind="render")}

    def test_narration_input_and_composition_output_pass(self):
        att = attempt(stage_id="composition", input_artifact_ids=["n1"],
                      output_artifact_ids=["c1"])
        c.enforce_stage_contract(att, {**self.narration, **self.composition}, True)

    def test_missing_narration_input_fails_when_enabled(self):
        att = attempt(stage_id="composition", output_artifact_ids=["c1"])
        c.enforce_stage_contract(att, self.composition, False)
        with self.assertRaises(c.ContractError):
            c.enforce_stage_contract(att, self.composition, True)

    def test_required_render_input_missing_fails(self):
        att = attempt(stage_id="render", output_artifact_ids=["r1"])
        with self.assertRaises(c.ContractError):
            c.enforce_stage_contract(att, self.render, False)
        good = attempt(stage_id="render", input_artifact_ids=["c1"], output_artifact_ids=["r1"])
        c.enforce_stage_contract(good, {**self.composition, **self.render}, False)

    def test_missing_output_fails(self):
        att = attempt(stage_id="render", input_artifact_ids=["c1"])
        with self.assertRaises(c.ContractError):
            c.enforce_stage_contract(att, self.composition, False)

    def test_failed_or_unknown_attempts_preserve_partial(self):
        for outcome in ("failed", "unknown", "started", "cancelled"):
            att = attempt(stage_id="render", reported_execution_outcome=outcome)
            c.enforce_stage_contract(att, {}, False)

    def test_unknown_stage_is_rejected(self):
        with self.assertRaises(c.ContractError):
            c.stage_contract("does-not-exist")


if __name__ == "__main__":
    unittest.main(verbosity=2)
