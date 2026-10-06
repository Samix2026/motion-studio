"""Phase D tests for the Reference Analyzer (stdlib unittest)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from reference import analyzer, images, schema, video  # noqa: E402

_FIX = os.path.join(_ROOT, "tests", "fixtures")
_BRANDS = os.path.join(os.path.dirname(_ROOT), "templates", "tech-news-ar", "brands")


def write_png(path: str, w: int, h: int) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", ihdr))
        fh.write(chunk(b"IEND", b""))


def write_bmp(path: str, w: int, h: int) -> None:
    with open(path, "wb") as fh:
        fh.write(b"BM" + b"\x00" * 16 + struct.pack("<ii", w, h) + b"\x00" * 8)


def dir_hash(path: str) -> str:
    h = hashlib.sha256()
    for base, _d, names in os.walk(path):
        for n in sorted(names):
            p = os.path.join(base, n)
            h.update(os.path.relpath(p, path).encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


class ReferenceTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="reference-")
        self._orig_profiles = analyzer._PROFILE_DIR
        self._orig_reports = analyzer._REPORT_DIR
        analyzer._PROFILE_DIR = os.path.join(self.tmp, "profiles")
        analyzer._REPORT_DIR = os.path.join(self.tmp, "reports")

    def tearDown(self):
        analyzer._PROFILE_DIR = self._orig_profiles
        analyzer._REPORT_DIR = self._orig_reports
        shutil.rmtree(self.tmp, ignore_errors=True)

    def image_set(self):
        d = os.path.join(self.tmp, "images")
        os.makedirs(d, exist_ok=True)
        write_png(os.path.join(d, "a.png"), 1920, 1080)
        write_png(os.path.join(d, "b.png"), 1920, 1080)
        write_bmp(os.path.join(d, "c.bmp"), 1080, 1080)
        return d


class TestObservedDeterministic(ReferenceTestBase):
    def test_image_measurements_are_deterministic(self):
        d = self.image_set()
        first = analyzer.analyze(d)
        second = analyzer.analyze(d)
        self.assertEqual(first, second, "observed measurements must be deterministic")
        obs = first["observed"]
        self.assertEqual(3, obs["image_count"])
        self.assertEqual("16:9", obs["dominant_aspect_ratio"])
        self.assertEqual(1920, obs["width"])
        self.assertEqual(1080, obs["height"])
        self.assertEqual("images", first["source_type"])

    def test_image_header_readers(self):
        p = os.path.join(self.tmp, "x.png")
        write_png(p, 640, 360)
        self.assertEqual((640, 360), images.read_dimensions(p))
        self.assertEqual("16:9", images.aspect_ratio(640, 360))

    def test_ffprobe_parse_is_pure_and_deterministic(self):
        data = {"format": {"duration": "34.20"},
                "streams": [
                    {"codec_type": "video", "width": 1920, "height": 1080,
                     "r_frame_rate": "30/1"},
                    {"codec_type": "audio", "duration": "34.20"}]}
        self.assertEqual(video.parse_ffprobe(data), video.parse_ffprobe(json.loads(json.dumps(data))))
        parsed = video.parse_ffprobe(data)
        self.assertEqual(34.2, parsed["duration_seconds"])
        self.assertEqual(1920, parsed["width"])
        self.assertEqual(30.0, parsed["fps"])
        self.assertTrue(parsed["audio_present"])

    def test_scene_cut_parse_is_sorted_and_unique(self):
        text = "pts_time:0.5\npts_time:2.0\npts_time:0.5\n"
        self.assertEqual([0.5, 2.0], video.parse_scene_cuts(text))

    def test_cut_density_thresholds(self):
        self.assertEqual("high", analyzer._cut_density(25.0))
        self.assertEqual("medium", analyzer._cut_density(10.0))
        self.assertEqual("low", analyzer._cut_density(2.0))

    def test_manual_observed_and_inference(self):
        with open(os.path.join(_FIX, "manual_observations.json"), encoding="utf-8") as fh:
            manual = json.load(fh)
        profile = analyzer.analyze(manual=manual, reference_id="manual-1")
        self.assertEqual("manual", profile["source_type"])
        self.assertEqual(2.0, profile["observed"]["average_scene_duration"])
        self.assertEqual("fast", profile["inferred"]["pacing"])
        self.assertEqual("fast", profile["inferred"]["hook_speed"])
        self.assertEqual("hard cuts with light motion", profile["inferred"]["transition_style"])

    def test_pacing_bands(self):
        for avg, expected in ((1.5, "fast"), (3.0, "moderate"), (7.0, "slow")):
            profile = analyzer.analyze(manual={"observed": {"average_scene_duration": avg}},
                                       reference_id="p-%s" % avg)
            self.assertEqual(expected, profile["inferred"]["pacing"])


class TestObservedVsInferred(ReferenceTestBase):
    def test_sections_are_separate_and_valid(self):
        profile = analyzer.analyze(self.image_set())
        schema.validate(profile)
        self.assertTrue(set(profile["observed"].keys()) <= schema.OBSERVED_KEYS)
        self.assertTrue(set(profile["inferred"].keys()) <= schema.INFERRED_KEYS)
        overlap = set(profile["observed"]) & set(profile["inferred"])
        self.assertEqual(set(), overlap, "observed and inferred must not share keys")

    def test_inferred_always_present_even_when_unavailable(self):
        profile = analyzer.analyze(self.image_set())
        self.assertIn("layout_style", profile["inferred"])
        self.assertIsNone(profile["inferred"]["layout_style"])
        fields = {u["field"] for u in profile["unavailable"]}
        self.assertIn("layout_style", fields)

    def test_unavailable_stays_unavailable(self):
        profile = analyzer.analyze(self.image_set())
        fields = {u["field"] for u in profile["unavailable"]}
        for f in ("scene_count", "average_scene_duration", "text_density"):
            self.assertIn(f, fields)
        self.assertNotIn("scene_count", profile["observed"])
        self.assertIsNone(profile["inferred"]["pacing"])

    def test_bad_source_type_rejected(self):
        with self.assertRaises(schema.StyleProfileError):
            schema.validate({"schema_version": 1, "reference_id": "x",
                             "source_type": "website", "observed": {},
                             "inferred": {}, "unavailable": []})


class TestNoContentCopied(ReferenceTestBase):
    def test_script_and_transcript_never_copied(self):
        with open(os.path.join(_FIX, "manual_observations.json"), encoding="utf-8") as fh:
            manual = json.load(fh)
        profile = analyzer.analyze(manual=manual, reference_id="copy-check")
        blob = json.dumps(profile, ensure_ascii=False)
        for marker in ("DO-NOT-COPY-THIS-SCRIPT", "DO-NOT-COPY-THIS-TRANSCRIPT"):
            self.assertNotIn(marker, blob)

    def test_branding_and_logo_not_propagated(self):
        manual = {"observed": {"duration_seconds": 10.0},
                  "inferred": {},
                  "logo": "ACME-LOGO-PATH", "brand": "ACME-BRAND",
                  "channel": "ACME-CHANNEL", "watermark": "ACME"}
        profile = analyzer.analyze(manual=manual, reference_id="brand-check")
        blob = json.dumps(profile)
        for marker in ("ACME", "watermark", "logo", "channel"):
            self.assertNotIn(marker, blob)

    def test_unsupported_observed_key_rejected(self):
        with self.assertRaises(schema.StyleProfileError):
            schema.validate({"schema_version": 1, "reference_id": "x",
                             "source_type": "manual",
                             "observed": {"script": "nope"},
                             "inferred": {}, "unavailable": []})


class TestIntegrationSafety(ReferenceTestBase):
    def test_brand_profiles_unchanged(self):
        before = dir_hash(_BRANDS)
        profile = analyzer.analyze(self.image_set())
        analyzer.save_profile(profile)
        self.assertEqual(before, dir_hash(_BRANDS), "brand profiles must not be modified")

    def test_does_not_touch_other_directories(self):
        project = os.path.join(self.tmp, "fake-project")
        os.makedirs(project, exist_ok=True)
        with open(os.path.join(project, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<html>unchanged</html>")
        before = dir_hash(project)
        p = analyzer.analyze(self.image_set())
        analyzer.save_profile(p)
        self.assertEqual(before, dir_hash(project))

    def test_saves_only_under_profile_and_report_dirs(self):
        profile = analyzer.analyze(self.image_set(), reference_id="save-check")
        path = analyzer.save_profile(profile)
        self.assertTrue(path.startswith(analyzer._PROFILE_DIR))
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(os.path.isfile(os.path.join(analyzer._REPORT_DIR, "save-check.md")))
        self.assertEqual(profile, analyzer.load_profile("save-check"))


class TestOffline(unittest.TestCase):
    def test_reference_package_is_offline(self):
        for base, _d, names in os.walk(_ROOT):
            for n in names:
                if not n.endswith(".py") or "__pycache__" in base:
                    continue
                path = os.path.join(base, n)
                if (os.sep + "tests" + os.sep) in path:
                    continue
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
                for bad in ("import requests", "import urllib", "import socket",
                            "urlopen", "http.client"):
                    self.assertNotIn(bad, text, "%s must stay offline" % path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
