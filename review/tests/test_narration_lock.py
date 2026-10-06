"""Regression tests for narration-locked scene protection.

A scene marked data-narration-locked="true" has its duration bound to real
narration/caption timing. It must never be shortened below that (nor trimmed),
while lengthening stays allowed. Non-narrated behaviour is unchanged.

Run:  python3 -m unittest discover -s review/tests -v
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from review import analyzer, htmlmodel, proposal_engine, revision  # noqa: E402
from review import reviewer  # noqa: E402

_POC = os.path.join(os.path.dirname(_ROOT), "tests", "word-sync", "alice-ar-kinetic")

_HTML = """<!doctype html>
<html lang="ar"><head><meta charset="UTF-8">
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>:root{--brand-background:#131416;}.clip{position:absolute;inset:0;}</style>
</head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="__DUR__"
     data-fps="30" data-width="1920" data-height="1080">
  <audio id="nar" src="narration.mp3" data-start="0" data-duration="__DUR__" data-volume="1"></audio>
  <section id="s1" class="clip" data-start="0" data-duration="__DUR__" __LOCK__>
    <h1 id="a" class="headline">عنوان</h1>
  </section>
</div>
<script>
const tl = gsap.timeline({ paused: true });
__SCRIPT__
window.__timelines = window.__timelines || {};
window.__timelines["main"] = tl;
</script>
</body></html>
"""


class NarrationLockBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="narlock-")
        self._orig = revision._STATE_DIR
        revision._STATE_DIR = os.path.join(self.tmp, "state")
        os.makedirs(revision._STATE_DIR, exist_ok=True)

    def tearDown(self):
        revision._STATE_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, duration=12.0, locked=True, word_end_ms=11500,
              caption_end_ms=11500, script=None, name="proj"):
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        script = script or 'tl.fromTo("#a", { opacity: 0 }, { opacity: 1, duration: 0.5 }, 8.5);'
        html = (_HTML.replace("__DUR__", str(float(duration)))
                .replace("__LOCK__", 'data-narration-locked="true"' if locked else "")
                .replace("__SCRIPT__", script))
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        words = [{"word": "مرحبا", "start_ms": 8000, "end_ms": min(10000, word_end_ms),
                  "confidence": None},
                 {"word": "بالعالم", "start_ms": min(10000, word_end_ms),
                  "end_ms": word_end_ms, "confidence": None}]
        with open(os.path.join(d, "word-timings.json"), "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "provider": "elevenlabs",
                       "audio_duration_ms": int(float(duration) * 1000), "words": words},
                      fh, ensure_ascii=False)
        with open(os.path.join(d, "captions.json"), "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "source": "word-timings",
                       "captions": [{"start_ms": 8000, "end_ms": caption_end_ms,
                                     "text": "مرحبا بالعالم", "word_count": 2}]},
                      fh, ensure_ascii=False)
        return d

    def model(self, project):
        m = htmlmodel.parse(project)
        analyzer.narration_for(project, m)
        return m

    def review(self, project):
        report = analyzer.analyze(project)
        proposals, notes = reviewer.review(project, report)
        return report, proposals, notes


class TestNarrationLock(NarrationLockBase):
    def test_a_locked_hold_yields_no_shortening_proposal(self):
        project = self.build(duration=12.0, locked=True, word_end_ms=11500)
        report, proposals, notes = self.review(project)
        static = [f for f in report["findings"]
                  if f["category"] == "scene_pacing" and "static" in f["description"].lower()]
        self.assertTrue(static, "the reading hold is still measured")
        durations = [p for p in proposals if p["operation"]["type"] in
                     ("adjust_scene_duration", "trim_static_hold")]
        self.assertEqual([], durations, "narration-locked scene must not be shortened")
        self.assertTrue(any("narration-locked" in n for n in notes))

    def test_trim_static_hold_refused_when_locked(self):
        project = self.build(locked=True)
        m = self.model(project)
        with self.assertRaises(proposal_engine.SimulationError):
            proposal_engine.simulate(m, {"type": "trim_static_hold", "scene": 1})

    def test_b_shortening_before_final_word_rejected(self):
        project = self.build(duration=12.0, locked=True, word_end_ms=10500,
                             caption_end_ms=10500)
        m = self.model(project)
        with self.assertRaises(proposal_engine.SimulationError):
            proposal_engine.simulate(m, {"type": "adjust_scene_duration",
                                         "scene": 1, "from": 12.0, "to": 9.0})

    def test_c_shortening_before_final_caption_rejected(self):
        # word end 9000, caption end 11000: 10.0s passes the word but not the caption
        project = self.build(duration=12.0, locked=True, word_end_ms=9000,
                             caption_end_ms=11000)
        m = self.model(project)
        with self.assertRaises(proposal_engine.SimulationError):
            proposal_engine.simulate(m, {"type": "adjust_scene_duration",
                                         "scene": 1, "from": 12.0, "to": 10.0})

    def test_d_lengthening_locked_scene_allowed(self):
        project = self.build(duration=12.0, locked=True, word_end_ms=10500)
        m = self.model(project)
        sim = proposal_engine.simulate(m, {"type": "adjust_scene_duration",
                                           "scene": 1, "from": 12.0, "to": 13.0})
        self.assertTrue(sim["ok"])
        self.assertGreater(sim["duration_after"], sim["duration_before"])

    def test_e_non_narrated_shortening_unchanged(self):
        project = self.build(duration=12.0, locked=False)
        report, proposals, _notes = self.review(project)
        kinds = [p["operation"]["type"] for p in proposals]
        self.assertIn("adjust_scene_duration", kinds,
                      "non-narrated static scene keeps the existing behaviour")
        p = next(p for p in proposals if p["operation"]["type"] == "adjust_scene_duration")
        self.assertLess(p["operation"]["to"], 12.0)

    def test_locked_engine_without_timing_rejects_shortening(self):
        project = self.build(locked=True)
        # remove timing files to model a locked scene with no verification data
        os.remove(os.path.join(project, "word-timings.json"))
        os.remove(os.path.join(project, "captions.json"))
        m = self.model(project)
        with self.assertRaises(proposal_engine.SimulationError):
            proposal_engine.simulate(m, {"type": "adjust_scene_duration",
                                         "scene": 1, "from": 12.0, "to": 6.0})


class TestAlicePoc(unittest.TestCase):
    def setUp(self):
        self._orig = revision._STATE_DIR
        self.tmp = tempfile.mkdtemp(prefix="narlock-poc-")
        revision._STATE_DIR = os.path.join(self.tmp, "state")
        os.makedirs(revision._STATE_DIR, exist_ok=True)

    def tearDown(self):
        revision._STATE_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_f_poc_has_no_destructive_scene_pacing_proposal(self):
        report = analyzer.analyze(_POC)
        proposals, _notes = reviewer.review(_POC, report)
        destructive = [p for p in proposals
                       if p["operation"]["type"] in ("adjust_scene_duration", "trim_static_hold")]
        self.assertEqual([], destructive,
                         "natural narration holds must not create destructive proposals")
        self.assertEqual([], [f for f in report["findings"]
                              if f["category"] == "caption_audio_sync"],
                         "caption_audio_sync stays clean")
        scene = report["measurements"]["scenes"][0]
        self.assertTrue(scene["narration_locked"])
        self.assertIsNotNone(scene["narration_min_duration_s"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
