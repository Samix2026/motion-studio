"""Advisory rendered diagnostics: near-still, long holds, empty frames, boundary dips.

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

from review import analyzer, pixels, reviewer, revision  # noqa: E402

_FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "mini_project")
HAS_FFMPEG = bool(shutil.which("ffmpeg"))
ADVISORY = {"long_hold", "empty_frame", "boundary_dip"}


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + list(args), check=True)


class TestDiagnosticLogic(unittest.TestCase):
    def test_still_runs_timing(self):
        # samples 2..5 still: frames 2..6 unchanged -> 0.2s to 0.6s at 10 fps
        runs = pixels._still_runs([1, 1, 0, 0, 0, 0, 1], 0.05, 10)
        self.assertEqual([{"start": 0.2, "end": 0.6, "duration": 0.4}], runs)

    def test_empty_spans_skip_frame_zero_window(self):
        cov = [0.0, 0.0, 0.2, 0.2, 0.001, 0.002, 0.2]
        spans = pixels.empty_spans(cov, 10, 0.01, skip_before=0.2)
        self.assertEqual(1, len(spans))
        self.assertEqual((0.4, 0.6, 0.2), (spans[0]["start"], spans[0]["end"], spans[0]["duration"]))
        self.assertEqual(0.001, spans[0]["min_coverage"])

    def test_boundary_dip_against_nearby_median(self):
        cov = [0.1] * 60
        cov[30] = 0.01                      # dip exactly at the 3.0s boundary
        dips = pixels.boundary_dips(cov, 10, [3.0, 4.5])
        self.assertTrue(dips[0]["dip"])
        self.assertEqual(3.0, dips[0]["at"])
        self.assertFalse(dips[1]["dip"])


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class TestDiagnosticsOnRenders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="diag-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _clip(self) -> str:
        """Box moves 0-1s, holds 1-3.5s, hidden 2.0-2.3s, moves again 3.5-4s."""
        out = os.path.join(self.tmp, "clip.mp4")
        ffmpeg("-f", "lavfi", "-i", "color=c=black:s=320x180:d=4:r=30",
               "-f", "lavfi", "-i", "color=c=white:s=60x60:d=4:r=30",
               "-filter_complex",
               "[0][1]overlay=x='if(lt(t,1),t*100,if(lt(t,3.5),100,100+(t-3.5)*200))':y=60"
               ":enable='not(between(t,2.0,2.3))'",
               "-t", "4", "-pix_fmt", "yuv420p", out)
        return out

    def test_near_still_finds_the_hold(self):
        res = pixels.near_still(self._clip(), 320, 180)
        self.assertIsNotNone(res)
        self.assertGreaterEqual(res["longest_hold"], 1.0)
        self.assertTrue(any(h["start"] >= 0.9 and h["end"] <= 3.6 for h in res["holds"]))

    def test_empty_frames_and_dip_found(self):
        cov = pixels.coverage_series(self._clip(), 320, 180, 4.0)
        spans = pixels.empty_spans(cov, 10, 0.01, skip_before=0.5)
        self.assertEqual(1, len(spans))
        self.assertAlmostEqual(2.0, spans[0]["start"], delta=0.15)
        self.assertTrue(pixels.boundary_dips(cov, 10, [2.1])[0]["dip"])

    def test_missing_file_is_unavailable(self):
        self.assertIsNone(pixels.near_still(os.path.join(self.tmp, "none.mp4"), 320, 180))
        self.assertIsNone(pixels.coverage_series(os.path.join(self.tmp, "none.mp4"), 320, 180, 4.0))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class TestDiagnosticsAreAdvisory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="diagan-")
        self.project = os.path.join(self.tmp, "proj")
        shutil.copytree(_FIXTURE, self.project)
        self._orig = revision._STATE_DIR
        revision._STATE_DIR = os.path.join(self.tmp, "state")
        os.makedirs(revision._STATE_DIR)
        os.makedirs(os.path.join(self.project, "renders"))
        dur = analyzer.htmlmodel.parse(self.project).duration
        ffmpeg("-f", "lavfi", "-i", "color=c=black:s=180x320:d=%s:r=30" % dur, "-pix_fmt", "yuv420p",
               os.path.join(self.project, "renders", "video.mp4"))

    def tearDown(self):
        revision._STATE_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_findings_are_measured_advisory_and_never_proposed(self):
        report = analyzer.analyze(self.project)
        diag = [f for f in report["findings"] if f["category"] in ADVISORY]
        self.assertTrue({"long_hold", "empty_frame"} <= {f["category"] for f in diag})
        for f in diag:
            self.assertNotEqual("high", f["severity"])
            self.assertTrue(f["description"].startswith("Advisory:"))
        for check in ADVISORY:
            self.assertEqual("complete", report["measurement_status"][check])
        proposals, _notes = reviewer.review(self.project, report)
        ids = {f["id"] for f in diag}
        self.assertFalse([p for p in proposals if p["finding_id"] in ids])


if __name__ == "__main__":
    unittest.main(verbosity=2)
