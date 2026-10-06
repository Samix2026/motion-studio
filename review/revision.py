"""Revision tracking for the review layer.

Revision state lives OUTSIDE the video projects, under review/state/, so a
review never modifies the project it inspects. Staleness is decided by a
content hash of the project's review-relevant files.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, Optional

from . import inputs as review_inputs

_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")

_HASH_FILES = ["index.html", "script.md", "storyboard.md", "sources.md", "meta.json"]


def slug_for(project_dir: str) -> str:
    return os.path.basename(os.path.normpath(os.path.abspath(project_dir)))


def state_key(project_dir: str) -> str:
    """Path-unique state key: readable slug + short hash of the absolute path."""
    abspath = os.path.normpath(os.path.abspath(project_dir))
    digest = hashlib.sha1(abspath.encode("utf-8")).hexdigest()[:8]
    return "%s-%s" % (os.path.basename(abspath), digest)


def content_hash(project_dir: str) -> str:
    h = hashlib.sha256()
    for name in _HASH_FILES:
        path = os.path.join(project_dir, name)
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                h.update(fh.read())
        h.update(b"\0")
    # asset inventory (path + size) so added/removed audio changes the revision
    assets_root = os.path.join(project_dir, "assets")
    inventory = []
    for root, _dirs, files in os.walk(assets_root):
        for fn in files:
            fp = os.path.join(root, fn)
            inventory.append((os.path.relpath(fp, project_dir), os.path.getsize(fp)))
    for rel, size in sorted(inventory):
        h.update(("%s:%d" % (rel, size)).encode("utf-8"))
    return h.hexdigest()


def _state_path(slug: str) -> str:
    return os.path.join(_STATE_DIR, "%s.json" % slug)


def load_state(slug: str) -> Optional[Dict]:
    path = _state_path(slug)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_state(slug: str, state: Dict) -> None:
    os.makedirs(_STATE_DIR, exist_ok=True)
    path = _state_path(slug)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def default_state(project_dir: str) -> Dict:
    """An in-memory default view for a project with no saved state."""
    key = state_key(project_dir)
    return {
        "slug": slug_for(project_dir),
        "state_key": key,
        "project_dir": os.path.abspath(project_dir),
        "revision": 1,
        "content_hash": content_hash(project_dir),
        "history": [],
        "initialized": False,
    }


def load_state_view(project_dir: str) -> Dict:
    """Read-only state accessor: saved state if present, else a default view.

    Never creates files or directories. Read commands use this; only explicit
    mutation commands may initialise or save state.
    """
    state = load_state(state_key(project_dir))
    if state is not None:
        return state
    return default_state(project_dir)


def get_or_init_state(project_dir: str) -> Dict:
    """Return state for a project, initialising revision 1 on first review."""
    key = state_key(project_dir)
    state = load_state(key)
    if state is None:
        state = default_state(project_dir)
        state.pop("initialized", None)
        save_state(key, state)
    return state


def record_audit(project_dir: str, entry: Dict) -> None:
    key = state_key(project_dir)
    state = load_state(key) or get_or_init_state(project_dir)
    state.setdefault("history", []).append(entry)
    state["last_audit"] = entry
    save_state(key, state)


def is_stale(proposal: Dict, project_dir: str) -> bool:
    """True if the project changed since the proposal was generated.

    New evidence carries a full review-input descriptor; staleness is decided by
    reconstructing the exact saved selection and comparing content-based
    fingerprints. Historical evidence without a descriptor falls back to the
    legacy project hash."""
    status = review_inputs.freshness_for_saved(project_dir, proposal)
    if status.get("status") == "current":
        return False
    if status.get("status") == "stale":
        return True
    expected = proposal.get("project_hash")
    if not expected:
        return True
    return content_hash(project_dir) != expected
