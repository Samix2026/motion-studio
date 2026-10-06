"""Typography system tests (stdlib unittest).

Run:  python3 -m unittest discover -s design/tests -v
Render-browser proof (slow, needs npx + Chrome):  MS_RENDER_TESTS=1 python3 -m unittest discover -s design/tests -v
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from design import typography  # noqa: E402
from review import pixels  # noqa: E402

TEMPLATE = typography.TEMPLATE_DIR
RENDER_TESTS = os.environ.get("MS_RENDER_TESTS") == "1"

POS_LOG = "   Fonts: 3 loaded\n\x1b[32m◇\x1b[0m  1 snapshots saved to /tmp/x\n"
NEG_LOG = "   Fonts: 0 loaded, 2 failed\n   Fonts FAILED: SF Arabic (700 normal), Geeza Pro (400 normal)\n"


def _write_project(root: str, style: str, width: int = 1080, height: int = 1920,
                   body: str = '<p class="sub">نص</p>') -> str:
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
        fh.write('<html><head><style>%s</style></head><body>'
                 '<div id="root" data-composition-id="main" data-width="%d" data-height="%d">'
                 '%s</div></body></html>' % (style, width, height, body))
    return root


class TestBundledFont(unittest.TestCase):
    def test_template_uses_bundled_arabic_font(self):
        rep = typography.static_font_report(TEMPLATE)
        self.assertEqual(("Alexandria", "Alexandria"), (rep["required_family"], rep["primary_family"]))
        self.assertEqual("lib/type-scale.json", rep["required_source"])
        self.assertEqual("bundled", rep["status"])
        self.assertFalse(rep["fallback_risk"])
        self.assertEqual([], rep["missing_files"])
        self.assertEqual([], rep["system_faces"], "template must not reference system-only faces")

    def test_font_files_are_real_and_licensed(self):
        scale = typography.load_scale()
        for rel in scale["font"]["files"].values():
            path = os.path.join(TEMPLATE, rel)
            with open(path, "rb") as fh:
                self.assertEqual(b"wOF2", fh.read(4), "%s is not a WOFF2 file" % rel)
        with open(os.path.join(TEMPLATE, scale["font"]["license_file"]), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", text)

    def test_wrong_primary_family_fails_the_required_font(self):
        """A project whose type-scale requires Alexandria but whose composition
        declares, bundles and loads another family is an error, not a pass."""
        tmp = tempfile.mkdtemp(prefix="typo-")
        try:
            proj = os.path.join(tmp, "p")
            os.makedirs(os.path.join(proj, "lib"))
            os.makedirs(os.path.join(proj, "assets", "fonts"))
            shutil.copy(typography.SCALE_PATH, os.path.join(proj, "lib", "type-scale.json"))
            open(os.path.join(proj, "assets", "fonts", "x.ttf"), "wb").close()
            style = '@font-face{font-family:"%s";src:url("assets/fonts/x.ttf")}:root{--ms-font:"%s",sans-serif}'
            _write_project(proj, style % ("IBM Plex Sans Arabic", "IBM Plex Sans Arabic"))
            rep = typography.static_font_report(proj)
            self.assertEqual(("Alexandria", "IBM Plex Sans Arabic", "wrong_family"),
                             (rep["required_family"], rep["primary_family"], rep["status"]))
            self.assertTrue(rep["fallback_risk"])
            _write_project(proj, style % ("Alexandria", "Alexandria"))
            self.assertEqual("bundled", typography.static_font_report(proj)["status"])
            # an explicit project override is honoured
            with open(os.path.join(proj, "meta.json"), "w", encoding="utf-8") as fh:
                fh.write('{"production": {"typography": "IBM Plex Sans Arabic"}}')
            self.assertEqual("wrong_family", typography.static_font_report(proj)["status"])
            _write_project(proj, style % ("IBM Plex Sans Arabic", "IBM Plex Sans Arabic"))
            self.assertEqual("bundled", typography.static_font_report(proj)["status"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_fallback_is_detectable_statically(self):
        tmp = tempfile.mkdtemp(prefix="typo-")
        try:
            system = _write_project(os.path.join(tmp, "a"),
                                    '@font-face{font-family:"SF Arabic";src:local("SF Arabic")}'
                                    ':root{--font-ar:"SF Arabic","Geeza Pro",sans-serif}')
            rep = typography.static_font_report(system)
            self.assertEqual("system_only", rep["status"])
            self.assertTrue(rep["fallback_risk"])
            self.assertIn("SF Arabic", rep["system_faces"])

            undeclared = _write_project(os.path.join(tmp, "b"), "body{font-family:Tajawal,sans-serif}")
            self.assertEqual("undeclared", typography.static_font_report(undeclared)["status"])

            missing = _write_project(os.path.join(tmp, "c"),
                                     '@font-face{font-family:"X";src:url("assets/fonts/x.ttf")}'
                                     ':root{--font-ar:"X",sans-serif}')
            rep = typography.static_font_report(missing)
            self.assertEqual("missing_file", rep["status"])
            self.assertTrue(rep["fallback_risk"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_fallback_is_detectable_from_render_log(self):
        ok = typography.parse_snapshot_font_log(POS_LOG)
        self.assertEqual({"loaded": 3, "failed": 0, "failed_families": []}, ok)
        bad = typography.parse_snapshot_font_log(NEG_LOG)
        self.assertEqual(2, bad["failed"])
        self.assertEqual(["SF Arabic", "Geeza Pro"], bad["failed_families"])
        self.assertIsNone(typography.parse_snapshot_font_log("no diagnostics"))


class TestTypeScale(unittest.TestCase):
    def setUp(self):
        self.scale = typography.load_scale()

    def test_scale_is_valid(self):
        self.assertEqual([], typography.scale_meets_minimums(self.scale))

    def _css_block(self, selector: str) -> dict:
        with open(os.path.join(TEMPLATE, "lib", "type.css"), encoding="utf-8") as fh:
            css = fh.read()
        body = re.search(r"%s\s*\{(.*?)\}" % re.escape(selector), css, re.S).group(1)
        return {k: float(v) for k, v in re.findall(r"--ts-([\w-]+)\s*:\s*([0-9.]+)px", body)}

    def test_landscape_scale_16x9(self):
        spec = self.scale["formats"]["landscape"]
        self.assertEqual((1920, 1080), (spec["width"], spec["height"]))
        for role in ("headline", "secondary", "caption", "credit", "handle", "stat"):
            self.assertIn(role, spec["scale"])
        css = {k.replace("-", "_"): v for k, v in self._css_block('[data-format="landscape"]').items()}
        self.assertEqual({k: float(v) for k, v in spec["scale"].items()}, css, "type.css out of sync")
        self.assertGreaterEqual(typography.phone_px(spec["scale"]["secondary"], 1920, self.scale), 10)

    def test_portrait_scale_9x16(self):
        spec = self.scale["formats"]["portrait"]
        self.assertEqual((1080, 1920), (spec["width"], spec["height"]))
        css = {k.replace("-", "_"): v for k, v in
               self._css_block('[data-format="portrait"]').items()}
        self.assertEqual({k: float(v) for k, v in spec["scale"].items()}, css, "type.css out of sync")
        self.assertGreaterEqual(typography.phone_px(spec["scale"]["secondary"], 1080, self.scale), 14)
        # secondary text grew from the legacy 42px
        self.assertGreater(spec["scale"]["secondary"], 42)

    def test_mobile_readability_measures_legacy_and_new(self):
        tmp = tempfile.mkdtemp(prefix="typo-")
        try:
            legacy = _write_project(os.path.join(tmp, "legacy"), ".sub{font-size:34px}",
                                    1920, 1080)
            rep = typography.mobile_readability(legacy, self.scale)
            item = rep["items"][0]
            self.assertEqual(("sub", "landscape"), (item["class"], rep["format"]))
            self.assertAlmostEqual(34 * 390 / 1920.0, item["phone_px"], places=1)
            self.assertFalse(item["ok"])

            lib = os.path.join(TEMPLATE, "lib", "type.css")
            new = _write_project(os.path.join(tmp, "new"), "", 1920, 1080,
                                 '<p class="t-secondary">نص</p>')
            os.makedirs(os.path.join(new, "lib"))
            shutil.copy(lib, os.path.join(new, "lib", "type.css"))
            with open(os.path.join(new, "index.html"), encoding="utf-8") as fh:
                html = fh.read().replace("<head>", '<head><link rel="stylesheet" href="lib/type.css" />')
            with open(os.path.join(new, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(html)
            item = typography.mobile_readability(new, self.scale)["items"][0]
            self.assertEqual(54.0, item["css_px"])
            self.assertTrue(item["ok"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
class TestFrameZero(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="frame0-")
        self.rule = typography.load_scale()["frame_zero"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _video(self, name: str, box_from: float) -> str:
        out = os.path.join(self.tmp, name)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=0x08080a:s=320x568:d=2:r=30", "-vf",
                        "drawbox=x=40:y=200:w=240:h=60:color=white:t=fill:enable='gte(t,%s)'" % box_from,
                        "-pix_fmt", "yuv420p", out], check=True)
        return out

    def test_empty_black_opening_fails(self):
        res = pixels.frame_zero(self._video("late.mp4", 1.2), 320, 568, self.rule)
        self.assertTrue(res["near_black_empty_at_0"])
        self.assertFalse(res["meaningful_by_deadline"])

    def test_content_at_frame_zero_passes(self):
        res = pixels.frame_zero(self._video("hook.mp4", 0), 320, 568, self.rule)
        self.assertTrue(res["meaningful_at_0"])
        self.assertFalse(res["near_black_empty_at_0"])

    def test_content_by_deadline_passes(self):
        res = pixels.frame_zero(self._video("quick.mp4", 0.3), 320, 568, self.rule)
        self.assertFalse(res["meaningful_at_0"])
        self.assertTrue(res["meaningful_by_deadline"])


@unittest.skipUnless(RENDER_TESTS, "set MS_RENDER_TESTS=1 (needs npx hyperframes + Chrome)")
class TestRenderBrowserFont(unittest.TestCase):
    """Proves the bundled face loads in the real HyperFrames render browser."""

    def test_template_font_loads_in_render_browser(self):
        tmp = tempfile.mkdtemp(prefix="fontrender-")
        try:
            proj = os.path.join(tmp, "tpl")
            shutil.copytree(TEMPLATE, proj, ignore=shutil.ignore_patterns("examples"))
            res = typography.render_font_check(proj)
            self.assertEqual("loaded", res["status"], res)
            self.assertGreaterEqual(res["log"]["loaded"], 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_system_font_fallback_detected_in_render_browser(self):
        tmp = tempfile.mkdtemp(prefix="fontrender-")
        try:
            proj = os.path.join(tmp, "tpl")
            shutil.copytree(TEMPLATE, proj, ignore=shutil.ignore_patterns("examples"))
            path = os.path.join(proj, "index.html")
            with open(path, encoding="utf-8") as fh:
                html = fh.read()
            html = html.replace('<link rel="stylesheet" href="lib/type.css" />',
                                '<style>@font-face{font-family:"SF Arabic";src:local("SF Arabic");'
                                'font-weight:700}</style>')
            html = html.replace('--font-ar: var(--ms-font);', '--font-ar: "SF Arabic", sans-serif;')
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(html)
            res = typography.render_font_check(proj)
            self.assertEqual("wrong_family", res["status"], res)  # the template requires Alexandria
            self.assertIn("SF Arabic", res["log"]["failed_families"])
            # even when a project explicitly requires the system face, it still fails to load
            with open(os.path.join(proj, "meta.json"), "w", encoding="utf-8") as fh:
                fh.write('{"production": {"typography": "SF Arabic"}}')
            self.assertEqual("fallback", typography.render_font_check(proj)["status"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
