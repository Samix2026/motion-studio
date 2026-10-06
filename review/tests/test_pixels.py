"""Deterministic rendered-pixel checks (FFmpeg + stdlib).

Run:  python3 -m unittest discover -s review/tests -v
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from design import typography  # noqa: E402
from review import analyzer, pixels, revision  # noqa: E402

_FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "mini_project")
HAS_FFMPEG = bool(shutil.which("ffmpeg"))


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + list(args), check=True)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class TestPixelMeasurements(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pixels-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _frozen_content_with_moving_chrome(self) -> str:
        out = os.path.join(self.tmp, "hold.mp4")
        ffmpeg("-f", "lavfi", "-i", "color=c=black:s=320x568:d=4:r=30",
               "-f", "lavfi", "-i", "color=c=white:s=60x60:d=4:r=30",
               "-f", "lavfi", "-i", "color=c=red:s=40x10:d=4:r=30",
               "-filter_complex",
               "[0][1]overlay=x='min(t\\,1)*100':y=200[a];[a][2]overlay=x='t*60':y=540",
               "-t", "4", "-pix_fmt", "yuv420p", out)
        return out

    def test_freeze_detected_from_pixels_despite_moving_chrome(self):
        video = self._frozen_content_with_moving_chrome()
        # a continuously moving progress bar hides the hold when measured full-frame
        self.assertEqual([], pixels.freeze_regions(video, 2.0, total_duration=4.0))
        regions = pixels.freeze_regions(video, 2.0, content_crop=(0.10, 0.14), total_duration=4.0)
        self.assertEqual(1, len(regions))
        self.assertAlmostEqual(1.0, regions[0]["start"], delta=0.1)
        self.assertGreaterEqual(regions[0]["duration"], 2.8)

    def test_moving_content_is_not_frozen(self):
        out = os.path.join(self.tmp, "move.mp4")
        ffmpeg("-f", "lavfi", "-i", "color=c=black:s=320x180:d=3:r=30",
               "-f", "lavfi", "-i", "color=c=white:s=40x40:d=3:r=30",
               "-filter_complex", "[0][1]overlay=x='t*80':y=60", "-t", "3", "-pix_fmt", "yuv420p", out)
        self.assertEqual([], pixels.freeze_regions(out, 1.0, content_crop=(0.1, 0.1), total_duration=3.0))

    def _still(self, name: str, box: str) -> str:
        out = os.path.join(self.tmp, name)
        ffmpeg("-f", "lavfi", "-i", "color=c=0x101014:s=480x270", "-frames:v", "1",
               "-vf", "drawbox=%s:color=white:t=fill" % box, out)
        return out

    def _pattern(self, name: str, vf: str) -> str:
        out = os.path.join(self.tmp, name)
        ffmpeg("-f", "lavfi", "-i", "testsrc=size=480x270:rate=1", "-frames:v", "1", "-vf", vf, out)
        return out

    def test_duplicate_layout_similarity(self):
        # dHash needs texture; flat synthetic frames all look alike (documented limitation)
        a = self._pattern("a.png", "null")
        a2 = self._pattern("a2.png", "drawbox=x=400:y=10:w=30:h=16:color=white:t=fill")
        b = self._pattern("b.png", "hflip,vflip")
        ha, ha2, hb = (pixels.frame_hash(p, 0) for p in (a, a2, b))
        self.assertEqual(0, pixels.hamming(ha, ha))
        pairs = pixels.similar_pairs([ha, ha2, hb], 28)
        self.assertEqual([(1, 2)], [(p["a"], p["b"]) for p in pairs])
        self.assertGreater(pixels.hamming(ha, hb), 28)

    def test_frame_stats_coverage(self):
        empty = pixels.frame_stats(pixels.gray_frame(self._still("e.png", "x=0:y=0:w=1:h=1"), 0, 96, 54))
        full = pixels.frame_stats(pixels.gray_frame(self._still("f.png", "x=100:y=60:w=280:h=150"), 0, 96, 54))
        self.assertLess(empty["content_coverage"], 0.01)
        self.assertGreater(full["content_coverage"], 0.2)


class TestTextAndPhone(unittest.TestCase):
    def test_text_density_counts_arabic_and_latin_words(self):
        scenes = [SimpleNamespace(index=1, duration=4.0, text="الروبوتاكسي لا يعتمد على NVIDIA DRIVE · 14"),
                  SimpleNamespace(index=2, duration=0.0, text="")]
        d = pixels.text_density(scenes)
        self.assertEqual(7, d[0]["words"])  # "·" is not a word
        self.assertEqual(1.75, d[0]["words_per_second"])
        self.assertIsNone(d[1]["words_per_second"])

    def test_phone_scale_readability(self):
        scale = typography.load_scale()
        self.assertAlmostEqual(18.06, typography.phone_px(50, 1080, scale), places=2)
        self.assertAlmostEqual(6.91, typography.phone_px(34, 1920, scale), places=2)


class TestAnalyzerIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pxan-")
        self.project = os.path.join(self.tmp, "proj")
        shutil.copytree(_FIXTURE, self.project)
        self._orig = revision._STATE_DIR
        revision._STATE_DIR = os.path.join(self.tmp, "state")
        os.makedirs(revision._STATE_DIR)

    def tearDown(self):
        revision._STATE_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rendered_checks_unavailable_without_render(self):
        report = analyzer.analyze(self.project)
        unavailable = {u["check"] for u in report["unavailable"]}
        for check in ("frame_zero", "rendered_freeze", "shot_diversity"):
            self.assertIn(check, unavailable)
        self.assertEqual("measured", report["measurements"]["mobile_readability"]["status"])
        self.assertTrue(report["measurements"]["text_density"])

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
    def test_rendered_checks_run_on_a_render(self):
        os.makedirs(os.path.join(self.project, "renders"))
        dur = analyzer.htmlmodel.parse(self.project).duration
        ffmpeg("-f", "lavfi", "-i", "color=c=black:s=180x320:d=%s:r=30" % dur, "-pix_fmt", "yuv420p",
               os.path.join(self.project, "renders", "video.mp4"))
        report = analyzer.analyze(self.project)
        cats = {f["category"] for f in report["findings"]}
        self.assertIn("frame_zero", cats)
        self.assertIn("rendered_freeze", cats)
        self.assertIn("shot_diversity", cats)
        for f in report["findings"]:
            self.assertTrue(f["measured"])
            self.assertIsInstance(f["evidence"]["measured_value"], (int, float))


class TestUnavailableAndPartial(unittest.TestCase):
    """A6: unavailable/partial measurement semantics must be explicit."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pxavail-")
        self.project = os.path.join(self.tmp, "proj")
        shutil.copytree(_FIXTURE, self.project)
        os.makedirs(os.path.join(self.project, "renders"))
        with open(os.path.join(self.project, "renders", "video.mp4"), "wb") as fh:
            fh.write(b"fake-render")
        self._orig = revision._STATE_DIR
        revision._STATE_DIR = os.path.join(self.tmp, "state")

    def tearDown(self):
        revision._STATE_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_render(self):
        return {"duration": 8.0, "size": 10, "has_audio": True, "has_video": True,
                "video": {"codec_name": "h264", "width": 1920, "height": 1080},
                "audio": {"codec_name": "aac"}}

    def test_measurement_status_is_exposed_separately(self):
        report = analyzer.analyze(self.project)
        status = report["measurement_status"]
        for family in ("scene_pacing", "text_readability", "text_density",
                       "caption_audio_sync", "silence_regions", "frame_zero",
                       "rendered_freeze", "shot_diversity", "mobile_readability"):
            self.assertIn(family, status)
            self.assertIn(status[family], ("complete", "unavailable", "partial"))

    def test_silence_probe_failure_is_unavailable(self):
        with mock.patch.object(analyzer, "_ffprobe", return_value=self._fake_render()), \
                mock.patch.object(analyzer, "_silence_regions", return_value=None):
            report = analyzer.analyze(self.project)
        self.assertEqual("unavailable", report["measurement_status"]["silence_regions"])
        self.assertIn("silence_regions", {u["check"] for u in report["unavailable"]})

    def test_deadline_frame_failure_is_not_substituted(self):
        buf = bytes([128]) * 16

        def gray(path, t, w, h, crop=None, timeout=60):
            return buf if t == 0 else None

        with mock.patch.object(pixels, "gray_frame", side_effect=gray):
            self.assertIsNone(pixels.frame_zero("x.mp4", 4, 4, {"deadline_seconds": 0.5}))

    def test_frame_zero_available_when_both_frames_decode(self):
        with mock.patch.object(pixels, "gray_frame", return_value=bytes([0]) * 16):
            result = pixels.frame_zero("x.mp4", 4, 4, {"deadline_seconds": 0.5})
        self.assertIsNotNone(result)
        self.assertIn("at_deadline", result)

    def test_one_midpoint_failure_is_partial(self):
        calls = {"n": 0}

        def frame_hash(path, t):
            calls["n"] += 1
            return 1 if calls["n"] == 1 else None

        with mock.patch.object(analyzer, "_ffprobe", return_value=self._fake_render()), \
                mock.patch.object(pixels, "frame_hash", side_effect=frame_hash), \
                mock.patch.object(pixels, "freeze_regions", return_value=[]):
            report = analyzer.analyze(self.project)
        self.assertEqual("partial", report["measurement_status"]["shot_diversity"])
        coverage = report["measurements"]["rendered"]["shot_hash_coverage"]
        self.assertLess(coverage["sampled"], coverage["total"])

    def test_all_midpoint_failures_are_unavailable(self):
        with mock.patch.object(analyzer, "_ffprobe", return_value=self._fake_render()), \
                mock.patch.object(pixels, "frame_hash", return_value=None), \
                mock.patch.object(pixels, "freeze_regions", return_value=[]):
            report = analyzer.analyze(self.project)
        self.assertEqual("unavailable", report["measurement_status"]["shot_diversity"])
        self.assertIn("shot_diversity", {u["check"] for u in report["unavailable"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
