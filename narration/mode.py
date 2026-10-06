"""Narration mode resolution (stdlib only, read-only).

Modes
-----
off       no narration (default); the narration pipeline is not active
optional  narration may be used; missing assets are non-blocking
required  narration must exist; missing assets block the pipeline

The mode lives in the project's ``meta.json`` as ``"narration"`` and defaults
to ``off`` when absent. ``{"narration": {"mode": "..."}}`` is also accepted.
"""

from __future__ import annotations

import json
import os

MODES = ("off", "optional", "required")
DEFAULT_MODE = "off"


class NarrationError(ValueError):
    pass


def normalize(value) -> str:
    """Coerce a meta.json value to a valid mode. None -> default."""
    if value is None:
        return DEFAULT_MODE
    if isinstance(value, dict):
        value = value.get("mode", DEFAULT_MODE)
    if not isinstance(value, str):
        raise NarrationError("narration mode must be a string, got %s" % type(value).__name__)
    v = value.strip().lower()
    if v not in MODES:
        raise NarrationError("narration mode must be one of %s, got %r"
                             % ("|".join(MODES), value))
    return v


def from_meta(meta: dict) -> str:
    if not isinstance(meta, dict):
        raise NarrationError("meta.json must be an object")
    return normalize(meta.get("narration"))


def load(project_dir: str) -> str:
    """Read the mode from <project>/meta.json. Missing file -> off."""
    path = os.path.join(project_dir, "meta.json")
    if not os.path.isfile(path):
        return DEFAULT_MODE
    try:
        with open(path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError) as exc:
        raise NarrationError("meta.json could not be read: %s" % exc)
    return from_meta(meta)


def enabled(mode: str) -> bool:
    return normalize(mode) != "off"
