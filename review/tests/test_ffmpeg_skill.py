"""Phase 1 tests for the optional ffmpeg-skill measurement/evidence layer.

Run:  python3 -m unittest discover -s review/tests -v

These tests build a local, pinned ffmpeg-skill fixture (package.json version
1.25.0 + fake scripts). No npm, npx, or network is used anywhere.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_ROOT)
sys.path.insert(0, _REPO)

from review import ffmpeg_skill as fs  # noqa: E402
from review import process  # noqa: E402

FAKE_SCRIPT = r'''
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "_behavior.json"), encoding="utf-8") as fh:
    beh = json.load(fh)
if beh.get("sleep"):
    time.sleep(beh["sleep"])
if "raw" in beh:
    sys.stdout.write(beh["raw"])
    sys.stderr.write(beh.get("raw_err", ""))
    sys.exit(beh.get("rc", 0))
op = os.path.basename(sys.argv[0])
if op == "_contract.py":
    sys.stdout.write(json.dumps(beh.get("doctor", {})))
elif op == "probe.py":
    sys.stdout.write(json.dumps(beh.get("probe", {})))
elif op == "check.py":
    sys.stdout.write(json.dumps(beh.get("check", {})))
    sys.exit(beh.get("check_rc", 0))
elif op == "look.py":
    out = sys.argv[sys.argv.index("-o") + 1]
    if beh.get("look_write", True):
        with open(out, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")
    sys.stderr.write(beh.get("look_err", ""))
    sys.stdout.write(json.dumps({"outputs": [os.path.basename(out)]}))
    sys.exit(beh.get("look_rc", 0))
'''

DEFAULT_DOCTOR = {
    "ok": True, "available": ["filter:drawtext", "filter:subtitles"],
    "missing": [], "missing_optional": [], "unknown": [], "detection": {},
    "errors": [], "gpu_encoders": {}, "tools": {"caption": {"usable": "yes"}},
    "fonts": {"scripts": {"ar": {"status": "available", "file": "NotoNaskhArabic.ttf"}}},
}
DEFAULT_PROBE = {
    "file": "video.mp4", "duration": 1.0,
    "video": {"codec": "h264", "variable_frame_rate_suspected": False,
              "hdr": False, "hdr_format": None, "dolby_vision": None,
              "bit_depth": 8, "rotation": 0, "color_space": "bt709",
              "color_primaries": "bt709", "color_transfer": "bt709",
              "color_range": "tv"},
    "subtitle_streams": [], "audio_streams": [],
}
DEFAULT_CHECK = {"platform": "reels", "checks": [], "failed": 0, "warnings": 0, "ok": True}


class FakeProc:
    def __init__(self, stdout=b"", stderr=b"", rc=0, hang=False):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = rc
        self._hang = hang
        self.killed = False

    def wait(self, timeout=None):
        if self._hang:
            raise subprocess.TimeoutExpired(cmd="skill", timeout=timeout)
        return self.returncode

    def kill(self):
        self.killed = True


def make_skill(root: str, **behavior) -> str:
    scripts = os.path.join(root, "scripts")
    os.makedirs(scripts, exist_ok=True)
    for name in ("_contract.py", "probe.py", "check.py", "look.py"):
        with open(os.path.join(scripts, name), "w", encoding="utf-8") as fh:
            fh.write(FAKE_SCRIPT)
    with open(os.path.join(scripts, "_behavior.json"), "w", encoding="utf-8") as fh:
        json.dump(behavior, fh)
    with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": "ffmpeg-skill", "version": behavior.get("version", fs.SKILL_VERSION)}, fh)
    return root


class SkillTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ffskill-")
        self.reports = os.path.join(self.tmp, "reports")
        self.vision_inputs = os.path.join(self.tmp, "vision_inputs")
        self._p1 = mock.patch.object(fs, "REPORTS_DIR", self.reports)
        self._p2 = mock.patch.object(fs, "_VISION_INPUTS_DIR", self.vision_inputs)
        self._p1.start()
        self._p2.start()
        self.addCleanup(self._p1.stop)
        self.addCleanup(self._p2.stop)

        self.project = os.path.join(self.tmp, "my-proj")
        os.makedirs(os.path.join(self.project, "renders"))
        self.render = os.path.join(self.project, "renders", "video.mp4")
        with open(self.render, "wb") as fh:
            fh.write(b"RENDER-BYTES-DO-NOT-TOUCH")

        self.skill = make_skill(
            os.path.join(self.tmp, "ffmpeg-skill"),
            doctor=DEFAULT_DOCTOR, probe=DEFAULT_PROBE, check=DEFAULT_CHECK)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestEvidenceLifecycle(SkillTestBase):
    def test_1_collect_does_not_modify_input(self):
        with open(self.render, "rb") as fh:
            before = fh.read()
        fs.collect_evidence(self.project, skill_root=self.skill)
        with open(self.render, "rb") as fh:
            self.assertEqual(before, fh.read())

    def test_2_never_writes_under_renders(self):
        fs.save_evidence(self.project, fs.collect_evidence(self.project, skill_root=self.skill))
        self.assertEqual(["video.mp4"], sorted(os.listdir(os.path.join(self.project, "renders"))))

    def test_3_rejects_operation_outside_allowlist(self):
        with self.assertRaises(fs.SkillError):
            fs._script_path(self.skill, "cut.py")
        self.assertEqual({"check", "doctor", "look", "probe"}, set(fs.ALLOWED_OPERATIONS))

    def test_8_deterministic_output_names(self):
        first = fs.evidence_path(self.project)
        second = fs.evidence_path(self.project)
        self.assertEqual(first, second)
        self.assertTrue(first.endswith(".skill.json"))
        self.assertTrue(fs.look_evidence_path(self.project).endswith(".skill-look.png"))

    def test_9_existing_evidence_not_overwritten_silently(self):
        evidence = fs.collect_evidence(self.project, skill_root=self.skill)
        fs.save_evidence(self.project, evidence)
        with self.assertRaises(fs.EvidenceExistsError):
            fs.save_evidence(self.project, evidence)
        path = fs.save_evidence(self.project, evidence, overwrite=True)
        self.assertTrue(os.path.isfile(path))


class TestSecurityBoundary(SkillTestBase):
    def test_4_shell_false_and_fixed_argv(self):
        captured = {}

        def fake_popen(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return FakeProc(stdout=json.dumps(DEFAULT_PROBE).encode(), rc=0)

        with mock.patch.object(process.subprocess, "Popen", side_effect=fake_popen):
            fs.run_probe(self.render, skill_root=self.skill, project_dir=self.project)
        self.assertIsInstance(captured["argv"], list)
        self.assertFalse(captured["kwargs"].get("shell", False))
        self.assertEqual(self.skill, captured["kwargs"]["cwd"])
        self.assertEqual("python3", fs._display_argv(captured["argv"], self.skill, self.render,
                                                     "renders/video.mp4")[0])

    def test_5_remote_and_escaping_paths_rejected(self):
        for bad in ("http://example/ffmpeg-skill", "https://e/x", "//host/share"):
            with self.assertRaises(fs.SkillError):
                fs.resolve_skill_root(bad)
        # a symlinked script escaping the root is refused
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "probe.py"), "w", encoding="utf-8") as fh:
            fh.write("print('{}')")
        os.remove(os.path.join(self.skill, "scripts", "probe.py"))
        os.symlink(os.path.join(outside, "probe.py"),
                   os.path.join(self.skill, "scripts", "probe.py"))
        with self.assertRaises(fs.SkillError):
            fs.resolve_skill_root(self.skill)

    def test_6_timeout_enforced(self):
        make_skill(self.skill, sleep=5, probe=DEFAULT_PROBE)
        result = fs.run_probe(self.render, skill_root=self.skill, timeout=1)
        self.assertEqual("failed", result["measurement_status"])
        self.assertEqual(fs.ERR_TIMEOUT, result["error"]["kind"])

    def test_7_stdout_and_stderr_bounded(self):
        make_skill(self.skill, raw="x" * 5000)
        with mock.patch.object(fs, "STDOUT_LIMIT", 64):
            result = fs.run_probe(self.render, skill_root=self.skill)
        self.assertEqual("failed", result["measurement_status"])
        self.assertEqual(fs.ERR_OVERFLOW, result["error"]["kind"])

    def test_platform_must_be_allowlisted(self):
        with self.assertRaises(fs.SkillError):
            fs.run_check(self.render, platform="myspace; rm -rf /", skill_root=self.skill)
        with self.assertRaises(fs.SkillError):
            fs.collect_evidence(self.project, skill_root=self.skill, platform="evil")
        self.assertEqual("reels", fs.normalize_platform("ig"))


class TestFailureBehavior(SkillTestBase):
    def test_10_skill_failure_does_not_break_review(self):
        evidence = fs.collect_evidence(self.project, skill_root=os.path.join(self.tmp, "missing"))
        self.assertEqual("unavailable", evidence["measurement_status"])
        self.assertFalse(evidence["dependency"]["available"])
        self.assertEqual({}, evidence["operations"])

    def test_11_malformed_json_handled_safely(self):
        make_skill(self.skill, raw="{not json", probe=DEFAULT_PROBE)
        result = fs.run_probe(self.render, skill_root=self.skill)
        self.assertEqual("failed", result["measurement_status"])
        self.assertEqual(fs.ERR_JSON, result["error"]["kind"])

    def test_version_mismatch_is_recorded(self):
        make_skill(self.skill, version="1.24.0", probe=DEFAULT_PROBE)
        evidence = fs.collect_evidence(self.project, skill_root=self.skill)
        self.assertFalse(evidence["dependency"]["available"])
        self.assertEqual(fs.ERR_VERSION, evidence["dependency"]["error"]["kind"])

    def test_invalid_media_is_invalid_input(self):
        result = fs.run_probe("http://remote/x.mp4", skill_root=self.skill)
        self.assertEqual("failed", result["measurement_status"])
        self.assertEqual(fs.ERR_INVALID, result["error"]["kind"])

    def test_check_fail_rows_are_evidence_not_findings(self):
        make_skill(self.skill, check={"platform": "reels", "checks": [
            {"check": "duration", "status": "FAIL", "kind": "format"}],
            "failed": 1, "warnings": 0, "ok": False}, check_rc=1)
        result = fs.run_check(self.render, platform="reels", skill_root=self.skill)
        self.assertEqual("complete", result["measurement_status"])
        self.assertEqual(1, result["exit_status"])
        self.assertEqual(1, result["summary"]["failed"])


class TestProvenanceAndEvidence(SkillTestBase):
    def test_12_provenance_records_versions_and_input_hash(self):
        from review import inputs as review_inputs
        evidence = fs.collect_evidence(self.project, skill_root=self.skill)
        prov = evidence["provenance"]
        self.assertEqual(fs.SKILL_VERSION, prov["ffmpeg_skill_version"])
        self.assertEqual(fs.CONTRACT_VERSION, prov["contract_version"])
        self.assertIn("generated_at", prov)
        probe = evidence["operations"]["probe"]
        self.assertEqual(review_inputs.sha256_file(self.render), probe["input"]["sha256"])
        self.assertEqual("renders/video.mp4", probe["input"]["path"])
        self.assertNotIn(self.tmp, json.dumps(evidence))

    def test_13_look_skipped_when_existing_visual_evidence(self):
        snaps = os.path.join(self.project, "snapshots")
        os.makedirs(snaps)
        with open(os.path.join(snaps, "contact-sheet.jpg"), "wb") as fh:
            fh.write(b"jpg")
        evidence = fs.collect_evidence(self.project, skill_root=self.skill, look=True)
        look = evidence["operations"]["look"]
        self.assertEqual("skipped", look["measurement_status"])
        self.assertTrue(look["reason"].startswith("existing_visual_evidence"))
        self.assertFalse(os.path.isfile(fs.look_evidence_path(self.project)))

    def test_look_runs_only_when_requested_and_insufficient(self):
        no_look = fs.collect_evidence(self.project, skill_root=self.skill)
        self.assertNotIn("look", no_look["operations"])
        evidence = fs.collect_evidence(self.project, skill_root=self.skill, look=True)
        self.assertEqual("complete", evidence["operations"]["look"]["measurement_status"])
        self.assertTrue(os.path.isfile(fs.look_evidence_path(self.project)))

    def test_look_output_must_stay_under_reports(self):
        with self.assertRaises(fs.SkillError):
            fs.run_look(self.render, os.path.join(self.tmp, "elsewhere.png"),
                        skill_root=self.skill, project_dir=self.project)

    def test_doctor_reused_from_existing_evidence(self):
        first = fs.collect_evidence(self.project, skill_root=self.skill)
        fs.save_evidence(self.project, first)
        second = fs.collect_evidence(self.project, skill_root=self.skill)
        self.assertEqual("complete", second["operations"]["doctor"]["measurement_status"])
        self.assertTrue(any("doctor reused" in n for n in second["notes"]))

    def test_14_no_findings_or_proposals(self):
        evidence = fs.collect_evidence(self.project, skill_root=self.skill, look=True)
        self.assertNotIn("findings", evidence)
        self.assertNotIn("proposals", evidence)
        with open(fs.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("import reviewer", src)
        self.assertNotIn("proposal_schema", src)

    def test_15_no_mcp_npm_or_package_dependency(self):
        with open(fs.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("npx", src)
        self.assertNotIn("npm install", src)
        self.assertNotIn("mcp", src.lower())
        self.assertFalse(os.path.isfile(os.path.join(_REPO, "package.json")))


class TestPhase1Closure(SkillTestBase):
    """Regression tests for the three Phase 1 closure fixes."""

    def test_structured_failure_json_is_not_complete(self):
        make_skill(self.skill, raw=json.dumps({
            "status": "failed", "exit_code": 1,
            "error": {"kind": "input", "code": "INPUT_INVALID",
                      "message": "input not found: x.mp4", "retryable": False},
            "commands": []}))
        result = fs.run_probe(self.render, skill_root=self.skill)
        self.assertEqual("failed", result["measurement_status"])
        self.assertEqual(fs.ERR_INVALID, result["error"]["kind"])
        self.assertIsInstance(result["output"], dict)          # raw doc preserved
        self.assertEqual("failed", result["output"]["status"])
        self.assertLessEqual(len(result["diagnostic"] or ""), process.DIAGNOSTIC_LIMIT + 32)

    def test_structured_dependency_failure_is_unavailable(self):
        make_skill(self.skill, raw=json.dumps({
            "status": "failed",
            "error": {"kind": "missing_tool", "code": "DEPENDENCY_MISSING",
                      "message": "libx264 not available"},
            "commands": []}))
        result = fs.run_probe(self.render, skill_root=self.skill)
        self.assertEqual("unavailable", result["measurement_status"])
        self.assertEqual(fs.ERR_DEPENDENCY, result["error"]["kind"])

    def test_check_structured_failure_not_complete(self):
        make_skill(self.skill, raw=json.dumps({
            "status": "failed",
            "error": {"kind": "verification", "code": "VERIFICATION_FAILED",
                      "message": "deliverable does not meet platform spec"},
            "platform": "reels", "failed": 1, "warnings": 0, "ok": False,
            "checks": [{"check": "loudness", "status": "FAIL", "kind": "judgement"}]}))
        result = fs.run_check(self.render, platform="reels", skill_root=self.skill)
        self.assertEqual("failed", result["measurement_status"])
        self.assertEqual(fs.ERR_TOOL, result["error"]["kind"])
        self.assertEqual(1, result["summary"]["failed"])       # rows still preserved
        self.assertEqual("reels", result["platform"])

    def test_doctor_ok_false_is_partial_not_complete(self):
        make_skill(self.skill, doctor={
            "ok": False, "missing": ["filter:drawtext", "filter:subtitles"],
            "missing_optional": [], "unknown": [], "tools": {}, "fonts": {}})
        result = fs.run_doctor(skill_root=self.skill)
        self.assertEqual("partial", result["measurement_status"])
        self.assertNotEqual("complete", result["measurement_status"])
        self.assertEqual(fs.ERR_CAPABILITY, result["error"]["kind"])
        self.assertIsInstance(result["output"], dict)          # raw doc preserved
        self.assertFalse(result["relevant"]["ok"])

    def test_doctor_ok_true_still_complete(self):
        result = fs.run_doctor(skill_root=self.skill)
        self.assertEqual("complete", result["measurement_status"])

    def test_look_runtime_capability_failure_is_unavailable(self):
        make_skill(self.skill, look_rc=1, look_write=False,
                   look_err="No such filter: 'drawtext'")
        out = fs.look_evidence_path(self.project)
        result = fs.run_look(self.render, out, skill_root=self.skill, project_dir=self.project)
        self.assertEqual("unavailable", result["measurement_status"])
        self.assertEqual(fs.ERR_CAPABILITY, result["error"]["kind"])
        self.assertFalse(os.path.isfile(out))

    def test_look_capability_failure_does_not_break_base_review(self):
        make_skill(self.skill, look_rc=1, look_write=False,
                   look_err="No such filter: 'drawtext'")
        evidence = fs.collect_evidence(self.project, skill_root=self.skill, look=True)
        self.assertEqual("unavailable", evidence["operations"]["look"]["measurement_status"])
        self.assertNotEqual("complete", evidence["measurement_status"])
        self.assertNotIn("findings", evidence)
        self.assertNotIn("proposals", evidence)


if __name__ == "__main__":
    unittest.main(verbosity=2)
