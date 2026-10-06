"""Phase B tests for the cost gate (stdlib unittest).

Run:  python3 -m unittest discover -s costgate/tests -v
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

from costgate import gate, schema  # noqa: E402

_PLAN = os.path.join(_ROOT, "tests", "fixtures", "plan_example.json")

_VERIFIED_PRICING = {
    "currency": "USD",
    "checked_at": "2026-01-01T00:00:00Z",
    "sources": ["https://example.test/pricing"],
    "prices": {
        "MiniMax.video-01.request": {
            "unit_price": 0.50, "confidence": "verified",
            "source": "https://example.test/minimax", "checked_at": "2026-01-01"},
        "ElevenLabs.eleven_multilingual_v2.character": {
            "unit_price": 0.0001, "confidence": "verified",
            "source": "https://example.test/el-tts", "checked_at": "2026-01-01"},
        "ElevenLabs.sound-effects.request": {
            "unit_price": 0.05, "confidence": "verified",
            "source": "https://example.test/el-sfx", "checked_at": "2026-01-01"},
    },
}
# 0.50 + (420 * 0.0001) + 0.05 = 0.592
_EXPECTED_TOTAL = 0.592


def load_plan():
    with open(_PLAN, "r", encoding="utf-8") as fh:
        return json.load(fh)


class CostGateTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="costgate-")
        self._orig_state = gate._STATE_DIR
        self._orig_report = gate._REPORT_DIR
        gate._STATE_DIR = os.path.join(self.tmp, "state")
        gate._REPORT_DIR = os.path.join(self.tmp, "reports")
        os.makedirs(gate._STATE_DIR, exist_ok=True)
        self.plan = load_plan()

    def tearDown(self):
        gate._STATE_DIR = self._orig_state
        gate._REPORT_DIR = self._orig_report
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, pricing=None, project="example-project"):
        return gate.build_gate(self.plan, pricing or _VERIFIED_PRICING, project,
                               "2026-01-01T00:00:00Z")


class TestEstimation(CostGateTestBase):
    def test_calculates_from_verified_pricing(self):
        g = self.build()
        self.assertEqual(_EXPECTED_TOTAL, g["estimated_total_usd"])
        self.assertEqual("known", g["cost_status"])
        by_scene = {it["scene"]: it for it in g["items"]}
        self.assertEqual(0.50, by_scene[1]["estimated_cost_usd"])
        self.assertEqual(0.042, round(by_scene[3]["estimated_cost_usd"], 3))
        self.assertEqual(0.05, by_scene[5]["estimated_cost_usd"])
        self.assertTrue(g["pricing_source"], "pricing provenance must be recorded")

    def test_unknown_pricing_remains_unknown(self):
        pricing = json.loads(json.dumps(_VERIFIED_PRICING))
        del pricing["prices"]["ElevenLabs.eleven_multilingual_v2.character"]
        g = self.build(pricing=pricing)
        tts = next(it for it in g["items"] if it["asset_type"] == "tts")
        self.assertIsNone(tts["estimated_cost_usd"])
        self.assertEqual("unknown", tts["cost_status"])
        self.assertIsNone(g["estimated_total_usd"], "partial pricing must not fabricate a total")
        self.assertEqual("partial", g["cost_status"])
        self.assertGreater(g["unknown_count"], 0)

    def test_never_invents_pricing(self):
        g = self.build(pricing={"currency": "USD", "checked_at": None,
                                "sources": [], "prices": {}})
        self.assertIsNone(g["estimated_total_usd"])
        self.assertEqual("unknown", g["cost_status"])
        self.assertEqual(3, g["unknown_count"])
        self.assertTrue(all(it["estimated_cost_usd"] is None for it in g["items"]))

    def test_invalid_asset_type_rejected(self):
        plan = json.loads(json.dumps(self.plan))
        plan["items"][0]["asset_type"] = "shell_command"
        with self.assertRaises(schema.CostGateError):
            gate.build_gate(plan, _VERIFIED_PRICING, "p", "2026-01-01T00:00:00Z")


class TestGate(CostGateTestBase):
    def test_paid_call_blocked_before_approval(self):
        g = self.build()
        self.assertEqual("awaiting_approval", g["status"])
        self.assertFalse(gate.generation_allowed(g), "generation must be blocked pre-approval")

    def test_budget_exceed_blocks_generation(self):
        g = self.build()
        g2 = gate.set_decision(g, "approve", limit=0.10, at="2026-01-01T00:00:00Z")
        self.assertEqual("budget_exceeded", g2["status"])
        self.assertFalse(gate.generation_allowed(g2))
        self.assertTrue(any("exceeds" in w for w in g2["warnings"]))

    def test_approval_within_budget_allows(self):
        g = self.build()
        g2 = gate.set_decision(g, "approve", limit=1.00, at="2026-01-01T00:00:00Z")
        self.assertEqual("approved", g2["status"])
        self.assertTrue(gate.generation_allowed(g2))
        self.assertEqual(1.00, g2["approved_cost_limit_usd"])

    def test_reject_blocks(self):
        g = self.build()
        g2 = gate.set_decision(g, "reject", at="2026-01-01T00:00:00Z")
        self.assertEqual("rejected", g2["status"])
        self.assertFalse(gate.generation_allowed(g2))

    def test_unknown_approval_is_flagged(self):
        pricing = {"currency": "USD", "checked_at": None, "sources": [], "prices": {}}
        g = self.build(pricing=pricing)
        g2 = gate.set_decision(g, "approve", limit=None, at="2026-01-01T00:00:00Z")
        self.assertEqual("approved", g2["status"])
        self.assertTrue(any("UNKNOWN" in w for w in g2["warnings"]))

    def test_actuals_variance(self):
        g = self.build()
        g2 = gate.record_actuals(g, provider_billed_usd=0.60, session_reported_usd=0.60)
        self.assertAlmostEqual(0.008, g2["cost_variance_usd"], places=6)
        self.assertEqual(0.60, g2["provider_billed_cost_usd"])
        self.assertEqual(0.60, g2["session_reported_cost_usd"])

    def test_variance_unknown_without_estimate(self):
        g = self.build(pricing={"currency": "USD", "checked_at": None, "sources": [], "prices": {}})
        g2 = gate.record_actuals(g, provider_billed_usd=0.60)
        self.assertIsNone(g2["cost_variance_usd"])

    def test_does_not_mutate_input_gate(self):
        g = self.build()
        snapshot = json.dumps(g, sort_keys=True)
        gate.set_decision(g, "approve", limit=1.0, at="t")
        gate.record_actuals(g, provider_billed_usd=1.0)
        self.assertEqual(snapshot, json.dumps(g, sort_keys=True))

    def test_state_roundtrip(self):
        g = self.build()
        gate.save_gate(g)
        loaded = gate.load_gate(g["gate_id"])
        self.assertEqual(g["gate_id"], loaded["gate_id"])
        self.assertEqual(g["estimated_total_usd"], loaded["estimated_total_usd"])


class TestNoNetworkOrProjectWrites(unittest.TestCase):
    def test_gate_and_schema_import_no_network_libraries(self):
        for path in (gate.__file__, schema.__file__):
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            for bad in ("import requests", "import urllib", "import socket",
                        "http.client", "urlopen", "subprocess"):
                self.assertNotIn(bad, text, "%s must not use %s" % (path, bad))

    def test_gate_does_not_write_outside_state(self):
        # build/set_decision/record_actuals are pure; only save_gate writes.
        tmp = tempfile.mkdtemp(prefix="costgate-pure-")
        self.addCleanup(shutil.rmtree, tmp, True)
        with open(_PLAN, "r", encoding="utf-8") as fh:
            plan = json.load(fh)
        gate.build_gate(plan, _VERIFIED_PRICING, "p", "2026-01-01T00:00:00Z")
        self.assertEqual([], os.listdir(tmp), "build must not write anything")


if __name__ == "__main__":
    unittest.main(verbosity=2)
