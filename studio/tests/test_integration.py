"""Phase E integration tests — read-only workflow across the four subsystems."""

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

from costgate import gate as cg  # noqa: E402
from reference import analyzer as ra  # noqa: E402
from review import analyzer as rva  # noqa: E402
from review import revision as rv  # noqa: E402
from studio import status as st  # noqa: E402
from timing import adapter as ta  # noqa: E402
from timing import schema as ts  # noqa: E402

_REPO = os.path.dirname(_ROOT)
_FIXTURE = os.path.join(_REPO, "review", "tests", "fixtures", "mini_project")
_PLAN = os.path.join(_REPO, "costgate", "tests", "fixtures", "plan_example.json")
_BRANDS = os.path.join(_REPO, "templates", "tech-news-ar", "brands")


def dir_hash(path: str) -> str:
    h = hashlib.sha256()
    for base, _d, names in os.walk(path):
        for n in sorted(names):
            p = os.path.join(base, n)
            h.update(os.path.relpath(p, path).encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


class IntegrationBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="studio-it-")
        self.project = os.path.join(self.tmp, "proj")
        shutil.copytree(_FIXTURE, self.project)

        self._rv = rv._STATE_DIR
        self._cg = (cg._STATE_DIR, cg._REPORT_DIR)
        self._ra = (ra._PROFILE_DIR, ra._REPORT_DIR)
        rv._STATE_DIR = os.path.join(self.tmp, "review-state")
        cg._STATE_DIR = os.path.join(self.tmp, "cost-state")
        cg._REPORT_DIR = os.path.join(self.tmp, "cost-reports")
        ra._PROFILE_DIR = os.path.join(self.tmp, "ref-profiles")
        ra._REPORT_DIR = os.path.join(self.tmp, "ref-reports")
        for d in (rv._STATE_DIR, cg._STATE_DIR, cg._REPORT_DIR, ra._PROFILE_DIR, ra._REPORT_DIR):
            os.makedirs(d, exist_ok=True)

    def tearDown(self):
        rv._STATE_DIR = self._rv
        cg._STATE_DIR, cg._REPORT_DIR = self._cg
        ra._PROFILE_DIR, ra._REPORT_DIR = self._ra
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_timings(self, triples, duration_ms=5000):
        words = [{"word": w, "start_ms": s, "end_ms": e, "confidence": None}
                 for (w, s, e) in triples]
        with open(os.path.join(self.project, "word-timings.json"), "w", encoding="utf-8") as fh:
            json.dump(ts.make("elevenlabs", duration_ms, words), fh)

    def write_captions(self, caps):
        with open(os.path.join(self.project, "captions.json"), "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "captions": caps}, fh)

    def save_gate(self, decision=None, limit=None):
        plan = cg.load_json(_PLAN)
        g = cg.build_gate(plan, cg.load_pricing(), self.project, "2026-01-01T00:00:00Z")
        if decision:
            g = cg.set_decision(g, decision, limit=limit, at="2026-01-01T00:10:00Z")
        cg.save_gate(g)
        return g


class TestWorkflow(IntegrationBase):
    def test_works_without_reference_profile(self):
        state = st.inspect(self.project)
        self.assertEqual("skipped", state["reference"]["status"])
        self.assertIn("findings", state["review"])

    def test_cost_gate_absent_blocks_generation(self):
        state = st.inspect(self.project)
        self.assertEqual("BLOCKED", state["cost_gate"]["status"])
        self.assertFalse(state["paid_generation_allowed"])

    def test_paid_generation_blocked_before_approval(self):
        state = st.inspect(self.project, plan_path=_PLAN)
        self.assertEqual("AWAITING_APPROVAL", state["cost_gate"]["status"])
        self.assertFalse(state["paid_generation_allowed"])
        self.assertTrue(state["cost_gate"]["unknown_cost"], "empty catalog must surface UNKNOWN")

    def test_approved_cost_gate_permits_boundary(self):
        self.save_gate("approve", limit=1.0)
        state = st.inspect(self.project)
        self.assertEqual("APPROVED", state["cost_gate"]["status"])
        self.assertTrue(state["paid_generation_allowed"])

    def test_rejected_gate_blocks(self):
        self.save_gate("reject")
        state = st.inspect(self.project)
        self.assertEqual("REJECTED", state["cost_gate"]["status"])
        self.assertFalse(state["paid_generation_allowed"])

    def test_reference_profile_is_read_only_and_not_a_defect(self):
        prof = ra.analyze(manual={"observed": {"average_scene_duration": 1.0},
                                  "inferred": {"pacing": "fast", "layout_style": "minimal"}},
                          reference_id="ref-1")
        ra.save_profile(prof)
        brands_before = dir_hash(_BRANDS)
        ref_before = dir_hash(ra._PROFILE_DIR)

        baseline = st.inspect(self.project)
        with_ref = st.inspect(self.project, reference_id="ref-1")

        self.assertEqual("loaded", with_ref["reference"]["status"])
        self.assertEqual(baseline["review"]["findings"], with_ref["review"]["findings"],
                         "reference metadata must never create review defects")
        self.assertEqual(brands_before, dir_hash(_BRANDS), "brand profiles must not change")
        self.assertEqual(ref_before, dir_hash(ra._PROFILE_DIR), "reference profiles are read-only")

    def test_normalized_timings_consumed_without_provider(self):
        self.write_timings([("hello", 0, 500), ("world", 600, 1200)])
        self.write_captions([{"start_ms": 0, "end_ms": 800, "text": "hello world"}])
        with mock.patch.object(ta, "normalize",
                               side_effect=AssertionError("provider must not be called")):
            state = st.inspect(self.project)
        self.assertTrue(state["timing"]["word_timings"])
        self.assertEqual(2, state["timing"]["word_count"])
        self.assertGreaterEqual(state["review"]["findings_by_category"].get("caption_audio_sync", 0), 1)

    def test_missing_timings_remain_unavailable(self):
        state = st.inspect(self.project)
        self.assertFalse(state["timing"]["word_timings"])
        self.assertIn("caption_audio_sync", state["review"]["unavailable"])

    def test_review_never_auto_applies(self):
        before = sorted(os.listdir(self.tmp))
        state = st.inspect(self.project)
        self.assertFalse(state["review_auto_applied"])
        self.assertEqual(before, sorted(os.listdir(self.tmp)),
                         "inspection must not create version directories")
        self.assertEqual([], [d for d in os.listdir(self.tmp) if d.startswith("proj-rev")])

    def test_existing_render_unchanged(self):
        renders = os.path.join(self.project, "renders")
        os.makedirs(renders, exist_ok=True)
        payload = b"FAKE-RENDER-BYTES"
        with open(os.path.join(renders, "video.mp4"), "wb") as fh:
            fh.write(payload)
        before = hashlib.sha256(payload).hexdigest()
        st.inspect(self.project, plan_path=_PLAN)
        with open(os.path.join(renders, "video.mp4"), "rb") as fh:
            self.assertEqual(before, hashlib.sha256(fh.read()).hexdigest())

    def test_backward_compatibility_no_optional_data(self):
        state = st.inspect(self.project)
        self.assertEqual("skipped", state["reference"]["status"])
        self.assertFalse(state["timing"]["word_timings"])
        self.assertEqual("BLOCKED", state["cost_gate"]["status"])
        self.assertIn("gate2_review", state["gates"])

    def test_status_markdown_renders(self):
        md = st.render_report_md(st.inspect(self.project, plan_path=_PLAN))
        self.assertIn("GATE 1", md)
        self.assertIn("GATE 2", md)
        self.assertIn("Auto-applied: False", md)


class TestOfflineIntegration(unittest.TestCase):
    def test_studio_package_is_offline(self):
        root = os.path.join(_ROOT)
        for base, _d, names in os.walk(root):
            if (os.sep + "tests") in base:
                continue
            for n in names:
                if not n.endswith(".py") or "__pycache__" in base:
                    continue
                path = os.path.join(base, n)
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
                for bad in ("import requests", "import urllib", "import socket",
                            "urlopen", "http.client"):
                    self.assertNotIn(bad, text, "%s must stay offline" % path)


if __name__ == "__main__":
    unittest.main(verbosity=2)