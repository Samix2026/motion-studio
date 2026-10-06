"""Multimodal visual review interface tests (offline fixtures only).

Run:  python3 -m unittest discover -s review/tests -v
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from costgate import gate as cost_gate, schema as cost_schema  # noqa: E402
from review import apply_proposal, htmlmodel, proposal_engine, proposal_schema, quality, revision, vision  # noqa: E402

FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "vision", "judgments.json")
MINI = os.path.join(_ROOT, "tests", "fixtures", "mini_project")
HAS_FFMPEG = bool(shutil.which("ffmpeg"))

GRAMMAR_HTML = """<!doctype html>
<html lang="ar"><head><meta charset="UTF-8" /></head><body>
<div id="root" data-composition-id="main" data-format="landscape" data-start="0" data-duration="6" data-fps="30" data-width="320" data-height="180">
<section id="s1" class="clip g-scene" data-grammar="full_bleed_media" data-variant="bottom_band" data-beat-kind="hook" data-start="0" data-duration="2" data-track-index="1"><div class="g"><figure class="g-media" id="s1media"><img id="s1img" src="assets/hero.png" alt="" /></figure><h1 class="t-headline">عنوان الخطاف</h1></div></section>
<section id="s2" class="clip g-scene" data-grammar="big_number" data-variant="center" data-beat-kind="statistic" data-start="2" data-duration="2" data-track-index="2"><div class="g"><p class="t-stat">14</p></div></section>
<section id="s3" class="clip g-scene" data-grammar="comparison" data-variant="columns" data-beat-kind="comparison" data-start="4" data-duration="2" data-track-index="3"><div class="g"><p class="t-secondary">قبل</p><p class="t-secondary">بعد</p></div></section>
</div>
<script>
const tl = gsap.timeline({ paused: true });
tl.fromTo("#s1media", { opacity: 0.6 }, { opacity: 1, duration: 0.5, ease: "power2.out" }, 0);
window.__timelines["main"] = tl;
</script></body></html>
"""


def tree_hash(path: str) -> str:
    h = hashlib.sha256()
    for root, _dirs, files in os.walk(path):
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            h.update(os.path.relpath(fp, path).encode())
            with open(fp, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


class VisionBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vision-")
        self._orig = revision._STATE_DIR
        revision._STATE_DIR = os.path.join(self.tmp, "state")
        os.makedirs(revision._STATE_DIR)
        self.project = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.project, "renders"))
        with open(os.path.join(self.project, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(GRAMMAR_HTML)
        for name, body in (("meta.json", '{"id": "proj", "brand": "nvidia"}'), ("script.md", "نص"),
                           ("storyboard.md", "لوحة"), ("sources.md", "مصادر")):
            with open(os.path.join(self.project, name), "w", encoding="utf-8") as fh:
                fh.write(body)
        self.render = os.path.join(self.project, "renders", "preview.mp4")
        self.inputs = os.path.join(self.tmp, "inputs")

    def tearDown(self):
        revision._STATE_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_render(self):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x202020:s=320x180:d=6:r=30",
                        "-vf", "drawbox=x=20:y=20:w=120:h=60:color=white:t=fill:enable='lt(t,2)',"
                               "drawbox=x=180:y=90:w=100:h=60:color=white:t=fill:enable='between(t,2,4)'",
                        "-pix_fmt", "yuv420p", self.render], check=True)

    def manifest_stub(self):
        return {"midpoints": ["m1", "m2", "m3"], "hook_frames": ["h0", "h1", "h2", "h3"],
                "transition_strips": ["t1", "t2"], "contact_sheet": "sheet"}

    def review(self):
        return vision.run_visual_review(self.project, self.manifest_stub(), vision.FixtureProvider(FIXTURE))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class TestInputs(VisionBase):
    def test_build_inputs_extracts_frames_outside_project(self):
        self.make_render()
        before = tree_hash(self.project)
        m = vision.build_inputs(self.project, self.render, self.inputs)
        self.assertEqual(3, len(m["midpoints"]))
        self.assertEqual(4, len(m["hook_frames"]))
        self.assertEqual(2, len(m["transition_strips"]))
        self.assertEqual("contact-sheet.png", m["contact_sheet"])
        for name in m["midpoints"] + m["hook_frames"] + m["transition_strips"] + [m["contact_sheet"]]:
            self.assertTrue(os.path.isfile(os.path.join(self.inputs, name)), name)
        self.assertEqual(["full_bleed_media", "big_number", "comparison"],
                         m["metadata"]["layout_signature"]["signature"])
        self.assertEqual("nvidia", m["metadata"]["brand"])
        self.assertEqual(sorted(proposal_schema.VISION_OPERATIONS), m["allowed_operations"])
        self.assertEqual(before, tree_hash(self.project), "inputs must not modify the project")
        self.assertEqual(10, vision.image_count(m))

    def test_build_inputs_requires_render_and_outside_dir(self):
        with self.assertRaises(ValueError):
            vision.build_inputs(self.project, None, self.inputs)
        self.make_render()
        with self.assertRaises(ValueError):
            vision.build_inputs(self.project, self.render, os.path.join(self.project, "vision"))


class TestJudgment(VisionBase):
    def test_multimodal_findings_are_marked_ai_judgment(self):
        res = self.review()
        self.assertEqual(5, len(res["findings"]))
        for f in res["findings"]:
            self.assertEqual(proposal_schema.AI_JUDGMENT, f["basis"])
            self.assertFalse(f["measured"])
            self.assertIsNone(f["evidence"]["measured_value"])
            self.assertEqual("visual_judgment", f["category"])
            proposal_schema.validate_finding(f)
        self.assertIn("AI JUDGMENT", vision.render_vision_md(res))
        self.assertTrue(any("unsupported dimension" in n for n in res["notes"]))
        self.assertFalse(res["auto_applied"])

    def test_judgment_cannot_be_disguised_as_measured_fact(self):
        f = self.review()["findings"][0]
        forged = dict(f, basis=proposal_schema.MEASURED_FACT)
        with self.assertRaises(proposal_schema.SchemaError):
            proposal_schema.validate_finding(forged)
        with_value = dict(f, evidence=dict(f["evidence"], measured_value=0.9))
        with self.assertRaises(proposal_schema.SchemaError):
            proposal_schema.validate_finding(with_value)

    def test_multimodal_finding_cannot_hard_fail(self):
        res = self.review()
        self.assertTrue(all(f["hard_fail"] is False for f in res["findings"]))
        self.assertTrue(any("hard_fail ignored" in n for n in res["notes"]))
        with self.assertRaises(proposal_schema.SchemaError):
            proposal_schema.validate_finding(dict(res["findings"][0], hard_fail=True))
        with self.assertRaises(quality.QualityError):
            quality.score({"accuracy_sourcing": 30, "hook_editorial_clarity": 18, "asset_quality": 9,
                           "brand_identity_fit": 9, "arabic_rtl_quality": 10, "technical_validation": 5},
                          hard_fails=[{"reason": "looks cheap", "basis": proposal_schema.AI_JUDGMENT}])

    def test_proposal_whitelist_enforced(self):
        res = self.review()
        ops = [p["operation"]["type"] for p in res["proposals"]]
        self.assertEqual(["swap_layout_variant", "add_push_in", "enlarge_secondary_text"], ops)
        self.assertTrue(all(p["origin"] == "multimodal" for p in res["proposals"]))
        rejected = [n for n in res["notes"] if "not in the layout whitelist" in n]
        self.assertEqual(2, len(rejected))  # change_text_size and shell_command
        bad = dict(res["proposals"][0], operation={"type": "change_text_size", "class": "sub", "to": 80})
        with self.assertRaises(proposal_schema.SchemaError):
            proposal_schema.validate_proposal(bad)

    def test_layout_operations_reject_legacy_scenes(self):
        model = htmlmodel.parse(MINI)
        for op in ({"type": "swap_layout_variant", "scene": 1, "to": "top_band"},
                   {"type": "reduce_empty_space", "scene": 1}):
            with self.assertRaises(proposal_engine.SimulationError):
                proposal_engine.simulate(model, op)

    def test_layout_operation_bounds(self):
        model = htmlmodel.parse(self.project)
        for op in ({"type": "swap_layout_variant", "scene": 2, "to": "diagonal"},
                   {"type": "enlarge_secondary_text", "scene": 3, "factor": 2.0},
                   {"type": "add_push_in", "scene": 2, "target": "#s1img"},
                   {"type": "add_push_in", "scene": 1, "target": "#s1img", "scale": 1.5}):
            with self.assertRaises(proposal_engine.SimulationError):
                proposal_engine.simulate(model, op)

    def test_visual_quality_score_from_judgments(self):
        res = self.review()
        self.assertEqual({"score": 9.6, "max": 15, "source": "multimodal_review"}, res["visual_quality"])


class TestGate2AndCost(VisionBase):
    def test_gate2_preserved_only_approved_layout_edits_apply(self):
        before = tree_hash(self.project)
        props = self.review()["proposals"]
        self.assertTrue(all(p["status"] == "awaiting_review" for p in props))
        self.assertEqual([], apply_proposal.apply_approved(self.project, props, [])["applied"])
        self.assertEqual(before, tree_hash(self.project))

        result = apply_proposal.apply_approved(self.project, props, [p["id"] for p in props])
        with open(os.path.join(result["new_dir"], "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('data-variant="top_band"', html)
        self.assertRegex(html, r'<img id="s1img" src="assets/hero.png" alt="" data-push-in="1.06" />')
        self.assertRegex(html, r'<section id="s3"[^>]*style="--secondary-scale: 1.15"')
        self.assertEqual(before, tree_hash(self.project), "source project untouched")
        self.assertEqual(htmlmodel.parse(self.project).duration, htmlmodel.parse(result["new_dir"]).duration)

    def test_stale_vision_proposal_rejected(self):
        props = self.review()["proposals"]
        with open(os.path.join(self.project, "index.html"), "a", encoding="utf-8") as fh:
            fh.write("<!-- edited after review -->")
        with self.assertRaises(apply_proposal.StaleRevisionError):
            apply_proposal.apply_approved(self.project, props, [props[0]["id"]])

    def test_paid_provider_blocked_until_cost_gate_approved(self):
        calls = []

        class PaidStub(vision.VisionProvider):
            name = "paid-stub"
            requires_payment = True

            def review(self, manifest):
                calls.append(manifest)
                return {"judgments": []}

        with self.assertRaises(vision.CostGateBlocked):
            vision.run_visual_review(self.project, self.manifest_stub(), PaidStub())
        self.assertEqual([], calls, "a paid provider must not be called before approval")
        vision.run_visual_review(self.project, self.manifest_stub(), PaidStub(), gate_check=lambda p: None)
        self.assertEqual(1, len(calls))

    def test_cost_plan_item_is_valid_and_unknown_priced(self):
        items = vision.cost_plan_items(self.manifest_stub(), "ExampleVision", "vision-model")
        plan = {"project": "proj", "items": items}
        cost_schema.validate_plan(plan)
        g = cost_gate.build_gate(plan, {"currency": "USD", "prices": {}}, self.project, created_at="")
        self.assertIn(g["cost_status"], ("unknown", "partial"))
        self.assertFalse(cost_gate.generation_allowed(g))

    def test_no_network_in_review_modules(self):
        for name in ("vision.py", "pixels.py", "quality.py"):
            with open(os.path.join(_ROOT, name), encoding="utf-8") as fh:
                src = fh.read()
            for token in ("urllib", "http.client", "import requests", "import socket", "urlopen"):
                self.assertNotIn(token, src, "%s must not use %s" % (name, token))


class TestQuality(unittest.TestCase):
    MEASURED = {"accuracy_sourcing": 30, "hook_editorial_clarity": 19, "asset_quality": 10,
                "brand_identity_fit": 9, "arabic_rtl_quality": 10, "technical_validation": 5}

    def test_visual_quality_cannot_be_self_scored(self):
        with self.assertRaises(quality.QualityError):
            quality.score(dict(self.MEASURED, visual_quality=14))
        with self.assertRaises(quality.QualityError):
            quality.score(self.MEASURED, visual={"score": 14, "source": "self"})

    def test_unreviewed_visual_is_marked_and_blocks_ready(self):
        res = quality.score(self.MEASURED)
        self.assertIsNone(res["quality_score"])
        self.assertIsNone(res["quality_breakdown"]["visual_quality"])
        self.assertEqual("not_independently_reviewed", res["visual_quality_status"])
        self.assertEqual(97.6, res["normalized_without_visual"])
        self.assertFalse(res["ready_to_publish"])
        self.assertEqual("minor_review_required", res["decision"])

    def test_independent_visual_review_completes_the_score(self):
        res = quality.score(self.MEASURED, visual={"score": 9.6, "source": "multimodal_review"})
        self.assertEqual(92.6, res["quality_score"])
        self.assertTrue(res["ready_to_publish"])
        human = quality.score(self.MEASURED, visual={"score": 6, "source": "human_review"})
        self.assertEqual("minor_review_required", human["decision"])

    def test_measured_hard_fail_still_blocks(self):
        res = quality.score(self.MEASURED, visual={"score": 15, "source": "human_review"},
                            hard_fails=[{"reason": "unverified claim", "basis": proposal_schema.MEASURED_FACT}])
        self.assertTrue(res["hard_fail_triggered"])
        self.assertEqual("do_not_publish", res["decision"])

    def test_measured_categories_still_required(self):
        with self.assertRaises(quality.QualityError):
            quality.score(dict(self.MEASURED, accuracy_sourcing=None))
        with self.assertRaises(quality.QualityError):
            quality.score(dict(self.MEASURED, technical_validation=9))


if __name__ == "__main__":
    unittest.main(verbosity=2)
