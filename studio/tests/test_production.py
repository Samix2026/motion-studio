"""Production pipeline: brief/state/gates/critics/QA, and the numeric trace path.

Browser tests run only when node and the pinned tracer are installed
(`python3 studio/cli.py trace <project> --install`); everything else is offline.
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from studio import prerender, production as P, production_cli as C, trace as T  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "trace_project")

LEGACY_HTML = """<!doctype html><html><head><style>
.t { font-family: sans-serif; }
</style></head><body>
<div id="root" data-composition-id="main" data-width="320" data-height="180" data-duration="2">
  <section id="s1" class="clip" data-start="0" data-duration="1" data-track-index="0"><h1>Hello</h1>%s</section>
  <section id="s2" class="clip" data-start="1" data-duration="1" data-track-index="0"><h1>World</h1></section>
</div></body></html>"""


def quiet(fn, *a, **k):
    with redirect_stdout(io.StringIO()):
        return fn(*a, **k)


class ProjectBase(unittest.TestCase):
    extra_html = ""
    meta = {"name": "legacy", "brand": "generic", "audio": {"requested": False},
            "outputs": {"master": {"resolution": "320x180"}}}  # the fixture declares its own format

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ms-prod-")
        self.p = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.p, "assets"))
        self.write("index.html", LEGACY_HTML % self.extra_html)
        self.write("meta.json", json.dumps(self.meta))
        self.write("package.json", '{"scripts": {"render": "npx --yes hyperframes@0.0.1 render"}}')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, name, text):
        with open(os.path.join(self.p, name), "w", encoding="utf-8") as fh:
            fh.write(text)


class TestBriefAndCompatibility(ProjectBase):
    def test_existing_project_remains_compatible(self):
        brief, bf = P.load_brief(self.p)
        self.assertEqual((brief["fps"], brief["resolution"], brief["audio"]), (30, "320x180", "none"))
        self.assertEqual(brief["sources"]["resolution"], "meta.outputs")
        self.assertFalse([f for f in bf if f["severity"] == prerender.ERROR])
        spec, sf = P.load_spec(self.p)
        self.assertIsNone(spec)
        self.assertEqual(sf, [])
        with mock.patch.object(T, "availability", return_value={"available": False, "reason": "no tracer"}):
            self.assertIsNone(quiet(C.run_brief_spec_build, self.p))
            st = quiet(C.run_validation, self.p, True, False, False)
        self.assertIn(st, (P.PASS, P.WARN))
        self.assertEqual(sorted(os.listdir(self.p)), ["assets", "index.html", "meta.json", "package.json",
                                                      "production"], "only production/ is added")

    def test_brief_block_overrides_and_validates(self):
        meta = dict(self.meta, production={"audio": "music+sfx", "fps": 30, "required_text": ["Hello"],
                                           "policy": {"warnings_block": True}})
        self.write("meta.json", json.dumps(meta))
        brief, bf = P.load_brief(self.p)
        self.assertEqual((brief["audio"], brief["policy"]["warnings_block"]), ("music+sfx", True))
        self.write("meta.json", json.dumps(dict(self.meta, production={"audio": "loud", "resolution": "1x1"})))
        _, bf = P.load_brief(self.p)
        self.assertEqual(sorted(f["code"] for f in bf if f["severity"] == prerender.ERROR),
                         ["bad_audio_policy", "resolution_mismatch"])

    def test_required_and_forbidden_text(self):
        self.write("meta.json", json.dumps(dict(self.meta, production={"required_text": ["Missing words"],
                                                                         "forbidden_text": ["World"]})))
        brief, _ = P.load_brief(self.p)
        self.assertEqual(sorted(f["code"] for f in P.check_build(self.p, brief) if f["severity"] == "ERROR"),
                         ["forbidden_text_present", "required_text_missing"])


class TestHandlePlaceholder(ProjectBase):
    """The template placeholder @your_handle must never reach a render."""

    def codes(self, footer):
        self.write("index.html", LEGACY_HTML % footer)
        brief, _ = P.load_brief(self.p)
        return [f["code"] for f in P.check_build(self.p, brief) if f["severity"] == prerender.ERROR]

    def test_unresolved_placeholder_blocks_the_build(self):
        self.assertEqual(self.codes('<span class="t-handle">@your_handle</span>'), ["handle_placeholder"])
        self.assertEqual(quiet(C.run_brief_spec_build, self.p), "build", "blocked before validation and render")

    def test_real_handle_is_accepted(self):
        self.assertEqual(self.codes('<span class="t-handle">@example_studio</span>'), [])

    def test_no_handle_is_accepted(self):
        self.assertEqual(self.codes(""), [])
        self.assertEqual(self.codes("<!-- footer handle: @your_handle (removed on purpose) -->"), [])


class TestTemplatesAreRunnable(unittest.TestCase):
    """Every shipped project directory pins the known-good runtime and has one root composition."""
    projects = sorted(os.path.dirname(p) for p in glob.glob(
        os.path.join(os.path.dirname(_ROOT), "templates", "**", "hyperframes.json"), recursive=True))

    def test_every_template_pins_the_known_good_hyperframes(self):
        self.assertTrue(self.projects)
        for project in self.projects:
            self.assertEqual(T.pinned_version(project), T.HYPERFRAMES_VERSION, project)

    def test_documentation_names_only_the_known_good_hyperframes(self):
        repo = os.path.dirname(_ROOT)
        for path in glob.glob(os.path.join(repo, "**", "*.md"), recursive=True):
            with open(path, encoding="utf-8") as fh:
                versions = set(re.findall(r"hyperframes@(\d+\.\d+\.\d+)", fh.read()))
            self.assertLessEqual(versions, {T.HYPERFRAMES_VERSION}, os.path.relpath(path, repo))

    def test_one_root_composition_per_project_directory(self):
        for project in self.projects:
            roots = []
            for path in glob.glob(os.path.join(project, "*.html")):
                with open(path, encoding="utf-8") as fh:
                    if "data-composition-id" in fh.read():
                        roots.append(os.path.basename(path))
            self.assertEqual(roots, ["index.html"], project)


class TestExpectedFormat(ProjectBase):
    """The expected format is declared (default 1920x1080), never read from the composition."""
    bare = {"name": "legacy", "brand": "generic", "audio": {"requested": False}}

    def errors(self):
        brief, bf = P.load_brief(self.p)
        return brief, [f["code"] for f in bf if f["severity"] == prerender.ERROR]

    def html(self, w, h):
        self.write("index.html", (LEGACY_HTML % "").replace('data-width="320" data-height="180"',
                                                           'data-width="%d" data-height="%d"' % (w, h)))

    def test_default_standard_output_is_1920x1080(self):
        self.write("meta.json", json.dumps(self.bare))
        self.html(1920, 1080)
        brief, errs = self.errors()
        self.assertEqual((brief["resolution"], brief["sources"]["resolution"], errs),
                         ("1920x1080", "default", []))

    def test_undeclared_portrait_composition_is_an_error(self):
        self.write("meta.json", json.dumps(self.bare))
        self.html(1080, 1920)
        brief, errs = self.errors()
        self.assertEqual((brief["resolution"], errs), ("1920x1080", ["resolution_mismatch"]))

    def test_explicit_portrait_override(self):
        self.write("meta.json", json.dumps(dict(self.bare, format="portrait")))
        self.html(1080, 1920)
        brief, errs = self.errors()
        self.assertEqual((brief["resolution"], brief["sources"]["resolution"], errs),
                         ("1080x1920", "meta.format", []))
        self.html(1920, 1080)
        self.assertEqual(self.errors()[1], ["resolution_mismatch"], "portrait declared, landscape built")


class TestRequiredFont(ProjectBase):
    def test_wrong_primary_family_is_a_build_error(self):
        os.makedirs(os.path.join(self.p, "lib"))
        self.write("lib/type-scale.json", '{"font": {"family": "Alexandria"}}')
        brief, _ = P.load_brief(self.p)
        codes = [f["code"] for f in P.check_build(self.p, brief) if f["severity"] == prerender.ERROR]
        self.assertEqual(codes, ["font_required_mismatch"])  # LEGACY_HTML declares no Alexandria


class TestVisualFirst(ProjectBase):
    def codes(self):
        brief, _ = P.load_brief(self.p)
        return sorted({f["code"] for f in P.check_build(self.p, brief) if f["severity"] == prerender.ERROR})

    def test_storyboard_without_the_visual_story_block_blocks_the_build(self):
        self.assertEqual(self.codes(), [], "legacy project without a storyboard: warned, not blocked")
        self.write("storyboard.md", "# Storyboard\n\n1. headline\n2. list\n")
        self.assertEqual(self.codes(), ["visual_role_missing", "visual_story_missing"])
        self.write("meta.json", json.dumps(dict(self.meta, production={"policy": {"visual_story": False}})))
        self.assertEqual(self.codes(), [], "explicit opt-out for a legacy project")


class TestGates(ProjectBase):
    extra_html = '<img src="assets/logo.png">'

    def gate(self, **kw):
        brief, _ = P.load_brief(self.p)
        ctx = P.context(self.p, brief, None)
        with mock.patch.object(P.subprocess, "run") as run:
            r = P.render(self.p, brief, ctx, P.production_hash(self.p), **kw)
        return r, run

    def record_pre(self, validation=P.PASS):
        h = P.production_hash(self.p)
        for s in ("brief", "spec", "build"):
            P.record(self.p, s, P.PASS, "ok", phash=h)
        P.record(self.p, "validation", validation, "x", phash=h)

    def test_missing_required_asset_blocks_render(self):
        self.record_pre()
        r, run = self.gate()
        self.assertTrue(r["blocked"])
        self.assertTrue(any("assets/logo.png" in x for x in r["reasons"]))
        run.assert_not_called()

    def test_blocking_validation_prevents_render(self):
        self.write("assets/logo.png", "png")
        self.record_pre(P.FAIL)
        r, run = self.gate()
        self.assertTrue(r["blocked"])
        self.assertTrue(any(x.startswith("validation: FAIL") for x in r["reasons"]))
        run.assert_not_called()

    def test_validation_not_run_or_stale_blocks_render(self):
        self.write("assets/logo.png", "png")
        r, run = self.gate()
        self.assertTrue(any("validation: NOT RUN" in x for x in r["reasons"]))
        self.record_pre()
        self.write("index.html", LEGACY_HTML % "<p>edited</p>")  # builder edits after validation
        r, run = self.gate()
        self.assertTrue(any("validation: STALE" in x for x in r["reasons"]))
        run.assert_not_called()

    def test_warnings_do_not_block_render_by_default(self):
        self.write("assets/logo.png", "png")
        self.record_pre(P.WARN)
        brief, _ = P.load_brief(self.p)
        self.assertEqual(P.gate_reasons(self.p, P.production_hash(self.p), brief, False), [])
        brief["policy"]["warnings_block"] = True
        self.assertTrue(P.gate_reasons(self.p, P.production_hash(self.p), brief, False))

    def test_review_required_blocks_until_critics_pass(self):
        self.write("assets/logo.png", "png")
        self.record_pre()
        brief, _ = P.load_brief(self.p)
        reasons = P.gate_reasons(self.p, P.production_hash(self.p), brief, True)
        self.assertTrue(any(r.startswith("motion_critic") for r in reasons))

    def test_critics_are_advisory_unless_review_required(self):
        self.write("assets/logo.png", "png")
        self.record_pre()
        brief, _ = P.load_brief(self.p)
        h = P.production_hash(self.p)
        self.assertEqual(P.gate_reasons(self.p, h, brief, False), [], "no review started: render allowed")
        P.record(self.p, "motion_critic", P.PENDING, "awaiting", phash=h)
        self.assertEqual(P.gate_reasons(self.p, h, brief, False), [], "optional critic never blocks")
        P.record(self.p, "motion_critic", P.FAIL, "8 findings", phash=h)
        self.assertEqual(P.gate_reasons(self.p, h, brief, False), [], "optional critic never blocks")
        self.assertTrue(any(r.startswith("motion_critic: FAIL") for r in P.gate_reasons(self.p, h, brief, True)),
                        "strict mode still gates on the critic")

    def test_override_is_visible(self):
        self.record_pre(P.FAIL)
        brief, _ = P.load_brief(self.p)
        ctx = P.context(self.p, brief, None)
        out = os.path.join(self.p, "renders", "video.mp4")

        def fake_render(cmd, **kw):
            os.makedirs(os.path.dirname(out), exist_ok=True)
            open(out, "w").close()
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch.object(P.subprocess, "run", side_effect=fake_render), \
                mock.patch.object(P, "_npx_hf", return_value=["npx", "hyperframes"]):
            r = P.render(self.p, brief, ctx, P.production_hash(self.p), override="client deadline")
        self.assertEqual(r["status"], P.PASS)
        self.assertIn("OVERRIDE: client deadline", r["summary"])
        self.assertTrue(r["bypassed"])

    def test_refuses_to_overwrite_foreign_render(self):
        self.write("assets/logo.png", "png")
        self.record_pre()
        os.makedirs(os.path.join(self.p, "renders"))
        self.write("renders/video.mp4", "someone else's master")
        r, run = self.gate()
        self.assertTrue(r["blocked"])
        run.assert_not_called()


class TestCritics(ProjectBase):
    def verdict(self, **kw):
        doc = {"critic": "motion", "reviewer": "motion-critic", "pack": "abc", "verdict": "PASS",
               "findings": []}
        doc.update(kw)
        return P.validate_critic_record(doc, "motion", "abc")

    def finding(self, sev):
        return {"severity": sev, "scene": "s1", "frame": 3, "issue": "i", "evidence": "e", "correction": "c"}

    def test_builder_cannot_judge(self):
        _, errs = self.verdict(reviewer="builder")
        self.assertTrue(any("builder ≠ judge" in e for e in errs))

    def test_stale_pack_refused(self):
        _, errs = self.verdict(pack="old")
        self.assertTrue(any("stale" in e for e in errs))

    def test_findings_need_location_and_correction(self):
        _, errs = self.verdict(findings=[{"severity": "MINOR", "issue": "x"}])
        self.assertEqual(len(errs), 3)

    def test_stricter_verdict_wins(self):
        rec, _ = self.verdict(verdict="PASS", findings=[self.finding("BLOCKING")])
        self.assertEqual(rec["verdict"], P.FAIL)
        rec, _ = self.verdict(verdict="PASS", findings=[self.finding("MAJOR")])
        self.assertEqual(rec["verdict"], P.WARN)
        rec, _ = self.verdict(verdict="PASS", findings=[self.finding("MINOR")])
        self.assertEqual(rec["verdict"], P.WARN)
        rec, _ = self.verdict(verdict="FAIL", findings=[])
        self.assertEqual(rec["verdict"], P.FAIL)

    def test_fix_loop_escalates(self):
        state = {"stages": {}, "history": [
            {"stage": "motion_critic", "status": P.FAIL, "hash": h} for h in ("a", "b", "b", "c")]}
        self.assertEqual(P.fix_iterations(state), 3)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
class TestQA(ProjectBase):
    def media(self, audio):
        out = os.path.join(self.tmp, "v.mp4")
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=2"]
        if audio:
            cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest"]
        subprocess.run(cmd + ["-c:v", "libx264", "-pix_fmt", "yuv420p", out], check=True)
        return out

    def test_silent_project_skips_audio_and_verifies_no_stream(self):
        brief, _ = P.load_brief(self.p)
        ctx = P.context(self.p, brief, None)
        path = self.media(audio=False)
        self.assertEqual([f for f in P.qa(path, brief, ctx) if f["severity"] == prerender.ERROR], [])
        status, _ = P.audio_qa(path, brief, ctx)
        self.assertEqual(status, P.SKIPPED)
        noisy = self.media(audio=True)
        self.assertIn("unexpected_audio", [f["code"] for f in P.qa(noisy, brief, ctx)])

    def test_render_at_the_wrong_size_fails_qa(self):
        brief, _ = P.load_brief(self.p)
        ctx = P.context(self.p, brief, None)
        wrong = dict(brief, resolution="1920x1080")  # declared format differs from the 320x180 render
        self.assertIn("resolution", [f["code"] for f in P.qa(self.media(audio=False), wrong, ctx)
                                     if f["severity"] == prerender.ERROR])

    def test_qa_detects_spec_mismatch_and_missing_audio(self):
        self.write("meta.json", json.dumps(dict(self.meta, production={"audio": "sfx", "fps": 25})))
        brief, _ = P.load_brief(self.p)
        ctx = P.context(self.p, brief, None)
        path = self.media(audio=False)
        self.assertIn("fps", [f["code"] for f in P.qa(path, brief, ctx)])
        status, f = P.audio_qa(path, brief, ctx)
        self.assertEqual((status, f[0]["code"]), (P.FAIL, "missing_audio"))
        status, f = P.audio_qa(self.media(audio=True), brief, ctx)
        self.assertIn("loudness_measured", [x["code"] for x in f])
        self.assertNotEqual(status, P.FAIL)


class TestTraceCacheAndFailure(unittest.TestCase):
    """Trace path without a browser: the adapter is replaced by a recorded trace."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ms-trace-")
        self.p = os.path.join(self.tmp, "fx")
        shutil.copytree(FIXTURE, self.p)
        brief, _ = P.load_brief(self.p)
        self.ctx = P.context(self.p, brief, None)
        frames = self.ctx["frames"]
        y = [0.0] * frames
        y[15] = 120.0
        self.raw = {"ok": True, "duration": 3, "fps": 30, "frames": frames, "width": 320, "height": 180,
                    "elements": [{"key": "glitch", "reason": "animated", "scene": "s1"}], "truncated": 0,
                    "tracks": {"glitch.y": y, "glitch.alpha": [1] * frames}, "stage_visible": [1] * frames,
                    "reseek_mismatches": [], "timing_ms": {}}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def patched(self, run):
        return mock.patch.multiple(T, availability=mock.Mock(return_value={"available": True, "version": "x"}),
                                   run_trace=run)

    def test_trace_cache_invalidates_after_composition_change(self):
        run = mock.Mock(return_value=self.raw)
        with self.patched(run):
            self.assertEqual(T.get_trace(self.p, self.ctx)["status"], "traced")
            self.assertEqual(T.get_trace(self.p, self.ctx)["status"], "cached")
            self.assertEqual(run.call_count, 1)
            with open(os.path.join(self.p, "index.html"), "a", encoding="utf-8") as fh:
                fh.write("<!-- edit -->\n")
            self.assertEqual(T.get_trace(self.p, self.ctx)["status"], "traced")
            self.assertEqual(run.call_count, 2)
        doc = T.load_cached(self.p, T.cache_key(self.p, self.ctx, {}))
        self.assertEqual(doc["composition_hash"], T.composition_hash(self.p))

    def test_stale_trace_is_never_used_when_tracer_missing(self):
        with self.patched(mock.Mock(return_value=self.raw)):
            T.get_trace(self.p, self.ctx)
        with open(os.path.join(self.p, "index.html"), "a", encoding="utf-8") as fh:
            fh.write("<!-- edit -->\n")
        with mock.patch.object(T, "availability", return_value={"available": False, "reason": "gone"}):
            self.assertEqual(T.get_trace(self.p, self.ctx)["status"], "unavailable")

    def test_recorded_runtime_spike_is_detected(self):
        with self.patched(mock.Mock(return_value=self.raw)):
            f, info = P.numeric_validation(self.p, self.ctx, None, P.DEFAULT_POLICY)
        self.assertEqual(info["status"], P.FAIL)
        self.assertIn(("one_frame_outlier", 15, "glitch.y"),
                      [(x["code"], x["frame"], x["property"]) for x in f])

    def test_trace_failure_cannot_be_reported_as_pass(self):
        for avail, run in (({"available": False, "reason": "browser trace unavailable: node not found"}, None),
                           ({"available": True, "version": "x"}, {"ok": False, "error": "Chrome crashed"})):
            with mock.patch.object(T, "availability", return_value=avail), \
                    mock.patch.object(T, "run_trace", return_value=run):
                f, info = P.numeric_validation(self.p, self.ctx, None, P.DEFAULT_POLICY)
                self.assertEqual(info["status"], P.SKIPPED)
                self.assertTrue(info["reason"])
                f, info = P.numeric_validation(self.p, self.ctx, None,
                                               dict(P.DEFAULT_POLICY, require_numeric_validation=True))
                self.assertEqual(info["status"], P.FAIL)
                self.assertIn("numeric_validation_required", [x["code"] for x in f])

    def test_report_states_skip_reason(self):
        with mock.patch.object(T, "availability", return_value={"available": False, "reason": "browser trace "
                                                                "unavailable: tracer not installed"}):
            quiet(C.run_brief_spec_build, self.p)
            quiet(C.run_validation, self.p, True, False, False)
        text = P.report(self.p)
        self.assertIn("Numeric trace: SKIPPED — reason: browser trace unavailable", text)


def _tracer_ready():
    v = T.pinned_version(FIXTURE)
    return bool(shutil.which("node")) and bool(v) and T.tracer_installed(v)


@unittest.skipUnless(_tracer_ready(), "browser tracer not installed (studio/cli.py trace <p> --install)")
class TestBrowserTrace(unittest.TestCase):
    """Real runtime trace of the CSS-animated fixture (no render)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ms-btrace-")
        cls.p = os.path.join(cls.tmp, "fx")
        shutil.copytree(FIXTURE, cls.p)
        brief, _ = P.load_brief(cls.p)
        cls.ctx = P.context(cls.p, brief, None)
        cls.first = T.get_trace(cls.p, cls.ctx, refresh=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def validate(self, spec=None):
        f, info = P.numeric_validation(self.p, self.ctx, spec, P.DEFAULT_POLICY)
        return [(x["severity"], x["code"], x["frame"], x["property"]) for x in f], info

    def test_deterministic_trace_identical_twice(self):
        self.assertEqual(self.first["status"], "traced", self.first.get("reason"))
        second = T.get_trace(self.p, self.ctx, refresh=True)
        self.assertEqual(second["trace"]["tracks"], self.first["trace"]["tracks"])
        self.assertEqual(second["trace"]["stage_visible"], self.first["trace"]["stage_visible"])
        self.assertEqual(self.first["trace"]["reseek_mismatches"], [])

    def test_runtime_transform_spike_detected(self):
        got, info = self.validate()
        self.assertIn(("ERROR", "one_frame_outlier", 15, "glitch.y"), got)
        self.assertEqual(info["status"], P.FAIL)

    def test_runtime_opacity_spike_detected(self):
        got, _ = self.validate()
        self.assertIn(("ERROR", "one_frame_outlier", 60, "flash.opacity"), got)

    def test_intentional_runtime_jump_accepted(self):
        got, _ = self.validate()
        self.assertIn(("WARNING", "suspicious_jump", 30, "jumper.x"), got)
        got, _ = self.validate({"discontinuities": [{"kind": "intentional_jump", "frame": 30,
                                                     "property": "jumper.*"}]})
        self.assertNotIn(("WARNING", "suspicious_jump", 30, "jumper.x"), got)
        self.assertIn(("INFO", "jump_accepted", 30, "jumper.x"), got)

    def test_camera_whip_annotation_prevents_false_positive(self):
        got, _ = self.validate()
        self.assertTrue([g for g in got if g[3] == "camera.x" and g[0] == "WARNING"])
        got, _ = self.validate({"discontinuities": [{"kind": "whip", "frames": [70, 78], "property": "camera.*"}]})
        self.assertFalse([g for g in got if g[3].startswith("camera.") and g[0] != "INFO"])

    def test_smooth_motion_is_clean(self):
        got, _ = self.validate()
        self.assertFalse([g for g in got if g[3] and g[3].startswith("pan.") and g[0] != "INFO"])

    def test_spec_tracks_are_authoritative_and_compared(self):
        spec = {"tracks": {"pan.x": [[0, 0], [89, 200]]}}
        got, info = self.validate(spec)
        self.assertEqual(info["sources"], ["spec", "trace"])
        self.assertIn(("WARNING", "runtime_differs_from_spec"), [g[:2] for g in got])


if __name__ == "__main__":
    unittest.main()
