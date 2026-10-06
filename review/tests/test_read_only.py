"""Unit A: read-only separation and freshness-aware consumers.

Run:  python3 -m unittest discover -s review/tests -v
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from costgate import gate as cost_gate  # noqa: E402
from narration import plan as nar_plan  # noqa: E402
from reference import analyzer as ref_analyzer  # noqa: E402
from review import analyzer, inputs as review_inputs, revision  # noqa: E402
from review import cli as review_cli  # noqa: E402
from studio import status as studio_status  # noqa: E402
from timing import schema as timing_schema  # noqa: E402

_FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "mini_project")


def tree_hash(path: str) -> str:
    h = hashlib.sha256()
    for base, _dirs, names in os.walk(path):
        for n in sorted(names):
            p = os.path.join(base, n)
            h.update(os.path.relpath(p, path).encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


class ReadOnlyBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="readonly-")
        self.project = os.path.join(self.tmp, "proj")
        shutil.copytree(_FIXTURE, self.project)
        self._saved = (revision._STATE_DIR, cost_gate._STATE_DIR, cost_gate._REPORT_DIR,
                       ref_analyzer._PROFILE_DIR, ref_analyzer._REPORT_DIR)
        revision._STATE_DIR = os.path.join(self.tmp, "review-state")
        cost_gate._STATE_DIR = os.path.join(self.tmp, "cost-state")
        cost_gate._REPORT_DIR = os.path.join(self.tmp, "cost-reports")
        ref_analyzer._PROFILE_DIR = os.path.join(self.tmp, "ref-profiles")
        ref_analyzer._REPORT_DIR = os.path.join(self.tmp, "ref-reports")

    def tearDown(self):
        (revision._STATE_DIR, cost_gate._STATE_DIR, cost_gate._REPORT_DIR,
         ref_analyzer._PROFILE_DIR, ref_analyzer._REPORT_DIR) = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestNoInitialization(ReadOnlyBase):
    def test_analyze_creates_no_state(self):
        analyzer.analyze(self.project)
        self.assertFalse(os.path.exists(revision._STATE_DIR))

    def test_narration_plan_creates_no_state_or_reports(self):
        reports = os.path.join(_ROOT, "reports")
        before = sorted(os.listdir(reports))
        nar_plan.plan(self.project)
        self.assertFalse(os.path.exists(revision._STATE_DIR))
        self.assertEqual(before, sorted(os.listdir(reports)))

    def test_review_status_read_path_creates_no_state(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = review_cli.main(["status", self.project])
        self.assertEqual(0, code)
        self.assertIn("project: proj", out.getvalue())
        self.assertFalse(os.path.exists(revision._STATE_DIR))
        with redirect_stdout(io.StringIO()):
            review_cli.main(["report", self.project])
        self.assertFalse(os.path.exists(revision._STATE_DIR))

    def test_studio_status_creates_no_state_anywhere(self):
        studio_status.inspect(self.project)
        for d in (revision._STATE_DIR, cost_gate._STATE_DIR, cost_gate._REPORT_DIR,
                  ref_analyzer._PROFILE_DIR, ref_analyzer._REPORT_DIR):
            self.assertFalse(os.path.exists(d), d)

    def test_studio_status_read_only_across_workspace(self):
        before = tree_hash(self.tmp)
        studio_status.inspect(self.project)
        self.assertEqual(before, tree_hash(self.tmp))


class TestReportFreshnessConsumer(ReadOnlyBase):
    def _write_report(self, doc):
        root = os.path.join(self.tmp, "root")
        reports = os.path.join(root, "review", "reports")
        os.makedirs(reports, exist_ok=True)
        key = revision.state_key(self.project)
        path = os.path.join(reports, "%s-rev1.json" % key)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return root

    def _clean(self, root):
        original = nar_plan._ROOT
        nar_plan._ROOT = root
        try:
            return nar_plan._latest_review_clean(self.project)
        finally:
            nar_plan._ROOT = original

    def _current_report(self, coverage="complete", findings=None):
        report = analyzer.analyze(self.project)
        report["measurement_status"] = {"caption_audio_sync": coverage}
        report["findings"] = findings or []
        return report

    def test_current_clean_available_counts_as_clean(self):
        root = self._write_report(self._current_report("complete"))
        self.assertIs(True, self._clean(root))

    def test_current_but_unavailable_is_not_clean(self):
        root = self._write_report(self._current_report("unavailable"))
        self.assertIsNone(self._clean(root))

    def test_current_but_partial_is_not_clean(self):
        root = self._write_report(self._current_report("partial"))
        self.assertIsNone(self._clean(root))

    def test_current_with_caption_finding_is_not_clean(self):
        root = self._write_report(self._current_report(
            "complete", [{"category": "caption_audio_sync"}]))
        self.assertIs(False, self._clean(root))

    def test_stale_report_is_not_current(self):
        report = self._current_report("complete")
        report["review_fingerprint"] = "0" * 64
        root = self._write_report(report)
        self.assertIsNone(self._clean(root))

    def test_old_report_without_descriptor_is_unverified(self):
        root = self._write_report({"findings": []})
        self.assertIsNone(self._clean(root))

    def test_missing_caption_evidence_is_not_clean(self):
        report = self._current_report("complete")
        del report["measurement_status"]
        root = self._write_report(report)
        self.assertIsNone(self._clean(root))

    def test_malformed_report_is_not_clean(self):
        root = self._write_report(["not", "an", "object"])
        self.assertIsNone(self._clean(root))


class TestNoReviewOrTTS(ReadOnlyBase):
    def _narration_project(self):
        project = os.path.join(self.tmp, "narr")
        os.makedirs(os.path.join(project, "renders"))
        html = ("<!doctype html><html lang=\"ar\"><head><meta charset=\"UTF-8\"></head><body>"
                "<div id=\"root\" data-composition-id=\"main\" data-start=\"0\" "
                "data-duration=\"5\" data-fps=\"30\" data-width=\"1920\" data-height=\"1080\">"
                "<audio id=\"nar\" src=\"narration.mp3\" data-start=\"0\" data-duration=\"5\" "
                "data-volume=\"1\"></audio>"
                "<section id=\"s1\" class=\"clip\" data-start=\"0\" data-duration=\"5\" "
                "data-narration-locked=\"true\"><h1 id=\"a\">عنوان</h1></section>"
                "</div></body></html>")
        with open(os.path.join(project, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        with open(os.path.join(project, "meta.json"), "w", encoding="utf-8") as fh:
            json.dump({"narration": "required"}, fh)
        with open(os.path.join(project, "narration.mp3"), "wb") as fh:
            fh.write(b"ID3\x04\x00\x00\x00\x00\x00\x00")
        words = [{"word": "مرحبا", "start_ms": 0, "end_ms": 1500, "confidence": None}]
        with open(os.path.join(project, "word-timings.json"), "w", encoding="utf-8") as fh:
            json.dump(timing_schema.make("elevenlabs", 5000, words), fh)
        with open(os.path.join(project, "captions.json"), "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "captions": [
                {"start_ms": 0, "end_ms": 1500, "text": "مرحبا"}]}, fh)
        return project

    def test_plan_does_not_call_review_or_tts(self):
        from timing import adapter as timing_adapter
        project = self._narration_project()
        before = tree_hash(project)
        with mock.patch.object(analyzer, "analyze",
                               side_effect=AssertionError("planning must not run review")), \
                mock.patch.object(timing_adapter, "normalize",
                                  side_effect=AssertionError("planning must not call TTS")):
            doc = nar_plan.plan(project)
        self.assertIn("steps", doc)
        self.assertEqual(before, tree_hash(project))
        self.assertFalse(os.path.exists(revision._STATE_DIR))


class TestLegacyCli(ReadOnlyBase):
    def test_legacy_review_command_still_available(self):
        args = review_cli.build_parser().parse_args(["review", self.project])
        self.assertEqual("cmd_review", args.func.__name__)
        self.assertIsNone(args.render)
        self.assertIsNone(args.composition)
        os.makedirs(os.path.join(self.project, "renders"), exist_ok=True)
        with open(os.path.join(self.project, "renders", "video.mp4"), "wb") as fh:
            fh.write(b"AAAA")
        self.assertTrue(analyzer._render_path(self.project).endswith("video.mp4"))


class TestProductionUntouched(ReadOnlyBase):
    def test_read_paths_do_not_change_repo_review_records(self):
        roots = [os.path.join(_ROOT, name) for name in ("reports", "proposals", "state")]
        before = {r: tree_hash(r) for r in roots if os.path.isdir(r)}
        analyzer.analyze(self.project)
        nar_plan.plan(self.project)
        studio_status.inspect(self.project)
        for r, digest in before.items():
            self.assertEqual(digest, tree_hash(r), r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
