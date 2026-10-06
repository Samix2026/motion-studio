"""Tests for tools/mark-published.py.

Run:
  python3 -m unittest discover -s tools/tests -v

All tests use temporary directories; no real project is ever touched.
"""

from __future__ import annotations

import contextlib
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

TOOL_PATH = Path(__file__).resolve().parent.parent / "mark-published.py"
_spec = importlib.util.spec_from_file_location("mark_published", TOOL_PATH)
mark = importlib.util.module_from_spec(_spec)
sys.modules["mark_published"] = mark  # dataclasses/typing need the module registered
_spec.loader.exec_module(mark)  # type: ignore[union-attr]

TZ = datetime.timezone(datetime.timedelta(hours=3))
NOW = datetime.datetime(2026, 9, 15, 19, 30, tzinfo=TZ)


class MarkBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.videos = self.root / "videos"
        self.videos.mkdir()
        self.addCleanup(self._tmp.cleanup)

    def make_project(self, name: str, *, meta=None, write_meta=True,
                     master_rel="renders/video-final.mp4",
                     master_bytes=b"final-master", write_master=True) -> Path:
        pdir = self.videos / name
        (pdir / "renders").mkdir(parents=True, exist_ok=True)
        if write_meta:
            payload = meta if meta is not None else {"id": name, "name": name,
                                                     "status": "approved"}
            (pdir / "meta.json").write_text(json.dumps(payload), encoding="utf-8")
        if write_master and master_rel:
            mpath = pdir / master_rel
            mpath.parent.mkdir(parents=True, exist_ok=True)
            mpath.write_bytes(master_bytes)
        return pdir

    def mark(self, project_dir, *, confirm=True, published_at=None, out=None):
        captured = out if out is not None else io.StringIO()
        code = mark.mark_project(
            project_dir=project_dir,
            videos_dir=self.videos,
            workspace_root=self.root,
            home=self.root,
            published_at=published_at,
            confirm=lambda _prompt: confirm,
            now=NOW,
            out=captured,
        )
        return code, captured.getvalue()

    def read_meta(self, pdir: Path) -> dict:
        return json.loads((pdir / "meta.json").read_text(encoding="utf-8"))


class MarkTests(MarkBase):
    def test_01_valid_project_marks_published(self):
        pdir = self.make_project("good")
        code, text = self.mark(pdir)
        self.assertEqual(code, 0)
        meta = self.read_meta(pdir)
        self.assertEqual(meta["status"], "published")
        self.assertEqual(meta["final_master"], "renders/video-final.mp4")
        self.assertEqual(meta["published_at"], "2026-09-15T19:30:00+03:00")
        self.assertIn("Cleanup eligible after:", text)
        self.assertIn("2026-09-22T19:30:00+03:00", text)

    def test_02_missing_project_rejected(self):
        code, text = self.mark(self.videos / "ghost")
        self.assertEqual(code, 1)
        self.assertIn("project not found", text)

    def test_03_missing_meta_rejected(self):
        pdir = self.make_project("nometa", write_meta=False)
        code, text = self.mark(pdir)
        self.assertEqual(code, 1)
        self.assertIn("meta.json not found", text)
        self.assertFalse((pdir / "meta.json").exists())

    def test_04_missing_master_rejected(self):
        pdir = self.make_project("nomaster", write_master=False)
        before = (pdir / "meta.json").read_text(encoding="utf-8")
        code, text = self.mark(pdir)
        self.assertEqual(code, 1)
        self.assertIn("final master not found", text)
        self.assertEqual((pdir / "meta.json").read_text(encoding="utf-8"), before)

    def test_05_zero_byte_master_rejected(self):
        pdir = self.make_project("empty", master_bytes=b"")
        code, text = self.mark(pdir)
        self.assertEqual(code, 1)
        self.assertIn("zero bytes", text)
        self.assertNotEqual(self.read_meta(pdir).get("status"), "published")

    def test_06_existing_metadata_preserved(self):
        meta = {
            "id": "keep",
            "name": "keep",
            "brand": "anthropic",
            "cost_gate_id": "keep-abc-123",
            "review_revision": 1,
            "status": "approved",
        }
        pdir = self.make_project("keep", meta=meta)
        code, _ = self.mark(pdir)
        self.assertEqual(code, 0)
        after = self.read_meta(pdir)
        self.assertEqual(after["brand"], "anthropic")
        self.assertEqual(after["cost_gate_id"], "keep-abc-123")
        self.assertEqual(after["review_revision"], 1)
        self.assertEqual(after["id"], "keep")
        self.assertEqual(after["status"], "published")

    def test_07_default_confirmation_is_no(self):
        pdir = self.make_project("noabort")
        before = (pdir / "meta.json").read_text(encoding="utf-8")
        code, text = self.mark(pdir, confirm=False)
        self.assertEqual(code, 0)
        self.assertIn("Aborted", text)
        self.assertEqual((pdir / "meta.json").read_text(encoding="utf-8"), before)

    def test_07b_default_confirm_reads_input(self):
        with mock.patch("builtins.input", return_value=""):
            self.assertFalse(mark.default_confirm("? "))
        with mock.patch("builtins.input", return_value="y"):
            self.assertTrue(mark.default_confirm("? "))
        with mock.patch("builtins.input", return_value="n"):
            self.assertFalse(mark.default_confirm("? "))

    def test_08_already_published_keeps_timestamp(self):
        meta = {"status": "published",
                "published_at": "2026-09-01T10:00:00+03:00",
                "final_master": "renders/video-final.mp4"}
        pdir = self.make_project("already", meta=meta)
        before = (pdir / "meta.json").read_text(encoding="utf-8")
        code, text = self.mark(pdir, confirm=True)
        self.assertEqual(code, 0)
        self.assertIn("ALREADY PUBLISHED", text)
        self.assertEqual((pdir / "meta.json").read_text(encoding="utf-8"), before)
        self.assertEqual(self.read_meta(pdir)["published_at"],
                         "2026-09-01T10:00:00+03:00")

    def test_09_manual_published_at_accepted(self):
        pdir = self.make_project("manual")
        given = mark.parse_timestamp("2026-09-10T18:30:00+03:00")
        code, _ = self.mark(pdir, published_at=given)
        self.assertEqual(code, 0)
        self.assertEqual(self.read_meta(pdir)["published_at"],
                         "2026-09-10T18:30:00+03:00")

    def test_10_invalid_timestamp_rejected(self):
        self.assertIsNone(mark.parse_timestamp("not-a-date"))
        self.assertIsNone(mark.parse_timestamp(""))
        code = mark.main(["anyproject", "--published-at", "2026-13-99",
                          "--videos-dir", str(self.videos)])
        self.assertEqual(code, 2)


class SafetyTests(MarkBase):
    def test_11_unsafe_paths_rejected(self):
        for candidate in (Path("/"), Path.home(), self.root, self.videos):
            safe, why = mark.is_safe_project_path(
                candidate, self.videos, self.root, Path.home())
            self.assertFalse(safe, "expected unsafe: %s" % candidate)
            self.assertTrue(why)
        safe, _ = mark.is_safe_project_path(
            self.videos / ".." / ".." / "etc", self.videos, self.root,
            Path.home())
        self.assertFalse(safe)

    def test_11b_symlink_escape_rejected(self):
        outside = self.root / "outside"
        (outside / "renders").mkdir(parents=True)
        (outside / "meta.json").write_text(json.dumps({"status": "approved"}),
                                           encoding="utf-8")
        (outside / "renders" / "video-final.mp4").write_bytes(b"x")
        os.symlink(outside, self.videos / "escape")
        code, text = self.mark(self.videos / "escape")
        self.assertEqual(code, 1)
        self.assertIn("symlink", text)

    def test_11c_invalid_project_name_rejected(self):
        self.assertIsNotNone(mark._validate_project_name(".."))
        self.assertIsNotNone(mark._validate_project_name("a/b"))
        self.assertIsNotNone(mark._validate_project_name("/etc"))
        self.assertIsNone(mark._validate_project_name("salesforce-in-claude-beta"))


class ListTests(MarkBase):
    def test_12_list_does_not_mutate(self):
        a = self.make_project("alpha", meta={"status": "published",
                                             "published_at": "2026-09-15T19:30:00+03:00"})
        b = self.make_project("beta", meta={"status": "approved"})
        before_a = (a / "meta.json").read_text(encoding="utf-8")
        before_b = (b / "meta.json").read_text(encoding="utf-8")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = mark.main(["--list", "--videos-dir", str(self.videos)])
        text = stdout.getvalue()
        self.assertIn("alpha", text)  # main reached the list mode
        self.assertEqual(code, 0)
        self.assertIn("PROJECT", text)
        self.assertIn("alpha", text)
        self.assertIn("published", text)
        self.assertIn("2026-09-15 19:30", text)
        self.assertIn("7 days", text)
        self.assertIn("beta", text)
        self.assertEqual((a / "meta.json").read_text(encoding="utf-8"), before_a)
        self.assertEqual((b / "meta.json").read_text(encoding="utf-8"), before_b)

    def test_list_rejects_combination(self):
        code = mark.main(["--list", "someproject",
                          "--videos-dir", str(self.videos)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
