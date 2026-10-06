"""Explicit review inputs, content hashing, descriptor, and freshness.

The explicit path NEVER discovers a render: the caller names the exact render,
composition, CSS, timing/caption files, snapshots, and declared local
dependencies. Only literal local references are validated — there is no
JavaScript dependency resolver, no browser execution, and no remote/CDN
fetching. Runtime/dynamic dependency coverage is reported as partial/unsupported.

Freshness is content-based: a review descriptor is built from SHA-256 hashes of
the selected inputs (whether or not they validate), the effective rules,
typography, implementation identity, and local tool identities. Path+size is
never used as evidence of freshness.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

REVIEW_INPUTS_VERSION = 2
FINGERPRINT_VERSION = 2

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RULES_PATH = os.path.join(_REPO_ROOT, "review", "rules", "defaults.json")
_TYPOGRAPHY_PATH = os.path.join(_REPO_ROOT, "templates", "tech-news-ar", "lib", "type-scale.json")
_IMPL_FILES = (
    "review/inputs.py",
    "review/analyzer.py",
    "review/htmlmodel.py",
    "review/pixels.py",
    "review/process.py",
    "design/typography.py",
    "timing/schema.py",
    "timing/adapter.py",
)

_REMOTE_RE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.\-]*://|//)")
_LINK_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
_HREF_RE = re.compile(r'href\s*=\s*"([^"]+)"', re.IGNORECASE)
_SRC_RE = re.compile(r'src\s*=\s*"([^"]+)"', re.IGNORECASE)


class ReviewInputError(Exception):
    """An explicit review input is missing, remote, or unsupported."""


# ---------------------------------------------------------------- hashing

def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha_or_none(path: Optional[str]) -> Optional[str]:
    if not path or not os.path.isfile(path):
        return None
    return sha256_file(path)


def _sha256_json(obj) -> str:
    return sha256_bytes(canonical(obj).encode("utf-8"))


def _repo_rel(path: str) -> str:
    return os.path.relpath(path, _REPO_ROOT).replace(os.sep, "/")


def _project_rel(project_dir: str, path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return os.path.relpath(path, project_dir).replace(os.sep, "/")


def load_default_rules() -> Dict:
    with open(_RULES_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- path rules

def reject_remote(value: object, label: str) -> None:
    if isinstance(value, str) and _REMOTE_RE.match(value):
        raise ReviewInputError("%s must be local, not a remote reference: %s" % (label, value))


def resolve_local(project_dir: str, path: str, label: str) -> str:
    reject_remote(path, label)
    candidate = path if os.path.isabs(path) else os.path.join(project_dir, path)
    candidate = os.path.abspath(candidate)
    if not os.path.isfile(candidate):
        raise ReviewInputError("%s is not an existing local file: %s" % (label, path))
    return candidate


# ---------------------------------------------------------------- discovery (legacy only)

def _refs(html: str, tags: re.Pattern, attr: re.Pattern,
          require: Optional[str] = None) -> List[str]:
    out = []
    for tag in tags.findall(html):
        if require and require not in tag:
            continue
        m = attr.search(tag)
        if m:
            out.append(m.group(1))
    return out


def _read_index(project_dir: str) -> str:
    with open(os.path.join(project_dir, "index.html"), "r", encoding="utf-8") as fh:
        return fh.read()


def _local_refs(html: str, tags: re.Pattern, attr: re.Pattern,
                require: Optional[str] = None) -> List[str]:
    return [v for v in _refs(html, tags, attr, require) if not _REMOTE_RE.match(v)]


def remote_references(project_dir: str) -> List[str]:
    try:
        html = _read_index(project_dir)
    except OSError:
        return []
    values = (_refs(html, _SCRIPT_RE, _SRC_RE) + _refs(html, _LINK_RE, _HREF_RE))
    return sorted({v for v in values if _REMOTE_RE.match(v)})


def dependency_provenance(project_dir: str, declared: Sequence[str]) -> Dict:
    """Honest local-only coverage; runtime/dynamic JS is not enumerable here."""
    try:
        required = discover_dependencies(project_dir)
    except OSError:
        required = []
    declared_set = {os.path.normpath(p) for p in declared}
    return {
        "required_local": sorted(_project_rel(project_dir, p) for p in required),
        "declared": sorted(_project_rel(project_dir, p) for p in declared_set),
        "remote_references": remote_references(project_dir),
        "runtime_dynamic": "unsupported",
        "coverage": "partial_local_only",
    }


def discover_render(project_dir: str) -> Optional[str]:
    d = os.path.join(project_dir, "renders")
    if not os.path.isdir(d):
        return None
    cands = [f for f in sorted(os.listdir(d))
             if f.lower().endswith((".mp4", ".mov", ".m4v"))]
    if not cands:
        return None
    if "video.mp4" in cands:
        return os.path.join(d, "video.mp4")
    return os.path.join(d, cands[0])


def discover_css(project_dir: str) -> List[str]:
    try:
        html = _read_index(project_dir)
    except OSError:
        return []
    refs = _local_refs(html, _LINK_RE, _HREF_RE, require="stylesheet")
    return [os.path.normpath(os.path.join(project_dir, r)) for r in refs]


def discover_dependencies(project_dir: str) -> List[str]:
    html = _read_index(project_dir)
    refs = (_local_refs(html, _SCRIPT_RE, _SRC_RE)
            + _local_refs(html, _LINK_RE, _HREF_RE))
    seen, out = set(), []
    for r in refs:
        p = os.path.normpath(os.path.join(project_dir, r))
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def discover_timings(project_dir: str) -> Optional[str]:
    root = os.path.join(project_dir, "word-timings.json")
    if os.path.isfile(root):
        return root
    assets = os.path.join(project_dir, "assets")
    if os.path.isdir(assets):
        for base, _dirs, names in os.walk(assets):
            for fn in sorted(names):
                if fn.endswith(".word-timings.json"):
                    return os.path.join(base, fn)
    return None


def discover_captions(project_dir: str) -> Optional[str]:
    for path in (os.path.join(project_dir, "captions.json"),
                 os.path.join(project_dir, "assets", "captions.json")):
        if os.path.isfile(path):
            return path
    return None


def discover_snapshots(project_dir: str) -> List[str]:
    snap_dir = os.path.join(project_dir, "snapshots")
    if not os.path.isdir(snap_dir):
        return []
    return [os.path.join(snap_dir, fn) for fn in sorted(os.listdir(snap_dir))
            if fn.endswith(".png")]


def extract_dom_captions(html: str) -> Optional[List[Dict]]:
    if 'data-role="caption"' not in html:
        return None
    caps = []
    for tag in re.findall(r"<[^>]*data-role=\"caption\"[^>]*>", html):
        attrs = dict(re.findall(r'([A-Za-z0-9_:\-]+)\s*=\s*"([^"]*)"', tag))
        start = float(attrs.get("data-start", 0) or 0) * 1000.0
        dur = float(attrs.get("data-duration", 0) or 0) * 1000.0
        caps.append({"start_ms": start, "end_ms": start + dur, "text": attrs.get("data-text", "")})
    return caps


# ---------------------------------------------------------------- input model

class ReviewInputs:
    """The exact set of inputs selected for a deterministic review."""

    def __init__(self, project_dir: str, *, render_path: Optional[str],
                 composition_path: str, css_paths: Sequence[str] = (),
                 timing_path: Optional[str] = None, caption_path: Optional[str] = None,
                 dependencies: Sequence[str] = (), snapshot_paths: Optional[Sequence[str]] = None,
                 narration_enabled: bool = False, review_config: Optional[Dict] = None,
                 explicit: bool = True, caption_source_hint: Optional[str] = None):
        self.project_dir = os.path.abspath(project_dir)
        self.render_path = render_path
        self.composition_path = composition_path
        self.css_paths = list(css_paths)
        self.timing_path = timing_path
        self.caption_path = caption_path
        self.dependencies = list(dependencies)
        self.snapshot_paths = None if snapshot_paths is None else list(snapshot_paths)
        self.narration_enabled = bool(narration_enabled)
        self.review_config = dict(review_config or {})
        self.explicit = explicit
        self.caption_source_hint = caption_source_hint

    @classmethod
    def from_explicit(cls, project_dir: str, *, render: str, composition: str,
                      css: Optional[Sequence[str]] = None,
                      timings: Optional[str] = None, captions: Optional[str] = None,
                      dependencies: Optional[Sequence[str]] = None,
                      snapshots: Optional[Sequence[str]] = None,
                      narration_enabled: bool = False,
                      review_config: Optional[Dict] = None) -> "ReviewInputs":
        """Build an explicit input model; every named path must be local/existing."""
        project_dir = os.path.abspath(project_dir)
        if not os.path.isdir(project_dir):
            raise ReviewInputError("project dir does not exist: %s" % project_dir)
        if not render:
            raise ReviewInputError("an explicit render path is required; no render is auto-selected")
        render_path = resolve_local(project_dir, render, "explicit render")
        if not composition:
            raise ReviewInputError("an explicit composition HTML path is required")
        composition_path = resolve_local(project_dir, composition, "explicit composition")
        if os.path.basename(composition_path) != "index.html" or \
                os.path.dirname(composition_path) != project_dir:
            raise ReviewInputError(
                "explicit composition must be the project's index.html "
                "(the deterministic parser reads that file)")
        css_paths = [resolve_local(project_dir, p, "explicit css") for p in (css or [])]
        timing_path = resolve_local(project_dir, timings, "explicit timing") if timings else None
        caption_path = resolve_local(project_dir, captions, "explicit caption") if captions else None
        deps = [resolve_local(project_dir, p, "declared dependency")
                for p in (dependencies or [])]
        snap_paths = None
        if snapshots is not None:
            snap_paths = [resolve_local(project_dir, p, "snapshot") for p in snapshots]
        return cls(project_dir, render_path=render_path, composition_path=composition_path,
                   css_paths=css_paths, timing_path=timing_path, caption_path=caption_path,
                   dependencies=deps, snapshot_paths=snap_paths,
                   narration_enabled=narration_enabled, review_config=review_config,
                   explicit=True)

    @classmethod
    def legacy(cls, project_dir: str) -> "ReviewInputs":
        """Discovery-based inputs for the legacy review commands."""
        project_dir = os.path.abspath(project_dir)
        composition = os.path.join(project_dir, "index.html")
        return cls(project_dir, render_path=discover_render(project_dir),
                   composition_path=composition, css_paths=discover_css(project_dir),
                   timing_path=discover_timings(project_dir),
                   caption_path=discover_captions(project_dir),
                   dependencies=discover_dependencies(project_dir),
                   snapshot_paths=discover_snapshots(project_dir),
                   narration_enabled=False, review_config=None, explicit=False)

    @classmethod
    def from_descriptor(cls, project_dir: str, descriptor: Dict,
                        require_existing: bool = False) -> "ReviewInputs":
        """Reconstruct the exact saved selection (does not re-discover)."""
        if not isinstance(descriptor, dict):
            raise ReviewInputError("saved review descriptor is missing")
        if descriptor.get("schema_version") != REVIEW_INPUTS_VERSION:
            raise ReviewInputError("unsupported saved review descriptor version")
        project_dir = os.path.abspath(project_dir)

        def resolve(rel, label):
            if not rel:
                return None
            if require_existing:
                return resolve_local(project_dir, rel, label)
            return os.path.normpath(rel if os.path.isabs(rel) else os.path.join(project_dir, rel))

        render = resolve((descriptor.get("render") or {}).get("path"), "render")
        composition = resolve((descriptor.get("composition") or {}).get("path"), "composition")
        if not composition:
            raise ReviewInputError("saved review descriptor has no composition")
        css = [resolve(c.get("path"), "css") for c in descriptor.get("css", [])
               if isinstance(c, dict)]
        timings = descriptor.get("timings") or {}
        timing_path = resolve(timings.get("path"), "timing") if timings.get("selected") else None
        captions = descriptor.get("captions") or {}
        caption_path = resolve(captions.get("path"), "caption") \
            if captions.get("source") == "file" else None
        deps = [resolve(d.get("path"), "dependency") for d in descriptor.get("dependencies", [])
                if isinstance(d, dict)]
        snapshots = descriptor.get("snapshots") or {}
        snap_paths = None
        if snapshots.get("selected"):
            snap_paths = [resolve(f.get("path"), "snapshot")
                          for f in snapshots.get("files", []) if isinstance(f, dict)]
        config = descriptor.get("config") or {}
        return cls(project_dir, render_path=render, composition_path=composition,
                   css_paths=css, timing_path=timing_path, caption_path=caption_path,
                   dependencies=deps, snapshot_paths=snap_paths,
                   narration_enabled=bool(config.get("narration_enabled")),
                   review_config=config.get("review_config") or {},
                   explicit=bool(descriptor.get("explicit", True)),
                   caption_source_hint=captions.get("source"))

    # ------------------------------------------------------------ loading

    def load_timings(self) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
        if not self.timing_path:
            return None, None, None
        try:
            with open(self.timing_path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            return None, self.timing_path, str(exc)
        try:
            from timing import schema as timing_schema
            doc = timing_schema.validate(doc)
        except Exception as exc:
            return None, self.timing_path, str(exc)
        return doc, self.timing_path, None

    def load_captions(self) -> Tuple[Optional[List[Dict]], Optional[str]]:
        if not self.caption_path:
            return None, None
        try:
            with open(self.caption_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None, self.caption_path
        caps = data.get("captions") if isinstance(data, dict) else data
        if isinstance(caps, list):
            return caps, self.caption_path
        return None, self.caption_path

    # ------------------------------------------------------------ descriptor

    def descriptor(self, *, rules: Dict, rules_source: str = "default",
                   render_present: bool, timings_doc: Optional[Dict],
                   timings_error: Optional[str], captions: Optional[List[Dict]],
                   caption_source: str, tools: Optional[Dict] = None,
                   dependency_provenance: Optional[Dict] = None) -> Dict:
        composition_sha = _sha_or_none(self.composition_path)
        render_sha = _sha_or_none(self.render_path) if render_present else None
        css = sorted(
            ({"path": _project_rel(self.project_dir, p), "sha256": _sha_or_none(p)}
             for p in self.css_paths),
            key=lambda item: item["path"] or "")
        timings_selected = self.timing_path is not None
        timings = {
            "selected": timings_selected,
            "path": _project_rel(self.project_dir, self.timing_path),
            "sha256": _sha_or_none(self.timing_path),
            "valid": bool(timings_doc) and not timings_error,
            "error": bool(timings_error),
        }
        caption_sha = None
        if caption_source == "dom" and captions is not None:
            caption_sha = _sha256_json(captions)
        elif caption_source == "file" and self.caption_path:
            caption_sha = _sha_or_none(self.caption_path)
        captions_doc = {
            "selected": caption_source != "none",
            "source": caption_source,
            "path": _project_rel(self.project_dir, self.caption_path),
            "sha256": caption_sha,
            "valid": captions is not None,
        }
        dependencies = sorted(
            ({"path": _project_rel(self.project_dir, p),
              "resolved": os.path.isfile(p),
              "sha256": _sha_or_none(p)}
             for p in self.dependencies),
            key=lambda item: item["path"] or "")
        snapshots = {
            "selected": self.snapshot_paths is not None,
            "files": sorted(
                ({"path": _project_rel(self.project_dir, p), "sha256": _sha_or_none(p)}
                 for p in (self.snapshot_paths or [])),
                key=lambda item: item["path"] or ""),
        }
        implementation = {}
        for rel in _IMPL_FILES:
            full = os.path.join(_REPO_ROOT, rel)
            implementation[rel] = _sha_or_none(full)
        config: Dict = {}
        if self.narration_enabled:
            config["narration_enabled"] = True
        if self.review_config:
            config["review_config"] = self.review_config
        return {
            "schema_version": REVIEW_INPUTS_VERSION,
            "fingerprint_version": FINGERPRINT_VERSION,
            "project": os.path.basename(self.project_dir),
            "explicit": self.explicit,
            "render": {"present": bool(render_present and render_sha),
                       "path": _project_rel(self.project_dir, self.render_path),
                       "sha256": render_sha},
            "composition": {"path": _project_rel(self.project_dir, self.composition_path),
                            "sha256": composition_sha},
            "css": css,
            "timings": timings,
            "captions": captions_doc,
            "dependencies": dependencies,
            "snapshots": snapshots,
            "rules": {"sha256": _sha256_json(rules), "source": rules_source},
            "typography": {"path": _repo_rel(_TYPOGRAPHY_PATH),
                           "sha256": _sha_or_none(_TYPOGRAPHY_PATH)},
            "implementation": implementation,
            "tools": tools if tools is not None else process_tool_identities(),
            "dependency_provenance": dependency_provenance or {},
            "config": config,
        }

    @staticmethod
    def fingerprint(descriptor: Dict) -> str:
        return _sha256_json(descriptor)


def process_tool_identities() -> Dict:
    from . import process
    return process.tool_identities()


def rebuild_descriptor(project_dir: str, saved_descriptor: Dict) -> Dict:
    """Rebuild the descriptor from a saved selection using current content."""
    ri = ReviewInputs.from_descriptor(project_dir, saved_descriptor)
    rules = load_default_rules()
    timings_doc, _path, timings_error = ri.load_timings()
    source = (saved_descriptor.get("captions") or {}).get("source", "none")
    if source == "dom":
        try:
            caps = extract_dom_captions(_read_index(os.path.abspath(project_dir)))
        except OSError:
            caps = None
    elif source == "file":
        caps, _cpath = ri.load_captions()
    else:
        caps = None
    render_present = bool(ri.render_path) and os.path.isfile(ri.render_path)
    declared = list(ri.css_paths) + list(ri.dependencies)
    provenance = dependency_provenance(os.path.abspath(project_dir), declared)
    return ri.descriptor(rules=rules, rules_source="default", render_present=render_present,
                         timings_doc=timings_doc, timings_error=timings_error,
                         captions=caps, caption_source=source,
                         tools=process_tool_identities(),
                         dependency_provenance=provenance)


def freshness(current_fingerprint: str, saved: Optional[Dict]) -> Dict:
    """Compare a bare current fingerprint to a saved record's fingerprint."""
    saved = saved if isinstance(saved, dict) else None
    saved_fp = saved.get("review_fingerprint") if saved else None
    saved_ver = saved.get("review_fingerprint_version") if saved else None
    if not saved_fp or saved_ver != FINGERPRINT_VERSION:
        return {"status": "unverified",
                "reason": "saved record has no verifiable review fingerprint",
                "fingerprint": current_fingerprint}
    if saved_fp == current_fingerprint:
        return {"status": "current", "fingerprint": current_fingerprint}
    return {"status": "stale", "fingerprint": current_fingerprint,
            "saved_fingerprint": saved_fp}


def freshness_for_saved(project_dir: str, saved: Optional[Dict]) -> Dict:
    """Validate saved evidence against its exact saved selection, not discovery."""
    saved = saved if isinstance(saved, dict) else None
    descriptor = saved.get("review_inputs") if saved else None
    saved_fp = saved.get("review_fingerprint") if saved else None
    saved_ver = saved.get("review_fingerprint_version") if saved else None
    if not saved_fp or saved_ver != FINGERPRINT_VERSION or not isinstance(descriptor, dict):
        return {"status": "unverified",
                "reason": "saved record has no verifiable review descriptor"}
    if (descriptor.get("rules") or {}).get("source") != "default":
        return {"status": "unverified", "reason": "effective rules cannot be reconstructed"}
    try:
        rebuilt = rebuild_descriptor(os.path.abspath(project_dir), descriptor)
    except Exception:
        return {"status": "unverified", "reason": "saved selection cannot be reconstructed"}
    current = ReviewInputs.fingerprint(rebuilt)
    if current == saved_fp:
        return {"status": "current", "fingerprint": current}
    return {"status": "stale", "fingerprint": current, "saved_fingerprint": saved_fp}
