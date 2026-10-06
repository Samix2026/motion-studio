"""Narrow local FFmpeg/FFprobe process boundary for deterministic review.

There is no generic command runner. Only a small set of known local operations
is exposed (probe, detect silence, measure loudness, detect freezes, decode
one gray frame, read tool identity), and each builds its own fixed argv list. ``shell`` is always
False. Inputs must be existing local media/image files with a permitted
container/extension; URLs, network paths, playlists, and pseudo-protocol
inputs are refused before any subprocess launch. Children run with a minimal
explicit environment. Every invocation has a finite positive timeout and
bounded stdout/stderr collection. Failures raise :class:`ProcessError` and are
never reported as empty-success measurements.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import threading
from typing import Dict, List, Optional, Sequence, Tuple

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
DEFAULT_TIMEOUT = 60
DIAGNOSTIC_LIMIT = 8192
STDOUT_LIMIT = 1 << 20
STDERR_LIMIT = 64 << 10

_REMOTE_SCHEMES = (
    "http", "https", "ftp", "ftps", "sftp", "tcp", "udp", "rtmp", "rtmps",
    "rtsp", "rtsps", "srt", "rist", "gopher", "data", "file", "smb", "telnet",
    "tls", "unix", "pipe", "concat", "crypto", "subfile", "cache", "async",
    "libsmbclient",
)
_SCHEME_RE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.\-]*://|//)")
_ALLOWED_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".ts", ".m2ts",
                 ".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg", ".oga", ".opus",
                 ".png", ".jpg", ".jpeg", ".webp")
_PLAYLIST_EXTS = (".m3u", ".m3u8", ".pls", ".xspf", ".asx", ".wvx", ".mpd",
                  ".ism", ".txt")
_PLAYLIST_MARKERS = (b"#EXTM3U", b"[playlist]", b"#EXT-X-")

_ALLOWED_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES")


class ProcessError(Exception):
    """A local media tool is missing, refused, or failed."""


def bounded(text: Optional[str]) -> str:
    if not text:
        return ""
    if len(text) <= DIAGNOSTIC_LIMIT:
        return text
    return text[:DIAGNOSTIC_LIMIT] + "\n...[truncated]"


def _validate_timeout(timeout: object) -> float:
    if timeout is None or isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ProcessError("a finite positive timeout is required")
    if not math.isfinite(float(timeout)) or float(timeout) <= 0:
        raise ProcessError("a finite positive timeout is required")
    return float(timeout)


def _child_env(cwd: str) -> Dict[str, str]:
    """Minimal environment: no provider keys, proxies, hooks, or user vars."""
    env = {name: os.environ[name] for name in _ALLOWED_ENV if name in os.environ}
    env["TMPDIR"] = cwd
    return env


def ensure_local(path: object, label: str = "media input") -> str:
    """Return the absolute path of an existing, permitted local media/image file."""
    if not isinstance(path, str) or not path:
        raise ProcessError("%s must be a local file path" % label)
    if _SCHEME_RE.match(path):
        raise ProcessError("%s must be local, not a URL or network source" % label)
    lowered = path.lower()
    for scheme in _REMOTE_SCHEMES:
        if lowered.startswith(scheme + ":"):
            raise ProcessError("%s must be local, not a %s: source" % (label, scheme))
    if path.startswith("-"):
        raise ProcessError("%s must be a file path, not an option" % label)
    abspath = os.path.abspath(path)
    if not os.path.isfile(abspath):
        raise ProcessError("%s is not an existing local file: %s" % (label, path))
    if lowered.endswith(_PLAYLIST_EXTS):
        raise ProcessError("%s must be media, not a playlist/indirect source" % label)
    if not lowered.endswith(_ALLOWED_EXTS):
        raise ProcessError("%s has an unsupported local container/format" % label)
    with open(abspath, "rb") as fh:
        head = fh.read(512)
    for marker in _PLAYLIST_MARKERS:
        if marker in head:
            raise ProcessError("%s must be media, not a playlist/indirect source" % label)
    return abspath


def which_ffmpeg() -> str:
    exe = shutil.which(FFMPEG)
    if not exe:
        raise ProcessError("ffmpeg is not installed or not on PATH")
    return exe


def which_ffprobe() -> str:
    exe = shutil.which(FFPROBE)
    if not exe:
        raise ProcessError("ffprobe is not installed or not on PATH")
    return exe


def _run_bounded(argv: Sequence[str], *, timeout: object, cwd: Optional[str],
                 max_stdout: int, max_stderr: int) -> Tuple[int, bytes, bytes]:
    """Run a fixed argv list with bounded output and a minimal environment."""
    seconds = _validate_timeout(timeout)
    if not isinstance(argv, (list, tuple)) or not argv or any(not isinstance(a, str) for a in argv):
        raise ProcessError("media arguments must be an explicit non-empty list of strings")
    if cwd is None or not os.path.isdir(cwd):
        raise ProcessError("an existing explicit working directory is required")
    env = _child_env(cwd)
    try:
        proc = subprocess.Popen(list(argv), shell=False, cwd=cwd, env=env,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        raise ProcessError("failed to launch %s" % os.path.basename(argv[0]))

    out_box: List[bytes] = []
    err_box: List[bytes] = []
    exceeded: List[str] = []

    def reader(stream, limit: int, box: List[bytes], name: str) -> None:
        try:
            data = stream.read(limit + 1)
        except Exception:
            data = b""
        if len(data) > limit:
            exceeded.append(name)
            data = data[:limit]
        box.append(data)
        try:
            stream.close()
        except Exception:
            pass

    threads = [
        threading.Thread(target=reader, args=(proc.stdout, max_stdout, out_box, "stdout"), daemon=True),
        threading.Thread(target=reader, args=(proc.stderr, max_stderr, err_box, "stderr"), daemon=True),
    ]
    for t in threads:
        t.start()
    try:
        proc.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        for t in threads:
            t.join(1)
        raise ProcessError("media tool timed out after %ss" % seconds)
    for t in threads:
        t.join(5)
    if exceeded:
        raise ProcessError("media tool output exceeded the bounded limit (%s)"
                           % ",".join(sorted(exceeded)))
    stdout = out_box[0] if out_box else b""
    stderr = err_box[0] if err_box else b""
    return proc.returncode, stdout, stderr


def probe_media(path: str, timeout: object = DEFAULT_TIMEOUT) -> Dict:
    """Probe a local media file and return the parsed JSON payload.

    Empty output, malformed JSON, a wrong top-level shape, or a non-zero exit
    all raise ProcessError; none is returned as an empty-success measurement.
    """
    abspath = ensure_local(path)
    rc, stdout, stderr = _run_bounded(
        [which_ffprobe(), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", abspath],
        timeout=timeout, cwd=os.path.dirname(abspath),
        max_stdout=STDOUT_LIMIT, max_stderr=STDERR_LIMIT)
    if rc != 0:
        raise ProcessError("ffprobe failed (exit %s): %s"
                           % (rc, bounded(stderr.decode("utf-8", "replace").strip())))
    if not stdout.strip():
        raise ProcessError("ffprobe returned empty output")
    try:
        data = json.loads(stdout.decode("utf-8", "replace"))
    except ValueError:
        raise ProcessError("ffprobe returned unparseable JSON")
    if not isinstance(data, dict) or not isinstance(data.get("streams"), list) \
            or not isinstance(data.get("format"), dict):
        raise ProcessError("ffprobe returned an unexpected payload")
    return data


def _decode(blob: bytes) -> str:
    return blob.decode("utf-8", "replace")


def silence_regions(path: str, min_seconds: float, timeout: object = 120) -> List[Dict]:
    abspath = ensure_local(path)
    rc, _out, err = _run_bounded(
        [which_ffmpeg(), "-hide_banner", "-i", abspath, "-af",
         "silencedetect=noise=-45dB:d=%.2f" % min_seconds, "-f", "null", "-"],
        timeout=timeout, cwd=os.path.dirname(abspath),
        max_stdout=STDERR_LIMIT, max_stderr=STDERR_LIMIT)
    if rc != 0:
        raise ProcessError("silencedetect failed (exit %s)" % rc)
    text = _decode(err)
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[0-9.]+)", text)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?[0-9.]+)", text)]
    regions = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        regions.append({"start": s, "end": e, "duration": (e - s) if e is not None else None})
    return regions


def loudness(path: str, timeout: object = 300) -> Dict:
    """EBU R128 integrated loudness (LUFS) and true peak (dBTP) of audio stream 0."""
    abspath = ensure_local(path)
    rc, _out, err = _run_bounded(
        [which_ffmpeg(), "-hide_banner", "-nostats", "-i", abspath, "-map", "0:a:0",
         "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"],
        timeout=timeout, cwd=os.path.dirname(abspath),
        max_stdout=STDERR_LIMIT, max_stderr=STDERR_LIMIT)
    if rc != 0:
        raise ProcessError("ebur128 failed (exit %s)" % rc)
    text = _decode(err)
    summary = text[text.rfind("Summary:"):] if "Summary:" in text else ""
    i = re.search(r"I:\s*(-?[0-9.]+|-inf)\s*LUFS", summary)
    p = re.search(r"True peak:\s*Peak:\s*(-?[0-9.]+|-inf)\s*dBFS", summary)
    if not i or not p:
        raise ProcessError("ebur128 summary not found")
    num = lambda s: None if s == "-inf" else float(s)  # noqa: E731
    return {"integrated_lufs": num(i.group(1)), "true_peak_dbtp": num(p.group(1))}


def freezedetect(path: str, *, noise_db: float = -60.0, min_seconds: float = 2.5,
                 crop: Optional[Sequence[float]] = None,
                 total_duration: Optional[float] = None,
                 timeout: object = 300) -> List[Dict]:
    abspath = ensure_local(path)
    vf = _crop_filter(crop) + "freezedetect=n=%sdB:d=%.3f" % (noise_db, min_seconds)
    rc, _out, err = _run_bounded(
        [which_ffmpeg(), "-hide_banner", "-i", abspath, "-map", "0:v:0",
         "-vf", vf, "-f", "null", "-"],
        timeout=timeout, cwd=os.path.dirname(abspath),
        max_stdout=STDERR_LIMIT, max_stderr=STDERR_LIMIT)
    if rc != 0:
        raise ProcessError("freezedetect failed (exit %s)" % rc)
    text = _decode(err)
    starts = [float(x) for x in re.findall(r"freeze_start:\s*([0-9.]+)", text)]
    durs = [float(x) for x in re.findall(r"freeze_duration:\s*([0-9.]+)", text)]
    regions = []
    for i, s in enumerate(starts):
        if i < len(durs):
            d = durs[i]
        elif total_duration is not None:
            d = max(total_duration - s, 0.0)
        else:
            continue
        regions.append({"start": round(s, 3), "duration": round(d, 3), "end": round(s + d, 3)})
    return regions


def _crop_filter(crop: Optional[Sequence[float]]) -> str:
    if not crop:
        return ""
    top, bottom = float(crop[0]), float(crop[1])
    return "crop=iw:ih*%.4f:0:ih*%.4f," % (1.0 - top - bottom, top)


def motion_series(path: str, *, fps: float, width: int, height: int,
                  crop: Optional[Sequence[float]] = None, timeout: object = 300) -> List[float]:
    """Mean absolute luma difference (0-255) between consecutive sampled frames.

    Entry j compares samples j and j+1 (ffmpeg tblend + signalstats YAVG)."""
    abspath = ensure_local(path)
    vf = (_crop_filter(crop) + "fps=%s,scale=%d:%d:flags=area,format=gray,"
          "tblend=all_mode=difference,signalstats,"
          "metadata=print:key=lavfi.signalstats.YAVG:file=-" % (fps, width, height))
    rc, out, _err = _run_bounded(
        [which_ffmpeg(), "-v", "error", "-i", abspath, "-map", "0:v:0", "-an",
         "-vf", vf, "-f", "null", "-"],
        timeout=timeout, cwd=os.path.dirname(abspath),
        max_stdout=STDOUT_LIMIT * 4, max_stderr=STDERR_LIMIT)
    if rc != 0:
        raise ProcessError("motion measurement failed (exit %s)" % rc)
    return [float(x) for x in re.findall(r"YAVG=([0-9.]+)", _decode(out))]


def decode_gray_sequence(path: str, *, fps: float, width: int, height: int,
                         max_frames: int, timeout: object = 300) -> List[bytes]:
    """Area-downscaled gray frames sampled at fps, width*height bytes each."""
    abspath = ensure_local(path)
    size = width * height
    if size <= 0 or max_frames <= 0:
        raise ProcessError("frame dimensions and count must be positive")
    rc, out, _err = _run_bounded(
        [which_ffmpeg(), "-v", "error", "-i", abspath, "-map", "0:v:0", "-an",
         "-vf", "fps=%s,scale=%d:%d:flags=area,format=gray" % (fps, width, height),
         "-frames:v", str(max_frames), "-f", "rawvideo", "-"],
        timeout=timeout, cwd=os.path.dirname(abspath),
        max_stdout=size * max_frames, max_stderr=STDERR_LIMIT)
    if rc != 0:
        raise ProcessError("frame sequence decode failed (exit %s)" % rc)
    return [out[i:i + size] for i in range(0, len(out) - size + 1, size)]


def decode_gray_frame(path: str, *, timestamp: float, width: int, height: int,
                      crop: Optional[str] = None, is_image: bool = False,
                      timeout: object = 60) -> bytes:
    """Decode exactly one area-downscaled gray frame of width*height bytes."""
    abspath = ensure_local(path)
    if width <= 0 or height <= 0:
        raise ProcessError("frame dimensions must be positive")
    expected = width * height
    vf = ("%s," % crop if crop else "") + "scale=%d:%d:flags=area,format=gray" % (width, height)
    argv = [which_ffmpeg(), "-v", "error"]
    if not is_image:
        argv += ["-ss", "%.3f" % max(timestamp, 0.0)]
    argv += ["-i", abspath, "-frames:v", "1", "-vf", vf, "-f", "rawvideo", "-"]
    rc, stdout, stderr = _run_bounded(argv, timeout=timeout, cwd=os.path.dirname(abspath),
                                      max_stdout=expected, max_stderr=STDERR_LIMIT)
    if rc != 0:
        raise ProcessError("frame decode failed (exit %s)" % rc)
    if len(stdout) != expected:
        raise ProcessError("frame decode returned an unexpected size")
    return stdout


def _tool_identity(name: str, timeout: object = 15) -> Dict:
    exe = shutil.which(name)
    if not exe:
        return {"available": False, "identity": None}
    try:
        rc, stdout, stderr = _run_bounded([exe, "-version"], timeout=timeout,
                                          cwd=os.path.dirname(exe),
                                          max_stdout=STDERR_LIMIT, max_stderr=STDERR_LIMIT)
    except ProcessError:
        return {"available": False, "identity": None}
    if rc != 0:
        return {"available": False, "identity": None}
    text = (_decode(stdout) or _decode(stderr)).strip()
    line = text.splitlines()[0].strip() if text else ""
    if not line:
        return {"available": False, "identity": None}
    return {"available": True, "identity": bounded(line)}


def ffmpeg_identity() -> Dict:
    return _tool_identity(FFMPEG)


def ffprobe_identity() -> Dict:
    return _tool_identity(FFPROBE)


def tool_identities() -> Dict:
    return {"ffmpeg": ffmpeg_identity(), "ffprobe": ffprobe_identity()}
