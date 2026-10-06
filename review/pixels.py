"""Deterministic rendered-pixel measurements (FFmpeg + stdlib only).

Everything here reads a rendered video or image and returns measured numbers.
No ML, no network, no writes. When FFmpeg or the file is missing, functions
return None so callers can report the check as unavailable.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import Dict, List, Optional, Sequence

from . import process

_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")


def analysis_size(width: int, height: int, longest: int = 480) -> tuple:
    """Downscaled size that keeps the aspect ratio (even dimensions)."""
    if not width or not height:
        return longest, longest
    if width >= height:
        return longest, max(2, int(round(longest * height / width / 2.0)) * 2)
    return max(2, int(round(longest * width / height / 2.0)) * 2), longest


def gray_frame(path: str, t: float, width: int, height: int,
               crop: Optional[str] = None, timeout: int = 60) -> Optional[bytes]:
    """One grayscale frame at time t, area-downscaled to width x height."""
    if not os.path.isfile(path):
        return None
    try:
        return process.decode_gray_frame(
            path, timestamp=t, width=width, height=height, crop=crop,
            is_image=path.lower().endswith(_IMAGE_EXT), timeout=timeout)
    except process.ProcessError:
        return None


def frame_stats(buf: bytes) -> Dict:
    """Mean luma, dominant background luma, and content coverage (share of
    pixels that differ from the background by more than 32/255)."""
    n = len(buf)
    counts = Counter(buf)
    hist = [0] * 16
    for v, c in counts.items():
        hist[v >> 4] += c
    bg = max(range(16), key=lambda i: hist[i]) * 16 + 8
    content = sum(c for v, c in counts.items() if abs(v - bg) > 32)
    return {"mean_luma": round(sum(buf) / float(n), 2), "background_luma": bg,
            "content_coverage": round(content / float(n), 5)}


def frame_zero(path: str, width: int, height: int, rule: Dict) -> Optional[Dict]:
    """Frame-0 rule: meaningful content must be visible at frame 0 or by the
    deadline, and frame 0 must not be near-black and empty."""
    w, h = analysis_size(width, height)
    deadline = float(rule.get("deadline_seconds", 0.5))
    min_cov = float(rule.get("min_content_coverage", 0.01))
    near_black = float(rule.get("near_black_mean_luma", 24))
    b0 = gray_frame(path, 0.0, w, h)
    if b0 is None:
        return None
    bd = gray_frame(path, deadline, w, h)
    # A failed deadline frame is unavailable evidence: never substitute frame 0.
    if bd is None:
        return None
    s0 = frame_stats(b0)
    sd = frame_stats(bd)
    return {
        "at_0": s0,
        "at_deadline": sd,
        "deadline_seconds": deadline,
        "min_content_coverage": min_cov,
        "meaningful_at_0": s0["content_coverage"] >= min_cov,
        "meaningful_by_deadline": max(s0["content_coverage"], sd["content_coverage"]) >= min_cov,
        "near_black_empty_at_0": s0["mean_luma"] < near_black and s0["content_coverage"] < min_cov,
    }


# ---------------------------------------------------------------- freeze


def freeze_regions(path: str, min_seconds: float, noise_db: float = -60.0,
                   content_crop: Optional[Sequence[float]] = None,
                   total_duration: Optional[float] = None,
                   timeout: int = 300) -> Optional[List[Dict]]:
    """Rendered static holds from actual pixels (FFmpeg freezedetect).

    content_crop = (top, bottom) fractions excluded so persistent chrome such
    as a continuously filling progress bar does not mask a frozen content area.
    """
    if not os.path.isfile(path):
        return None
    try:
        return process.freezedetect(path, noise_db=noise_db, min_seconds=min_seconds,
                                    crop=content_crop, total_duration=total_duration,
                                    timeout=timeout)
    except process.ProcessError:
        return None


# ---------------------------------------------------------------- motion / coverage (advisory)


def _still_runs(series: Sequence[float], threshold: float, fps: float) -> List[Dict]:
    """Runs of consecutive samples whose frame difference stays below threshold.

    series[j] compares samples j and j+1, so a run j..k is still from j/fps to (k+1)/fps."""
    runs, start = [], None
    for j, v in enumerate(list(series) + [float("inf")]):
        if v < threshold and start is None:
            start = j
        elif v >= threshold and start is not None:
            runs.append({"start": round(start / fps, 2), "end": round(j / fps, 2),
                         "duration": round((j - start) / fps, 2)})
            start = None
    return runs


def near_still(path: str, width: int, height: int, *, fps: float = 10.0,
               threshold: float = 0.05, min_hold: float = 0.6,
               content_crop: Optional[Sequence[float]] = None,
               timeout: int = 300) -> Optional[Dict]:
    """Near-still time and holds from the rendered pixels (advisory context).

    Counts any pixel change as motion, so footage, grain or drifting particles
    read as moving: a diagnostic, never a quality verdict."""
    if not os.path.isfile(path):
        return None
    w, h = analysis_size(width, height)
    try:
        series = process.motion_series(path, fps=fps, width=w, height=h,
                                       crop=content_crop, timeout=timeout)
    except process.ProcessError:
        return None
    if not series:
        return None
    runs = _still_runs(series, threshold, fps)
    return {"fps": fps, "threshold": threshold, "samples": len(series),
            "near_still_seconds": round(sum(r["duration"] for r in runs), 1),
            "holds": [r for r in runs if r["duration"] > min_hold],
            "longest_hold": max([r["duration"] for r in runs] or [0.0])}


def coverage_series(path: str, width: int, height: int, duration: float, *,
                    fps: float = 10.0, timeout: int = 300) -> Optional[List[float]]:
    """Content coverage (frame_stats) of every sampled frame."""
    if not os.path.isfile(path) or not duration:
        return None
    w, h = analysis_size(width, height)
    try:
        frames = process.decode_gray_sequence(path, fps=fps, width=w, height=h,
                                              max_frames=int(duration * fps) + 2, timeout=timeout)
    except process.ProcessError:
        return None
    return [frame_stats(f)["content_coverage"] for f in frames] or None


def empty_spans(coverage: Sequence[float], fps: float, min_coverage: float,
                skip_before: float = 0.0) -> List[Dict]:
    """Contiguous near-empty spans (coverage below min_coverage) after skip_before."""
    spans, cur = [], None
    for i, c in enumerate(list(coverage) + [float("inf")]):
        t = i / fps
        if c < min_coverage and t >= skip_before:
            if cur is None:
                cur = {"start": round(t, 2), "min_coverage": c, "samples": 0}
            cur["samples"] += 1
            cur["min_coverage"] = min(cur["min_coverage"], c)
        elif cur is not None:
            cur["end"] = round(t, 2)
            cur["duration"] = round(cur["samples"] / fps, 2)
            spans.append(cur)
            cur = None
    return spans


def boundary_dips(coverage: Sequence[float], fps: float, boundaries: Sequence[float], *,
                  window: float = 0.6, ratio: float = 0.35) -> List[Dict]:
    """Coverage minimum within +-window of each scene boundary vs the median
    coverage 1-2 s away; a dip is a minimum below ratio x that median."""
    out = []
    for b in boundaries:
        near = [(i, c) for i, c in enumerate(coverage) if abs(i / fps - b) <= window]
        ref = sorted(c for i, c in enumerate(coverage) if 1.0 <= abs(i / fps - b) <= 2.0)
        if not near or not ref:
            continue
        i_min, c_min = min(near, key=lambda x: x[1])
        median = ref[len(ref) // 2]
        out.append({"boundary": round(b, 2), "at": round(i_min / fps, 2),
                    "min_coverage": c_min, "reference_coverage": median,
                    "dip": median > 0 and c_min < ratio * median})
    return out


# ---------------------------------------------------------------- similarity

HASH_W, HASH_H = 17, 16  # 256-bit difference hash
HASH_BITS = (HASH_W - 1) * HASH_H


def dhash(buf: bytes, width: int = HASH_W, height: int = HASH_H) -> int:
    bits = 0
    for y in range(height):
        row = buf[y * width:(y + 1) * width]
        for x in range(width - 1):
            bits = (bits << 1) | (1 if row[x] > row[x + 1] else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def frame_hash(path: str, t: float) -> Optional[int]:
    buf = gray_frame(path, t, HASH_W, HASH_H)
    return dhash(buf) if buf is not None else None


def similar_pairs(hashes: Sequence[Optional[int]], max_bits: int) -> List[Dict]:
    """All (i, j) pairs whose hashes are within max_bits (1-based indexes)."""
    out = []
    for i in range(len(hashes)):
        for j in range(i + 1, len(hashes)):
            if hashes[i] is None or hashes[j] is None:
                continue
            d = hamming(hashes[i], hashes[j])
            if d <= max_bits:
                out.append({"a": i + 1, "b": j + 1, "distance_bits": d,
                            "similarity": round(1.0 - d / float(HASH_BITS), 3)})
    return out


# ---------------------------------------------------------------- text

_WORD = re.compile(r"[0-9A-Za-z؀-ۿ]")


def word_count(text: str) -> int:
    return sum(1 for tok in (text or "").split() if _WORD.search(tok))


def text_density(scenes: Sequence) -> List[Dict]:
    """Visible words per scene and per second, from each scene's DOM text."""
    out = []
    for s in scenes:
        words = word_count(getattr(s, "text", ""))
        dur = float(getattr(s, "duration", 0) or 0)
        out.append({"index": s.index, "words": words, "duration": dur,
                    "words_per_second": round(words / dur, 2) if dur > 0 else None})
    return out
