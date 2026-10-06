"""Unit A (A5): narrow, local-only FFmpeg/FFprobe process boundary tests.

Run:  python3 -m unittest discover -s review/tests -v
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_ROOT))

from review import process  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg"))
HAS_FFPROBE = bool(shutil.which("ffprobe"))


class FakeProc:
    def __init__(self, stdout=b"", stderr=b"", rc=0, hang=False):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = rc
        self._hang = hang
        self.killed = False

    def wait(self, timeout=None):
        if self._hang:
            raise subprocess.TimeoutExpired(cmd="media", timeout=timeout)
        return self.returncode

    def kill(self):
        self.killed = True


VALID_PROBE = b'{"streams": [], "format": {}}'


class TestBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="proctest-")
        self.media = os.path.join(self.tmp, "clip.mp4")
        with open(self.media, "wb") as fh:
            fh.write(b"fake-but-allowed-local-media")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _capture(self, stdout=VALID_PROBE, stderr=b"", rc=0, hang=False):
        captured = {}

        def fake_popen(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return FakeProc(stdout=stdout, stderr=stderr, rc=rc, hang=hang)

        return captured, mock.patch.object(process.subprocess, "Popen", side_effect=fake_popen)

    def test_invocation_is_argv_with_shell_false_and_explicit_cwd(self):
        captured, patcher = self._capture()
        with patcher:
            process.probe_media(self.media)
        argv = captured["argv"]
        kwargs = captured["kwargs"]
        self.assertIsInstance(argv, list)
        self.assertTrue(argv[0].endswith("ffprobe"))
        self.assertFalse(kwargs.get("shell", False))
        self.assertEqual(self.tmp, kwargs["cwd"])

    def test_hostile_environment_and_hooks_not_inherited(self):
        hostile = {"ELEVENLABS_API_KEY": "secret", "HTTP_PROXY": "http://p",
                   "HTTPS_PROXY": "http://p", "PYTHONSTARTUP": "/tmp/hook.py",
                   "PYTHONPATH": "/tmp/x", "NPM_CONFIG_REGISTRY": "http://r",
                   "AWS_SECRET_ACCESS_KEY": "secret"}
        captured, patcher = self._capture()
        with mock.patch.dict(os.environ, hostile), patcher:
            process.probe_media(self.media)
        env = captured["kwargs"]["env"]
        for key, value in hostile.items():
            self.assertNotIn(key, env)
            self.assertNotIn(value, env.values())

    def test_remote_url_rejected_before_launch(self):
        for url in ("http://example/x.mp4", "https://example/x.mp4",
                    "ftp://example/x.mp4", "tcp://example/x", "udp://example/x",
                    "rtmp://example/live", "rtsp://example/x", "//host/share.mp4"):
            with self.assertRaises(process.ProcessError):
                process.ensure_local(url)

    def test_pseudo_protocol_and_playlist_inputs_rejected(self):
        concat = os.path.join(self.tmp, "concat.txt")
        with open(concat, "w", encoding="utf-8") as fh:
            fh.write("file 'clip.mp4'")
        with self.assertRaises(process.ProcessError):
            process.ensure_local("concat:" + concat)
        playlist = os.path.join(self.tmp, "list.m3u8")
        with open(playlist, "w", encoding="utf-8") as fh:
            fh.write("#EXTM3U\nhttp://remote/x.ts\n")
        with self.assertRaises(process.ProcessError):
            process.ensure_local(playlist)
        disguised = os.path.join(self.tmp, "disguised.mp4")
        with open(disguised, "w", encoding="utf-8") as fh:
            fh.write("#EXTM3U\nhttp://remote/x.ts\n")
        with self.assertRaises(process.ProcessError):
            process.ensure_local(disguised)
        unsupported = os.path.join(self.tmp, "notes.txt")
        with open(unsupported, "w", encoding="utf-8") as fh:
            fh.write("hello")
        with self.assertRaises(process.ProcessError):
            process.ensure_local(unsupported)

    def test_timeout_must_be_finite_positive(self):
        for bad in (None, 0, -1, float("inf"), float("nan")):
            with self.assertRaises(process.ProcessError):
                process.probe_media(self.media, timeout=bad)

    def test_timeout_expiry_raises(self):
        _captured, patcher = self._capture(hang=True)
        with patcher:
            with self.assertRaises(process.ProcessError):
                process.probe_media(self.media)

    def test_excessive_stdout_and_stderr_rejected(self):
        captured, patcher = self._capture(stdout=b"x" * (process.STDOUT_LIMIT + 16))
        with patcher:
            with self.assertRaises(process.ProcessError):
                process.probe_media(self.media)
        _captured, patcher = self._capture(stdout=b"\0" * 16,
                                           stderr=b"e" * (process.STDERR_LIMIT + 16))
        with patcher:
            with self.assertRaises(process.ProcessError):
                process.decode_gray_frame(self.media, timestamp=0.0, width=4, height=4)

    def test_empty_and_malformed_and_wrong_shape_ffprobe_rejected(self):
        for stdout in (b"", b"   ", b"{not json", b'{"streams": []}', b"[]",
                       b'{"format": {}}'):
            _captured, patcher = self._capture(stdout=stdout)
            with patcher:
                with self.assertRaises(process.ProcessError):
                    process.probe_media(self.media)

    def test_nonzero_probe_exit_rejected(self):
        _captured, patcher = self._capture(rc=1, stderr=b"boom")
        with patcher:
            with self.assertRaises(process.ProcessError):
                process.probe_media(self.media)

    def test_missing_tools_fail_clearly(self):
        with mock.patch.object(process.shutil, "which", return_value=None):
            with self.assertRaises(process.ProcessError):
                process.which_ffmpeg()
            with self.assertRaises(process.ProcessError):
                process.which_ffprobe()
            with self.assertRaises(process.ProcessError):
                process.probe_media(self.media)

    def test_nonzero_version_exit_is_not_available(self):
        _captured, patcher = self._capture(stdout=b"", rc=1)
        with patcher:
            ident = process.tool_identities()
        self.assertFalse(ident["ffmpeg"]["available"])
        self.assertFalse(ident["ffprobe"]["available"])

    def test_version_identity_available_on_success(self):
        _captured, patcher = self._capture(stdout=b"ffprobe version 6.1.1\n")
        with patcher:
            ident = process.tool_identities()
        self.assertTrue(ident["ffprobe"]["available"])
        self.assertIn("ffprobe version", ident["ffprobe"]["identity"])

    def test_empty_version_output_not_available(self):
        _captured, patcher = self._capture(stdout=b"", rc=0)
        with patcher:
            self.assertFalse(process.ffmpeg_identity()["available"])

    def test_bounded_diagnostics(self):
        self.assertLessEqual(len(process.bounded("x" * 100000)), process.DIAGNOSTIC_LIMIT + 32)

    def test_module_has_no_shell_true_or_network(self):
        with open(os.path.join(_ROOT, "process.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("shell=True", src)
        for bad in ("import socket", "import urllib", "import requests", "http.client"):
            self.assertNotIn(bad, src)


@unittest.skipUnless(HAS_FFMPEG and HAS_FFPROBE, "ffmpeg/ffprobe required")
class TestRealLocalMedia(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="procreal-")
        self.media = os.path.join(self.tmp, "clip.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                        "-i", "color=c=black:s=64x36:d=0.5:r=10", "-pix_fmt", "yuv420p",
                        self.media], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_probe_local_media(self):
        data = process.probe_media(self.media)
        self.assertIn("streams", data)
        self.assertTrue(any(s.get("codec_type") == "video" for s in data["streams"]))

    def test_decode_gray_frame(self):
        buf = process.decode_gray_frame(self.media, timestamp=0.0, width=8, height=8)
        self.assertEqual(64, len(buf))

    def test_tool_identities_available(self):
        ident = process.tool_identities()
        self.assertTrue(ident["ffmpeg"]["available"])
        self.assertTrue(ident["ffprobe"]["available"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
