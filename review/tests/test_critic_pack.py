"""Lean critic pack: exactly three composite images plus a fact digest.

Run:  python3 -m unittest discover -s review/tests -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from review import htmlmodel, vision  # noqa: E402

_FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "mini_project")
HAS_FFMPEG = bool(shutil.which("ffmpeg"))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class TestCriticPack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="critic-")
        self.project = os.path.join(self.tmp, "proj")
        shutil.copytree(_FIXTURE, self.project)
        self.render = os.path.join(self.tmp, "render.mp4")
        dur = htmlmodel.parse(self.project).duration
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc=s=180x320:d=%s:r=30" % dur, "-pix_fmt", "yuv420p", self.render],
                       check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_exactly_three_images_and_digest(self):
        out = os.path.join(self.tmp, "pack")
        before = sorted(os.listdir(self.project))
        pack = vision.build_critic_pack(self.project, self.render, out)
        self.assertEqual(["1_sheet.jpg", "2_keys.jpg", "3_transitions.jpg", "pack.md"], sorted(os.listdir(out)))
        self.assertEqual(before, sorted(os.listdir(self.project)))  # project untouched
        with open(os.path.join(out, "pack.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("Read: 1_sheet.jpg, 2_keys.jpg, 3_transitions.jpg", text)
        for heading in ("## Images", "## Beats", "## Series constraints", "## Measured facts"):
            self.assertIn(heading, text)
        self.assertIn("near-empty frames:", text)
        self.assertLessEqual(len(pack["key_times"]), vision.CRITIC_KEYS_MAX)

    def test_pack_must_be_outside_project(self):
        with self.assertRaises(ValueError):
            vision.build_critic_pack(self.project, self.render, os.path.join(self.project, "pack"))

    def test_render_is_explicit(self):
        with self.assertRaises(ValueError):
            vision.build_critic_pack(self.project, os.path.join(self.tmp, "missing.mp4"),
                                     os.path.join(self.tmp, "pack"))

    def test_pair_pack_is_blind_and_sealed(self):
        other = os.path.join(self.tmp, "other.mp4")
        dur = htmlmodel.parse(self.project).duration
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=blue:s=180x320:d=%s:r=30" % dur, "-pix_fmt", "yuv420p", other], check=True)
        for swap in (False, True):
            out = os.path.join(self.tmp, "pair-%s" % swap)
            pack = vision.build_pair_pack(self.project, self.render, other, out, swap=swap)
            self.assertEqual(["A_keys.jpg", "A_sheet.jpg", "B_keys.jpg", "B_sheet.jpg", "pack.md"],
                             sorted(os.listdir(out)))
            with open(pack["mapping_path"], encoding="utf-8") as fh:
                mapping = json.load(fh)
            self.assertEqual(os.path.abspath(other if swap else self.render), mapping["A"])
            self.assertFalse(pack["mapping_path"].startswith(out + os.sep))  # outside the pack
            with open(os.path.join(out, "pack.md"), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("Mode: pairwise", text)
            self.assertIn("Read: A_sheet.jpg, A_keys.jpg, B_sheet.jpg, B_keys.jpg", text)
            for leak in ("render.mp4", "other.mp4", self.tmp):
                self.assertNotIn(leak, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
