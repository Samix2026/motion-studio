"""Local video measurement via ffprobe/ffmpeg (no network, no CV deps).

The heavy lifting is in pure parse functions so results are deterministic and
testable without running ffmpeg.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


def is_video(path: str) -> bool:
    return os.path.isfile(path) and os.path.splitext(path)[1].lower() in VIDEO_EXT


def parse_ffprobe(data: Dict) -> Dict:
    """Pure: ffprobe JSON -> measured facts."""
    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {}) or {}
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    out: Dict = {}
    if fmt.get("duration") is not None:
        try:
            out["duration_seconds"] = round(float(fmt["duration"]), 3)
        except (TypeError, ValueError):
            pass
    for key, src in (("width", "width"), ("height", "height")):
        v = video.get(src)
        if isinstance(v, (int, float)) and v > 0:
            out[key] = int(v)
    rate = video.get("r_frame_rate")
    if isinstance(rate, str) and "/" in rate:
        num, den = rate.split("/")[:2]
        try:
            if float(den) > 0:
                out["fps"] = round(float(num) / float(den), 3)
        except (ValueError, ZeroDivisionError):
            pass
    out["audio_present"] = audio is not None
    if audio is not None and audio.get("duration") is not None:
        try:
            out["audio_duration_seconds"] = round(float(audio["duration"]), 3)
        except (TypeError, ValueError):
            pass
    return out


def probe(path: str, timeout: int = 60) -> Tuple[Optional[Dict], Optional[str]]:
    exe = shutil.which("ffprobe")
    if not exe:
        return None, "ffprobe not available"
    try:
        res = subprocess.run(
            [exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=timeout)
        if res.returncode != 0:
            return None, "ffprobe failed"
        return parse_ffprobe(json.loads(res.stdout)), None
    except Exception as exc:  # pragma: no cover - environment dependent
        return None, "ffprobe error: %s" % exc


_CUT_RE = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


def parse_scene_cuts(text: str) -> List[float]:
    """Pure: ffmpeg showinfo output -> sorted cut timestamps (seconds)."""
    return sorted({round(float(m), 3) for m in _CUT_RE.findall(text or "")})


def scene_cuts(path: str, threshold: float = 0.3, timeout: int = 180
               ) -> Tuple[Optional[List[float]], Optional[str]]:
    exe = shutil.which("ffmpeg")
    if not exe:
        return None, "ffmpeg not available"
    try:
        res = subprocess.run(
            [exe, "-hide_banner", "-i", path, "-vf",
             "select='gt(scene,%s)',showinfo" % threshold, "-an", "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout)
        return parse_scene_cuts(res.stderr), None
    except Exception as exc:  # pragma: no cover - environment dependent
        return None, "scene detection error: %s" % exc


_LOUD_RE = re.compile(r"I:\s*(-?[0-9.]+)\s*LUFS")


def parse_integrated_loudness(text: str) -> Optional[float]:
    m = _LOUD_RE.findall(text or "")
    return round(float(m[-1]), 2) if m else None


def integrated_loudness(path: str, timeout: int = 180) -> Optional[float]:
    exe = shutil.which("ffmpeg")
    if not exe:
        return None
    try:
        res = subprocess.run(
            [exe, "-hide_banner", "-i", path, "-filter_complex", "ebur128=peak=true",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout)
        return parse_integrated_loudness(res.stderr)
    except Exception:  # pragma: no cover
        return None
