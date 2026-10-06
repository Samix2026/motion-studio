"""Opt-in numeric browser trace: runtime motion -> normalized tracks.

Runs ``studio/hf_trace.mjs`` (the single HyperFrames/browser adapter) with the
public ``@hyperframes/producer`` package installed OUT of the repository, in
``~/.cache/motion-studio/hf-trace/<hyperframes-version>/`` (override with
``MOTION_STUDIO_TRACE_CACHE``). Installing it is an explicit opt-in
(``studio/cli.py trace --install``); nothing is added to the project.

The trace is cached in ``<project>/production/trace.json`` and bound to the
composition hash (+ fps, size, declared selectors). A changed composition makes
it stale; a stale trace is never used. Failure is explicit: callers get
``status`` ``unavailable``/``failed`` with a reason, never an empty success.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Dict, Optional

from studio import prerender

SCHEMA = 1
ADAPTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hf_trace.mjs")
_PIN = re.compile(r"hyperframes@(\d+\.\d+\.\d+)")
# Known-good HyperFrames runtime: what every template/example/starter pins and
# what is used when a project pins nothing. Upgrading is an explicit maintenance
# action (README "HyperFrames version policy").
HYPERFRAMES_VERSION = "0.8.35"
_HASHED_DIRS = ("lib", "compositions")
_HASHED_FILES = ("index.html", "hyperframes.json", "package.json")


def composition_hash(project_dir: str) -> str:
    """Hash of everything that decides what a frame looks like, except media.

    index.html, hyperframes.json, package.json (pinned engine), every file under
    lib/ and compositions/, and local scripts/styles index.html references.
    Media assets are excluded (size); the build stage checks they exist.
    """
    paths = set()
    for name in _HASHED_FILES:
        p = os.path.join(project_dir, name)
        if os.path.isfile(p):
            paths.add(p)
    for d in _HASHED_DIRS:
        for root, _, files in os.walk(os.path.join(project_dir, d)):
            paths.update(os.path.join(root, f) for f in files)
    paths.update(prerender._local_sources(project_dir))
    h = hashlib.sha256()
    for p in sorted(os.path.normpath(x) for x in paths):
        h.update(os.path.relpath(p, project_dir).encode())
        with open(p, "rb") as fh:
            h.update(hashlib.sha256(fh.read()).digest())
    return h.hexdigest()


def pinned_version(project_dir: str) -> Optional[str]:
    try:
        with open(os.path.join(project_dir, "package.json"), encoding="utf-8") as fh:
            m = _PIN.search(fh.read())
        return m.group(1) if m else None
    except OSError:
        return None


def cache_root() -> str:
    return os.environ.get("MOTION_STUDIO_TRACE_CACHE") or os.path.join(
        os.path.expanduser("~"), ".cache", "motion-studio", "hf-trace")


def tracer_modules(version: str) -> str:
    return os.path.join(cache_root(), version, "node_modules")


def tracer_installed(version: str) -> bool:
    nm = tracer_modules(version)
    return all(os.path.isfile(os.path.join(nm, "@hyperframes", p, "package.json"))
               for p in ("producer", "core"))


def install(version: str, timeout: int = 600) -> Dict:
    """Explicit opt-in: npm install the pinned public producer out of tree."""
    npm = shutil.which("npm")
    if not npm:
        return {"ok": False, "reason": "npm not found"}
    prefix = os.path.join(cache_root(), version)
    os.makedirs(prefix, exist_ok=True)
    pkg = os.path.join(prefix, "package.json")
    if not os.path.isfile(pkg):
        with open(pkg, "w", encoding="utf-8") as fh:
            fh.write('{"private": true}\n')
    res = subprocess.run(
        [npm, "install", "--ignore-scripts", "--no-audit", "--no-fund", "--prefix", prefix,
         "@hyperframes/producer@%s" % version, "@hyperframes/core@%s" % version],
        capture_output=True, text=True, timeout=timeout)
    ok = res.returncode == 0 and tracer_installed(version)
    return {"ok": ok, "path": prefix, "reason": None if ok else (res.stderr or res.stdout)[-800:]}


def availability(project_dir: str) -> Dict:
    version = pinned_version(project_dir)
    if not shutil.which("node"):
        return {"available": False, "reason": "browser trace unavailable: node not found"}
    if not version:
        return {"available": False,
                "reason": "browser trace unavailable: package.json pins no hyperframes@<version>"}
    if not tracer_installed(version):
        return {"available": False, "version": version,
                "reason": "browser trace unavailable: tracer for hyperframes %s not installed "
                          "(python3 studio/cli.py trace <project> --install)" % version}
    return {"available": True, "version": version}


def trace_path(project_dir: str) -> str:
    return os.path.join(project_dir, "production", "trace.json")


def cache_key(project_dir: str, ctx: Dict, selectors: Dict) -> str:
    blob = json.dumps({"hash": composition_hash(project_dir), "fps": ctx["fps"],
                       "w": ctx["width"], "h": ctx["height"], "selectors": selectors,
                       "schema": SCHEMA}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def load_cached(project_dir: str, key: str) -> Optional[Dict]:
    try:
        with open(trace_path(project_dir), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if doc.get("cache_key") == key and doc.get("schema") == SCHEMA else None


def normalize(raw: Dict) -> Dict:
    """Adapter output -> normalized track document (dense -> keyframes).

    Constant tracks carry no motion and are dropped, except ``*.alpha``, which
    the validator needs to know when an element is invisible.
    """
    tracks = {}
    for name, dense in raw["tracks"].items():
        if name.endswith(".rotation"):
            dense = _unwrap(dense)
        keep = name.endswith(".alpha") or len({json.dumps(v) for v in dense}) > 1
        if keep:
            tracks[name] = prerender.compress(dense)
    return {"fps": raw["fps"], "frames": raw["frames"], "duration": raw["duration"],
            "width": raw["width"], "height": raw["height"], "elements": raw["elements"],
            "truncated": raw["truncated"], "tracks": tracks,
            "stage_visible": raw["stage_visible"], "reseek_mismatches": raw["reseek_mismatches"],
            "reseek_invisible": raw.get("reseek_invisible", 0), "reseek_overflow": raw.get("reseek_overflow", 0),
            "adapter_timing_ms": raw.get("timing_ms"),
            "sampled": {"frames": raw["frames"], "elements": len(raw["elements"]),
                        "tracks_sampled": len(raw["tracks"]), "tracks_kept": len(tracks)}}


def _unwrap(dense):
    """Matrix-derived angles wrap at ±180°; continue them so a spin is not a jump."""
    out, offset, prev = [], 0.0, None
    for v in dense:
        if isinstance(v, (int, float)):
            if prev is not None:
                if v + offset - prev > 180:
                    offset -= 360
                elif v + offset - prev < -180:
                    offset += 360
            v = round(v + offset, 3)
            prev = v
        out.append(v)
    return out


def run_trace(project_dir: str, ctx: Dict, selectors: Dict, version: str,
              timeout: int = 600) -> Dict:
    fd, out = tempfile.mkstemp(prefix="ms-trace-", suffix=".json")
    os.close(fd)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI")}
    env["MS_TRACE_NODE_MODULES"] = tracer_modules(version)
    try:
        res = subprocess.run(
            ["node", ADAPTER, os.path.abspath(project_dir), "--fps", str(ctx["fps"]),
             "--width", str(ctx["width"]), "--height", str(ctx["height"]),
             "--selectors", json.dumps(selectors), "--out", out],
            capture_output=True, text=True, timeout=timeout, env=env)
        try:
            with open(out, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            raw = {"ok": False, "error": "adapter wrote no output: %s" % (res.stderr or "")[-600:]}
        return raw
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "trace timed out after %ss" % timeout}
    finally:
        os.unlink(out)


def get_trace(project_dir: str, ctx: Dict, selectors: Optional[Dict] = None,
              refresh: bool = False) -> Dict:
    """Cached-or-fresh trace. Returns {status, reason, trace, seconds}.

    status: ``cached`` | ``traced`` | ``unavailable`` | ``failed``. Only the
    first two carry a trace.
    """
    selectors = selectors or {}
    key = cache_key(project_dir, ctx, selectors)
    if not refresh:
        doc = load_cached(project_dir, key)
        if doc:
            return {"status": "cached", "reason": None, "trace": doc, "seconds": 0.0}
    avail = availability(project_dir)
    if not avail["available"]:
        return {"status": "unavailable", "reason": avail["reason"], "trace": None, "seconds": 0.0}
    t0 = time.monotonic()
    raw = run_trace(project_dir, ctx, selectors, avail["version"])
    seconds = round(time.monotonic() - t0, 2)
    if not raw.get("ok"):
        return {"status": "failed", "reason": "browser trace failed: %s" % raw.get("error", "?")[:600],
                "trace": None, "seconds": seconds}
    if raw["frames"] != ctx["frames"]:
        return {"status": "failed", "seconds": seconds, "trace": None,
                "reason": "browser trace saw %d frames, composition declares %d"
                          % (raw["frames"], ctx["frames"])}
    doc = normalize(raw)
    doc.update({"schema": SCHEMA, "source": "browser-trace", "adapter": "studio/hf_trace.mjs",
                "hyperframes_version": avail["version"], "cache_key": key,
                "composition_hash": composition_hash(project_dir), "trace_seconds": seconds})
    os.makedirs(os.path.dirname(trace_path(project_dir)), exist_ok=True)
    tmp = trace_path(project_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    os.replace(tmp, trace_path(project_dir))
    return {"status": "traced", "reason": None, "trace": doc, "seconds": seconds}
