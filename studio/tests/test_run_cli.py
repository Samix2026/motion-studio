"""Phase 1 CLI tests: legacy compatibility, additive commands, and isolation."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from studio import cli  # noqa: E402
from studio import manifest  # noqa: E402
from studio import run_cli  # noqa: E402

TS = "2026-01-01T00:00:00+00:00"


def dir_hash(path: str) -> str:
    h = hashlib.sha256()
    for base, _d, names in os.walk(path):
        for n in sorted(names):
            p = os.path.join(base, n)
            h.update(os.path.relpath(p, path).encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


class CliBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="studio-cli-")
        self.ws = os.path.realpath(os.path.join(self.tmp, "ws"))
        self.project = os.path.join(self.ws, "videos", "proj")
        os.makedirs(os.path.join(self.project, "renders"))
        with open(os.path.join(self.project, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<html></html>")
        with open(os.path.join(self.project, "renders", "video.mp4"), "wb") as fh:
            fh.write(b"AAAA")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def invoke(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def register_project(self):
        code, _o, _e = self.invoke(["project-register", "--workspace", self.ws,
                                    "--project-id", "proj", "--project-dir", "videos/proj",
                                    "--at", TS])
        self.assertEqual(0, code)

    def create_run(self, rid="run-1", narration=False):
        argv = ["run-create", "--workspace", self.ws, "--project-id", "proj",
                "--run-id", rid, "--revision", "rev1", "--revision-dir", "videos/proj",
                "--at", TS]
        if narration:
            argv.append("--narration")
        code, _o, _e = self.invoke(argv)
        self.assertEqual(0, code)


class TestLegacyCompatibility(CliBase):
    def test_status_parsing_unchanged(self):
        args = cli.build_parser().parse_args(
            ["status", "videos/proj", "--reference", "r1", "--plan", "p.json",
             "--pricing", "pricing.json", "--require-cost-approval"])
        self.assertEqual("cmd_status", args.func.__name__)
        self.assertEqual("videos/proj", args.project)
        self.assertEqual("r1", args.reference)
        self.assertTrue(args.require_cost_approval)

    def test_new_commands_are_additive(self):
        parser = cli.build_parser()
        for name, attr in [
            ("project-register", "cmd_project_register"),
            ("run-create", "cmd_run_create"),
            ("artifact-register", "cmd_artifact_register"),
            ("attempt-record", "cmd_attempt_record"),
            ("validation-record", "cmd_validation_record"),
            ("historical-reference", "cmd_historical_reference"),
            ("manifest-validate", "cmd_manifest_validate"),
            ("run-status", "cmd_run_status"),
            ("run-history", "cmd_run_history"),
        ]:
            self.assertTrue(hasattr(run_cli, attr), attr)
            self.assertIn(name, parser.format_help())


class TestLifecycle(CliBase):
    def _build_valid_run(self):
        self.register_project()
        self.create_run()
        code, _o, _e = self.invoke(["attempt-record", "--workspace", self.ws,
                                    "--project-id", "proj", "--run-id", "run-1",
                                    "--attempt-id", "att-comp", "--stage", "composition",
                                    "--origin", "external", "--outcome", "succeeded",
                                    "--output", "comp-1", "--at", TS])
        self.assertEqual(0, code)
        code, _o, _e = self.invoke(["artifact-register", "--workspace", self.ws,
                                    "--project-id", "proj", "--run-id", "run-1",
                                    "--artifact-id", "comp-1", "--kind", "composition",
                                    "--root", "project", "--path", "index.html",
                                    "--producer-attempt", "att-comp", "--at", TS])
        self.assertEqual(0, code)
        code, _o, _e = self.invoke(["attempt-record", "--workspace", self.ws,
                                    "--project-id", "proj", "--run-id", "run-1",
                                    "--attempt-id", "att-render", "--stage", "render",
                                    "--origin", "external", "--outcome", "succeeded",
                                    "--input", "comp-1", "--output", "render-1",
                                    "--at", TS])
        self.assertEqual(0, code)
        code, _o, _e = self.invoke(["artifact-register", "--workspace", self.ws,
                                    "--project-id", "proj", "--run-id", "run-1",
                                    "--artifact-id", "render-1", "--kind", "render",
                                    "--root", "project", "--path", "renders/video.mp4",
                                    "--producer-attempt", "att-render", "--at", TS])
        self.assertEqual(0, code)

    def test_full_recording_lifecycle(self):
        self._build_valid_run()
        code, out, _e = self.invoke(["manifest-validate", "--workspace", self.ws,
                                     "--project-id", "proj", "--run-id", "run-1"])
        self.assertEqual(0, code)
        self.assertTrue(json.loads(out)["valid"])
        code, out, _e = self.invoke(["run-status", "--workspace", self.ws,
                                     "--project-id", "proj", "--run-id", "run-1"])
        self.assertEqual(0, code)
        report = json.loads(out)
        self.assertTrue(report["reference_validity"])
        states = {a["artifact_id"]: a["state"] for a in report["artifacts"]}
        self.assertEqual("ok", states["render-1"])

    def test_error_exit_code_on_contract_failure(self):
        self.register_project()
        self.create_run()
        code, _o, _e = self.invoke(["artifact-register", "--workspace", self.ws,
                                    "--project-id", "proj", "--run-id", "run-1",
                                    "--artifact-id", "dup", "--kind", "render",
                                    "--root", "project", "--path", "renders/video.mp4",
                                    "--legacy-external", "--at", TS])
        self.assertEqual(0, code)
        code, _o, _e = self.invoke(["artifact-register", "--workspace", self.ws,
                                    "--project-id", "proj", "--run-id", "run-1",
                                    "--artifact-id", "dup", "--kind", "render",
                                    "--root", "project", "--path", "renders/video.mp4",
                                    "--legacy-external", "--at", TS])
        self.assertEqual(1, code)


class TestUsageErrors(CliBase):
    def test_malformed_usage_is_concise_and_writes_nothing(self):
        self.register_project()
        self.create_run()
        code, _o, err = self.invoke(["attempt-record", "--workspace", self.ws,
                                     "--project-id", "proj", "--run-id", "run-1",
                                     "--attempt-id", "att-1", "--stage", "composition",
                                     "--origin", "external", "--outcome", "failed",
                                     "--usage", "{", "--at", TS])
        self.assertEqual(1, code)
        self.assertIn("ERROR:", err)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("{", err)
        run = manifest.load_run(self.ws, "proj", "run-1")
        self.assertEqual({}, run["attempts"])

    def test_wrong_type_usage_fails_through_contract(self):
        self.register_project()
        self.create_run()
        code, _o, err = self.invoke(["attempt-record", "--workspace", self.ws,
                                     "--project-id", "proj", "--run-id", "run-1",
                                     "--attempt-id", "att-1", "--stage", "composition",
                                     "--origin", "external", "--outcome", "failed",
                                     "--usage", "[1, 2]", "--at", TS])
        self.assertEqual(1, code)
        self.assertIn("ERROR:", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual({}, manifest.load_run(self.ws, "proj", "run-1")["attempts"])


class TestIsolation(CliBase):
    def test_run_status_is_read_only(self):
        self.register_project()
        self.create_run()
        runs_before = dir_hash(os.path.join(self.ws, "runs"))
        project_before = dir_hash(self.project)
        self.invoke(["run-status", "--workspace", self.ws, "--project-id", "proj",
                     "--run-id", "run-1"])
        self.invoke(["run-history", "--workspace", self.ws])
        self.assertEqual(runs_before, dir_hash(os.path.join(self.ws, "runs")))
        self.assertEqual(project_before, dir_hash(self.project))

    def test_recording_evidence_does_not_approve(self):
        self.register_project()
        self.create_run()
        os.makedirs(os.path.join(self.ws, "runs"), exist_ok=True)
        legacy = os.path.join(self.ws, "runs", "gate-evidence.json")
        with open(legacy, "w", encoding="utf-8") as fh:
            fh.write("{}")
        code, _o, _e = self.invoke(["artifact-register", "--workspace", self.ws,
                                    "--project-id", "proj", "--run-id", "run-1",
                                    "--artifact-id", "gate-ev", "--kind", "validation_evidence",
                                    "--root", "workspace", "--path", "runs/gate-evidence.json",
                                    "--legacy-external", "--at", TS])
        self.assertEqual(0, code)
        code, _o, _e = self.invoke(["validation-record", "--workspace", self.ws,
                                    "--project-id", "proj", "--run-id", "run-1",
                                    "--validation-id", "val-1", "--validator", "costgate",
                                    "--validator-version", "1", "--evidence-ref",
                                    "costgate/state/gate.json", "--evidence-artifact", "gate-ev",
                                    "--result", "passed", "--scope", "cost", "--at", TS])
        self.assertEqual(0, code)
        code, out, _e = self.invoke(["run-status", "--workspace", self.ws,
                                     "--project-id", "proj", "--run-id", "run-1"])
        report = json.loads(out)
        self.assertNotIn("ready_to_publish", report)
        self.assertNotIn("approved", report)
        self.assertFalse(os.path.exists(os.path.join(self.project, "meta.json")))

    def test_recording_modules_do_not_execute_externally(self):
        root = os.path.dirname(os.path.abspath(__file__))
        studio = os.path.dirname(root)
        banned = ("subprocess", "os.system", "os.popen", "import socket", "import urllib",
                  "import requests", "http.client", "urlopen")
        for name in ("contracts.py", "artifacts.py", "manifest.py", "run_cli.py"):
            with open(os.path.join(studio, name), "r", encoding="utf-8") as fh:
                text = fh.read()
            for token in banned:
                self.assertNotIn(token, text, "%s must not reference %r" % (name, token))


class TestManifestValidateScope(CliBase):
    def build(self):
        self.register_project()
        self.create_run()
        self.invoke(["attempt-record", "--workspace", self.ws, "--project-id", "proj",
                     "--run-id", "run-1", "--attempt-id", "att-comp", "--stage",
                     "composition", "--origin", "external", "--outcome", "succeeded",
                     "--output", "comp-1", "--at", TS])
        self.invoke(["artifact-register", "--workspace", self.ws, "--project-id", "proj",
                     "--run-id", "run-1", "--artifact-id", "comp-1", "--kind", "composition",
                     "--root", "project", "--path", "index.html", "--producer-attempt",
                     "att-comp", "--at", TS])
        self.invoke(["attempt-record", "--workspace", self.ws, "--project-id", "proj",
                     "--run-id", "run-1", "--attempt-id", "att-render", "--stage", "render",
                     "--origin", "external", "--outcome", "succeeded", "--input", "comp-1",
                     "--output", "render-1", "--at", TS])
        self.invoke(["artifact-register", "--workspace", self.ws, "--project-id", "proj",
                     "--run-id", "run-1", "--artifact-id", "render-1", "--kind", "render",
                     "--root", "project", "--path", "renders/video.mp4", "--producer-attempt",
                     "att-render", "--at", TS])
        os.makedirs(os.path.join(self.ws, "runs"), exist_ok=True)
        evidence = os.path.join(self.ws, "runs", "gate-evidence.json")
        with open(evidence, "w", encoding="utf-8") as fh:
            fh.write("{}")
        self.invoke(["artifact-register", "--workspace", self.ws, "--project-id", "proj",
                     "--run-id", "run-1", "--artifact-id", "gate-ev",
                     "--kind", "validation_evidence", "--root", "workspace",
                     "--path", "runs/gate-evidence.json", "--legacy-external", "--at", TS])
        self.invoke(["validation-record", "--workspace", self.ws, "--project-id", "proj",
                     "--run-id", "run-1", "--validation-id", "val-1", "--validator", "ffprobe",
                     "--validator-version", "6.0", "--evidence-ref", "runs/gate-evidence.json",
                     "--evidence-artifact", "gate-ev", "--result", "passed", "--scope",
                     "render", "--at", TS])

    def test_valid_reports_each_scope(self):
        self.build()
        code, out, _err = self.invoke(["manifest-validate", "--workspace", self.ws,
                                       "--project-id", "proj", "--run-id", "run-1"])
        self.assertEqual(0, code)
        report = json.loads(out)
        for key in ("valid", "structural_validity", "reference_validity",
                    "relationship_validity", "stage_contract_validity",
                    "validation_evidence_integrity"):
            self.assertTrue(report[key], key)
        self.assertEqual("not_checked", report["production_artifact_integrity"])
        self.assertIn("run-status", report["artifact_integrity_note"])

    def test_changed_production_artifact_is_not_checked_here(self):
        self.build()
        with open(os.path.join(self.project, "renders", "video.mp4"), "wb") as fh:
            fh.write(b"ZZZZ")
        code, out, _err = self.invoke(["manifest-validate", "--workspace", self.ws,
                                       "--project-id", "proj", "--run-id", "run-1"])
        self.assertEqual(0, code)
        self.assertEqual("not_checked", json.loads(out)["production_artifact_integrity"])
        code, out, _err = self.invoke(["run-status", "--workspace", self.ws,
                                       "--project-id", "proj", "--run-id", "run-1"])
        self.assertEqual(0, code)
        states = {a["artifact_id"]: a["state"] for a in json.loads(out)["artifacts"]}
        self.assertEqual("changed", states["render-1"])

    def test_changed_validation_evidence_fails(self):
        self.build()
        with open(os.path.join(self.ws, "runs", "gate-evidence.json"), "w",
                  encoding="utf-8") as fh:
            fh.write('{"changed": true}')
        code, _out, err = self.invoke(["manifest-validate", "--workspace", self.ws,
                                       "--project-id", "proj", "--run-id", "run-1"])
        self.assertEqual(1, code)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
