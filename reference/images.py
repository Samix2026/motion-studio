"""Local image-set measurement (stdlib only, header parsing).

Dimensions are read from file headers — no image library, no network.
"""

from __future__ import annotations

import os
import struct
from typing import Dict, List, Optional, Tuple

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}


def is_image(path: str) -> bool:
    return os.path.isfile(path) and os.path.splitext(path)[1].lower() in IMAGE_EXT


def read_dimensions(path: str) -> Optional[Tuple[int, int]]:
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
            if len(head) < 26:
                return None
            if head.startswith(b"\x89PNG\r\n\x1a\n"):
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h)
            if head[:3] == b"GIF":
                w, h = struct.unpack("<HH", head[6:10])
                return int(w), int(h)
            if head[:2] == b"BM":
                w, h = struct.unpack("<ii", head[18:26])
                return int(w), abs(int(h))
            if head[:2] == b"\xff\xd8":
                return _jpeg_dimensions(fh)
    except Exception:
        return None
    return None


def _jpeg_dimensions(fh) -> Optional[Tuple[int, int]]:
    fh.seek(2)
    while True:
        b = fh.read(1)
        if not b:
            return None
        if b != b"\xff":
            continue
        marker = fh.read(1)
        while marker == b"\xff":
            marker = fh.read(1)
        if not marker:
            return None
        if marker[0] in (0xD8, 0xD9) or 0xD0 <= marker[0] <= 0xD7:
            continue
        size_raw = fh.read(2)
        if len(size_raw) < 2:
            return None
        (size,) = struct.unpack(">H", size_raw)
        if 0xC0 <= marker[0] <= 0xCF and marker[0] not in (0xC4, 0xC8, 0xCC):
            data = fh.read(5)
            if len(data) < 5:
                return None
            h, w = struct.unpack(">HH", data[1:5])
            return int(w), int(h)
        fh.seek(size - 2, os.SEEK_CUR)


def aspect_ratio(width: int, height: int) -> str:
    if not width or not height:
        return "unknown"
    from math import gcd
    g = gcd(int(width), int(height))
    w, h = int(width) // g, int(height) // g
    if w > 50 or h > 50:  # non-simple ratio
        return "%.3f:1" % (width / height)
    return "%d:%d" % (w, h)


def collect(paths: List[str]) -> Dict:
    """Measure a set of images: count, dominant aspect ratio, dimensions."""
    dims: List[Tuple[int, int]] = []
    for p in paths:
        d = read_dimensions(p)
        if d:
            dims.append(d)
    out: Dict = {"image_count": len(dims)}
    if not dims:
        return out
    ratios: Dict[str, int] = {}
    for w, h in dims:
        r = aspect_ratio(w, h)
        ratios[r] = ratios.get(r, 0) + 1
    out["dominant_aspect_ratio"] = max(ratios.items(), key=lambda kv: (kv[1], kv[0]))[0]
    out["width"] = dims[0][0]
    out["height"] = dims[0][1]
    return out


def find_images(root: str) -> List[str]:
    if os.path.isfile(root):
        return [root] if is_image(root) else []
    found: List[str] = []
    for base, _dirs, names in os.walk(root):
        for fn in sorted(names):
            p = os.path.join(base, fn)
            if is_image(p):
                found.append(p)
    return sorted(found)
