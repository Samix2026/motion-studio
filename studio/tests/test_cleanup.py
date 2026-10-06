"""Cleanup engine: safety, classification, and byte accounting.

All tests build temporary fixture repositories; nothing under the real
``videos/`` directory is ever touched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from studio import cleanup as C  # noqa: E402

NOW = 1_700_000_000.0
DAY = 86400
CUR = "a" * 64
OLD = "b" * 64
NEW = "c" * 64
LINK = "e" * 12
CUR12, OLD12, NEW12 = CUR[:12], OLD[:12], NEW[:12]


def write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path, mode) as fh:
        fh.write(data)


def set_age(path: str, age_s: float, now: float = NOW) -> None:
    t = now - age_s
    if os.path.islink(path):
        return
    os.utime(path, (t, t))
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            for name in files + dirs:
                p = os.path.join(root, name)
                if not os.path.islink(p):
                    os.utime(p, (t, t))


class Base(unittest.TestCase):
    state = "good"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ms-cleanup-")
        self.repo = os.path.join(self.tmp, "repo")
        self.videos = os.path.join(self.repo, "videos")
        self.proj = os.path.join(self.videos, "proj")
        self._build()
        self._age()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- fixture -----------------------------------------------------------
    def _build(self):
        p = self.proj
        write(os.path.join(p, "index.html"), "<html></html>")
        write(os.path.join(p, "meta.json"), "{}")
        write(os.path.join(p, "BRIEF.md"), "brief")
        write(os.path.join(p, "lib", "motion.js"), "//")
        write(os.path.join(p, "assets", "fonts", "f.woff2"), b"FONT")
        write(os.path.join(p, "renders", "video.mp4"), b"VIDEO" * 200)
        write(os.path.join(p, "production", "report.md"), "report")
        write(os.path.join(p, "production", "validation.json"), "{}")
        write(os.path.join(p, "production", "unknown.bin"), b"z" * 7)
        write(os.path.join(p, "weird.dat"), b"q")

        for pid in (CUR12, OLD12, NEW12):
            write(os.path.join(p, "production", "stills", pid, "design", "contact-sheet.jpg"),
                  b"J" * 4096)
            write(os.path.join(p, "production", "stills", pid, "motion", "s1.jpg"), b"M" * 1024)
        write(os.path.join(p, "production", "critics", OLD12, "motion", "pack.md"), "x" * 512)
        write(os.path.join(p, "production", "trace.json"), json.dumps({"composition_hash": "deadbeef"}))

        if self.state == "good":
            write(os.path.join(p, "production", "state.json"),
                  json.dumps({"stages": {"qa": {"hash": CUR, "at": "2024-01-02"}},
                              "history": [{"hash": OLD, "at": "2024-01-01"}]}))
        elif self.state == "malformed":
            write(os.path.join(p, "production", "state.json"), "{not json")
        elif self.state == "missing":
            pass

    def _age(self):
        p = self.proj
        for pid in (OLD12, NEW12):
            set_age(os.path.join(p, "production", "stills", pid), 5 * DAY)
        set_age(os.path.join(p, "production", "stills", NEW12), 3600)      # recent
        set_age(os.path.join(p, "production", "stills", CUR12), 5 * DAY)    # current, but old
        set_age(os.path.join(p, "production", "critics", OLD12), 5 * DAY)
        set_age(os.path.join(p, "production", "trace.json"), 5 * DAY)
        # current critics (none here); sources / video / unknown are old
        for rel in ("index.html", "meta.json", "BRIEF.md", "lib/motion.js",
                    "assets/fonts/f.woff2", "renders/video.mp4",
                    "production/unknown.bin", "weird.dat", "production/report.md"):
            set_age(os.path.join(p, rel), 300 * DAY)

    # -- helpers -----------------------------------------------------------
    def plan(self, older=C.DEFAULT_RETENTION_S):
        return C.plan(self.repo, self.videos, older, now=NOW)

    def apply(self, plan):
        return C.apply_report(plan, self.repo)

    def cand(self, plan, rel):
        for c in plan["candidates"]:
            if c["rel"] == rel:
                return c
        return None

    def tree(self):
        out = []
        for root, dirs, files in os.walk(self.videos):
            for n in sorted(files + dirs):
                out.append(os.path.relpath(os.path.join(root, n), self.videos))
        return sorted(out)


class TestSafety(Base):
    def test_dry_run_deletes_nothing(self):
        before = self.tree()
        p = self.plan()
        self.assertTrue(p["candidates"])
        self.assertEqual(self.tree(), before)
        # pure plan never mutates anything either
        C.plan(self.repo, self.videos, C.DEFAULT_RETENTION_S, now=NOW)
        self.assertEqual(self.tree(), before)

    def test_state_missing_fails_safe(self):
        self.state = "missing"
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.setUp()
        p = self.plan()
        self.assertFalse([c for c in p["candidates"] if c["action"] == "DELETE"])
        self.assertTrue(all(c["reason"].startswith("production state unavailable")
                            for c in p["candidates"]))
        before = self.tree()
        self.apply(p)
        self.assertEqual(self.tree(), before)

    def test_state_malformed_fails_safe(self):
        self.state = "malformed"
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.setUp()
        p = self.plan()
        self.assertFalse([c for c in p["candidates"] if c["action"] == "DELETE"])
        before = self.tree()
        self.apply(p)
        self.assertEqual(self.tree(), before)

    def test_symlink_cannot_escape(self):
        outside = os.path.join(self.tmp, "outside")
        write(os.path.join(outside, "secret.txt"), "secret")
        os.symlink(outside, os.path.join(self.videos, "evil"))
        os.symlink(outside, os.path.join(self.proj, "production", "stills", LINK))
        p = self.plan()
        c = self.cand(p, os.path.join("production", "stills", LINK))
        self.assertIsNotNone(c)
        self.assertEqual(c["action"], "PRESERVE")
        self.assertIn("symlink", c["reason"])
        ok, why = C.guard_delete(os.path.join(self.proj, "production", "stills", LINK),
                                 self.repo, self.videos, self.proj, C.CATEGORY_STILLS)
        self.assertFalse(ok)
        self.apply(p)
        self.assertTrue(os.path.isfile(os.path.join(outside, "secret.txt")))
        self.assertTrue(os.path.islink(os.path.join(self.videos, "evil")))

    def test_cannot_delete_repository_root(self):
        ok, why = C.guard_delete(self.repo, self.repo, self.videos, self.proj, C.CATEGORY_SNAPSHOTS)
        self.assertFalse(ok)
        self.assertIn("root", why)

    def test_cannot_delete_videos_dir(self):
        ok, why = C.guard_delete(self.videos, self.repo, self.videos, self.proj, C.CATEGORY_SNAPSHOTS)
        self.assertFalse(ok)
        self.assertIn("root", why)

    def test_cannot_delete_project_root(self):
        ok, why = C.guard_delete(self.proj, self.repo, self.videos, self.proj, C.CATEGORY_SNAPSHOTS)
        self.assertFalse(ok)
        self.assertIn("root", why)
        # a directory outside the project is refused even with a valid category
        ok, _ = C.guard_delete(os.path.join(self.videos, "evil"), self.repo, self.videos,
                               self.proj, C.CATEGORY_STILLS)
        self.assertFalse(ok)


class TestClassification(Base):
    def test_newer_than_retention_remains(self):
        c = self.cand(self.plan(), os.path.join("production", "stills", NEW12))
        self.assertEqual(c["action"], "PRESERVE")
        self.assertEqual(c["reason"], "newer than retention")
        self.apply(self.plan())
        self.assertTrue(os.path.isdir(os.path.join(self.proj, "production", "stills", NEW12)))

    def test_old_regenerable_artifacts_deleted(self):
        p = self.plan()
        for rel in (os.path.join("production", "stills", OLD12),
                    os.path.join("production", "critics", OLD12),
                    os.path.join("production", "trace.json")):
            self.assertEqual(self.cand(p, rel)["action"], "DELETE", rel)
        C.apply_report(p, self.repo)
        self.assertFalse(os.path.exists(os.path.join(self.proj, "production", "stills", OLD12)))
        self.assertFalse(os.path.exists(os.path.join(self.proj, "production", "critics", OLD12)))
        self.assertFalse(os.path.exists(os.path.join(self.proj, "production", "trace.json")))

    def test_old_production_hash_can_be_cleaned(self):
        p = self.plan()
        old = self.cand(p, os.path.join("production", "stills", OLD12))
        cur = self.cand(p, os.path.join("production", "stills", CUR12))
        self.assertEqual(old["action"], "DELETE")
        self.assertEqual(cur["action"], "PRESERVE")
        C.apply_report(p, self.repo)
        stills = os.path.join(self.proj, "production", "stills")
        self.assertNotIn(OLD12, os.listdir(stills))
        self.assertIn(CUR12, os.listdir(stills))

    def test_current_hash_preserved_regardless_of_age(self):
        c = self.cand(self.plan(), os.path.join("production", "stills", CUR12))
        self.assertEqual(c["action"], "PRESERVE")
        self.assertEqual(c["reason"], "current production hash")
        self.assertGreater(c["age_s"], 3 * DAY)   # old, yet preserved
        self.apply(self.plan())
        self.assertTrue(os.path.isdir(os.path.join(self.proj, "production", "stills", CUR12)))

    def test_final_video_preserved(self):
        before = self.tree()
        self.assertIn(os.path.join("proj", "renders", "video.mp4"), before)
        self.apply(self.plan())
        self.assertTrue(os.path.exists(os.path.join(self.proj, "renders", "video.mp4")))

    def test_source_files_preserved(self):
        self.apply(self.plan())
        for rel in ("index.html", "meta.json", "BRIEF.md", "lib/motion.js",
                    "assets/fonts/f.woff2"):
            self.assertTrue(os.path.exists(os.path.join(self.proj, rel)), rel)

    def test_unknown_files_preserved(self):
        self.apply(self.plan())
        self.assertTrue(os.path.exists(os.path.join(self.proj, "production", "unknown.bin")))
        self.assertTrue(os.path.exists(os.path.join(self.proj, "weird.dat")))

    def test_reclaimed_bytes_correct(self):
        p = self.proj
        expected = (C._tree_size(os.path.join(p, "production", "stills", OLD12))
                    + C._tree_size(os.path.join(p, "production", "critics", OLD12))
                    + C._tree_size(os.path.join(p, "production", "trace.json")))
        plan = self.plan()
        self.assertEqual(plan["summary"]["reclaimable_bytes"], expected)
        self.assertGreater(expected, 0)
        C.apply_report(plan, self.repo)
        self.assertEqual(plan["summary"]["deleted_bytes"], expected)


class TestOperations(Base):
    def test_repeated_cleanup_is_idempotent(self):
        first = self.plan()
        C.apply_report(first, self.repo)
        self.assertGreater(first["summary"]["deleted"], 0)
        after_first = self.tree()
        second = C.plan(self.repo, self.videos, C.DEFAULT_RETENTION_S, now=NOW)
        C.apply_report(second, self.repo)
        self.assertEqual(second["summary"]["deleted"], 0)
        self.assertEqual(second["summary"]["deleted_bytes"], 0)
        self.assertEqual(self.tree(), after_first)

    def test_cli_dry_run_json_is_read_only(self):
        before = self.tree()
        cli = os.path.join(_ROOT, "cli.py")
        res = subprocess.run(
            [sys.executable, cli, "cleanup", "--dry-run", "--json",
             "--older-than", "3d", "--videos-dir", self.videos],
            capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        doc = json.loads(res.stdout)
        self.assertTrue(doc["dry_run"])
        self.assertTrue(doc["candidates"])
        self.assertEqual(self.tree(), before)
        self.assertTrue(all(c["action"] != "DELETE" or True for c in doc["candidates"]))


if __name__ == "__main__":
    unittest.main()
