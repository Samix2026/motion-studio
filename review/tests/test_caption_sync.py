"""Phase C review-integration tests: real caption/audio sync from word timings.

The deterministic analyzer must produce caption-sync findings only from real
word timings, and must stay `unavailable` otherwise. It never mutates a project.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from review import analyzer, proposal_schema, revision  # noqa: E402
from timing import adapter as timing_adapter  # noqa: E402
from timing import schema as timing_schema  # noqa: E402

_FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "mini_project")


def dir_hash(path: str) -> str:
    h = hashlib.sha256()
    for root, _dirs, files in os.walk(path):
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            h.update(os.path.relpath(fp, path).encode())
            with open(fp, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


class CaptionSyncBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="capsync-")
        self.project = os.path.join(self.tmp, "proj")
        shutil.copytree(_FIXTURE, self.project)
        self._orig = revision._STATE_DIR
        revision._STATE_DIR = os.path.join(self.tmp, "state")
        os.makedirs(revision._STATE_DIR, exist_ok=True)

    def tearDown(self):
        revision._STATE_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_timings(self, triples, provider="elevenlabs", duration_ms=5000):
        words = [{"word": w, "start_ms": s, "end_ms": e, "confidence": None}
                 for (w, s, e) in triples]
        doc = timing_schema.make(provider, duration_ms, words)
        with open(os.path.join(self.project, "word-timings.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

    def write_captions(self, captions):
        with open(os.path.join(self.project, "captions.json"), "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "captions": captions}, fh)

    def analyze(self):
        return analyzer.analyze(self.project)

    def caption_findings(self, report):
        return [f for f in report["findings"] if f["category"] == "caption_audio_sync"]


class TestCaptionSyncFindings(CaptionSyncBase):
    def test_detects_caption_ending_before_phrase(self):
        self.write_timings([("hello", 0, 500), ("world", 600, 1200)])
        self.write_captions([{"start_ms": 0, "end_ms": 800, "text": "hello world"}])
        findings = self.caption_findings(self.analyze())
        self.assertEqual(1, len(findings))
        f = findings[0]
        proposal_schema.validate_finding(f)
        self.assertEqual("milliseconds", f["evidence"]["unit"])
        self.assertEqual(400.0, f["evidence"]["measured_value"])
        self.assertIn("ends 400ms before", f["description"])
        self.assertEqual("word-timings+captions", f["evidence"]["source"])

    def test_detects_caption_beginning_too_early(self):
        self.write_timings([("hello", 700, 1100)])
        self.write_captions([{"start_ms": 0, "end_ms": 1100, "text": "hello"}])
        findings = self.caption_findings(self.analyze())
        self.assertEqual(1, len(findings))
        self.assertEqual(700.0, findings[0]["evidence"]["measured_value"])
        self.assertIn("begins 700ms before", findings[0]["description"])

    def test_aligned_caption_yields_no_finding(self):
        self.write_timings([("hello", 0, 500), ("world", 600, 1200)])
        self.write_captions([{"start_ms": 0, "end_ms": 1200, "text": "hello world"}])
        self.assertEqual([], self.caption_findings(self.analyze()))

    def test_small_offset_within_tolerance_ignored(self):
        self.write_timings([("hello", 0, 500), ("world", 600, 1200)])
        self.write_captions([{"start_ms": 0, "end_ms": 1280, "text": "hello world"}])
        self.assertEqual([], self.caption_findings(self.analyze()))

    def test_multiple_captions_report_offsets(self):
        self.write_timings([("one", 0, 400), ("two", 500, 900), ("three", 1000, 1500)])
        self.write_captions([{"start_ms": 0, "end_ms": 600, "text": "one two"},
                             {"start_ms": 1000, "end_ms": 1500, "text": "three"}])
        findings = self.caption_findings(self.analyze())
        self.assertEqual(1, len(findings))
        self.assertEqual(300.0, findings[0]["evidence"]["measured_value"])


class TestUnavailablePreserved(CaptionSyncBase):
    def test_unavailable_without_word_timings(self):
        report = self.analyze()
        self.assertEqual([], self.caption_findings(report))
        checks = {u["check"]: u["reason"] for u in report["unavailable"]}
        self.assertIn("caption_audio_sync", checks)
        self.assertIn("no word-timings", checks["caption_audio_sync"])
        self.assertIsNone(report["measurements"]["word_timings"])

    def test_unavailable_with_timings_but_no_captions(self):
        self.write_timings([("hello", 0, 500)])
        report = self.analyze()
        self.assertIn("caption_audio_sync", {u["check"] for u in report["unavailable"]})
        self.assertEqual(1, report["measurements"]["word_timings"]["count"])

    def test_malformed_timings_are_unavailable_not_fabricated(self):
        with open(os.path.join(self.project, "word-timings.json"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"schema_version": 1, "provider": "elevenlabs",
                                 "audio_duration_ms": 1000,
                                 "words": [{"word": "x", "start_ms": 900, "end_ms": 1200,
                                            "confidence": None}]}))
        self.write_captions([{"start_ms": 0, "end_ms": 1000, "text": "x"}])
        report = self.analyze()
        self.assertEqual([], self.caption_findings(report))
        reasons = {u["check"]: u["reason"] for u in report["unavailable"]}
        self.assertIn("could not be validated", reasons["caption_audio_sync"])

    def test_caption_without_overlapping_speech_skipped(self):
        self.write_timings([("hello", 2000, 2400)])
        self.write_captions([{"start_ms": 0, "end_ms": 500, "text": "unrelated"}])
        self.assertEqual([], self.caption_findings(self.analyze()))


class TestNonDestructiveAndOffline(CaptionSyncBase):
    def test_analyze_does_not_mutate_project(self):
        self.write_timings([("hello", 0, 500)])
        self.write_captions([{"start_ms": 0, "end_ms": 300, "text": "hello"}])
        before = dir_hash(self.project)
        self.analyze()
        self.assertEqual(before, dir_hash(self.project), "analysis must be read-only")

    def test_analyze_never_calls_provider_adapter(self):
        self.write_timings([("hello", 0, 500)])
        self.write_captions([{"start_ms": 0, "end_ms": 500, "text": "hello"}])
        with mock.patch.object(timing_adapter, "normalize",
                               side_effect=AssertionError("provider must not be called")):
            report = self.analyze()
        self.assertIsInstance(report["findings"], list)

    def test_findings_validate_against_existing_schema(self):
        self.write_timings([("hello", 0, 500)])
        self.write_captions([{"start_ms": 0, "end_ms": 200, "text": "hello"}])
        for f in self.caption_findings(self.analyze()):
            proposal_schema.validate_finding(f)


if __name__ == "__main__":
    unittest.main(verbosity=2)
