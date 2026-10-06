"""Gated production pipeline: BRIEF → SPEC → BUILD → VALIDATE → STILLS →
CRITICS → (FIX) → RENDER → QA → AUDIO.

A stage result is PASS / WARN / FAIL / SKIPPED (critics: PENDING until a critic
verdict is recorded). FAIL blocks every downstream stage. Every result is bound
to the production hash (composition hash + meta.json + spec.json); a changed
project makes earlier results STALE, so a builder's fix always goes back
through validation and the critics — it can never inherit an approval.

State lives in ``<project>/production/`` (state.json, validation.json, trace.json,
stills/, critics/, report.md). Existing projects need no new files: the brief is
inferred from meta.json + the composition, the spec from the composition.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from design import brand_reach, context_scope, typography, visual_story
from review import htmlmodel, pixels, process
from studio import prerender, trace as trace_mod

SCHEMA = 1
PASS, WARN, FAIL, SKIPPED, PENDING = "PASS", "WARN", "FAIL", "SKIPPED", "PENDING"
STAGES = (("brief", "Brief"), ("spec", "Spec"), ("build", "Build"), ("validation", "Validation"),
          ("stills", "Stills"), ("motion_critic", "Motion Critic"),
          ("design_critic", "Design Critic"), ("render", "Render"), ("qa", "Post-render QA"),
          ("audio", "Audio"))
PRE_RENDER = ("brief", "spec", "build", "validation", "stills", "motion_critic", "design_critic")
AUDIO_POLICIES = ("none", "sfx", "music", "music+sfx")
DEFAULT_POLICY = {
    "warnings_block": False,             # WARN does not block unless set
    "require_numeric_validation": False,  # trace unavailable → SKIPPED (True → FAIL)
    "require_review": False,             # True → strict mode: stills + critics gate the render
    "max_fix_iterations": 1,             # strict mode only: critic FAIL rounds before escalation
    "stills": 6,
    "visual_story": True,                # visual-first check (storyboard block + data-visual roles)
    "max_text_only_scenes": 1,           # scenes allowed to be text-only (data-visual="text")
}
CRITIC_SEVERITIES = ("BLOCKING", "MAJOR", "MINOR")
# The expected output format is declared, never read back from the composition.
STANDARD_RESOLUTION = "1920x1080"
FORMAT_RESOLUTIONS = {"landscape": "1920x1080", "portrait": "1080x1920"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def prod_dir(project: str) -> str:
    return os.path.join(project, "production")


# ---------------------------------------------------------------- hash + state

def production_hash(project: str) -> str:
    h = hashlib.sha256(trace_mod.composition_hash(project).encode())
    for name in ("meta.json", "spec.json"):
        p = os.path.join(project, name)
        if os.path.isfile(p):
            with open(p, "rb") as fh:
                h.update(name.encode() + hashlib.sha256(fh.read()).digest())
    return h.hexdigest()


def load_state(project: str) -> Dict:
    try:
        return _read_json(os.path.join(prod_dir(project), "state.json"))
    except (OSError, ValueError):
        return {"schema": SCHEMA, "stages": {}, "history": []}


def save_state(project: str, state: Dict) -> None:
    _write_json(os.path.join(prod_dir(project), "state.json"), state)


def record(project: str, stage: str, status: str, summary: str, *, phash: str,
           details: Optional[Dict] = None, seconds: Optional[float] = None,
           override: Optional[str] = None) -> Dict:
    state = load_state(project)
    entry = {"status": status, "summary": summary, "hash": phash, "at": _now(),
             "seconds": seconds}
    if details:
        entry["details"] = details
    if override:
        entry["override"] = override
    state["stages"][stage] = entry
    state["history"].append(dict(entry, stage=stage))
    save_state(project, state)
    return entry


def stage_status(state: Dict, stage: str, phash: str) -> str:
    """Current status of a stage: its recorded status, STALE, or NOT RUN."""
    e = state["stages"].get(stage)
    if not e:
        return "NOT RUN"
    return e["status"] if e["hash"] == phash else "STALE"


# ---------------------------------------------------------------- brief + spec

def _meta(project: str) -> Optional[Dict]:
    p = os.path.join(project, "meta.json")
    return _read_json(p) if os.path.isfile(p) else None


def _audio_policy(meta: Dict) -> str:
    a = meta.get("audio")
    if not isinstance(a, dict) or not a.get("requested"):
        return "none"
    kinds = [k for k in ("music", "sfx") if a.get(k)]
    return "+".join(kinds) if kinds else "sfx"


def load_brief(project: str) -> Tuple[Dict, List[Dict]]:
    """Machine-readable brief: meta.json `production` block, else inferred.

    Every field is optional; `sources` records where each value came from.
    """
    f: List[Dict] = []
    meta = _meta(project)
    if meta is None:
        f.append(prerender.finding(prerender.WARNING, "no_meta", "no meta.json; brief inferred from the composition",
                                   source="brief"))
        meta = {}
    prod = meta.get("production") or {}
    master = (meta.get("outputs") or {}).get("master") or {}
    vt = (meta.get("design_manifest") or {}).get("video_type") or {}
    model = htmlmodel.parse(project) if os.path.isfile(os.path.join(project, "index.html")) else None
    sources: Dict[str, str] = {}

    def pick(field, *cands):
        for src, val in cands:
            if val not in (None, "", [], {}, 0):  # 0 = attribute absent (e.g. no data-fps)
                sources[field] = src
                return val
        return None

    comp_res = "%dx%d" % (model.width, model.height) if model and model.width else None
    b = {
        "project": pick("project", ("meta.production", prod.get("project")), ("meta", meta.get("name")),
                        ("directory", os.path.basename(os.path.abspath(project)))),
        "objective": pick("objective", ("meta.production", prod.get("objective")),
                          ("meta.design_manifest", vt.get("primary_job_to_be_done"))),
        "audience": pick("audience", ("meta.production", prod.get("audience")),
                         ("meta.design_manifest", vt.get("primary_audience"))),
        "core_message": pick("core_message", ("meta.production", prod.get("core_message"))),
        "duration_s": pick("duration_s", ("meta.production", prod.get("duration_s")),
                           ("meta.outputs", master.get("duration_s")),
                           ("composition", model.duration if model else None)),
        "aspect_ratio": pick("aspect_ratio", ("meta.production", prod.get("aspect_ratio")),
                             ("meta.outputs", master.get("aspect_ratio"))),
        "resolution": pick("resolution", ("meta.production", prod.get("resolution")),
                           ("meta.outputs", master.get("resolution")),
                           ("meta.format", FORMAT_RESOLUTIONS.get(meta.get("format"))),
                           ("default", STANDARD_RESOLUTION)),
        "fps": pick("fps", ("meta.production", prod.get("fps")), ("meta.outputs", master.get("fps")),
                    ("composition", model.fps if model else None), ("default", 30)),
        "language": pick("language", ("meta.production", prod.get("language")), ("default", "ar")),
        "direction": pick("direction", ("meta.production", prod.get("direction")), ("default", "rtl")),
        "brand_constraints": pick("brand_constraints", ("meta.production", prod.get("brand_constraints")),
                                  ("meta", meta.get("brand"))),
        "typography": pick("typography", ("meta.production", prod.get("typography"))),
        "assets": prod.get("assets") or [],
        "required_text": prod.get("required_text") or [],
        "forbidden": prod.get("forbidden") or [],
        "forbidden_text": prod.get("forbidden_text") or [],
        "audio": pick("audio", ("meta.production", prod.get("audio")), ("meta.audio", _audio_policy(meta))),
        "loudness_lufs": prod.get("loudness_lufs"),
        "delivery": {"file": pick("delivery.file", ("meta.production", (prod.get("delivery") or {}).get("file")),
                                  ("meta.outputs", master.get("file")), ("default", "renders/video.mp4")),
                     "codec": pick("delivery.codec", ("meta.production", (prod.get("delivery") or {}).get("codec")),
                                   ("meta.outputs", master.get("codec")), ("default", "h264"))},
        "policy": dict(DEFAULT_POLICY, **(prod.get("policy") or {})),
    }
    b["sources"] = sources
    if b["audio"] not in AUDIO_POLICIES:
        f.append(prerender.finding(prerender.ERROR, "bad_audio_policy", "audio must be one of %s"
                                   % ", ".join(AUDIO_POLICIES), source="brief", observed=b["audio"]))
    if not (isinstance(b["fps"], (int, float)) and b["fps"] > 0):
        f.append(prerender.finding(prerender.ERROR, "bad_fps", "fps must be positive", source="brief",
                                   observed=b["fps"]))
    if model and comp_res and b["resolution"] != comp_res:
        f.append(prerender.finding(prerender.ERROR, "resolution_mismatch",
                                   "expected %s (%s) but the composition is %s; build at the expected "
                                   "size, or declare the format explicitly in meta.json "
                                   "(`format: portrait` or `production.resolution`)"
                                   % (b["resolution"], sources["resolution"], comp_res), source="brief"))
    if model and model.duration and b["duration_s"] and isinstance(b["fps"], (int, float)) \
            and abs(float(b["duration_s"]) - model.duration) > 1.0 / b["fps"] + 1e-6:
        f.append(prerender.finding(prerender.ERROR, "duration_mismatch", "brief %ss but composition is %ss"
                                   % (b["duration_s"], model.duration), source="brief"))
    if not os.path.isfile(os.path.join(project, "BRIEF.md")):
        f.append(prerender.finding(prerender.INFO, "no_brief_md", "no BRIEF.md (human brief)", source="brief"))
    return b, f



def load_spec(project: str) -> Tuple[Optional[Dict], List[Dict]]:
    """Optional spec.json. None when absent (scenes are inferred)."""
    p = os.path.join(project, "spec.json")
    if not os.path.isfile(p):
        return None, []
    try:
        spec = _read_json(p)
    except ValueError as exc:
        return None, [prerender.finding(prerender.ERROR, "spec_unreadable", str(exc), source="spec")]
    f = []
    types = {"scenes": list, "tracks": dict, "discontinuities": list, "trace": dict, "validator": dict}
    if not isinstance(spec, dict):
        return None, [prerender.finding(prerender.ERROR, "spec_malformed", "spec must be an object",
                                        source="spec")]
    for key, typ in types.items():
        if key in spec and not isinstance(spec[key], typ):
            f.append(prerender.finding(prerender.ERROR, "spec_malformed", "%s must be a %s"
                                       % (key, typ.__name__), source="spec"))
    for i, s in enumerate(spec.get("scenes") or []):
        if not isinstance(s, dict) or not s.get("id"):
            f.append(prerender.finding(prerender.ERROR, "spec_malformed", "scene %d needs an id" % i,
                                       source="spec"))
    return spec, f


def context(project: str, brief: Dict, spec: Optional[Dict]) -> Dict:
    model = htmlmodel.parse(project)
    fps = brief["fps"]
    width, height = model.width, model.height
    if not width and isinstance(brief.get("resolution"), str) and "x" in brief["resolution"]:
        width, height = (int(x) for x in brief["resolution"].split("x"))
    duration = model.duration or float(brief.get("duration_s") or 0)
    return {
        "fps": fps, "width": width, "height": height, "duration": duration,
        "frames": int(round(duration * fps)),
        "scenes": [{"id": s.id, "start": int(round(s.start * fps)), "end": int(round(s.end * fps)),
                    "text": s.text, "grammar": _attr(s.raw, "data-grammar")} for s in model.scenes],
        "thresholds": ((spec or {}).get("validator") or {}).get("thresholds") or {},
    }


def _attr(tag: str, name: str) -> Optional[str]:
    m = re.search(r'%s="([^"]*)"' % re.escape(name), tag or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------- build

_REF = re.compile(r"""\b(?:src|href|poster)\s*=\s*["']([^"'#?]+)""")
_URL = re.compile(r"""url\(\s*["']?([^"')#?]+)""")
_COMMENTS = re.compile(r"/\*.*?\*/|<!--.*?-->", re.S)


def check_build(project: str, brief: Dict) -> List[Dict]:
    """Composition exists, every local reference exists, fonts bundled, required text."""
    index = os.path.join(project, "index.html")
    if not os.path.isfile(index):
        return [prerender.finding(prerender.ERROR, "no_composition", "index.html missing", source="build")]
    f: List[Dict] = []
    files = [index] + [p for p in prerender._local_sources(project) if p.endswith(".css")]
    missing = set()
    for path in files:
        with open(path, encoding="utf-8") as fh:
            text = _COMMENTS.sub(" ", fh.read())
        for ref in _REF.findall(text) + _URL.findall(text):
            ref = ref.strip()
            if re.match(r"^([a-z]+:|//|%23)", ref) or "${" in ref:  # %23: SVG fragment in a data URI
                continue
            # HyperFrames resolves CSS url() from the project root; accept either base.
            cands = [os.path.normpath(os.path.join(b, ref)) for b in (project, os.path.dirname(path))]
            if not any(os.path.exists(c) for c in cands):
                missing.add(os.path.relpath(cands[0], project))
    for m in sorted(missing):
        f.append(prerender.finding(prerender.ERROR, "missing_asset", "referenced file does not exist",
                                   source="build", prop=m))
    if brief["policy"].get("visual_story"):
        vs = visual_story.check(project, brief["policy"].get("max_text_only_scenes", 1))
        for e in vs["errors"]:
            f.append(prerender.finding(prerender.ERROR, e["code"], e["message"], source="build"))
        if not vs["enforced"]:
            f.append(prerender.finding(prerender.WARNING, "visual_story_not_checked", vs["advisories"][0],
                                       source="build"))
    advisory = brand_reach.reach(project)["advisory"]
    if advisory:  # advisory only: never a gate
        f.append(prerender.finding(prerender.INFO, "brand_palette_reach", advisory, source="build"))
    fonts = typography.static_font_report(project)
    if fonts["status"] == "wrong_family":
        f.append(prerender.finding(prerender.ERROR, "font_required_mismatch",
                                   "required font %s (%s) but the primary family is %s"
                                   % (fonts["required_family"], fonts["required_source"],
                                      fonts["primary_family"]), source="build"))
    elif fonts["status"] == "missing_file":
        f.append(prerender.finding(prerender.ERROR, "font_missing", "declared font file missing",
                                   source="build", observed=fonts["missing_files"]))
    elif fonts["fallback_risk"]:
        f.append(prerender.finding(prerender.WARNING, "font_fallback_risk", "primary font is %s"
                                   % fonts["status"], source="build", observed=fonts["primary_family"]))
    with open(index, encoding="utf-8") as fh:
        html = fh.read()
    if context_scope.HANDLE_PLACEHOLDER in _COMMENTS.sub(" ", html):
        f.append(prerender.finding(
            prerender.ERROR, "handle_placeholder",
            "the template placeholder %s is still in index.html: replace it with your own "
            "social handle, or delete the handle element if this video carries no handle "
            "(then set user_identity.show_handle: false in meta.json)"
            % context_scope.HANDLE_PLACEHOLDER, source="build"))
    visible = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    for text in brief.get("required_text") or []:
        if text not in visible:
            f.append(prerender.finding(prerender.ERROR, "required_text_missing", "required text not in "
                                       "the composition", source="build", observed=text))
    for text in brief.get("forbidden_text") or []:
        if text in visible:
            f.append(prerender.finding(prerender.ERROR, "forbidden_text_present", "forbidden text in "
                                       "the composition", source="build", observed=text))
    return f


# ---------------------------------------------------------------- validation

def _npx_hf(project: str) -> Optional[List[str]]:
    npx = shutil.which("npx")
    if not npx:
        return None
    ver = trace_mod.pinned_version(project) or trace_mod.HYPERFRAMES_VERSION
    return [npx, "--yes", "hyperframes@%s" % ver]


def hyperframes_check(project: str, timeout: int = 600) -> List[Dict]:
    """Existing HyperFrames gate (lint, runtime, layout/overflow, motion sidecar,
    contrast) mapped into findings. Unavailability is a WARNING, never a pass."""
    cmd = _npx_hf(project)
    if not cmd:
        return [prerender.finding(prerender.WARNING, "check_unavailable", "npx not found; hyperframes check "
                                  "did not run", source="hyperframes")]
    env = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI")}
    try:
        res = subprocess.run(cmd + ["check", os.path.abspath(project), "--json"], capture_output=True,
                             text=True, timeout=timeout, env=env)
        doc = json.loads(res.stdout)
    except (subprocess.TimeoutExpired, ValueError) as exc:
        return [prerender.finding(prerender.WARNING, "check_unavailable", "hyperframes check did not "
                                  "complete: %s" % str(exc)[:200], source="hyperframes")]
    sev = {"error": prerender.ERROR, "warning": prerender.WARNING, "info": prerender.INFO}
    out = []
    for section in ("lint", "runtime", "layout", "motion", "contrast"):
        for x in (doc.get(section) or {}).get("findings") or []:
            t = x.get("time")
            out.append(prerender.finding(sev.get(x.get("severity"), prerender.INFO),
                                         "hf_%s" % x.get("code", section), x.get("message", "")[:300],
                                         source="hyperframes/" + section,
                                         prop=x.get("selector") or x.get("file"),
                                         observed=("t=%ss" % t) if t is not None else None))
    return out


def _alpha_map(tracks: Dict[str, List]) -> Dict[str, Tuple[int, List[float]]]:
    out = {}
    for name, tr in tracks.items():
        el, prop = prerender.split_track(name)
        if prop == "alpha" or (prop == "opacity" and el not in out):
            out[el] = prerender.densify(tr)
    return out


def numeric_validation(project: str, ctx: Dict, spec: Optional[Dict], policy: Dict,
                       use_trace: bool = True, refresh_trace: bool = False) -> Tuple[List[Dict], Dict]:
    """spec tracks + runtime trace → normalized tracks → the same validator."""
    f: List[Dict] = []
    spec = spec or {}
    annotations, af = prerender.resolve_annotations(spec.get("discontinuities"), ctx["fps"])
    f.extend(af)
    info: Dict = {"sources": []}
    spec_tracks = {}
    if spec.get("tracks"):
        spec_tracks, nf = prerender.normalize_tracks(spec["tracks"], ctx["frames"], "spec")
        f.extend(nf)
        f.extend(prerender.validate_tracks(spec_tracks, ctx, annotations, "spec", _alpha_map(spec_tracks)))
        info["sources"].append("spec")
    review_frames = [x for s in spec.get("scenes") or [] for x in s.get("review_frames") or []
                     if isinstance(x, int)]
    if use_trace:
        res = trace_mod.get_trace(project, ctx, (spec.get("trace") or {}).get("selectors") or {},
                                  refresh=refresh_trace)
        info["trace"] = {k: res[k] for k in ("status", "reason", "seconds")}
    else:
        res = {"status": "unavailable", "reason": "browser trace disabled (--no-trace)", "trace": None}
        info["trace"] = {"status": "disabled", "reason": res["reason"], "seconds": 0}
    if res["trace"]:
        doc = res["trace"]
        tracks, nf = prerender.normalize_tracks(doc["tracks"], ctx["frames"], "trace")
        f.extend(nf)
        alpha = _alpha_map(tracks)
        motion = {k: v for k, v in tracks.items() if not k.endswith(".alpha")}
        f.extend(prerender.dedupe_box(prerender.validate_tracks(motion, ctx, annotations, "trace", alpha)))
        f.extend(prerender.check_trace_runtime(doc, ctx, review_frames))
        f.extend(prerender.check_offstage(tracks, ctx, alpha))
        f.extend(_spec_vs_trace(spec_tracks, tracks))
        if doc.get("truncated"):
            f.append(prerender.finding(prerender.WARNING, "trace_truncated", "%d elements beyond the trace cap "
                                       "were not traced" % doc["truncated"], source="trace"))
        info["sources"].append("trace")
        info["trace"].update(doc["sampled"])
    elif policy.get("require_numeric_validation"):
        f.append(prerender.finding(prerender.ERROR, "numeric_validation_required",
                                   "policy requires numeric validation: %s" % res["reason"], source="trace"))
    nums = [x for x in f if x["source"] in ("spec", "trace")]
    if not info["sources"]:
        info["status"] = FAIL if policy.get("require_numeric_validation") else SKIPPED
    else:
        info["status"] = prerender.summarize(nums, policy.get("warnings_block"))["status"]
    if res["trace"] is None:
        info["reason"] = res["reason"]
    return f, info


def _spec_vs_trace(spec_tracks: Dict, trace_tracks: Dict) -> List[Dict]:
    """Declared keyframes are authoritative; runtime that disagrees is reported."""
    out = []
    for name, sp in spec_tracks.items():
        if name not in trace_tracks:
            continue
        t0, tv = prerender.densify(trace_tracks[name])
        kind = prerender.prop_kind(name)
        tol = {"position": 2.0, "size": 2.0, "scale": 0.01, "rotation": 0.5, "opacity": 0.02}.get(kind, 0.01)
        for f, v in sp:
            if 0 <= f - t0 < len(tv) and abs(tv[f - t0] - v) > tol:
                out.append(prerender.finding(prerender.WARNING, "runtime_differs_from_spec",
                                             "runtime value differs from the declared keyframe",
                                             source="trace", frame=f, prop=name,
                                             observed="spec %g, runtime %g" % (v, round(tv[f - t0], 3))))
                break
    return out


# ---------------------------------------------------------------- stills

def _energy(trace_doc: Optional[Dict], ctx: Dict) -> Optional[List[float]]:
    """Per-frame visible motion: normalized |Δ| summed over traced tracks of
    elements that are visible (alpha) and on stage (box) at that frame."""
    if not trace_doc:
        return None
    n = ctx["frames"]
    e = [0.0] * n
    w, h = ctx["width"] or 1080, ctx["height"] or 1080
    unit = float(min(w, h))
    tracks = trace_doc["tracks"]
    dense = {k: prerender.densify(v) for k, v in tracks.items()}

    def at(name, f, default):
        if name not in dense:
            return default
        f0, vals = dense[name]
        return vals[min(max(f - f0, 0), len(vals) - 1)]

    for name, (f0, vals) in dense.items():
        kind = prerender.prop_kind(name)
        if name.endswith(".alpha") or kind not in ("position", "scale", "opacity", "rotation"):
            continue
        el, _ = prerender.split_track(name)
        div = {"position": unit * 0.01, "scale": 0.01, "opacity": 0.05, "rotation": 1.0}[kind]
        for i in range(1, len(vals)):
            f = f0 + i
            if not 0 <= f < n or at(el + ".alpha", f, 1.0) <= prerender.INVISIBLE_ALPHA:
                continue
            x, y = at(el + ".box.x", f, 0.0), at(el + ".box.y", f, 0.0)
            bw, bh = at(el + ".box.w", f, 1.0), at(el + ".box.h", f, 1.0)
            if x >= w or y >= h or x + bw <= 0 or y + bh <= 0:
                continue
            e[f] += abs(vals[i] - vals[i - 1]) / div
    return e


def select_frames(ctx: Dict, spec: Optional[Dict], trace_doc: Optional[Dict],
                  validation_findings: List[Dict], target: int = 6) -> List[Dict]:
    """4–6 representative frames: explicit review_frames first, then the final
    state, settled hero of each scene (text-heavy and dense first), validator
    hot spots and the busiest transition — at least ~0.75 s apart."""
    frames, fps = ctx["frames"], ctx["fps"]
    energy = _energy(trace_doc, ctx)
    vis = (trace_doc or {}).get("stage_visible") or []
    cands: List[Tuple[float, int, str]] = []
    for s in (spec or {}).get("scenes") or []:
        for f in s.get("review_frames") or []:
            cands.append((100.0, f, "review_frame (spec)"))
    cands.append((90.0, frames - 1, "final state"))
    for s in ctx["scenes"]:
        lo, hi = s["start"], min(s["end"], frames) - 1
        if hi <= lo:
            continue
        hero = lo + int(0.7 * (hi - lo))
        if energy:   # first frame after the entrance where motion has settled
            for f in range(lo + int(0.25 * (hi - lo)), hi):
                if sum(energy[f: f + int(fps // 2)]) < 1.0:
                    hero = f
                    break
        words = len((s.get("text") or "").split())
        density = vis[hero] if hero < len(vis) else 0
        opening = s is ctx["scenes"][0]
        cands.append((85.0 if opening else 40.0 + min(words, 30) + min(density, 40) * 0.25, hero,
                      "%s hero of %s (%d words)" % ("opening" if opening else "settled", s["id"], words)))
    for x in validation_findings:
        if x["severity"] in ("ERROR", "WARNING") and isinstance(x.get("frame"), int):
            cands.append((70.0, x["frame"], "validator %s: %s" % (x["severity"], x["code"])))
    if energy:
        bounds = [s["start"] for s in ctx["scenes"] if s["start"] > 0]
        if bounds:
            def peak(b):
                win = range(max(0, b - int(fps // 2)), min(frames, b + int(fps // 2)))
                return max(win, key=lambda f: energy[f])
            busiest = max(bounds, key=lambda b: energy[peak(b)])
            cands.append((75.0, peak(busiest), "busiest transition (around frame %d)" % busiest))
    picked: List[Dict] = []
    gap = max(1, int(0.75 * fps))
    for score, f, why in sorted(cands, key=lambda c: (-c[0], c[1])):
        f = max(0, min(frames - 1, f))
        near = [p for p in picked if abs(p["frame"] - f) < gap]
        if near:
            near[0]["reasons"].append(why)
            continue
        if len(picked) < target or score >= 100:
            picked.append({"frame": f, "time": round(f / fps, 4), "reasons": [why]})
    return sorted(picked, key=lambda p: p["frame"])


def motion_strip_frames(ctx: Dict, max_boundaries: int = 5) -> List[Dict]:
    out = []
    for s in [s for s in ctx["scenes"] if s["start"] > 0][:max_boundaries]:
        for d in (-2, -1, 0, 1, 2):
            f = s["start"] + d
            if 0 <= f < ctx["frames"]:
                out.append({"frame": f, "time": round(f / ctx["fps"], 4), "boundary": s["id"]})
    return out


def snapshot(project: str, times: List[float], out_dir: str, timeout: int = 600) -> Dict:
    cmd = _npx_hf(project)
    if not cmd:
        return {"ok": False, "reason": "npx not found"}
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI")}
    res = subprocess.run(cmd + ["snapshot", os.path.abspath(project), "--at",
                                ",".join("%.4f" % t for t in times), "--no-end", "--describe", "false",
                                "-o", os.path.abspath(out_dir)],
                         capture_output=True, text=True, timeout=timeout, env=env)
    pngs = sorted(glob.glob(os.path.join(out_dir, "frame-*.png")))
    # HyperFrames splits a large contact sheet into contact-sheet-1.jpg, -2.jpg, ...
    sheets = sorted(glob.glob(os.path.join(out_dir, "contact-sheet*.jpg")),
                    key=lambda x: int(re.sub(r"\D", "", os.path.basename(x)) or 0))
    ok = res.returncode == 0 and len(pngs) == len(times)
    return {"ok": ok, "files": pngs, "sheets": sheets,
            "reason": None if ok else (res.stderr or res.stdout)[-500:]}


# ---------------------------------------------------------------- critics

def pack_id(phash: str) -> str:
    return phash[:12]


def motion_facts(ctx: Dict, trace_doc: Optional[Dict]) -> List[str]:
    """Measured, not judged: per-scene settle time, holds, dead time (trace)."""
    energy = _energy(trace_doc, ctx)
    if energy is None:
        return ["numeric trace unavailable: no measured motion facts"]
    fps = ctx["fps"]
    out = []
    for s in ctx["scenes"]:
        lo, hi = s["start"], min(s["end"], ctx["frames"])
        seg = energy[lo:hi]
        if not seg:
            continue
        still, longest, cur_start, settle = 0, (0, lo), None, None
        for i, e in enumerate(seg + [99.0]):
            if e < 0.05:
                still += 1
                cur_start = lo + i if cur_start is None else cur_start
            else:
                if cur_start is not None and lo + i - cur_start > longest[0]:
                    longest = (lo + i - cur_start, cur_start)
                cur_start = None
        for i in range(len(seg)):
            if sum(seg[i: i + int(fps // 2)]) < 1.0:
                settle = i
                break
        out.append("%s [%.2f–%.2fs]: entrance settles %s; still %.1fs of %.1fs; longest hold %.2fs from "
                   "%.2fs; peak motion %.1f at %.2fs"
                   % (s["id"], lo / fps, hi / fps,
                      ("at %.2fs" % ((lo + settle) / fps)) if settle is not None else "never",
                      still / fps, (hi - lo) / fps, longest[0] / fps, longest[1] / fps,
                      max(seg), (lo + seg.index(max(seg))) / fps))
    return out


def build_critic_packs(project: str, phash: str, brief: Dict, ctx: Dict, stills: Dict,
                       validation: Dict, trace_doc: Optional[Dict]) -> Dict:
    base = os.path.join(prod_dir(project), "critics", pack_id(phash))
    shutil.rmtree(base, ignore_errors=True)
    packs = {}
    scenes = "\n".join("| %s | %d–%d | %.2f–%.2fs | %s |" % (s["id"], s["start"], s["end"],
                                                         s["start"] / ctx["fps"], s["end"] / ctx["fps"],
                                                         s.get("grammar") or "-") for s in ctx["scenes"])
    head = ("Pack: %s (production hash %s)\nFormat: %sx%s @ %s fps, %.2fs, %d frames, language %s (%s)\n\n"
            "| scene | frames | time | grammar |\n|---|---|---|---|\n%s\n"
            % (pack_id(phash), phash[:12], ctx["width"], ctx["height"], ctx["fps"], ctx["duration"],
               ctx["frames"], brief["language"], brief["direction"], scenes))
    val = [x for x in validation.get("findings", [])   # visual facts only, not lint style
           if x["severity"] != "INFO" and x["source"] != "hyperframes/lint"][:15]
    val_md = "\n".join("- " + prerender.format_finding(x).replace("\n  ", " · ") for x in val) or "- none"
    for critic in ("design", "motion"):
        rows = stills[critic]["frames"]
        d = os.path.join(base, critic)
        os.makedirs(d)
        files = []
        for i, sheet in enumerate(stills[critic].get("sheets") or [], 1):
            files.append("sheet-%d.jpg" % i)
            shutil.copy(sheet, os.path.join(d, files[-1]))
        if critic == "motion":
            for i, sheet in enumerate(stills["design"].get("sheets") or [], 1):
                files.append("key-frames-%d.jpg" % i)
                shutil.copy(sheet, os.path.join(d, files[-1]))
        tiles = "\n".join("%d. frame %d (%.3fs) — %s" % (
            i + 1, r["frame"], r["time"],
            "; ".join(r["reasons"]) if r.get("reasons") else "boundary into %s" % r.get("boundary"))
            for i, r in enumerate(rows))
        if critic == "design":
            extra = ("## Brief\n- objective: %s\n- audience: %s\n- core message: %s\n- typography: %s\n"
                     "- brand constraints: %s\n- forbidden: %s\n- required text: %s\n"
                     % (brief["objective"], brief["audience"], brief["core_message"], brief["typography"],
                        brief["brand_constraints"], brief["forbidden"], brief["required_text"]))
        else:
            extra = ("## Measured motion (numeric trace; facts, not verdicts)\n%s\n\n"
                     "key-frames-*.jpg = the design stills, for context. Motion sheets show 5 consecutive "
                     "frames (b-2..b+2) around each scene boundary.\n"
                     % "\n".join("- " + x for x in motion_facts(ctx, trace_doc)))
        md = "\n".join([
            "# %s critic pack" % critic.title(), "Mode: %s" % critic, head,
            "## Sheet tiles (sheet-1, sheet-2, …; left→right, top→bottom)", tiles, "", extra,
            "## Validator findings (pre-render, facts)", val_md, "",
            "Read: %s" % ", ".join(["pack.md"] + files), ""])
        with open(os.path.join(d, "pack.md"), "w", encoding="utf-8") as fh:
            fh.write(md)
        packs[critic] = {"dir": d, "files": ["pack.md"] + files}
    return packs


def critic_prompt(critic: str, pack: Dict) -> str:
    return ("Agent %s-critic · Pack: %s/ · Read in one turn: %s · Reply with the JSON block only."
            % (critic, pack["dir"], ", ".join(pack["files"])))


def validate_critic_record(doc: Dict, critic: str, expected_pack: str) -> Tuple[Optional[Dict], List[str]]:
    """Check a critic's JSON verdict. The verdict is the STRICTER of the stated
    one and the one implied by the findings (BLOCKING → FAIL, MAJOR/MINOR → WARN)."""
    errs = []
    if not isinstance(doc, dict):
        return None, ["record must be a JSON object"]
    if doc.get("critic") != critic:
        errs.append("critic must be %r" % critic)
    if doc.get("reviewer") != "%s-critic" % critic:
        errs.append("reviewer must be the %s-critic agent, not %r (builder ≠ judge)" % (critic, doc.get("reviewer")))
    if doc.get("pack") != expected_pack:
        errs.append("pack %r is not the current pack %r (stale review; rebuild critics)"
                    % (doc.get("pack"), expected_pack))
    stated = doc.get("verdict")
    if stated not in (PASS, WARN, FAIL):
        errs.append("verdict must be PASS, WARN or FAIL")
    findings = doc.get("findings")
    if not isinstance(findings, list):
        errs.append("findings must be a list")
        findings = []
    for i, x in enumerate(findings):
        if not isinstance(x, dict):
            errs.append("finding %d is not an object" % i)
            continue
        if x.get("severity") not in CRITIC_SEVERITIES:
            errs.append("finding %d: severity must be one of %s" % (i, ", ".join(CRITIC_SEVERITIES)))
        if x.get("frame") is None and x.get("time") is None and not x.get("scene"):
            errs.append("finding %d: needs scene, frame or time" % i)
        for key in ("issue", "evidence", "correction"):
            if not str(x.get(key) or "").strip():
                errs.append("finding %d: %s is required" % (i, key))
    if errs:
        return None, errs
    sev = {x["severity"] for x in findings}
    implied = FAIL if "BLOCKING" in sev else (WARN if sev else PASS)
    order = {PASS: 0, WARN: 1, FAIL: 2}
    verdict = max(stated, implied, key=order.get)
    return {"verdict": verdict, "stated": stated, "findings": findings}, []


def fix_iterations(state: Dict) -> int:
    """Distinct production hashes on which a critic returned FAIL."""
    return len({h["hash"] for h in state["history"]
                if h.get("stage") in ("motion_critic", "design_critic") and h["status"] == FAIL})


# ---------------------------------------------------------------- render gate

def gate_reasons(project: str, phash: str, brief: Dict, require_review: bool) -> List[str]:
    """Everything that blocks a full render right now. Empty list = allowed."""
    state = load_state(project)
    reasons = []
    live = check_build(project, brief)   # assets are outside the hash: always re-check
    for x in live:
        if x["severity"] == prerender.ERROR:
            reasons.append("build: %s %s" % (x["reason"], x.get("property") or x.get("observed") or ""))
    need = ["brief", "spec", "validation"] + (["stills", "motion_critic", "design_critic"]
                                              if require_review else [])
    for stage in PRE_RENDER:
        st = stage_status(state, stage, phash)
        if stage in ("motion_critic", "design_critic") and stage not in need:
            continue  # critics are advisory unless review is required (strict mode)
        if st == FAIL:
            reasons.append("%s: FAIL — %s" % (stage, state["stages"][stage]["summary"]))
        elif stage in need and st not in (PASS, WARN):
            if stage in ("motion_critic", "design_critic") and st == SKIPPED:
                reasons.append("%s: SKIPPED but the policy requires review" % stage)
            elif st != SKIPPED:
                reasons.append("%s: %s for the current project state" % (stage, st))
        elif st == WARN and brief["policy"].get("warnings_block") and stage in need:
            reasons.append("%s: WARN and the policy makes warnings blocking" % stage)
    return reasons


def render(project: str, brief: Dict, ctx: Dict, phash: str, *, override: Optional[str] = None,
           overwrite: bool = False, require_review: Optional[bool] = None) -> Dict:
    req = brief["policy"].get("require_review") if require_review is None else require_review
    reasons = gate_reasons(project, phash, brief, req)
    if reasons and not override:
        return {"status": FAIL, "blocked": True, "reasons": reasons,
                "summary": "render blocked: %d gate(s) failed" % len(reasons)}
    out = os.path.join(project, brief["delivery"]["file"])
    state = load_state(project)
    last = ((state["stages"].get("render") or {}).get("details") or {}).get("sha256")
    if os.path.isfile(out) and not overwrite and _sha(out) != last:
        return {"status": FAIL, "blocked": True, "reasons": ["%s exists and was not produced by this "
                                                             "pipeline; pass --overwrite" % out],
                "summary": "render blocked: refusing to overwrite an existing render"}
    cmd = _npx_hf(project)
    if not cmd:
        return {"status": FAIL, "blocked": True, "reasons": ["npx not found"], "summary": "render unavailable"}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI")}
    t0 = time.monotonic()
    res = subprocess.run(cmd + ["render", os.path.abspath(project), "-q", "high", "-f", str(ctx["fps"]),
                                "-o", os.path.abspath(out)], capture_output=True, text=True, env=env)
    secs = round(time.monotonic() - t0, 1)
    if res.returncode != 0 or not os.path.isfile(out):
        return {"status": FAIL, "blocked": False, "seconds": secs, "reasons": [(res.stderr or res.stdout)[-500:]],
                "summary": "render failed (exit %s)" % res.returncode}
    return {"status": PASS, "blocked": False, "seconds": secs, "output": out, "sha256": _sha(out),
            "override": override, "bypassed": reasons if override else [],
            "summary": "rendered %s in %.1fs%s" % (os.path.relpath(out, project), secs,
                                                   " (OVERRIDE: %s)" % override if override else "")}


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- QA

def _rate(s: str) -> float:
    n, _, d = (s or "0/1").partition("/")
    return float(n) / float(d or 1) if float(d or 1) else 0.0


def qa(path: str, brief: Dict, ctx: Dict) -> List[Dict]:
    """Post-render facts against the brief. Separate from pre-render validation."""
    F = prerender.finding
    if not os.path.isfile(path):
        return [F(prerender.ERROR, "no_output", "render output missing", source="qa", prop=path)]
    try:
        probe = process.probe_media(path)
    except process.ProcessError as exc:
        return [F(prerender.ERROR, "probe_failed", str(exc), source="qa")]
    v = next((s for s in probe["streams"] if s.get("codec_type") == "video"), None)
    if v is None:
        return [F(prerender.ERROR, "no_video_stream", "no video stream", source="qa")]
    f: List[Dict] = []
    fps = ctx["fps"]
    res = "%sx%s" % (v.get("width"), v.get("height"))
    want_res = brief["resolution"]  # the declared format, not the composition's own size
    if res != want_res:
        f.append(F(prerender.ERROR, "resolution", "expected %s" % want_res, source="qa", observed=res))
    rate = _rate(v.get("r_frame_rate"))
    if abs(rate - fps) > 0.01:
        f.append(F(prerender.ERROR, "fps", "expected %s fps" % fps, source="qa", observed=round(rate, 3)))
    dur = float(probe["format"].get("duration") or v.get("duration") or 0)
    if abs(dur - ctx["duration"]) > 1.0 / fps + 0.05:
        f.append(F(prerender.ERROR, "duration", "expected %.3fs" % ctx["duration"], source="qa",
                   observed=round(dur, 3)))
    nb = v.get("nb_frames")
    if nb is not None and abs(int(nb) - ctx["frames"]) > 1:
        f.append(F(prerender.ERROR, "frame_count", "expected %d frames" % ctx["frames"], source="qa",
                   observed=int(nb)))
    codec = brief["delivery"]["codec"]
    if codec and v.get("codec_name") != codec:
        f.append(F(prerender.ERROR, "codec", "expected %s" % codec, source="qa", observed=v.get("codec_name")))
    if v.get("pix_fmt") not in (None, "yuv420p"):
        f.append(F(prerender.WARNING, "pix_fmt", "yuv420p plays everywhere", source="qa", observed=v.get("pix_fmt")))
    audio = [s for s in probe["streams"] if s.get("codec_type") == "audio"]
    if brief["audio"] == "none" and audio:
        f.append(F(prerender.ERROR, "unexpected_audio", "silent project has %d audio stream(s)" % len(audio),
                   source="qa"))
    w, h = pixels.analysis_size(ctx["width"], ctx["height"])
    for label, t, sev in (("first", 0.0, prerender.ERROR), ("last", max(0.0, dur - 1.5 / fps), prerender.WARNING)):
        buf = pixels.gray_frame(path, t, w, h)
        if buf is None:
            f.append(F(prerender.ERROR, "%s_frame_unreadable" % label, "could not decode", source="qa"))
            continue
        st = pixels.frame_stats(buf)
        if st["content_coverage"] < 0.01:
            f.append(F(sev, "%s_frame_empty" % label, "%s frame is empty/near-black" % label, source="qa",
                       frame=0 if label == "first" else ctx["frames"] - 1, observed=st))
    diag = _read_json(os.path.join(os.path.dirname(htmlmodel.__file__), "rules", "defaults.json"))["pixels"]["diagnostics"]
    cov = pixels.coverage_series(path, ctx["width"], ctx["height"], dur, fps=diag["fps"])
    if cov is None:
        f.append(F(prerender.WARNING, "coverage_unavailable", "content coverage not measured", source="qa"))
    else:
        for sp in pixels.empty_spans(cov, diag["fps"], diag["empty_frame_coverage"], skip_before=0.5):
            f.append(F(prerender.WARNING, "empty_frames", "near-empty frames %.2f–%.2fs" % (sp["start"], sp["end"]),
                       source="qa", frame=int(sp["start"] * fps)))
        bounds = [s["start"] / fps for s in ctx["scenes"] if s["start"] > 0]
        for b in pixels.boundary_dips(cov, diag["fps"], bounds, window=diag["boundary_window_seconds"],
                                      ratio=diag["boundary_dip_ratio"]):
            if b["dip"]:
                f.append(F(prerender.WARNING, "boundary_dip", "coverage dips at the %.2fs boundary" % b["boundary"],
                           source="qa", frame=int(b["at"] * fps), observed=b["min_coverage"]))
    return f


def audio_qa(path: str, brief: Dict, ctx: Dict) -> Tuple[str, List[Dict]]:
    """Audio stage. Silent projects are SKIPPED (QA verifies 0 audio streams)."""
    F = prerender.finding
    if brief["audio"] == "none":
        return SKIPPED, [F(prerender.INFO, "silent", "audio: none (QA checks for 0 audio streams)", source="audio")]
    try:
        probe = process.probe_media(path)
    except process.ProcessError as exc:
        return FAIL, [F(prerender.ERROR, "probe_failed", str(exc), source="audio")]
    a = [s for s in probe["streams"] if s.get("codec_type") == "audio"]
    if not a:
        return FAIL, [F(prerender.ERROR, "missing_audio", "brief expects %s, master has no audio stream"
                        % brief["audio"], source="audio")]
    f = []
    adur = float(a[0].get("duration") or probe["format"].get("duration") or 0)
    if abs(adur - ctx["duration"]) > 0.1 + 1.0 / ctx["fps"]:
        f.append(F(prerender.WARNING, "audio_duration", "audio %.3fs vs video %.3fs" % (adur, ctx["duration"]),
                   source="audio"))
    try:
        loud = process.loudness(path)
    except process.ProcessError as exc:
        f.append(F(prerender.WARNING, "loudness_unavailable", str(exc), source="audio"))
        loud = None
    if loud:
        tp = loud["true_peak_dbtp"]
        if tp is not None and tp > 0:
            f.append(F(prerender.ERROR, "clipping", "true peak above 0 dBTP", source="audio", observed=tp))
        elif tp is not None and tp > -1:
            f.append(F(prerender.WARNING, "true_peak", "true peak above −1 dBTP", source="audio", observed=tp))
        target = brief.get("loudness_lufs")
        if target is not None and loud["integrated_lufs"] is not None \
                and abs(loud["integrated_lufs"] - target) > 2:
            f.append(F(prerender.WARNING, "loudness", "target %s LUFS" % target, source="audio",
                       observed=loud["integrated_lufs"]))
        f.append(F(prerender.INFO, "loudness_measured", "integrated %s LUFS, true peak %s dBTP"
                   % (loud["integrated_lufs"], tp), source="audio"))
    f.append(F(prerender.INFO, "sync_not_measured", "audio/visual sync is not measured automatically",
               source="audio"))
    return prerender.summarize(f, brief["policy"].get("warnings_block"))["status"], f


# ---------------------------------------------------------------- report

def report(project: str) -> str:
    state = load_state(project)
    phash = production_hash(project)
    lines = ["PRODUCTION REPORT — %s (hash %s)" % (os.path.basename(os.path.abspath(project)), phash[:12]), ""]
    warnings = blocking = 0
    timing = []
    for key, label in STAGES:
        st = stage_status(state, key, phash)
        e = state["stages"].get(key) or {}
        note = ""
        if e.get("override"):
            note = "  OVERRIDE: %s" % e["override"]
        elif st in (FAIL, SKIPPED, PENDING, "STALE") and e.get("summary"):
            note = "  — %s" % e["summary"]
        lines.append("%s %s%s" % ((label + " ").ljust(20, "."), " " + st, note))
        if e.get("hash") == phash:
            d = e.get("details") or {}
            warnings += d.get("warnings", 0)
            blocking += d.get("errors", 0) if st == FAIL else 0
            if e.get("seconds"):
                timing.append("%s %.1fs" % (key, e["seconds"]))
    v = (state["stages"].get("validation") or {})
    num = (v.get("details") or {}).get("numeric") if v.get("hash") == phash else None
    lines.append("")
    if num:
        t = num.get("trace") or {}
        lines.append("Numeric trace: %s%s" % (num["status"], (" — reason: %s" % num["reason"]) if num.get("reason") else
                     " (%s; %s frames, %s elements, %s tracks kept, %ss)"
                     % ("+".join(num["sources"]), t.get("frames", "-"), t.get("elements", "-"),
                        t.get("tracks_kept", "-"), t.get("seconds", "-"))))
    lines.append("Warnings: %d" % warnings)
    lines.append("Blocking errors: %d" % blocking)
    it = fix_iterations(state)
    if it:
        lines.append("Fix iterations (critic FAIL rounds): %d" % it)
        for h in state["history"]:
            if h.get("stage") in ("motion_critic", "design_critic"):
                issues = "; ".join(x["issue"] for x in (h.get("details") or {}).get("findings", [])[:3])
                lines.append("  %s %s %s %s%s" % (h["at"], h["hash"][:8], h["stage"], h["status"],
                                                  (" — " + issues) if issues else ""))
    overrides = [h for h in state["history"] if h.get("override")]
    for h in overrides:
        bypassed = "; ".join((h.get("details") or {}).get("bypassed") or [])
        lines.append("OVERRIDE %s %s: %s%s" % (h["at"], h["stage"], h["override"],
                                              (" (bypassed: %s)" % bypassed) if bypassed else ""))
    r = state["stages"].get("render") or {}
    if r.get("hash") == phash and (r.get("details") or {}).get("output"):
        out = r["details"]["output"]
        lines += ["", "Output:", out if os.path.relpath(out).startswith("..") else os.path.relpath(out)]
    if timing:
        lines += ["", "Timing: " + ", ".join(timing)]
    text = "\n".join(lines) + "\n"
    os.makedirs(prod_dir(project), exist_ok=True)
    with open(os.path.join(prod_dir(project), "report.md"), "w", encoding="utf-8") as fh:
        fh.write("```\n" + text + "```\n")
    return text
