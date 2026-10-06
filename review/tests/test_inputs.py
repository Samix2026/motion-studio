"""Unit A (A1/A2/A3): explicit inputs, fingerprints, and freshness.

Run:  python3 -m unittest discover -s review/tests -v
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from review import analyzer, cli as review_cli, inputs as review_inputs, revision, reviewer  # noqa: E402
from timing import schema as timing_schema  # noqa: E402

_FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "mini_project")


class InputsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="inputs-")
        self.project = os.path.join(self.tmp, "proj")
        shutil.copytree(_FIXTURE, self.project)
        os.makedirs(os.path.join(self.project, "renders"))
        self.write("renders/video.mp4", b"AAAA")
        self._orig_state = revision._STATE_DIR
        revision._STATE_DIR = os.path.join(self.tmp, "state")

    def tearDown(self):
        revision._STATE_DIR = self._orig_state
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, payload):
        path = os.path.join(self.project, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(payload)
        return path

    def write_json(self, rel, doc):
        path = os.path.join(self.project, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path

    def write_timings(self, rel="word-timings.json", triples=((0, 500),)):
        words = [{"word": "x", "start_ms": s, "end_ms": e, "confidence": None}
                 for s, e in triples]
        return self.write_json(rel, timing_schema.make("elevenlabs", 2000, words))

    def write_captions(self, rel="captions.json", end_ms=500):
        return self.write_json(rel, {"schema_version": 1, "captions": [
            {"start_ms": 0, "end_ms": end_ms, "text": "x"}]})

    def inject(self, snippet):
        index = os.path.join(self.project, "index.html")
        with open(index, "r", encoding="utf-8") as fh:
            html = fh.read()
        with open(index, "w", encoding="utf-8") as fh:
            fh.write(html.replace("</head>", snippet + "</head>"))

    def link_css(self, rel, payload):
        self.write(rel, payload)
        self.inject('<link rel="stylesheet" href="%s">' % rel)
        return os.path.join(self.project, rel)

    def add_local_script(self, rel, payload):
        self.write(rel, payload)
        self.inject('<script src="%s"></script>' % rel)
        return os.path.join(self.project, rel)

    def explicit(self, **over):
        kwargs = dict(render="renders/video.mp4", composition="index.html",
                      css=review_inputs.discover_css(self.project),
                      dependencies=review_inputs.discover_dependencies(self.project))
        kwargs.update(over)
        return review_inputs.ReviewInputs.from_explicit(self.project, **kwargs)

    def analyze(self, inputs=None, **kw):
        return analyzer.analyze(self.project, inputs=inputs, **kw)

    def proposal(self, inputs):
        report = self.analyze(inputs)
        proposals, _notes = reviewer.review(self.project, report, inputs=inputs)
        return report, proposals[0]


class TestExplicitContract(InputsBase):
    def test_undeclared_css_fails_before_findings_change(self):
        self.link_css("styles/local.css", b".sub{font-size:24px;}")
        inputs = self.explicit(css=[], dependencies=[])
        with self.assertRaises(review_inputs.ReviewInputError):
            self.analyze(inputs)

    def test_extra_declared_css_fails(self):
        self.write("styles/extra.css", b".x{color:red;}")
        inputs = self.explicit(css=["styles/extra.css"], dependencies=["styles/extra.css"])
        with self.assertRaises(review_inputs.ReviewInputError):
            self.analyze(inputs)

    def test_declared_css_is_exactly_what_is_consumed(self):
        self.link_css("styles/local.css", b".sub{font-size:24px;}")
        report = self.analyze(self.explicit())
        self.assertEqual(["styles/local.css"],
                         [c["path"] for c in report["review_inputs"]["css"]])

    def test_selected_snapshots_control_measurement(self):
        s1 = self.write("snapshots/at-1s.png", b"PNG1")
        self.write("snapshots/at-2s.png", b"PNG2")
        not_selected = self.analyze(self.explicit(snapshots=None))
        self.assertEqual([], not_selected["measurements"]["snapshots"])
        selected = self.analyze(self.explicit(snapshots=[s1]))
        self.assertEqual(["at-1s.png"],
                         [s["file"] for s in selected["measurements"]["snapshots"]])

    def test_project_dir_mismatch_fails(self):
        other = os.path.join(self.tmp, "other")
        shutil.copytree(_FIXTURE, other)
        os.makedirs(os.path.join(other, "renders"))
        self.write("renders/video.mp4", b"AAAA")
        with open(os.path.join(other, "renders", "video.mp4"), "wb") as fh:
            fh.write(b"AAAA")
        inputs = review_inputs.ReviewInputs.from_explicit(
            other, render="renders/video.mp4", composition="index.html")
        with self.assertRaises(review_inputs.ReviewInputError):
            self.analyze(inputs)

    def test_explicit_timing_captions_override_legacy_discovery(self):
        # Legacy files are aligned and would produce no finding.
        self.write_timings("word-timings.json", ((0, 500),))
        self.write_captions("captions.json", end_ms=500)
        # Explicit selection points elsewhere and is misaligned.
        self.write_timings("alt-timings.json", ((600, 1200),))
        self.write_captions("alt-captions.json", end_ms=800)
        inputs = self.explicit(timings="alt-timings.json", captions="alt-captions.json")
        report = self.analyze(inputs)
        self.assertIn("caption_audio_sync",
                      {f["category"] for f in report["findings"]})
        self.assertTrue(report["measurements"]["word_timings"]["path"].endswith("alt-timings.json"))
        legacy = self.analyze()
        self.assertNotIn("caption_audio_sync",
                         {f["category"] for f in legacy["findings"]})

    def test_required_undeclared_literal_dependency_fails(self):
        self.add_local_script("local.js", b"console.log(1)")
        with self.assertRaises(review_inputs.ReviewInputError):
            self.analyze(self.explicit(dependencies=[]))

    def test_declared_local_dependency_is_allowed(self):
        self.add_local_script("local.js", b"console.log(1)")
        report = self.analyze(self.explicit())
        self.assertIn(report["review_inputs"]["dependency_provenance"]["coverage"],
                      ("partial_local_only",))

    def test_runtime_dependency_coverage_is_honest(self):
        report = self.analyze(self.explicit())
        prov = report["review_inputs"]["dependency_provenance"]
        self.assertEqual("partial_local_only", prov["coverage"])
        self.assertEqual("unsupported", prov["runtime_dynamic"])
        self.assertTrue(any("shop" in r or "cdn" in r or "gsap" in r
                            for r in prov["remote_references"]))

    def test_remote_explicit_dependency_rejected(self):
        for dep in ("https://cdn.example/x.js", "//cdn.example/x.js"):
            with self.assertRaises(review_inputs.ReviewInputError):
                self.explicit(dependencies=[dep])


class TestFingerprintA2(InputsBase):
    def test_effective_rules_change_fingerprint(self):
        base = analyzer.load_rules()
        r1 = json.loads(json.dumps(base))
        r2 = json.loads(json.dumps(base))
        r2["timing"]["max_static_hold_seconds"] = float(base["timing"]["max_static_hold_seconds"]) + 1.0
        inputs = self.explicit()
        f1 = self.analyze(inputs, rules=r1)["review_fingerprint"]
        f2 = self.analyze(inputs, rules=r2)["review_fingerprint"]
        f_default = self.analyze(inputs)["review_fingerprint"]
        self.assertNotEqual(f1, f2)
        self.assertNotEqual(f_default, f1)

    def test_equivalent_rule_key_ordering_does_not_change_fingerprint(self):
        base = analyzer.load_rules()
        reordered = {k: base[k] for k in reversed(list(base.keys()))}
        inputs = self.explicit()
        self.assertEqual(self.analyze(inputs, rules=base)["review_fingerprint"],
                         self.analyze(inputs, rules=reordered)["review_fingerprint"])

    def test_invalid_timing_bytes_still_content_addressed(self):
        self.write("bad-timings.json", b"{not valid timing}")
        inputs = self.explicit(timings="bad-timings.json")
        first = self.analyze(inputs)
        self.assertFalse(first["review_inputs"]["timings"]["valid"])
        self.assertIsNotNone(first["review_inputs"]["timings"]["sha256"])
        self.write("bad-timings.json", b"{not VALID timinG}")  # same size
        second = self.analyze(inputs)
        self.assertNotEqual(first["review_fingerprint"], second["review_fingerprint"])

    def test_same_invalid_timing_bytes_same_fingerprint(self):
        self.write("bad-timings.json", b"{not valid timing}")
        inputs = self.explicit(timings="bad-timings.json")
        first = self.analyze(inputs)["review_fingerprint"]
        second = self.analyze(inputs)["review_fingerprint"]
        self.assertEqual(first, second)

    def test_timing_validator_identity_participates(self):
        descriptor = self.analyze(self.explicit())["review_inputs"]
        self.assertIn("timing/schema.py", descriptor["implementation"])

    def test_unordered_dependency_inventory_is_stable(self):
        a = self.add_local_script("a.js", b"console.log('a')")
        b = self.add_local_script("b.js", b"console.log('b')")
        first = self.analyze(self.explicit(dependencies=[a, b]))["review_fingerprint"]
        second = self.analyze(self.explicit(dependencies=[b, a]))["review_fingerprint"]
        self.assertEqual(first, second)

    def test_inactive_configuration_does_not_change_fingerprint(self):
        inputs = self.explicit()
        inactive = self.analyze(inputs)["review_fingerprint"]
        inactive_explicit = self.analyze(
            self.explicit(narration_enabled=False, review_config={}))["review_fingerprint"]
        self.assertEqual(inactive, inactive_explicit)
        active = self.analyze(self.explicit(narration_enabled=True))["review_fingerprint"]
        self.assertNotEqual(inactive, active)

    def test_same_size_render_replacement_changes_fingerprint(self):
        inputs = self.explicit()
        first = self.analyze(inputs)["review_fingerprint"]
        self.write("renders/video.mp4", b"BBBB")
        self.assertNotEqual(first, self.analyze(inputs)["review_fingerprint"])

    def test_same_size_css_replacement_changes_fingerprint(self):
        self.link_css("styles/local.css", b".sub{font-size:24px;}")
        inputs = self.explicit()
        first = self.analyze(inputs)["review_fingerprint"]
        self.write("styles/local.css", b".sub{font-size:25px;}")  # same size
        self.assertNotEqual(first, self.analyze(inputs)["review_fingerprint"])

    def test_unrelated_file_change_does_not_change_fingerprint(self):
        inputs = self.explicit()
        first = self.analyze(inputs)["review_fingerprint"]
        self.write("sources.md", b"unrelated changed content not selected by review")
        self.assertEqual(first, self.analyze(inputs)["review_fingerprint"])

    def test_timing_and_caption_changes_update_fingerprint(self):
        self.write_timings()
        self.write_captions()
        inputs = self.explicit(timings="word-timings.json", captions="captions.json")
        first = self.analyze(inputs)["review_fingerprint"]
        self.write_captions(end_ms=700)
        second = self.analyze(inputs)["review_fingerprint"]
        self.assertNotEqual(first, second)
        self.write_timings(triples=((0, 300),))
        self.assertNotEqual(second, self.analyze(inputs)["review_fingerprint"])

    def test_rules_and_typography_are_in_fingerprint(self):
        descriptor = self.analyze(self.explicit())["review_inputs"]
        self.assertTrue(descriptor["rules"]["sha256"])
        self.assertTrue(descriptor["typography"]["sha256"])
        base = json.loads(json.dumps(descriptor))
        tweaked = json.loads(json.dumps(descriptor))
        tweaked["typography"]["sha256"] = "0" * 64
        self.assertNotEqual(review_inputs.ReviewInputs.fingerprint(base),
                            review_inputs.ReviewInputs.fingerprint(tweaked))

    def test_descriptor_uses_hashes_not_size(self):
        descriptor = self.analyze(self.explicit())["review_inputs"]
        self.assertEqual({"present", "path", "sha256"}, set(descriptor["render"]))
        self.assertEqual({"path", "sha256"}, set(descriptor["composition"]))

    def test_explicit_findings_match_legacy_for_identical_inputs(self):
        legacy = self.analyze()
        explicit = self.analyze(self.explicit(render="renders/video.mp4"))
        self.assertEqual(legacy["findings"], explicit["findings"])
        self.assertEqual({u["check"] for u in legacy["unavailable"]},
                         {u["check"] for u in explicit["unavailable"]})

    def test_implementation_identity_is_recorded(self):
        descriptor = self.analyze(self.explicit())["review_inputs"]
        for rel in ("review/analyzer.py", "review/process.py", "timing/schema.py"):
            self.assertIn(rel, descriptor["implementation"])
        self.assertIn("ffmpeg", descriptor["tools"])


class TestA3Freshness(InputsBase):
    def test_unchanged_explicit_evidence_is_current(self):
        _report, proposal = self.proposal(self.explicit())
        self.assertEqual("current", review_inputs.freshness_for_saved(self.project, proposal)["status"])
        self.assertFalse(revision.is_stale(proposal, self.project))

    def test_changed_render_invalidates(self):
        _report, proposal = self.proposal(self.explicit())
        self.write("renders/video.mp4", b"BBBB")  # same size
        self.assertEqual("stale", review_inputs.freshness_for_saved(self.project, proposal)["status"])
        self.assertTrue(revision.is_stale(proposal, self.project))

    def test_changed_timing_invalidates(self):
        self.write_timings()
        self.write_captions()
        inputs = self.explicit(timings="word-timings.json", captions="captions.json")
        _report, proposal = self.proposal(inputs)
        self.write_timings(triples=((0, 400),))
        self.assertTrue(revision.is_stale(proposal, self.project))

    def test_changed_caption_invalidates(self):
        self.write_timings()
        self.write_captions(end_ms=500)
        inputs = self.explicit(timings="word-timings.json", captions="captions.json")
        _report, proposal = self.proposal(inputs)
        self.write_captions(end_ms=900)
        self.assertTrue(revision.is_stale(proposal, self.project))

    def test_changed_css_invalidates(self):
        self.link_css("styles/local.css", b".sub{font-size:24px;}")
        _report, proposal = self.proposal(self.explicit())
        self.write("styles/local.css", b".sub{font-size:26px;}")  # same size
        self.assertTrue(revision.is_stale(proposal, self.project))

    def test_same_size_dependency_replacement_invalidates(self):
        self.add_local_script("local.js", b"console.log(1111)")
        _report, proposal = self.proposal(self.explicit())
        self.write("local.js", b"console.log(2222)")  # same size
        self.assertTrue(revision.is_stale(proposal, self.project))

    def test_extra_unselected_mp4_does_not_invalidate(self):
        _report, proposal = self.proposal(self.explicit())
        self.write("renders/other.mp4", b"EXTRA")
        self.assertEqual("current", review_inputs.freshness_for_saved(self.project, proposal)["status"])
        self.assertFalse(revision.is_stale(proposal, self.project))

    def test_saved_selection_is_reconstructed_exactly(self):
        inputs = self.explicit()
        report, _proposal = self.proposal(inputs)
        rebuilt = review_inputs.ReviewInputs.from_descriptor(self.project, report["review_inputs"])
        self.assertEqual(os.path.abspath(inputs.render_path), os.path.abspath(rebuilt.render_path))
        self.assertEqual(sorted(inputs.css_paths), sorted(rebuilt.css_paths))
        self.assertEqual(sorted(inputs.dependencies), sorted(rebuilt.dependencies))

    def test_historical_evidence_without_descriptor_is_unverified(self):
        status = review_inputs.freshness_for_saved(self.project, {"project_hash": "x"})
        self.assertEqual("unverified", status["status"])
        good = {"project_hash": revision.content_hash(self.project)}
        self.assertFalse(revision.is_stale(good, self.project))
        bad = {"project_hash": "0" * 64}
        self.assertTrue(revision.is_stale(bad, self.project))

    def test_report_labels_saved_evidence_state(self):
        report = self.analyze(self.explicit())
        proposals = [{"finding_id": "finding-001", "title": "t", "operation": {"type": "x"},
                      "duration_before": 1.0, "duration_after": 1.0, "warnings": [],
                      "confidence": 0.5, "status": "awaiting_review"}]
        stale = review_cli.render_report_md(report, proposals, evidence_status="stale")
        self.assertIn("Proposal evidence: STALE", stale)
        self.assertIn("WARNING", stale)
        current = review_cli.render_report_md(report, proposals, evidence_status="current")
        self.assertIn("Proposal evidence: CURRENT", current)
        self.assertNotIn("WARNING", current)


if __name__ == "__main__":
    unittest.main(verbosity=2)
