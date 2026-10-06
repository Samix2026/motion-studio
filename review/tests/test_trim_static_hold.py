"""Phase E tests for the trim_static_hold operation (distinct from adjust_scene_duration)."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from review import analyzer, apply_proposal, htmlmodel, proposal_engine, proposal_schema, revision  # noqa: E402
from review import reviewer  # noqa: E402

_FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "mini_project")


def dir_hash(path: str) -> str:
    h = hashlib.sha256()
    for base, _d, names in os.walk(path):
        for n in sorted(names):
            p = os.path.join(base, n)
            h.update(os.path.relpath(p, path).encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


class TrimStaticHoldTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="trim-")
        self.project = os.path.join(self.tmp, "proj")
        shutil.copytree(_FIXTURE, self.project)
        self._orig = revision._STATE_DIR
        revision._STATE_DIR = os.path.join(self.tmp, "state")
        os.makedirs(revision._STATE_DIR, exist_ok=True)

    def tearDown(self):
        revision._STATE_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_schema_accepts_trim_static_hold(self):
        proposal_schema.validate_proposal({
            "id": "proposal-900", "project_revision": 1, "project_hash": "x",
            "finding_id": "finding-001", "title": "t", "rationale": "r",
            "operation": {"type": "trim_static_hold", "scene": 2},
            "duration_before": 8.0, "duration_after": 5.1, "warnings": [],
            "confidence": 0.9, "status": "awaiting_review"})

    def test_simulation_derives_target_from_measured_hold(self):
        model = htmlmodel.parse(self.project)
        scene = model.scene_by_index(2)
        last_end = max(e.end for e in model.events_in_scene(scene))
        sim = proposal_engine.simulate(model, {"type": "trim_static_hold", "scene": 2})
        expected_to = round((last_end - scene.start) + 0.3, 3)
        self.assertEqual(expected_to, sim["edits"][0]["to"])
        self.assertEqual("scene_duration", sim["edits"][0]["kind"])
        self.assertTrue(sim["edits"][0]["ripple"])
        self.assertLess(sim["duration_after"], sim["duration_before"])
        # simulation must not mutate the real model
        self.assertEqual(3.5, scene.start)
        self.assertEqual(4.5, scene.duration)

    def test_no_hold_raises(self):
        model = htmlmodel.parse(self.project)
        # scene 1 has a ~0.1s hold only; keep_hold 0.3 makes the target >= current
        with self.assertRaises(proposal_engine.SimulationError):
            proposal_engine.simulate(model, {"type": "trim_static_hold", "scene": 1})

    def test_keeps_in_scene_animation_and_ripples_later_scenes(self):
        report = analyzer.analyze(self.project)
        before_model = htmlmodel.parse(self.project)
        before_events = [(e.selector, e.start) for e in before_model.events
                         if before_model.scene_by_index(2).start <= e.start < before_model.scene_by_index(2).end]

        proposal = {
            "id": "proposal-trim", "project_revision": report["revision"],
            "project_hash": report["content_hash"], "finding_id": "finding-001",
            "title": "Trim scene 2 static hold", "rationale": "measured idle tail",
            "operation": {"type": "trim_static_hold", "scene": 2},
            "duration_before": 8.0, "duration_after": 5.1, "warnings": [],
            "confidence": 0.9, "status": "approved"}

        before_source = dir_hash(self.project)
        result = apply_proposal.apply_approved(self.project, [proposal], ["proposal-trim"])
        self.assertEqual(before_source, dir_hash(self.project), "source must stay untouched")

        after_model = htmlmodel.parse(result["new_dir"])
        after_events = [(e.selector, e.start) for e in after_model.events
                        if after_model.scene_by_index(2).start <= e.start < after_model.scene_by_index(2).end]
        self.assertEqual(before_events, after_events,
                         "in-scene animation timing must be preserved")
        self.assertLess(after_model.duration, before_model.duration)

    def test_distinct_from_adjust_scene_duration(self):
        model = htmlmodel.parse(self.project)
        a = proposal_engine.simulate(model, {"type": "adjust_scene_duration",
                                             "scene": 2, "from": 4.5, "to": 2.0})
        b = proposal_engine.simulate(model, {"type": "trim_static_hold", "scene": 2})
        self.assertNotEqual(a["edits"][0]["to"], b["edits"][0]["to"],
                            "trim derives its own target from the measured hold")
        self.assertEqual("scene_duration", a["edits"][0]["kind"])
        self.assertEqual("scene_duration", b["edits"][0]["kind"])

    def test_reviewer_still_uses_adjust_scene_duration(self):
        report = analyzer.analyze(self.project)
        proposals, _notes = reviewer.review(self.project, report)
        types = {p["operation"]["type"] for p in proposals}
        self.assertIn("adjust_scene_duration", types,
                      "V1 reviewer behaviour is preserved; trim_static_hold is opt-in")


if __name__ == "__main__":
    unittest.main(verbosity=2)