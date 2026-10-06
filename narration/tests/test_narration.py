"""Tests for the narration mode + gated pipeline (read-only)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from narration import mode as nar_mode  # noqa: E402
from narration import plan as nar_plan  # noqa: E402

_POC = os.path.join(os.path.dirname(_ROOT), "tests", "word-sync", "alice-ar-kinetic")

_SCENE_HTML = """<!doctype html>
<html lang="ar"><head><meta charset="UTF-8"></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="__DUR__"
     data-fps="30" data-width="1920" data-height="1080">
  __AUDIO__
  <section id="s1" class="clip" data-start="0" data-duration="__DUR__" data-narration-locked="__LOCK__">
    <h1 id="a">عنوان</h1>
  </section>
</div></body></html>
"""


def _tree_hash(path: str) -> str:
    h = hashlib.sha256()
    for base, _dirs, names in os.walk(path):
        for n in sorted(names):
            p = os.path.join(base, n)
            h.update(os.path.relpath(p, path).encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


class ModeTest(unittest.TestCase):
    def test_default_off_and_parsing(self):
        self.assertEqual("off", nar_mode.normalize(None))
        self.assertEqual("off", nar_mode.from_meta({}))
        self.assertEqual("optional", nar_mode.from_meta({"narration": "optional"}))
        self.assertEqual("required", nar_mode.from_meta({"narration": "REQUIRED"}))
        self.assertEqual("required", nar_mode.from_meta({"narration": {"mode": "required"}}))
        self.assertFalse(nar_mode.enabled("off"))
        self.assertTrue(nar_mode.enabled("optional"))
        self.assertTrue(nar_mode.enabled("required"))

    def test_invalid_mode_rejected(self):
        with self.assertRaises(nar_mode.NarrationError):
            nar_mode.normalize("loud")
        with self.assertRaises(nar_mode.NarrationError):
            nar_mode.normalize(3)

    def test_load_missing_meta_is_off(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual("off", nar_mode.load(d))


class FixtureBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="narmode-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def project(self, duration=5.0, mode="required", with_audio=False,
                word_end_ms=None, caption_end_ms=None, locked=True, name="proj"):
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        audio = ('<audio id="nar" src="narration.mp3" data-start="0" data-duration="%s" '
                 'data-volume="1"></audio>' % duration) if with_audio else ""
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(_SCENE_HTML.replace("__DUR__", str(duration))
                     .replace("__AUDIO__", audio)
                     .replace("__LOCK__", "true" if locked else "false"))
        if with_audio:
            with open(os.path.join(d, "narration.mp3"), "wb") as fh:
                fh.write(b"ID3\x04\x00\x00\x00\x00\x00\x00")
        if mode is not None:
            with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as fh:
                json.dump({"narration": mode}, fh)
        if word_end_ms is not None:
            with open(os.path.join(d, "word-timings.json"), "w", encoding="utf-8") as fh:
                json.dump({"schema_version": 1, "provider": "elevenlabs",
                           "audio_duration_ms": int(duration * 1000),
                           "words": [{"word": "مرحبا", "start_ms": 0,
                                      "end_ms": word_end_ms, "confidence": None}]}, fh)
        if caption_end_ms is not None:
            with open(os.path.join(d, "captions.json"), "w", encoding="utf-8") as fh:
                json.dump({"schema_version": 1, "source": "word-timings",
                           "captions": [{"start_ms": 0, "end_ms": caption_end_ms,
                                         "text": "مرحبا"}]}, fh)
        return d

    def steps(self, doc):
        return {s["id"]: s["status"] for s in doc["steps"]}


class PlanTest(FixtureBase):
    def test_off_mode_is_inactive(self):
        project = self.project(mode="off")
        doc = nar_plan.plan(project)
        self.assertFalse(doc["enabled"])
        self.assertFalse(doc["blocked"])
        self.assertTrue(all(s["status"] == nar_plan.NA for s in doc["steps"]))
        self.assertEqual([], doc["scene_requirements"])

    def test_required_without_narration_is_blocked(self):
        project = self.project(mode="required")
        doc = nar_plan.plan(project)
        self.assertTrue(doc["enabled"])
        self.assertTrue(doc["blocked"])
        self.assertEqual(nar_plan.BLOCKED, self.steps(doc)["tts_generate"])

    def test_optional_without_narration_is_not_blocked(self):
        project = self.project(mode="optional")
        doc = nar_plan.plan(project)
        self.assertFalse(doc["blocked"])
        self.assertEqual(nar_plan.PENDING, self.steps(doc)["tts_generate"])

    def test_required_with_audio_and_timings_is_ready(self):
        project = self.project(mode="required", with_audio=True,
                               word_end_ms=1500, caption_end_ms=1500)
        doc = nar_plan.plan(project)
        steps = self.steps(doc)
        self.assertEqual(nar_plan.DONE, steps["tts_generate"])
        self.assertEqual(nar_plan.DONE, steps["provider_timestamps"])
        self.assertEqual(nar_plan.DONE, steps["normalize_timing"])
        self.assertEqual(nar_plan.DONE, steps["phrase_groups"])
        self.assertEqual(nar_plan.DONE, steps["mark_narrated_scenes"])
        self.assertFalse(doc["blocked"])

    def test_visual_minimum_dominates_short_narration(self):
        project = self.project(mode="required", with_audio=True,
                               word_end_ms=500, caption_end_ms=500)
        doc = nar_plan.plan(project)
        req = doc["scene_requirements"][0]
        # max(narration 0.5, caption 0.5, visual min 1.0) + 0.3 tail = 1.3
        self.assertAlmostEqual(0.5, req["narration_end_s"], places=3)
        self.assertAlmostEqual(1.3, req["required_duration_s"], places=3)
        self.assertFalse(req["needs_lengthen"])

    def test_narration_beyond_scene_requires_lengthening(self):
        project = self.project(duration=5.0, mode="required", with_audio=True,
                               word_end_ms=6500, caption_end_ms=6500)
        doc = nar_plan.plan(project)
        req = doc["scene_requirements"][0]
        self.assertAlmostEqual(6.8, req["required_duration_s"], places=3)
        self.assertTrue(req["needs_lengthen"])
        self.assertEqual(nar_plan.PENDING, self.steps(doc)["scene_durations"])

    def test_unmarked_narrated_scene_is_flagged(self):
        project = self.project(mode="required", with_audio=True,
                               word_end_ms=1500, caption_end_ms=1500, locked=False)
        doc = nar_plan.plan(project)
        self.assertEqual(nar_plan.BLOCKED, self.steps(doc)["mark_narrated_scenes"])

    def test_plan_does_not_write_to_project(self):
        project = self.project(mode="required", with_audio=True,
                               word_end_ms=1500, caption_end_ms=1500)
        before = _tree_hash(project)
        nar_plan.plan(project)
        self.assertEqual(before, _tree_hash(project))


class AlicePocTest(unittest.TestCase):
    def test_poc_default_mode_is_off(self):
        self.assertEqual("off", nar_mode.load(_POC))
        doc = nar_plan.plan(_POC)
        self.assertFalse(doc["enabled"])
        self.assertFalse(doc["blocked"])

    def test_poc_as_required_reports_locked_and_tail(self):
        tmp = tempfile.mkdtemp(prefix="narpoc-")
        try:
            dst = os.path.join(tmp, "poc")
            shutil.copytree(_POC, dst,
                            ignore=shutil.ignore_patterns("renders", ".DS_Store"))
            with open(os.path.join(dst, "meta.json"), "w", encoding="utf-8") as fh:
                json.dump({"narration": "required"}, fh)
            doc = nar_plan.plan(dst)
            steps = {s["id"]: s["status"] for s in doc["steps"]}
            self.assertEqual("required", doc["mode"])
            self.assertFalse(doc["blocked"])
            self.assertEqual(nar_plan.DONE, steps["normalize_timing"])
            self.assertEqual(nar_plan.DONE, steps["phrase_groups"])
            self.assertEqual(nar_plan.DONE, steps["mark_narrated_scenes"])
            self.assertEqual(nar_plan.DONE, steps["kinetic_captions"])
            req = doc["scene_requirements"][0]
            self.assertTrue(req["narration_locked"])
            self.assertAlmostEqual(11.213, req["required_duration_s"], places=3)
            self.assertTrue(req["needs_lengthen"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class NoNetworkTest(unittest.TestCase):
    def test_narration_modules_do_not_import_network(self):
        d = _ROOT  # the narration package directory
        for fn in ("mode.py", "plan.py", "cli.py"):
            with open(os.path.join(d, fn), encoding="utf-8") as fh:
                src = fh.read()
            for bad in ("import requests", "import urllib", "import http", "import socket"):
                self.assertNotIn(bad, src, "%s must not import network code" % fn)


if __name__ == "__main__":
    unittest.main(verbosity=2)
