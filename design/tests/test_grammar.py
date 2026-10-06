"""Scene-grammar tests (stdlib unittest).

Run:  python3 -m unittest discover -s design/tests -v
"""

from __future__ import annotations

import copy
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from design import grammar, typography  # noqa: E402
from review import htmlmodel  # noqa: E402

TEMPLATE = typography.TEMPLATE_DIR
LIB = os.path.join(TEMPLATE, "lib")
EXAMPLES = os.path.join(TEMPLATE, "examples")
DEMOS = {fmt: os.path.join(EXAMPLES, "grammar-demo-%s" % fmt) for fmt in ("landscape", "portrait")}
# Tracked pre-grammar (unannotated) compositions; never the git-ignored videos/.
LEGACY_PROJECTS = [
    TEMPLATE,
    os.path.join(_ROOT, "templates", "cinematic-saudi-documentary", "starter"),
    os.path.join(_ROOT, "tests", "word-sync", "alice-ar-kinetic"),
    os.path.join(_ROOT, "review", "tests", "fixtures", "mini_project"),
]


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _project(root: str, sections, width=1920, height=1080) -> str:
    os.makedirs(root, exist_ok=True)
    body = "".join('<section class="clip g-scene"%s data-start="%d" data-duration="3"></section>'
                   % ("".join(' %s="%s"' % kv for kv in attrs.items()), i * 3)
                   for i, attrs in enumerate(sections))
    with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
        fh.write('<html><body><div id="root" data-composition-id="main" data-width="%d" '
                 'data-height="%d">%s</div></body></html>' % (width, height, body))
    return root


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.reg = grammar.load_registry()

    def test_all_grammar_ids_validate(self):
        self.assertEqual([], grammar.validate_registry(self.reg))
        self.assertEqual(set(grammar.REQUIRED_GRAMMARS), set(self.reg["grammars"]))
        self.assertEqual(8, len(self.reg["grammars"]))

    def test_every_grammar_defines_required_fields(self):
        for gid, g in self.reg["grammars"].items():
            for field in ("layout", "media_treatment", "typography", "rtl", "entry", "exit",
                          "callouts", "suitable_for", "unsuitable_for"):
                self.assertTrue(field in g, "%s missing %s" % (gid, field))
            self.assertLessEqual(len(g["entry"]), 3, "%s: motion restraint" % gid)

    def test_motion_vocabulary_is_small_and_implemented(self):
        self.assertLessEqual(len(self.reg["motions"]), 12)
        self.assertEqual({"push_in", "crop_to_region", "highlight_box", "spotlight",
                          "callout_line", "pan_regions"}, set(self.reg["choreography"]))
        js = _read(os.path.join(LIB, "motion.js"))
        for spec in list(self.reg["motions"].values()) + list(self.reg["choreography"].values()):
            fn = spec["js"].split(".")[-1]
            self.assertRegex(js, r"\b%s\s*:\s*function" % re.escape(fn), spec["js"])

    def test_invalid_registry_is_rejected(self):
        bad = copy.deepcopy(self.reg)
        bad["grammars"]["big_number"]["entry"].append("spin_3d")
        bad["grammars"]["comparison"]["unsuitable_for"].append("comparison")
        del bad["grammars"]["kinetic_word"]
        problems = grammar.validate_registry(bad)
        self.assertTrue(any("spin_3d" in p for p in problems))
        self.assertTrue(any("both suitable and unsuitable" in p for p in problems))
        self.assertTrue(any("missing grammar kinetic_word" in p for p in problems))

    def test_candidates_are_content_based_and_deterministic(self):
        self.assertEqual(["big_number"], grammar.candidates("statistic", self.reg))
        self.assertEqual(["comparison"], grammar.candidates("comparison", self.reg))
        self.assertEqual(grammar.candidates("hook", self.reg), grammar.candidates("hook", self.reg))
        self.assertIn("screenshot_detail", grammar.candidates("ui_detail", self.reg))


class TestRTL(unittest.TestCase):
    def test_grammar_containers_are_rtl_and_screenshots_keep_ltr(self):
        css = _read(os.path.join(LIB, "grammar.css"))
        g_block = re.search(r"\n\.g \{(.*?)\}", css, re.S).group(1)
        self.assertIn("direction: rtl", g_block)
        shot = re.search(r"\n\.g-shot \{(.*?)\}", css, re.S).group(1)
        self.assertIn("direction: ltr", shot)
        self.assertIn("direction: rtl", re.search(r"\.g-chrome-bottom \{(.*?)\}", css, re.S).group(1))

    def test_motion_directions_follow_rtl_reading(self):
        js = _read(os.path.join(LIB, "motion.js"))
        self.assertIn('clipPath: "inset(0% 0% 0% " + hidden + "%)"', js, "reveal travels right to left")
        self.assertIn('clipPath: "inset(0% 100% 0% 0%)"', js, "exit wipe continues right to left")
        self.assertIn('transformOrigin: "100% 50%"', js, "lines draw from the right")
        self.assertRegex(js, r'(?s)rtlSlide:.*?x: opt\(o, "distance", 90\)', "enter from +x (right)")

    def test_every_grammar_documents_rtl_behavior(self):
        for gid, g in grammar.load_registry()["grammars"].items():
            self.assertIn("right", g["rtl"].lower(), gid)

    def test_demos_pass_no_tashkeel_and_scope_rtl(self):
        for fmt, demo in DEMOS.items():
            res = subprocess.run(["python3", os.path.join(demo, "tools", "check-tashkeel.py"), demo],
                                 capture_output=True, text=True)
            self.assertEqual(0, res.returncode, res.stdout + res.stderr)
            self.assertNotRegex(_read(os.path.join(demo, "index.html")), r"<html[^>]*dir=")

    @unittest.skipUnless(shutil.which("node"), "node required")
    def test_motion_js_syntax(self):
        res = subprocess.run(["node", "--check", os.path.join(LIB, "motion.js")],
                             capture_output=True, text=True)
        self.assertEqual(0, res.returncode, res.stderr)


class TestSignature(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gram-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_signature_from_annotations(self):
        p = _project(os.path.join(self.tmp, "a"), [
            {"data-grammar": "full_bleed_media"}, {"data-grammar": "big_number"},
            {"data-grammar": "comparison"}])
        self.assertEqual({"signature": ["full_bleed_media", "big_number", "comparison"],
                          "source": "data-grammar"}, grammar.layout_signature(p))

    def test_legacy_and_mixed_signatures(self):
        legacy = _project(os.path.join(self.tmp, "l"), [{}, {}])
        self.assertEqual({"signature": ["legacy_card", "legacy_card"], "source": "legacy_unannotated"},
                         grammar.layout_signature(legacy))
        mixed = _project(os.path.join(self.tmp, "m"), [{"data-grammar": "kinetic_word"}, {}])
        self.assertEqual("mixed", grammar.layout_signature(mixed)["source"])

    def test_validate_project_errors_and_advisories(self):
        p = _project(os.path.join(self.tmp, "v"), [
            {"data-grammar": "nope"},
            {"data-grammar": "big_number", "data-variant": "diagonal"},
            {"data-grammar": "big_number", "data-beat-kind": "process"}])
        res = grammar.validate_project(p)
        self.assertEqual(2, len(res["errors"]))
        self.assertEqual(1, len(res["advisories"]))
        self.assertIn("progressive_list", res["advisories"][0])

    def test_demo_compositions_cover_the_library(self):
        land = grammar.layout_signature(DEMOS["landscape"])
        port = grammar.layout_signature(DEMOS["portrait"])
        self.assertEqual("data-grammar", land["source"])
        self.assertEqual(set(grammar.REQUIRED_GRAMMARS), set(land["signature"]))
        self.assertGreaterEqual(len(set(port["signature"])), 6)
        self.assertNotEqual(land["signature"][:len(port["signature"])], port["signature"])
        for demo in DEMOS.values():
            res = grammar.validate_project(demo)
            self.assertEqual([], res["errors"], res)
            self.assertEqual([], res["advisories"], res)


class TestNovelty(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="novel-")
        self.runs = os.path.join(self.tmp, "runs")
        os.makedirs(self.runs)
        kinds = ["hook", "statistic", "ui_detail", "comparison", "takeaway"]
        self.sig = ["full_bleed_media", "big_number", "screenshot_detail", "comparison", "quote_or_statement"]
        self.project = _project(os.path.join(self.tmp, "new-story"),
                                [{"data-grammar": g, "data-beat-kind": k} for g, k in zip(self.sig, kinds)])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, run_id, signature, fmt="landscape", **extra):
        data = {"run_id": run_id, "layout_signature": signature, "format": fmt}
        data.update(extra)
        with open(os.path.join(self.runs, run_id + ".json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_repeat_is_advisory_only(self):
        self._run("2026-09-20-other-story", list(self.sig))
        res = grammar.novelty_advisory(self.project, self.runs)
        self.assertTrue(res["advisory_only"])
        self.assertEqual(["repeat"], [a["type"] for a in res["advisories"]])
        self.assertTrue(res["suggestions"])
        reg = grammar.load_registry()
        for s in res["suggestions"]:
            for alt in s["alternatives"]:
                self.assertIn(s["beat_kind"], reg["grammars"][alt]["suitable_for"])
                self.assertNotEqual(s["current"], alt)

    def test_distinct_sequence_has_no_advisory(self):
        self._run("2026-09-20-other", ["kinetic_word", "progressive_list", "split_media_text"])
        self.assertEqual([], grammar.novelty_advisory(self.project, self.runs)["advisories"])

    def test_near_repeat(self):
        near = list(self.sig)
        near[3] = "progressive_list"
        self._run("2026-09-20-other", near)
        res = grammar.novelty_advisory(self.project, self.runs)
        self.assertEqual(["near_repeat"], [a["type"] for a in res["advisories"]])

    def test_only_last_three_comparable_runs(self):
        self._run("2026-09-01-oldest", list(self.sig))            # 4th comparable -> ignored
        self._run("2026-09-02-a", ["kinetic_word"])
        self._run("2026-09-03-b", ["comparison"])
        self._run("2026-09-04-portrait", list(self.sig), fmt="portrait")  # other format
        self._run("2026-09-05-new-story-v2", list(self.sig))       # same story -> excluded
        self._run("2026-09-06-c", ["big_number"])
        res = grammar.novelty_advisory(self.project, self.runs)
        self.assertEqual(["2026-09-06-c", "2026-09-03-b", "2026-09-02-a"],
                         [c["run_id"] for c in res["compared"]])
        self.assertEqual([], res["advisories"])

    def test_hook_repeat_across_window(self):
        for i, rid in enumerate(("2026-09-02-a", "2026-09-03-b", "2026-09-04-c")):
            self._run(rid, ["full_bleed_media", ["progressive_list", "kinetic_word", "split_media_text"][i]])
        res = grammar.novelty_advisory(self.project, self.runs)
        self.assertIn("hook_repeat", [a["type"] for a in res["advisories"]])

    def test_legacy_runs_are_derived_and_never_match(self):
        videos = os.path.join(self.tmp, "videos")
        _project(os.path.join(videos, "legacy-story"), [{}, {}, {}])
        self._run("2026-09-02-legacy-story", None)
        res = grammar.novelty_advisory(self.project, self.runs, videos_dir=videos)
        self.assertEqual(["legacy_card"] * 3, res["compared"][0]["signature"])
        self.assertEqual([], res["advisories"])


class TestChoreographySafety(unittest.TestCase):
    def test_motion_runtime_never_touches_pixels_network_or_clocks(self):
        js = _read(os.path.join(LIB, "motion.js"))
        for token in ("getImageData", "putImageData", "toDataURL", "toBlob", "getContext",
                      "fetch(", "XMLHttpRequest", "Math.random", "Date.now", "new Date",
                      "setTimeout", "requestAnimationFrame", "repeat: -1", ".src ="):
            self.assertNotIn(token, js)

    def test_demo_media_are_repository_owned_placeholders(self):
        shared = {}
        for demo in DEMOS.values():
            media = [p for p in glob.glob(os.path.join(demo, "assets", "*")) if os.path.isfile(p)]
            self.assertTrue(media, demo)
            for path in media:
                name = os.path.basename(path)
                self.assertRegex(name, r"^placeholder-[a-z]+\.svg$", path)
                svg = _read(path)
                for token in ("<image", "data:", "href", "<script", "@import", "url(http"):
                    self.assertNotIn(token, svg, path)
                self.assertEqual(shared.setdefault(name, _sha(path)), _sha(path), "drift: %s" % path)
            refs = re.findall(r'<img[^>]*\ssrc="([^"]+)"', _read(os.path.join(demo, "index.html")))
            self.assertTrue(refs, demo)
            for ref in refs:
                self.assertRegex(ref, r"^assets/placeholder-[a-z]+\.svg$", demo)
                self.assertTrue(os.path.isfile(os.path.join(demo, ref)), "missing: %s/%s" % (demo, ref))

    def test_demo_lib_and_fonts_match_template(self):
        for demo in DEMOS.values():
            for sub in ("lib", os.path.join("assets", "fonts")):
                for path in glob.glob(os.path.join(TEMPLATE, sub, "*")):
                    copy_path = os.path.join(demo, sub, os.path.basename(path))
                    self.assertEqual(_sha(path), _sha(copy_path), "drift: %s" % copy_path)


class TestBackwardCompatibility(unittest.TestCase):
    def test_existing_projects_still_parse_and_are_untouched(self):
        projects = [os.path.join(p, "index.html") for p in LEGACY_PROJECTS]
        before = {p: _sha(p) for p in projects}
        for path in projects:
            proj = os.path.dirname(path)
            model = htmlmodel.parse(proj)
            self.assertTrue(model.scenes, proj)
            sig = grammar.layout_signature(proj)
            self.assertEqual("legacy_unannotated", sig["source"], proj)
            self.assertEqual("measured", typography.mobile_readability(proj)["status"], proj)
        self.assertEqual(before, {p: _sha(p) for p in projects})

    def test_legacy_template_path_still_valid(self):
        html = _read(os.path.join(TEMPLATE, "index.html"))
        self.assertEqual(1, html.count('window.__timelines["main"] = tl;'))
        self.assertNotIn("data-grammar", html)
        self.assertEqual("bundled", typography.static_font_report(TEMPLATE)["status"])
        self.assertTrue(htmlmodel.parse(TEMPLATE).scenes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
