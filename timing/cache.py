"""Timing cache that lives with the voice asset.

A voice asset ``assets/audio/voice/narration.mp3`` caches its normalized timing
as the sibling ``narration.word-timings.json``. A visual rerender, caption
restyle, or review run reads that file and must not call the provider.
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional

from . import schema

SUFFIX = ".word-timings.json"


def timing_path_for(voice_path: str) -> str:
    base, _ext = os.path.splitext(voice_path)
    return base + SUFFIX


def exists(voice_path: str) -> bool:
    return os.path.isfile(timing_path_for(voice_path))


def load(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as fh:
        return schema.validate(json.load(fh))


def load_cached(voice_path: str) -> Optional[Dict]:
    path = timing_path_for(voice_path)
    if not os.path.isfile(path):
        return None
    return load(path)


def write(path: str, doc: Dict, overwrite: bool = False) -> str:
    schema.validate(doc)
    if os.path.exists(path) and not overwrite:
        raise FileExistsError("timing cache already exists: %s" % path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


def write_for_voice(voice_path: str, doc: Dict, overwrite: bool = False) -> str:
    return write(timing_path_for(voice_path), doc, overwrite=overwrite)
