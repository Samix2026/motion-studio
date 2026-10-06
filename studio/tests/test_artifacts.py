"""Phase 1 artifact tests: streaming hashing, path safety, and integrity."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from studio import artifacts as a  # noqa: E402
from studio import contracts as c  # noqa: E402

TS = "2026-01-01T00:00:00+00:00"
REV = "videos/proj"


class ArtifactBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="studio-art-")
        self.ws = os.path.realpath(os.path.join(self.tmp, "ws"))
        self.project = os.path.join(self.ws, "videos", "proj")
        self.outside = os.path.join(self.tmp, "outside")
        os.makedirs(os.path.join(self.project, "renders"))
        os.makedirs(self.outside)
        self.write("renders/video.mp4", b"AAAA")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, payload):
        path = os.path.join(self.project, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(payload)
        return path


class TestHashing(ArtifactBase):
    def test_streaming_sha256_matches_reference(self):
        payload = os.urandom(3 * a.HASH_CHUNK + 7)
        path = self.write("renders/big.bin", payload)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), a.sha256_file(path))

    def test_build_artifact_records_hash_and_size(self):
        art = a.build_artifact("r1", "render", "project", "renders/video.mp4",
                               self.ws, REV, "att-1", False, TS)
        self.assertEqual("renders/video.mp4", art["path"])
        self.assertEqual(4, art["size_bytes"])
        self.assertEqual(hashlib.sha256(b"AAAA").hexdigest(), art["sha256"])


class TestPathSafety(ArtifactBase):
    def test_relative_and_absolute_project_dirs_normalize_equally(self):
        rel = a.normalize_project_dir(self.ws, REV)
        absolute = a.normalize_project_dir(self.ws, self.project)
        self.assertEqual(rel, absolute)
        self.assertEqual(REV, rel)

    def test_traversal_and_absolute_are_rejected(self):
        with self.assertRaises(c.PathSafetyError):
            a.normalize_project_dir(self.ws, "../outside")
        with self.assertRaises(c.PathSafetyError):
            a.resolve_artifact_path("project", "../../etc/passwd", self.ws, REV)
        with self.assertRaises(c.PathSafetyError):
            a.resolve_artifact_path("project", "/etc/passwd", self.ws, REV)

    def test_symlink_escape_is_rejected(self):
        with open(os.path.join(self.outside, "secret.txt"), "w", encoding="utf-8") as fh:
            fh.write("no")
        link = os.path.join(self.project, "renders", "escape")
        os.symlink(self.outside, link)
        with self.assertRaises(c.PathSafetyError):
            a.resolve_artifact_path("project", "renders/escape/secret.txt", self.ws, REV)

    def test_symlink_alias_to_env_is_rejected(self):
        env = os.path.join(self.project, ".env")
        with open(env, "w", encoding="utf-8") as fh:
            fh.write("SECRET=1")
        alias = os.path.join(self.project, "innocent.txt")
        os.symlink(env, alias)
        with self.assertRaises(c.PathSafetyError):
            a.resolve_artifact_path("project", "innocent.txt", self.ws, REV)
        with self.assertRaises(c.PathSafetyError):
            a.build_artifact("x", "other", "project", "innocent.txt", self.ws, REV,
                             None, True, TS)

    def test_symlink_alias_to_git_is_rejected(self):
        gitdir = os.path.join(self.project, ".git")
        os.makedirs(gitdir)
        with open(os.path.join(gitdir, "config"), "w", encoding="utf-8") as fh:
            fh.write("[core]")
        alias = os.path.join(self.project, "gitdir")
        os.symlink(gitdir, alias)
        with self.assertRaises(c.PathSafetyError):
            a.resolve_artifact_path("project", "gitdir/config", self.ws, REV)

    def test_refused_names_rejected(self):
        self.write(".env", b"SECRET=1")
        self.write("credentials", b"{}")
        self.write(".git", b"gitdir: x")
        for rel in (".env", "credentials", ".git"):
            with self.assertRaises(c.PathSafetyError):
                a.resolve_artifact_path("project", rel, self.ws, REV)

    def test_rejection_performs_no_outside_read(self):
        env = os.path.join(self.project, ".env")
        with open(env, "w", encoding="utf-8") as fh:
            fh.write("SECRET=1")
        os.symlink(env, os.path.join(self.project, "alias"))
        with mock.patch.object(a, "sha256_file",
                               side_effect=AssertionError("must not read refused file")):
            with self.assertRaises(c.PathSafetyError):
                a.build_artifact("x", "other", "project", "alias", self.ws, REV, None, True, TS)

    def test_missing_file_cannot_be_registered(self):
        with self.assertRaises(c.PathSafetyError):
            a.build_artifact("r1", "render", "project", "renders/absent.mp4",
                             self.ws, REV, "att-1", False, TS)


class TestIntegrity(ArtifactBase):
    def build(self):
        return a.build_artifact("r1", "render", "project", "renders/video.mp4",
                                self.ws, REV, "att-1", False, TS)

    def test_ok_state(self):
        report = a.check_artifact(self.build(), self.ws, REV)
        self.assertEqual("ok", report["state"])

    def test_missing_file_detected_without_regeneration(self):
        art = self.build()
        os.unlink(os.path.join(self.project, "renders", "video.mp4"))
        report = a.check_artifact(art, self.ws, REV)
        self.assertEqual("missing", report["state"])
        self.assertFalse(os.path.exists(os.path.join(self.project, "renders", "video.mp4")))

    def test_same_size_different_content_changes_hash(self):
        art = self.build()
        self.write("renders/video.mp4", b"BBBB")
        report = a.check_artifact(art, self.ws, REV)
        self.assertEqual("changed", report["state"])
        self.assertNotEqual(art["sha256"], report["actual_sha256"])

    def test_workspace_rooted_artifact(self):
        os.makedirs(os.path.join(self.ws, "runs"))
        with open(os.path.join(self.ws, "runs", "legacy.json"), "w", encoding="utf-8") as fh:
            fh.write("{}")
        art = a.build_artifact("legacy", "legacy_run_summary", "workspace", "runs/legacy.json",
                               self.ws, REV, None, True, TS)
        self.assertTrue(art["legacy_external"])
        self.assertEqual("runs/legacy.json", art["path"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
