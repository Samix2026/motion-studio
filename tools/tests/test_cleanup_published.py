"""Tests for tools/cleanup-published.py.

Run:
  python3 -m unittest discover -s tools/tests -v

All tests use temporary directories; no real project is ever touched.
"""

from __future__ import annotations

import datetime
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOL_PATH = Path(__file__).resolve().parent.parent / "cleanup-published.py"
_spec = importlib.util.spec_from_file_location("cleanup_published", TOOL_PATH)
cleanup = importlib.util.module_from_spec(_spec)
sys.modules["cleanup_published"] = cleanup  # dataclasses needs the module registered
_spec.loader.exec_module(cleanup)  # type: ignore[union-attr]

NOW = datetime.datetime(2026, 9, 15, 12, 0, tzinfo=datetime.timezone.utc)


class CleanupBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.videos = self.root / "videos"
        self.videos.mkdir()
        self.published = self.root / "Published"
        self.log = self.root / "logs" / "published-cleanup.jsonl"
        self.addCleanup(self._tmp.cleanup)

    def published_at(self, days_ago: int) -> str:
        return (NOW - datetime.timedelta(days=days_ago)).isoformat()

    def make_project(self, name: str, *, status="published",
                     days_ago=8, master_rel="renders/video-final.mp4",
                     master_bytes=b"final-master-bytes", write_master=True,
                     meta_extra=None) -> Path:
        pdir = self.videos / name
        (pdir / "renders").mkdir(parents=True, exist_ok=True)
        meta = {"id": name, "name": name}
        if status is not None:
            meta["status"] = status
        if days_ago is not None:
            meta["published_at"] = self.published_at(days_ago)
        if master_rel is not None:
            meta["final_master"] = master_rel
        if meta_extra:
            meta.update(meta_extra)
        (pdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        if write_master and master_rel:
            mpath = pdir / master_rel
            mpath.parent.mkdir(parents=True, exist_ok=True)
            mpath.write_bytes(master_bytes)
        return pdir

    def run_tool(self, *, days=7, project=None, execute=False):
        out = io.StringIO()
        code = cleanup.run(
            videos_dir=self.videos,
            published_dir=self.published,
            log_path=self.log,
            days=days,
            now=NOW,
            project=project,
            execute=execute,
            home=self.root,
            workspace_root=self.root,
            out=out,
        )
        return code, out.getvalue()


class EligibilityTests(CleanupBase):
    def test_01_unpublished_is_skipped(self):
        self.make_project("draft", status="draft", days_ago=99)
        eligible, skipped = cleanup.scan(self.videos, self.root, self.root, 7, NOW)
        self.assertEqual(eligible, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("not published", skipped[0].reason)

    def test_02_published_too_recent_is_skipped(self):
        self.make_project("fresh", days_ago=3)
        eligible, skipped = cleanup.scan(self.videos, self.root, self.root, 7, NOW)
        self.assertEqual(eligible, [])
        self.assertIn("< 7", skipped[0].reason)

    def test_03_published_old_enough_is_eligible(self):
        self.make_project("ready", days_ago=8)
        eligible, skipped = cleanup.scan(self.videos, self.root, self.root, 7, NOW)
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0].name, "ready")
        self.assertEqual(eligible[0].age_days, 8)
        self.assertTrue(eligible[0].master_size > 0)

    def test_04_missing_final_master_is_skipped(self):
        self.make_project("nomaster", days_ago=99, write_master=False)
        eligible, skipped = cleanup.scan(self.videos, self.root, self.root, 7, NOW)
        self.assertEqual(eligible, [])
        self.assertIn("not found", skipped[0].reason)

    def test_05_zero_byte_master_is_skipped(self):
        self.make_project("empty", days_ago=99, master_bytes=b"")
        eligible, skipped = cleanup.scan(self.videos, self.root, self.root, 7, NOW)
        self.assertEqual(eligible, [])
        self.assertIn("zero bytes", skipped[0].reason)

    def test_missing_meta_is_skipped(self):
        (self.videos / "nometa").mkdir()
        eligible, skipped = cleanup.scan(self.videos, self.root, self.root, 7, NOW)
        self.assertEqual(eligible, [])
        self.assertIn("no meta.json", skipped[0].reason)

    def test_missing_published_at_is_skipped(self):
        self.make_project("nodate", days_ago=None)
        eligible, skipped = cleanup.scan(self.videos, self.root, self.root, 7, NOW)
        self.assertEqual(eligible, [])
        self.assertIn("published_at", skipped[0].reason)


class DryRunTests(CleanupBase):
    def test_06_dry_run_never_mutates(self):
        pdir = self.make_project("ready", days_ago=8)
        code, text = self.run_tool(execute=False)
        self.assertEqual(code, 0)
        self.assertTrue(pdir.exists())
        self.assertFalse((self.published / "ready.mp4").exists())
        self.assertFalse(self.log.exists())
        self.assertIn("No files changed.", text)
        self.assertIn("READY", text)


class ExecuteTests(CleanupBase):
    def test_07_verified_copy_then_delete(self):
        pdir = self.make_project("ready", days_ago=8, master_bytes=b"payload-123")
        code, text = self.run_tool(execute=True)
        self.assertEqual(code, 0)
        dest = self.published / "ready.mp4"
        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_bytes(), b"payload-123")
        self.assertFalse(pdir.exists())
        self.assertTrue(self.log.exists())
        records = [json.loads(line) for line in
                   self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["project"], "ready")
        self.assertEqual(records[0]["sha256"],
                         cleanup.sha256_file(dest))
        self.assertIn("CLEANED", text)

    def test_08_hash_mismatch_prevents_deletion(self):
        pdir = self.make_project("ready", days_ago=8)
        calls = {"n": 0}

        def fake_sha(path, chunk=1024 * 1024):
            calls["n"] += 1
            return "aaaa" if calls["n"] == 1 else "bbbb"

        with mock.patch.object(cleanup, "sha256_file", side_effect=fake_sha):
            code, text = self.run_tool(execute=True)
        self.assertEqual(code, 1)
        self.assertTrue(pdir.exists())
        self.assertIn("hash mismatch", text)
        self.assertFalse(self.log.exists())

    def test_09_destination_conflict_different_hash(self):
        pdir = self.make_project("ready", days_ago=8, master_bytes=b"new-content")
        self.published.mkdir(parents=True, exist_ok=True)
        dest = self.published / "ready.mp4"
        dest.write_bytes(b"different-content")
        code, text = self.run_tool(execute=True)
        self.assertEqual(code, 1)
        self.assertTrue(pdir.exists())
        self.assertEqual(dest.read_bytes(), b"different-content")
        self.assertIn("conflict", text)
        self.assertFalse(self.log.exists())

    def test_10_identical_destination_is_reused(self):
        pdir = self.make_project("ready", days_ago=8, master_bytes=b"same-bytes")
        self.published.mkdir(parents=True, exist_ok=True)
        dest = self.published / "ready.mp4"
        dest.write_bytes(b"same-bytes")
        code, text = self.run_tool(execute=True)
        self.assertEqual(code, 0)
        self.assertFalse(pdir.exists())
        self.assertEqual(dest.read_bytes(), b"same-bytes")
        record = json.loads(self.log.read_text(encoding="utf-8").splitlines()[0])
        self.assertTrue(record["reused_existing_destination"])
        self.assertIn("reused", text.lower())


class SafetyTests(CleanupBase):
    def test_11_unsafe_paths_rejected(self):
        home = Path.home()
        cases = [Path("/"), home, self.root, self.videos]
        for candidate in cases:
            safe, why = cleanup.is_safe_deletion_target(
                candidate, self.videos, self.root, home)
            self.assertFalse(safe, "expected unsafe: %s" % candidate)
            self.assertTrue(why)

    def test_11b_traversal_rejected(self):
        safe, why = cleanup.is_safe_deletion_target(
            self.videos / ".." / ".." / "etc", self.videos, self.root, Path.home())
        self.assertFalse(safe)

    def test_12_symlink_escape_is_skipped(self):
        outside = self.root / "outside-project"
        (outside / "renders").mkdir(parents=True)
        (outside / "meta.json").write_text(json.dumps({
            "status": "published",
            "published_at": self.published_at(99),
            "final_master": "renders/video-final.mp4",
        }), encoding="utf-8")
        (outside / "renders" / "video-final.mp4").write_bytes(b"x")
        link = self.videos / "escape"
        os.symlink(outside, link)
        eligible, skipped = cleanup.scan(self.videos, self.root, self.root, 7, NOW)
        self.assertEqual(eligible, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("symlink points outside", skipped[0].reason)

    def test_master_escaping_project_is_skipped(self):
        outside_master = self.root / "secret.mp4"
        outside_master.write_bytes(b"secret")
        pdir = self.videos / "escaper"
        pdir.mkdir()
        (pdir / "meta.json").write_text(json.dumps({
            "status": "published",
            "published_at": self.published_at(99),
            "final_master": "../../secret.mp4",
        }), encoding="utf-8")
        eligible, skipped = cleanup.scan(self.videos, self.root, self.root, 7, NOW)
        self.assertEqual(eligible, [])
        self.assertIn("escapes", skipped[0].reason)


class ScopeAndDaysTests(CleanupBase):
    def test_13_project_limits_scope(self):
        a = self.make_project("alpha", days_ago=8)
        b = self.make_project("beta", days_ago=8)
        code, text = self.run_tool(project="alpha", execute=True)
        self.assertEqual(code, 0)
        self.assertFalse(a.exists())
        self.assertTrue(b.exists(), "beta must be untouched")
        self.assertFalse((self.published / "beta.mp4").exists())
        self.assertNotIn("beta", text)

    def test_14_days_window(self):
        self.make_project("eight", days_ago=8)
        eligible, skipped = cleanup.scan(self.videos, self.root, self.root, 10, NOW)
        self.assertEqual(eligible, [])
        self.assertIn("< 10", skipped[0].reason)
        eligible, _ = cleanup.scan(self.videos, self.root, self.root, 7, NOW)
        self.assertEqual(len(eligible), 1)

    def test_15_days_zero_rejected(self):
        self.assertEqual(cleanup.main(["--days", "0"]), 2)
        self.assertEqual(cleanup.main(["--days", "-3"]), 2)

    def test_invalid_project_name_rejected(self):
        self.assertIsNotNone(cleanup._validate_project_name(".."))
        self.assertIsNotNone(cleanup._validate_project_name("a/b"))
        self.assertIsNotNone(cleanup._validate_project_name("/etc"))
        self.assertIsNone(cleanup._validate_project_name("salesforce-in-claude-beta"))


if __name__ == "__main__":
    unittest.main()
