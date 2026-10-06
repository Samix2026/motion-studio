"""Unit B (Increment 1): request validation and the narrow execution boundary."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from studio import contracts, execution, execution_process, manifest  # noqa: E402

TS = "2026-01-01T00:00:00+00:00"

_PROVIDER_RESPONSE = {
    "words": [
        {"word": "hello", "start_ms": 0, "end_ms": 500},
        {"word": "world", "start_ms": 600, "end_ms": 1200},
    ],
    "audio_duration_ms": 2000,
}


class ExecutionBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ub-exec-")
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
            workspace=self.ws, project_id="proj", run_id="run-1", attempt_id="att-1",
            input_artifact_ids=("narration-1", "provider-1"),
            provider_response_artifact_id="provider-1",
            output_timing_artifact_id="timing-1", output_timing_path="word-timings.json",
            confirm=True)
        kwargs.update(over)
        return execution.TimingExecutionRequest(**kwargs)

    def attempts(self):
        return manifest.load_run(self.ws, "proj", "run-1")["attempts"]

    def artifacts(self):
        return manifest.load_run(self.ws, "proj", "run-1")["artifacts"]

    def assert_no_side_effects(self):
        self.assertEqual({}, self.attempts())
        self.assertNotIn("timing-1", self.artifacts())
        self.assertFalse(os.path.exists(os.path.join(self.project, "word-timings.json")))
        self.assertFalse(os.path.exists(execution.execution_lock_path(self.ws, "proj", "run-1")))


class TestProcessBoundary(ExecutionBase):
    def test_local_file_rejects_remote_and_pseudo(self):
        for value in ("http://x/p.json", "https://x/p.json", "rtsp://x", "concat:a.json",
                      "pipe:0", "//host/share.json", "-weird.json"):
            with self.assertRaises(execution_process.ExecutionProcessError):
                execution_process.ensure_local_file(value)

    def test_local_file_rejects_missing(self):
        with self.assertRaises(execution_process.ExecutionProcessError):
            execution_process.ensure_local_file(os.path.join(self.project, "absent.json"))

    def test_load_json_rejects_non_object_and_malformed(self):
        bad = self.write("bad.json", b"[1, 2, 3]")
        with self.assertRaises(execution_process.ExecutionProcessError):
            execution_process.load_json_file(bad)
        broken = self.write("broken.json", b"{not json")
        with self.assertRaises(execution_process.ExecutionProcessError):
            execution_process.load_json_file(broken)

    def test_timeout_must_be_finite_positive(self):
        for bad in (None, 0, -1, float("inf"), float("nan"), True, "10"):
            with self.assertRaises(execution_process.ExecutionProcessError):
                execution_process.validate_timeout(bad)
        self.assertEqual(2.5, execution_process.validate_timeout(2.5))

    def test_unsupported_provider_rejected(self):
        with self.assertRaises(execution_process.ExecutionProcessError):
            execution_process.normalize_timing("nope", os.path.join(self.project, "provider.json"))

    def test_write_json_atomic_refuses_overwrite(self):
        target = os.path.join(self.project, "out.json")
        execution_process.write_json_atomic(target, {"a": 1})
        with self.assertRaises(execution_process.ExecutionProcessError):
            execution_process.write_json_atomic(target, {"a": 2})


class TestRequestValidation(ExecutionBase):
    def test_unsupported_stage_rejected_before_side_effects(self):
        with self.assertRaises(execution.ExecutionError):
            execution.execute_timing(self.request(stage_id="render"))
        self.assert_no_side_effects()

    def test_confirmation_required(self):
        with self.assertRaises(execution.ExecutionError):
            execution.execute_timing(self.request(confirm=False))
        self.assert_no_side_effects()

    def test_invalid_timeout_rejected(self):
        with self.assertRaises(execution.ExecutionError):
            execution.execute_timing(self.request(timeout_seconds=0))
        self.assert_no_side_effects()

    def test_unsupported_provider_rejected(self):
        with self.assertRaises(execution.ExecutionError):
            execution.execute_timing(self.request(provider="unknown"))
        self.assert_no_side_effects()

    def test_missing_input_artifact_rejected(self):
        with self.assertRaises(contracts.UnknownReferenceError):
            execution.execute_timing(self.request(input_artifact_ids=("narration-1", "ghost-1"),
                                                  provider_response_artifact_id="ghost-1"))
        self.assert_no_side_effects()

    def test_provider_response_must_be_an_input(self):
        with self.assertRaises(execution.ExecutionError):
            execution.execute_timing(self.request(input_artifact_ids=("narration-1",)))
        self.assert_no_side_effects()

    def test_required_narration_input_enforced(self):
        with self.assertRaises(execution.ExecutionError):
            execution.execute_timing(self.request(input_artifact_ids=("provider-1",)))
        self.assert_no_side_effects()

    def test_existing_output_file_refused(self):
        self.write("word-timings.json", b"{}")
        with self.assertRaises(execution.ExecutionError):
            execution.execute_timing(self.request())
        self.assertEqual({}, self.attempts())
        self.assertNotIn("timing-1", self.artifacts())

    def test_existing_artifact_id_refused(self):
        with self.assertRaises(contracts.DuplicateIdentityError):
            execution.execute_timing(self.request(output_timing_artifact_id="narration-1"))
        self.assert_no_side_effects()

    def test_output_path_traversal_rejected(self):
        with self.assertRaises(contracts.PathSafetyError):
            execution.execute_timing(self.request(output_timing_path="../escape.json"))
        self.assert_no_side_effects()

    def test_duplicate_attempt_id_refused(self):
        manifest.record_attempt(self.ws, "proj", "run-1", "att-existing", "timing", "external",
                                "failed", created_at=TS)
        with self.assertRaises(contracts.DuplicateIdentityError):
            execution.execute_timing(self.request(attempt_id="att-existing"))
        self.assertEqual({"att-existing"}, set(self.attempts()))


class TestOfflineBoundary(unittest.TestCase):
    def test_execution_modules_have_no_network_or_subprocess(self):
        studio = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        banned = ("import socket", "import urllib", "import requests", "http.client",
                  "import subprocess", "subprocess.", "os.system", "shell=True", "urlopen")
        for name in ("execution.py", "execution_process.py"):
            with open(os.path.join(studio, name), "r", encoding="utf-8") as fh:
                src = fh.read()
            for token in banned:
                self.assertNotIn(token, src, "%s must not contain %r" % (name, token))


if __name__ == "__main__":
    unittest.main(verbosity=2)
