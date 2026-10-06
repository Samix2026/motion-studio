"""Tests for tools/check-run-record.py."""
import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_run_record", Path(__file__).resolve().parent.parent / "check-run-record.py")
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)  # type: ignore[union-attr]

GOOD = {"started_at": "2026-10-05T10:00:00+03:00", "ended_at": "2026-10-05T10:20:00+03:00",
        "total_production_seconds": 1200, "quality_score": 93, "render_retries": 0,
        "manual_interventions": 1}


class CheckRunRecordTests(unittest.TestCase):
    def test_complete_record_passes(self):
        self.assertEqual(check.problems(GOOD), [])

    def test_null_metrics_fail(self):
        for key in GOOD:
            self.assertTrue(check.problems(dict(GOOD, **{key: None})), key)

    def test_total_must_match_timestamps(self):
        self.assertTrue(check.problems(dict(GOOD, total_production_seconds=600)))

    def test_prose_intervention_count_fails(self):
        self.assertTrue(check.problems(dict(GOOD, manual_interventions="three mix retries")))

    def test_timestamp_needs_offset(self):
        self.assertTrue(check.problems(dict(GOOD, started_at="2026-10-05T10:00:00",
                                            ended_at="2026-10-05T10:20:00")))


if __name__ == "__main__":
    unittest.main()
