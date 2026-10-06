"""Pre-render validator: pure checks on normalized tracks, structure, determinism."""

from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from studio import prerender as v  # noqa: E402

CTX = {"fps": 30, "frames": 600, "width": 1920, "height": 1080,
       "scenes": [{"id": "intro", "start": 0, "end": 300}, {"id": "reveal", "start": 300, "end": 600}]}


def codes(findings, severity=None):
    return [f["code"] for f in findings if severity is None or f["severity"] == severity]


def run(tracks, annotations=(), alpha=None, ctx=CTX):
    norm, fmt = v.normalize_tracks(tracks, ctx["frames"], "spec")
    anns, _ = v.resolve_annotations(list(annotations), ctx["fps"])
    return fmt + v.validate_tracks(norm, ctx, anns, "spec", alpha)


class TestMotionChecks(unittest.TestCase):
    def test_normal_keyframes_pass(self):
        f = run({"hero.x": [[0, 0], [60, 400], [120, 400]],
                 "hero.scale": [[0, 0.9], [30, 1.0], [599, 1.05]],
                 "hero.opacity": [[0, 0], [15, 1], [599, 1]],
                 "dense.y": [[i, 100 * math.sin(i / 20.0)] for i in range(600)]})
        self.assertEqual([x for x in f if x["severity"] != v.INFO], [])

    def test_one_frame_outlier_fails(self):
        f = run({"camera.x": [[0, 0], [417, 82], [418, 1682], [419, 82], [500, 82]]})
        errs = [x for x in f if x["severity"] == v.ERROR]
        self.assertEqual(len(errs), 1)
        self.assertEqual((errs[0]["code"], errs[0]["frame"], errs[0]["property"], errs[0]["scene"]),
                         ("one_frame_outlier", 418, "camera.x", "reveal"))
        self.assertEqual(errs[0]["observed"], "82 → 1682 → 82")

    def test_unannotated_jump_warns_but_does_not_error(self):
        f = run({"card.x": [[0, 0], [100, 0], [101, 700], [200, 700]]})
        self.assertEqual(codes(f, v.WARNING), ["suspicious_jump"])
        self.assertEqual(codes(f, v.ERROR), [])

    def test_intentional_jump_passes(self):
        f = run({"card.x": [[0, 0], [100, 0], [101, 700], [200, 700]]},
                [{"kind": "intentional_jump", "frame": 101, "property": "card.*"}])
        self.assertEqual(codes(f, v.WARNING) + codes(f, v.ERROR), [])
        self.assertIn("jump_accepted", codes(f, v.INFO))

    def test_hard_cut_annotation_and_scene_boundary_pass(self):
        tracks = {"bg.y": [[0, 0], [150, 0], [151, 600], [299, 600], [300, 0], [599, 0]]}
        f = run(tracks, [{"kind": "hard_cut", "time": 151 / 30.0}])
        self.assertEqual(codes(f, v.WARNING) + codes(f, v.ERROR), [])
        reasons = [x["reason"] for x in f if x["code"] == "jump_accepted"]
        self.assertTrue(any("hard_cut annotation" in r for r in reasons))
        self.assertTrue(any("scene boundary" in r for r in reasons))

    def test_annotation_scope_is_respected(self):
        tracks = {"a.x": [[0, 0], [99, 0], [100, 900], [101, 0]], "b.x": [[0, 0], [99, 0], [100, 900], [101, 0]]}
        f = run(tracks, [{"kind": "allow_outlier", "frame": 100, "property": "a.x"}])
        errs = [x["property"] for x in f if x["severity"] == v.ERROR]
        self.assertEqual(errs, ["b.x"])
        f = run(tracks, [{"kind": "allow_outlier", "frame": 140, "property": "*"}])
        self.assertEqual(len(codes(f, v.ERROR)), 2, "annotation outside its frame window must not suppress")

    def test_hard_cut_does_not_hide_a_spike(self):
        f = run({"a.x": [[0, 0], [99, 0], [100, 900], [101, 0]]}, [{"kind": "hard_cut", "frame": 100}])
        self.assertEqual(codes(f, v.ERROR), ["one_frame_outlier"])

    def test_whip_annotation_prevents_false_positive(self):
        whip = {"camera.x": [[0, 0], [72, 0], [73, 183], [74, 325], [75, 301], [76, 300], [599, 300]]}
        self.assertIn("suspicious_jump", codes(run(whip), v.WARNING))
        f = run(whip, [{"kind": "whip", "frames": [70, 78], "property": "camera.*"}])
        self.assertEqual(codes(f, v.WARNING) + codes(f, v.ERROR), [])

    def test_impact_shake_with_annotation(self):
        shake = {"stage.x": [[0, 0], [200, 0], [201, 60], [202, -60], [203, 40], [204, 0], [599, 0]]}
        self.assertTrue(codes(run(shake), v.ERROR))
        self.assertEqual(codes(run(shake, [{"kind": "impact", "frame": 202}]), v.ERROR), [])

    def test_opacity_spike_detected(self):
        f = run({"flash.opacity": [[0, 1], [59, 1], [60, 0], [61, 1], [599, 1]]})
        self.assertEqual([(x["code"], x["frame"]) for x in f if x["severity"] == v.ERROR],
                         [("one_frame_outlier", 60)])

    def test_scale_and_rotation_spikes(self):
        f = run({"logo.scale": [[0, 1], [99, 1], [100, 2.5], [101, 1]],
                 "logo.rotation": [[0, 0], [99, 0], [100, 90], [101, 0]]})
        self.assertEqual(sorted(x["property"] for x in f if x["severity"] == v.ERROR),
                         ["logo.rotation", "logo.scale"])

    def test_change_while_invisible_is_ignored(self):
        tracks = {"card.x": [[0, 0], [99, 0], [100, 900], [101, 0]]}
        alpha = {"card": (0, [0.0] * 600)}
        self.assertEqual(codes(run(tracks, alpha=alpha), v.ERROR), [])

    def test_periodic_steps_are_a_blink_not_a_jump(self):
        pts = [[0, 1]]
        for k in range(1, 7):
            pts += [[18 * k - 1, pts[-1][1]], [18 * k, 1 - pts[-1][1]]]
        f = run({"caret.opacity": pts})
        self.assertEqual(codes(f, v.WARNING), [])

    def test_nan_and_infinity_fail(self):
        f = run({"a.x": [[0, 0], [10, float("nan")]], "b.y": [[0, float("inf")]]})
        self.assertEqual(codes(f, v.ERROR).count("non_finite_value"), 2)

    def test_malformed_keyframes_fail(self):
        f = run({"dup.x": [[0, 0], [5, 1], [5, 2]], "uns.x": [[10, 0], [5, 1]],
                 "rng.x": [[0, 0], [600, 1]], "neg.x": [[-1, 0]], "bad.x": [[0.5, 1]],
                 "shape.x": [[0, 1, 2]], "empty.x": [], "op.opacity": [[0, 1.4]]})
        c = codes(f, v.ERROR)
        for code in ("duplicate_frame", "unsorted_keyframes", "frame_out_of_range", "malformed_keyframe",
                     "malformed_track", "invalid_value"):
            self.assertIn(code, c)

    def test_bad_annotation_kind_is_an_error(self):
        _, f = v.resolve_annotations([{"kind": "teleport", "frame": 3}, {"kind": "whip"}], 30)
        self.assertEqual(codes(f), ["bad_annotation", "bad_annotation"])

    def test_compress_is_lossless_under_interpolation(self):
        dense = [0, 0, 0, 5, 10, 10, 10, 10, 3, 3]
        kf = v.compress(dense)
        self.assertLess(len(kf), len(dense))
        first, back = v.densify(kf)
        self.assertEqual((first, back), (0, [float(x) for x in dense]))


class TestStructure(unittest.TestCase):
    def test_impossible_ranges_fail(self):
        ctx = dict(CTX, scenes=[{"id": "a", "start": 0, "end": 0}, {"id": "b", "start": 500, "end": 700},
                                {"id": "a", "start": 10, "end": 20}])
        c = codes(v.check_structure(ctx, None), v.ERROR)
        self.assertEqual(c.count("impossible_frame_range"), 2)
        self.assertIn("duplicate_scene", c)

    def test_spec_scene_ranges_and_review_frames(self):
        spec = {"scenes": [{"id": "intro", "frame_start": 0, "frame_end": 300, "review_frames": [310]},
                           {"id": "reveal", "frame_start": 400, "frame_end": 300},
                           {"id": "ghost", "frame_start": 0, "frame_end": 10}]}
        f = v.check_structure(CTX, spec)
        self.assertIn("review_frame_out_of_scene", codes(f, v.ERROR))
        self.assertIn("impossible_frame_range", codes(f, v.ERROR))
        self.assertIn("spec_scene_missing", codes(f, v.WARNING))

    def test_zero_duration_fails(self):
        self.assertIn("invalid_duration", codes(v.check_structure(dict(CTX, frames=0), None), v.ERROR))

    def test_runtime_trace_facts(self):
        trace = {"stage_visible": [0] * 20 + [3] * 580,
                 "reseek_mismatches": [{"frame": 7, "track": "a.x", "forward": 1, "reseek": 2, "alpha": [1, 1]}],
                 "reseek_invisible": 4}
        f = v.check_trace_runtime(trace, CTX, [5])
        self.assertIn("empty_opening", codes(f, v.ERROR))
        self.assertIn("empty_review_frame", codes(f, v.ERROR))
        self.assertIn("seek_order_dependent", codes(f, v.ERROR))
        self.assertIn("seek_order_dependent_invisible", codes(f, v.INFO))


class TestDeterminismScan(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="ms-det-")
        os.makedirs(os.path.join(self.d, "lib"))

    def tearDown(self):
        shutil.rmtree(self.d)

    def write(self, name, text):
        with open(os.path.join(self.d, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_scan(self):
        self.write("index.html", """<html><head>
<style>
  .a { transition: opacity .3s; }
  .b { transition: none; }
  .c { animation: spin 2s linear infinite; }
  .d { animation: fade 1s ease both; }
</style>
<script src="lib/motion.js"></script>
<script src="lib/gsap.min.js"></script>
<script src="https://cdn.example.com/x.js"></script>
</head><body><script>
  var r = Math.random();
  var seeded = mulberry32(42)();
  var j = Math.random(); // ms:allow-nondeterminism seeded fallback reviewed
  // Date.now() in a comment is fine
</script></body></html>""")
        self.write("lib/motion.js", "setTimeout(build, 10);\nvar t = performance.now();\ntl.to(x, {repeat: -1});\n")
        self.write("lib/gsap.min.js", "Date.now();Math.random();")
        f = v.scan_determinism(self.d)
        got = sorted((x["severity"], x["code"].replace("nondeterminism_", "")) for x in f)
        self.assertEqual(got, sorted([
            ("WARNING", "css_transition"), ("ERROR", "css_infinite_animation"), ("ERROR", "math_random"),
            ("INFO", "math_random"), ("WARNING", "timer"), ("ERROR", "clock"), ("ERROR", "infinite_repeat")]))


class TestSummary(unittest.TestCase):
    def test_warnings_do_not_block_by_default(self):
        f = [v.finding(v.WARNING, "x", "y"), v.finding(v.INFO, "z", "w")]
        self.assertEqual(v.summarize(f)["status"], "WARN")
        self.assertEqual(v.summarize(f)["blocking"], 0)
        self.assertEqual(v.summarize(f, warnings_block=True)["status"], "FAIL")
        self.assertEqual(v.summarize([v.finding(v.ERROR, "e", "e")])["status"], "FAIL")

    def test_format_matches_spec_example(self):
        f = v.finding(v.ERROR, "one_frame_outlier", "one-frame outlier with no intentional annotation",
                      source="trace", scene="reveal", frame=418, prop="camera.x", observed="82 → 1682 → 82")
        text = v.format_finding(f)
        for part in ("ERROR", "scene: reveal", "frame: 418", "property: camera.x", "change: 82 → 1682 → 82"):
            self.assertIn(part, text)


if __name__ == "__main__":
    unittest.main()
