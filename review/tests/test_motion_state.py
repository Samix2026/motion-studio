"""Regression tests for helper-driven (lib/motion.js) motion detection.

The reviewer must not shorten a scene just because its motion is expressed
through the scene-grammar helpers (MS.*) instead of literal GSAP calls. These
tests lock the motion-state model (detected | none | unknown), the eligibility
rules for trim_static_hold / adjust_scene_duration, and the fact that pixel
freeze detection stays authoritative.

Run:  python3 -m unittest discover -s review/tests -v
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from review import analyzer, htmlmodel, proposal_engine, revision  # noqa: E402
from review import reviewer  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg"))

_HTML = """<!doctype html>
<html lang="ar">
  <head>
    <meta charset="UTF-8" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    __LIB__
    <style>
      :root { --brand-background: #131416; --brand-text: #ffffff; }
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1920px; height: 1080px; overflow: hidden; }
      #root { position: relative; width: 1920px; height: 1080px; background: var(--brand-background); }
      .clip { position: absolute; inset: 0; width: 100%; height: 100%; }
      .headline { font-size: 68px; color: var(--brand-text); }
      .sub { font-size: 28px; color: #c9c9c9; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="__DUR__"
         data-fps="30" data-width="1920" data-height="1080">
__BODY__
    </div>
    <script>
      const tl = gsap.timeline({ paused: true });
__SCRIPT__
      window.__timelines = window.__timelines || {};
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


def scene(sid: str, start: float, dur: float, inner: str) -> str:
    return ('      <section id="%s" class="clip" data-start="%s" data-duration="%s">\n'
            '        <h1 id="%s-h" class="headline">عنوان</h1>\n%s\n      </section>'
            % (sid, start, dur, sid, inner))


class MotionStateBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="motionstate-")
        self._orig = revision._STATE_DIR
        revision._STATE_DIR = os.path.join(self.tmp, "state")
        os.makedirs(revision._STATE_DIR, exist_ok=True)

    def tearDown(self):
        revision._STATE_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, body: str, script: str, duration: float = 8.0,
              motion_lib: bool = False, name: str = "proj") -> str:
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        html = (_HTML.replace("__DUR__", str(duration))
                .replace("__BODY__", body)
                .replace("__LIB__", '<script src="lib/motion.js"></script>' if motion_lib else "")
                .replace("__SCRIPT__", script))
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        return d

    def review(self, project: str):
        report = analyzer.analyze(project)
        proposals, _notes = reviewer.review(project, report)
        return report, proposals

    def static_findings(self, report):
        return [f for f in report["findings"]
                if f["category"] == "scene_pacing" and "static" in f["description"].lower()]


class TestLiteralGsap(MotionStateBase):
    """A/B: literal GSAP must behave exactly as before."""

    def test_a_literal_motion_scene_is_detected(self):
        body = scene("s1", 0, 4, "")
        project = self.build(body, 'tl.fromTo("#s1-h", { opacity: 0 }, '
                                   '{ opacity: 1, duration: 0.5 }, 3.5);', duration=4)
        model = htmlmodel.parse(project)
        self.assertEqual("detected", model.motion_state(model.scene_by_index(1)))
        self.assertTrue(model.motion_parse_complete)
        report, proposals = self.review(project)
        self.assertEqual([], self.static_findings(report),
                         "a moving literal scene must not read as static")
        self.assertFalse([p for p in proposals if p["operation"].get("scene") == 1])

    def test_b_literal_static_scene_still_eligible(self):
        body = scene("s1", 0, 4, "")
        project = self.build(body, "", duration=4)
        model = htmlmodel.parse(project)
        self.assertEqual("none", model.motion_state(model.scene_by_index(1)))
        self.assertTrue(model.is_static_hold_verified(model.scene_by_index(1)))
        report, proposals = self.review(project)
        findings = self.static_findings(report)
        self.assertEqual(1, len(findings), "a truly static literal scene stays eligible")
        self.assertAlmostEqual(4.0, findings[0]["evidence"]["measured_value"], places=3)
        kinds = [p["operation"]["type"] for p in proposals]
        self.assertIn("adjust_scene_duration", kinds)

    def test_literal_parsing_unchanged(self):
        fixture = os.path.join(_ROOT, "tests", "fixtures", "mini_project")
        model = htmlmodel.parse(fixture)
        self.assertEqual(5, len(model.events), "literal event parsing is unchanged")
        self.assertTrue(all(e.source == "literal" for e in model.events))
        self.assertTrue(model.motion_parse_complete)


class TestHelperMotion(MotionStateBase):
    """C/D: scene-grammar helper motion is recognized, never assumed static."""

    def test_c_helper_scene_is_detected(self):
        body = scene("s1", 0, 4, "")
        project = self.build(
            body, 'MS.enter.fadeScale(tl, "#s1-h", 3.5, { duration: 0.5 });',
            duration=4, motion_lib=True)
        model = htmlmodel.parse(project)
        self.assertEqual("detected", model.motion_state(model.scene_by_index(1)))
        self.assertTrue(model.motion_parse_complete)
        self.assertEqual("helper:enter.fadeScale", model.events[-1].source)
        report, proposals = self.review(project)
        self.assertEqual([], self.static_findings(report))
        self.assertEqual([], proposals, "no false trim_static_hold / duration proposal")

    def test_d_unknown_helper_marks_scene_unknown(self):
        body = scene("s1", 0, 4, "")
        project = self.build(
            body, 'MS.enter.warp(tl, "#s1-h", 3.5, { duration: 0.5 });',
            duration=4, motion_lib=True)
        model = htmlmodel.parse(project)
        self.assertFalse(model.motion_parse_complete)
        self.assertEqual("unknown", model.motion_state(model.scene_by_index(1)))
        self.assertFalse(model.is_static_hold_verified(model.scene_by_index(1)))
        report, proposals = self.review(project)
        self.assertEqual([], self.static_findings(report),
                         "unknown motion must not be reported as static")
        self.assertEqual([], proposals)
        with self.assertRaises(proposal_engine.SimulationError):
            proposal_engine.simulate(model, {"type": "trim_static_hold", "scene": 1})
        with self.assertRaises(proposal_engine.SimulationError):
            proposal_engine.simulate(model, {"type": "adjust_scene_duration",
                                             "scene": 1, "from": 4.0, "to": 1.0})

    def test_non_literal_helper_target_is_unknown(self):
        body = scene("s1", 0, 4, "")
        project = self.build(
            body, 'const sel = "#s1-h";\n      MS.enter.fadeScale(tl, sel, 3.5, { duration: 0.5 });',
            duration=4, motion_lib=True)
        model = htmlmodel.parse(project)
        self.assertEqual("unknown", model.motion_state(model.scene_by_index(1)))

    def test_motion_lib_without_calls_is_unknown(self):
        body = scene("s1", 0, 4, "")
        project = self.build(body, "", duration=4, motion_lib=True)
        model = htmlmodel.parse(project)
        self.assertEqual("unknown", model.motion_state(model.scene_by_index(1)))

    def test_safe_and_unsafe_edits_on_verified_scene(self):
        # A verified scene still allows lengthening even if a hypothetical
        # helper were unknown elsewhere; shortened edits are the guarded ones.
        body = scene("s1", 0, 4, "")
        project = self.build(body, "", duration=4)
        model = htmlmodel.parse(project)
        sim = proposal_engine.simulate(model, {"type": "adjust_scene_duration",
                                               "scene": 1, "from": 4.0, "to": 4.5})
        self.assertTrue(sim["ok"])


class TestSceneGrammarFixture(MotionStateBase):
    """F: a scene-grammar composition yields no 0.4-1.0s false proposals."""

    def _grammar_project(self) -> str:
        body = "\n".join([
            scene("s1", 0, 5, '        <div class="g" id="s1m">media</div>'),
            scene("s2", 5, 6, '        <div class="g" id="s2t">text</div>'),
            scene("s3", 11, 6, '        <div class="g" id="s3t">text</div>'),
        ])
        script = "\n".join([
            'MS.camera.pushIn(tl, "#s1m", 0, 5, { scale: 1.06 });',
            'MS.enter.maskReveal(tl, "#s1-h", 0, { start: 0.65, duration: 0.7 });',
            'MS.enter.fadeScale(tl, "#s2-h", 5.1, { duration: 0.8 });',
            'MS.enter.rtlSlide(tl, "#s2t", 6.2);',
            'MS.enter.rtlSlide(tl, "#s3-h", 11.1);',
            'MS.exit.fadeOut(tl, "#s3 .g", 16.6);',
            'MS.applyReviewAttributes(tl);',
        ])
        return self.build(body, script, duration=17, motion_lib=True)

    def test_f_no_false_short_duration_proposals(self):
        project = self._grammar_project()
        model = htmlmodel.parse(project)
        self.assertTrue(model.motion_parse_complete)
        states = {s.index: model.motion_state(s) for s in model.scenes}
        self.assertEqual({1: "detected", 2: "detected", 3: "detected"}, states)
        report, proposals = self.review(project)
        # Scene 2 keeps a real static tail; it is reported with a non-destructive
        # target, never the parser-absence 0.4s.
        findings = self.static_findings(report)
        self.assertEqual([2], [f["scene"] for f in findings])
        durations = [p["operation"].get("to") for p in proposals
                     if p["operation"]["type"] in ("adjust_scene_duration", "trim_static_hold")]
        self.assertTrue(durations, "the genuine static tail is still reported")
        for to in durations:
            self.assertGreater(to, 1.0, "no 0.4-1.0s parser-absence proposal")
        self.assertFalse([f for f in findings if f["scene"] in (1, 3)],
                         "scenes with scene-spanning helper motion are not static")


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class TestPixelFreezeAuthoritative(MotionStateBase):
    """E: unparsed helper motion suppresses timeline holds, but pixel freeze
    detection still reports the real frozen scene."""

    def test_e_frozen_render_still_detected(self):
        body = scene("s1", 0, 4, "")
        project = self.build(
            body, 'MS.enter.warp(tl, "#s1-h", 3.5, { duration: 0.5 });',
            duration=4, motion_lib=True)
        os.makedirs(os.path.join(project, "renders"))
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "color=c=black:s=180x320:d=4:r=30", "-pix_fmt", "yuv420p",
             os.path.join(project, "renders", "video.mp4")], check=True)
        report = analyzer.analyze(project)
        cats = {f["category"] for f in report["findings"]}
        self.assertIn("rendered_freeze", cats,
                      "pixel freeze evidence must survive unknown timeline motion")
        self.assertEqual([], self.static_findings(report),
                         "timeline static holds stay suppressed while motion is unknown")
        self.assertFalse(report["measurements"]["motion"]["parse_complete"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
