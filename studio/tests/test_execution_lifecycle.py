"""Unit B (Increment 1): managed timing execution lifecycle (success/failure/lock)."""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from studio import artifacts, cli, contracts, execution, manifest  # noqa: E402

TS = "2026-01-01T00:00:00+00:00"

_PROVIDER_RESPONSE = {
    "words": [
        {"word": "hello", "start_ms": 0, "end_ms": 500},
        {"word": "world", "start_ms": 600, "end_ms": 1200},
    ],
    "audio_duration_ms": 2000,
}


class LifecycleBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-life-")
        self.ws = os.path.realpath(os.path.join(self.tmp, "ws"))
        self.project = os.path.join(self.ws, "videos", "proj")
        os.makedirs(self.project)
        self.write("index.html", b"<html></html>")
        self.write("narration.mp3", b"ID3")
        self.write("provider.json", json.dumps(_PROVIDER_RESPONSE).encode())
        manifest.register_project(self.ws, "proj", "videos/proj", created_at=TS)
        manifest.create_run(self.ws, "proj", "run-1", "rev1", "videos/proj", created_at=TS)
        manifest.register_artifact(self.ws, "proj", "run-1", "narration-1", "narration",
                                   "project", "narration.mp3", legacy_external=True, created_at=TS)
        manifest.register_artifact(self.ws, "proj", "run-1", "provider-1", "other",
                                   "project", "provider.json", legacy_external=True, created_at=TS)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, payload):
        path = os.path.join(self.project, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(payload)
        return path

    def request(self, **over):
        kwargs = dict(
            workspace=self.ws, project_id="proj", run_id="run-1", attempt_id="att-timing-1",
            input_artifact_ids=("narration-1", "provider-1"),
            provider_response_artifact_id="provider-1",
            output_timing_artifact_id="timing-1", output_timing_path="word-timings.json",
            output_captions_artifact_id="captions-1", output_captions_path="captions.json",
            confirm=True)
        kwargs.update(over)
        return execution.TimingExecutionRequest(**kwargs)

    def load_run(self):
        return manifest.load_run(self.ws, "proj", "run-1")

    def run_path(self):
        return manifest.manifest_path(self.ws, "proj", "run-1")


class TestSuccess(LifecycleBase):
    def test_successful_execution_receipt_and_artifacts(self):
        result = execution.execute_timing(self.request())
        self.assertEqual("succeeded", result["status"])
        run = self.load_run()
        self.assertEqual({"att-timing-1"}, set(run["attempts"]))
        attempt = run["attempts"]["att-timing-1"]
        self.assertEqual("succeeded", attempt["reported_execution_outcome"])
        self.assertEqual("timing", attempt["stage_id"])
        self.assertEqual(["timing-1", "captions-1"], attempt["output_artifact_ids"])
        for aid, kind in (("timing-1", "timing"), ("captions-1", "caption")):
            artifact = run["artifacts"][aid]
            self.assertEqual(kind, artifact["kind"])
            self.assertEqual("att-timing-1", artifact["producer_attempt_id"])
            self.assertEqual(artifacts.sha256_file(
                os.path.join(self.project, artifact["path"])), artifact["sha256"])
        self.assertTrue(os.path.isfile(os.path.join(self.project, "word-timings.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.project, "captions.json")))
        manifest.validate_run_manifest(run)  # full structural/reference/contract check
        report = manifest.inspect_run(self.ws, "proj", "run-1")
        self.assertTrue(report["complete"])
        self.assertTrue(report["reference_resolution"])

    def test_execution_lock_released_after_success(self):
        execution.execute_timing(self.request())
        self.assertFalse(os.path.exists(
            execution.execution_lock_path(self.ws, "proj", "run-1")))

    def test_read_only_inspection_does_not_change_run(self):
        execution.execute_timing(self.request())
        with open(self.run_path(), "rb") as fh:
            before = fh.read()
        manifest.inspect_run(self.ws, "proj", "run-1")
        manifest.validate_run_manifest(self.load_run())
        with redirect_stdout(io.StringIO()):
            code = cli.main(["run-status", "--workspace", self.ws,
                             "--project-id", "proj", "--run-id", "run-1"])
        self.assertEqual(0, code)
        with open(self.run_path(), "rb") as fh:
            self.assertEqual(before, fh.read())

    def test_cli_timing_execute_end_to_end(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main([
                "timing-execute", "--workspace", self.ws, "--project-id", "proj",
                "--run-id", "run-1", "--attempt-id", "att-cli",
                "--input", "narration-1", "--input", "provider-1",
                "--provider-response-artifact", "provider-1",
                "--output-timing-artifact", "timing-cli",
                "--output-timing-path", "word-timings-cli.json",
                "--confirm"])
        self.assertEqual(0, code)
        self.assertIn("succeeded", out.getvalue())
        run = self.load_run()
        self.assertEqual("succeeded", run["attempts"]["att-cli"]["reported_execution_outcome"])


class TestFailure(LifecycleBase):
    def test_execution_failure_records_failed_receipt_without_outputs(self):
        self.write("provider.json", json.dumps({"words": []}).encode())
        result = execution.execute_timing(self.request())
        self.assertEqual("failed", result["status"])
        run = self.load_run()
        self.assertEqual({"att-timing-1"}, set(run["attempts"]))
        attempt = run["attempts"]["att-timing-1"]
        self.assertEqual("failed", attempt["reported_execution_outcome"])
        self.assertEqual([], attempt["output_artifact_ids"])
        self.assertTrue(attempt["error"])
        self.assertNotIn("timing-1", run["artifacts"])
        self.assertNotIn("captions-1", run["artifacts"])
        self.assertFalse(os.path.exists(os.path.join(self.project, "word-timings.json")))
        self.assertFalse(os.path.exists(os.path.join(self.project, "captions.json")))

    def test_failure_has_no_automatic_retry(self):
        self.write("provider.json", json.dumps({"words": []}).encode())
        execution.execute_timing(self.request())
        self.assertEqual(1, len(self.load_run()["attempts"]))
        self.assertFalse(os.path.exists(
            execution.execution_lock_path(self.ws, "proj", "run-1")))


class TestOverwriteAndConcurrency(LifecycleBase):
    def test_rerun_same_request_does_not_overwrite(self):
        execution.execute_timing(self.request())
        with open(os.path.join(self.project, "word-timings.json"), "rb") as fh:
            before = fh.read()
        with self.assertRaises(contracts.ContractError):
            execution.execute_timing(self.request())
        run = self.load_run()
        self.assertEqual({"att-timing-1"}, set(run["attempts"]))
        with open(os.path.join(self.project, "word-timings.json"), "rb") as fh:
            self.assertEqual(before, fh.read())

    def test_new_attempt_same_output_path_does_not_overwrite(self):
        execution.execute_timing(self.request())
        with open(os.path.join(self.project, "word-timings.json"), "rb") as fh:
            before = fh.read()
        with self.assertRaises(contracts.ContractError):
            execution.execute_timing(self.request(
                attempt_id="att-rerun", output_timing_artifact_id="timing-rerun"))
        run = self.load_run()
        self.assertEqual({"att-timing-1"}, set(run["attempts"]))
        with open(os.path.join(self.project, "word-timings.json"), "rb") as fh:
            self.assertEqual(before, fh.read())

    def test_concurrent_execution_fails_safely(self):
        lock_path = execution.execution_lock_path(self.ws, "proj", "run-1")
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        with open(lock_path, "w", encoding="utf-8") as fh:
            fh.write("held")
        try:
            with self.assertRaises(contracts.ConcurrentWriterError):
                execution.execute_timing(self.request())
            self.assertEqual({}, self.load_run()["attempts"])
        finally:
            os.unlink(lock_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
