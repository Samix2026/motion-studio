"""V1 tests for the AI Video Review & Approval Layer (stdlib unittest).

Run:  python3 -m unittest discover -s review/tests -v
      (also collectible by pytest)
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from review import analyzer, apply_proposal, proposal_engine, proposal_schema, reviewer, revision  # noqa: E402

_FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "mini_project")

_TASHKEEL = set([chr(c) for c in range(0x064B, 0x0660)] + [chr(0x0670)]
                + [chr(c) for c in range(0x0610, 0x061B)]
                + [chr(c) for c in range(0x06D6, 0x06EE)])


def tree_hash(path: str) -> str:
    h = hashlib.sha256()
    for root, _dirs, files in os.walk(path):
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            h.update(os.path.relpath(fp, path).encode())
            with open(fp, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


class ReviewTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="revtest-")
        self.project = os.path.join(self.tmp, "proj")
        shutil.copytree(_FIXTURE, self.project)
        # isolate revision state so tests never touch the repo's review/state
        self._orig_state_dir = revision._STATE_DIR
        revision._STATE_DIR = os.path.join(self.tmp, "state")
        os.makedirs(revision._STATE_DIR, exist_ok=True)

    def tearDown(self):
        revision._STATE_DIR = self._orig_state_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _review(self):
        report = analyzer.analyze(self.project)
        proposals, _notes = reviewer.review(self.project, report)
        return report, proposals

    def _new_dirs(self):
        return sorted(d for d in os.listdir(self.tmp) if d.startswith("proj-rev"))


class TestReview(ReviewTestBase):
    def test_proposal_creation_does_not_alter_project(self):
        before = tree_hash(self.project)
        report, proposals = self._review()
        proposal_schema.validate_all(report["findings"], proposals)
        self.assertTrue(proposals, "fixture should yield proposals")
        self.assertEqual(before, tree_hash(self.project), "review must not change the project")
        self.assertEqual([], self._new_dirs(), "review must not create a version dir")

    def test_approved_proposal_creates_new_revision(self):
        before = tree_hash(self.project)
        _report, proposals = self._review()
        target = proposals[0]["id"]
        result = apply_proposal.apply_approved(self.project, proposals, [target])
        self.assertTrue(os.path.isdir(result["new_dir"]))
        self.assertEqual(2, result["new_revision"])
        state = revision.load_state(revision.state_key(result["new_dir"]))
        self.assertEqual(2, state["revision"])
        self.assertEqual(before, tree_hash(self.project), "source must be untouched")

    def test_rejected_proposal_changes_nothing(self):
        _report, proposals = self._review()
        for p in proposals:
            p["status"] = "rejected"
        approved = [p["id"] for p in proposals if p["status"] == "approved"]
        result = apply_proposal.apply_approved(self.project, proposals, approved)
        self.assertEqual([], result["applied"])
        self.assertEqual([], self._new_dirs(), "rejected proposals must change nothing")

    def test_stale_proposal_rejected(self):
        _report, proposals = self._review()
        with open(os.path.join(self.project, "index.html"), "a", encoding="utf-8") as fh:
            fh.write("\n<!-- changed after review -->\n")
        with self.assertRaises(apply_proposal.StaleRevisionError):
            apply_proposal.apply_approved(self.project, proposals, [proposals[0]["id"]])
        self.assertEqual([], self._new_dirs(), "stale apply must not write anything")

    def test_duration_before_after_correct(self):
        report, proposals = self._review()
        p = next(p for p in proposals if p["operation"]["type"] == "adjust_scene_duration")
        scene = next(s for s in report["measurements"]["scenes"]
                     if s["index"] == p["operation"]["scene"])
        hold = scene["static_hold"]
        target = analyzer.load_rules()["timing"]["target_static_hold_seconds"]
        expected_to = round(max(scene["duration"] - (hold - target), 0.4), 3)
        self.assertAlmostEqual(expected_to, p["operation"]["to"], places=3)
        self.assertAlmostEqual(report["composition"]["duration"], p["duration_before"], places=3)
        expected_after = p["duration_before"] + (p["operation"]["to"] - p["operation"]["from"])
        self.assertAlmostEqual(expected_after, p["duration_after"], places=3)

    def test_unsupported_operation_rejected(self):
        for bad in ("shell_command", "rm_rf", "write_source_code", ""):
            with self.assertRaises(proposal_schema.SchemaError):
                proposal_schema.validate_proposal({
                    "id": "proposal-999", "project_revision": 1, "finding_id": "finding-001",
                    "title": "x", "rationale": "y", "operation": {"type": bad},
                    "duration_before": 1.0, "duration_after": 1.0, "warnings": [],
                    "confidence": 0.5, "status": "awaiting_review",
                })

    def test_missing_evidence_not_a_finding(self):
        report = analyzer.analyze(self.project)
        cats = {f["category"] for f in report["findings"]}
        self.assertNotIn("caption_audio_sync", cats,
                         "no transcript/captions must not fabricate a sync finding")
        unavail = {u["check"] for u in report["unavailable"]}
        self.assertIn("caption_audio_sync", unavail)
        self.assertIn("silence_regions", unavail)
        for f in report["findings"]:
            self.assertTrue(f.get("measured", False))
            self.assertIn("measured_value", f["evidence"])

    def test_existing_render_untouched(self):
        renders = os.path.join(self.project, "renders")
        os.makedirs(renders, exist_ok=True)
        render_path = os.path.join(renders, "video.mp4")
        payload = b"FAKE-MP4-BYTES-do-not-touch"
        with open(render_path, "wb") as fh:
            fh.write(payload)
        with open(render_path, "rb") as fh:
            render_before = hashlib.sha256(fh.read()).hexdigest()

        _report, proposals = self._review()
        result = apply_proposal.apply_approved(self.project, proposals,
                                               [p["id"] for p in proposals])
        self.assertFalse(os.path.exists(os.path.join(result["new_dir"], "renders")),
                         "new version must not carry a render")
        with open(render_path, "rb") as fh:
            render_after = hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(render_before, render_after,
                         "existing render must be byte-identical")

    def test_rtl_no_tashkeel_checks_pass(self):
        _report, proposals = self._review()
        result = apply_proposal.apply_approved(self.project, proposals,
                                               [p["id"] for p in proposals])
        new_index = os.path.join(result["new_dir"], "index.html")
        with open(new_index, encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(any(0x0600 <= ord(c) <= 0x06FF for c in text), "Arabic must remain present")
        self.assertEqual([], [c for c in text if c in _TASHKEEL], "no Arabic tashkeel")
        guard = os.path.join(result["new_dir"], "tools", "check-tashkeel.py")
        res = subprocess.run(["python3", guard, result["new_dir"]],
                             capture_output=True, text=True)
        self.assertEqual(0, res.returncode, "no-tashkeel guard must pass on the new version")

    def test_apply_refuses_existing_target(self):
        _report, proposals = self._review()
        ids = [p["id"] for p in proposals]
        apply_proposal.apply_approved(self.project, proposals, ids)
        with self.assertRaises(apply_proposal.ApplyError):
            apply_proposal.apply_approved(self.project, proposals, ids)


class TestEngine(ReviewTestBase):
    def test_shift_sfx_simulation_is_side_effect_free(self):
        report, _proposals = self._review()
        model = None
        from review import htmlmodel
        model = htmlmodel.parse(self.project)
        before = [a.start for a in model.audio]
        sim = proposal_engine.simulate(model, {"type": "shift_sfx", "audio_id": "au-click",
                                               "delta_seconds": -0.6})
        self.assertTrue(sim["ok"])
        self.assertEqual(before, [a.start for a in model.audio], "simulation must not mutate")

    def test_simulate_rejects_unknown_target(self):
        from review import htmlmodel
        model = htmlmodel.parse(self.project)
        with self.assertRaises(proposal_engine.SimulationError):
            proposal_engine.simulate(model, {"type": "adjust_scene_duration",
                                             "scene": 99, "from": 1.0, "to": 0.5})


if __name__ == "__main__":
    unittest.main(verbosity=2)
