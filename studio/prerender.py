"""Pre-render validator: cheap checks that run BEFORE an expensive render.

Pure and source-agnostic. Numeric checks take normalized tracks
``{"<element>.<prop>": [[frame, value], ...]}``; they never know whether the
tracks came from ``spec.json`` or from the browser trace (``studio/trace.py``).
Between keyframes a track is linearly interpolated, so a hold is encoded by its
two endpoints and a dense per-frame trace is a valid track as-is.

Findings: ``{"severity": ERROR|WARNING|INFO, "code", "source", "scene", "frame",
"property", "observed", "reason"}``. ERROR blocks a full render; WARNING is
visible but does not block unless the production policy says so.

stdlib only. Reads files; never writes.
"""

from __future__ import annotations

import fnmatch
import math
import os
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ERROR, WARNING, INFO = "ERROR", "WARNING", "INFO"

# Intentional-discontinuity annotations: which checks each kind suppresses and
# its default half-window in frames when only `frame` is given.
ANNOTATIONS = {
    "hard_cut": ({"jump"}, 1),
    "intentional_jump": ({"jump"}, 1),
    "whip": ({"jump", "spike"}, 6),
    "impact": ({"jump", "spike"}, 4),
    "allow_outlier": ({"jump", "spike"}, 1),
}

# Property kinds, by longest matching suffix of the track name.
_KINDS = (
    ("box.x", "position"), ("box.y", "position"), ("box.w", "size"), ("box.h", "size"),
    ("translateX", "position"), ("translateY", "position"), ("x", "position"), ("y", "position"),
    ("scaleX", "scale"), ("scaleY", "scale"), ("scale", "scale"),
    ("rotation", "rotation"), ("rotate", "rotation"), ("rotationX", "rotation"),
    ("rotationY", "rotation"), ("opacity", "opacity"), ("alpha", "opacity"),
    ("width", "size"), ("height", "size"),
)

DEFAULT_THRESHOLDS = {
    # spike: one-frame excursion that returns; jump: one-frame step that stays.
    # Position values are fractions of the stage's shorter edge.
    "position": {"spike": 0.02, "jump": 0.12, "relative": False, "stage": True},
    "size": {"spike": 0.15, "jump": 0.5, "relative": True, "stage": False},
    "scale": {"spike": 0.08, "jump": 0.25, "relative": False, "stage": False},
    "rotation": {"spike": 8.0, "jump": 30.0, "relative": False, "stage": False},
    "opacity": {"spike": 0.3, "jump": 0.9, "relative": False, "stage": False},
    "other": {"spike": 0.25, "jump": 1.0, "relative": True, "stage": False},
}
JUMP_LOCAL_RATIO = 8.0      # a jump must also dwarf the local per-frame motion
INVISIBLE_ALPHA = 0.01


def finding(severity, code, reason, *, source="", scene=None, frame=None,
            prop=None, observed=None) -> Dict:
    return {"severity": severity, "code": code, "source": source, "scene": scene,
            "frame": frame, "property": prop, "observed": observed, "reason": reason}


def split_track(name: str) -> Tuple[str, str]:
    """``"hero.box.x"`` -> ``("hero", "box.x")``; unknown suffix -> last segment."""
    for suffix, _ in sorted(_KINDS, key=lambda k: -len(k[0])):
        if name.endswith("." + suffix):
            return name[: -len(suffix) - 1], suffix
    head, _, tail = name.rpartition(".")
    return head, tail


def prop_kind(name: str) -> str:
    _, prop = split_track(name)
    return dict(_KINDS).get(prop, "other")


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ---------------------------------------------------------------- normalization

def normalize_tracks(raw, frames: int, source: str) -> Tuple[Dict[str, List[List[float]]], List[Dict]]:
    """Validate a ``{name: [[frame, value], ...]}`` mapping.

    Returns the usable tracks and the format findings (malformed, duplicate,
    unsorted, out-of-range frames, NaN/Infinity). A track with any such ERROR
    is excluded from motion checks so one bad value cannot cascade.
    """
    out: Dict[str, List[List[float]]] = {}
    found: List[Dict] = []
    if not isinstance(raw, dict):
        return out, [finding(ERROR, "malformed_tracks", "tracks must be an object", source=source)]
    for name, pts in raw.items():
        bad = []
        if not isinstance(pts, list) or not pts:
            bad.append(finding(ERROR, "malformed_track", "track must be a non-empty list of [frame, value]",
                               source=source, prop=name))
        else:
            prev = None
            for i, p in enumerate(pts):
                if not (isinstance(p, (list, tuple)) and len(p) == 2):
                    bad.append(finding(ERROR, "malformed_keyframe", "keyframe %d is not [frame, value]" % i,
                                       source=source, prop=name, observed=p))
                    continue
                f, v = p
                if not (isinstance(f, int) and not isinstance(f, bool)):
                    bad.append(finding(ERROR, "malformed_keyframe", "frame must be an integer",
                                       source=source, prop=name, observed=f))
                    continue
                if not _finite(v):
                    bad.append(finding(ERROR, "non_finite_value", "value is %s" % v, source=source,
                                       prop=name, frame=f, observed=v))
                if f < 0 or (frames and f >= frames):
                    bad.append(finding(ERROR, "frame_out_of_range",
                                       "frame %d outside 0..%d" % (f, frames - 1), source=source,
                                       prop=name, frame=f))
                if prev is not None and f == prev:
                    bad.append(finding(ERROR, "duplicate_frame", "frame %d defined twice" % f,
                                       source=source, prop=name, frame=f))
                elif prev is not None and f < prev:
                    bad.append(finding(ERROR, "unsorted_keyframes", "frame %d after %d" % (f, prev),
                                       source=source, prop=name, frame=f))
                prev = f
            if not bad and prop_kind(name) == "opacity":
                for f, v in pts:
                    if not -1e-6 <= v <= 1 + 1e-6:
                        bad.append(finding(ERROR, "invalid_value", "opacity outside 0..1", source=source,
                                           prop=name, frame=f, observed=v))
        found.extend(bad)
        if not bad:
            out[name] = [[int(f), float(v)] for f, v in pts]
    return out, found


def compress(dense: Sequence) -> List[List[float]]:
    """Dense per-frame values -> keyframes, dropping interior points of holds.

    Lossless under linear interpolation. Non-numeric samples (NaN/Infinity as
    strings from the browser) are kept as-is so normalization reports them.
    """
    out: List[List[float]] = []
    n = len(dense)
    for f, v in enumerate(dense):
        if v is None:
            continue
        if 0 < f < n - 1 and dense[f - 1] == v and dense[f + 1] == v:
            continue
        if isinstance(v, str):
            v = {"NaN": float("nan"), "Infinity": float("inf"), "-Infinity": float("-inf")}.get(v, v)
        out.append([f, v])
    return out


def densify(track: List[List[float]]) -> Tuple[int, List[float]]:
    """Keyframes -> (first_frame, per-frame values) by linear interpolation."""
    first = track[0][0]
    vals: List[float] = []
    for (f0, v0), (f1, v1) in zip(track, track[1:]):
        for f in range(f0, f1):
            vals.append(v0 + (v1 - v0) * (f - f0) / (f1 - f0))
    vals.append(track[-1][1])
    return first, vals


# ---------------------------------------------------------------- annotations

def resolve_annotations(raw: Iterable[Dict], fps: float) -> Tuple[List[Dict], List[Dict]]:
    """Spec ``discontinuities`` -> [{kind, lo, hi, pattern, suppress}], findings."""
    out, found = [], []
    for i, a in enumerate(raw or []):
        kind = a.get("kind") if isinstance(a, dict) else None
        if kind not in ANNOTATIONS:
            found.append(finding(ERROR, "bad_annotation", "discontinuity %d: unknown kind %r (use %s)"
                                 % (i, kind, ", ".join(sorted(ANNOTATIONS))), source="spec"))
            continue
        suppress, half = ANNOTATIONS[kind]
        if "frames" in a:
            lo, hi = a["frames"]
        elif "times" in a:
            lo, hi = (int(round(t * fps)) for t in a["times"])
        elif "frame" in a or "time" in a:
            f = a["frame"] if "frame" in a else int(round(a["time"] * fps))
            lo, hi = f - half, f + half
        else:
            found.append(finding(ERROR, "bad_annotation", "discontinuity %d (%s) needs frame/frames/time/times"
                                 % (i, kind), source="spec"))
            continue
        pattern = a.get("property") or a.get("track") or "*"
        out.append({"kind": kind, "lo": int(lo), "hi": int(hi), "pattern": pattern,
                    "suppress": suppress, "note": a.get("note")})
    return out, found


def _annotation_for(annotations, name: str, frame: int, check: str) -> Optional[Dict]:
    for a in annotations:
        if check in a["suppress"] and a["lo"] <= frame <= a["hi"] and fnmatch.fnmatchcase(name, a["pattern"]):
            return a
    return None


# ---------------------------------------------------------------- motion checks

def _scene_at(scenes, frame) -> Optional[str]:
    for s in scenes:
        if s["start"] <= frame < s["end"]:
            return s["id"]
    return None


def _thresholds(kind: str, ctx: Dict, value_scale: float) -> Tuple[float, float]:
    t = dict(DEFAULT_THRESHOLDS[kind])
    t.update((ctx.get("thresholds") or {}).get(kind, {}))
    unit = 1.0
    if t["stage"]:
        unit = float(min(ctx.get("width") or 1080, ctx.get("height") or 1080))
    elif t["relative"]:
        unit = max(abs(value_scale), 1e-6)
    return t["spike"] * unit, t["jump"] * unit


def validate_tracks(tracks: Dict[str, List[List[float]]], ctx: Dict, annotations: List[Dict],
                    source: str, alpha: Optional[Dict[str, Tuple[int, List[float]]]] = None) -> List[Dict]:
    """One-frame outliers (ERROR) and unannotated one-frame jumps (WARNING).

    ``ctx``: fps, frames, width, height, scenes [{id, start, end}] (frames),
    optional thresholds. ``alpha``: element -> dense effective opacity; changes
    while an element is invisible on both sides are not visible glitches.
    Jumps on a scene boundary (±1 frame) are implicit hard cuts (INFO).
    """
    found: List[Dict] = []
    scenes = ctx.get("scenes") or []
    boundaries = {b for s in scenes for b in (s["start"], s["end"])}
    alpha = alpha or {}
    for name, track in tracks.items():
        if len(track) < 2:
            continue
        kind = prop_kind(name)
        element, _ = split_track(name)
        first, vals = densify(track)
        spike_t, jump_t = _thresholds(kind, ctx, max(abs(v) for v in vals))
        el_alpha = alpha.get(element)

        def invisible(f):
            if el_alpha is None:
                return False
            a0, av = el_alpha
            return 0 <= f - a0 < len(av) and av[f - a0] <= INVISIBLE_ALPHA

        deltas = [b - a for a, b in zip(vals, vals[1:])]
        flagged_spike = set()
        for i in range(1, len(vals) - 1):
            d1, d2 = deltas[i - 1], deltas[i]
            if d1 * d2 >= 0 or min(abs(d1), abs(d2)) <= spike_t:
                continue
            if abs(vals[i + 1] - vals[i - 1]) >= 0.5 * min(abs(d1), abs(d2)):
                continue
            f = first + i
            if invisible(f - 1) and invisible(f) and invisible(f + 1):
                continue
            flagged_spike.update((i - 1, i))
            obs = "%g → %g → %g" % (_r(vals[i - 1]), _r(vals[i]), _r(vals[i + 1]))
            ann = _annotation_for(annotations, name, f, "spike")
            if ann:
                found.append(finding(INFO, "outlier_annotated", "one-frame outlier accepted by %s annotation"
                                     % ann["kind"], source=source, scene=_scene_at(scenes, f), frame=f,
                                     prop=name, observed=obs))
            else:
                found.append(finding(ERROR, "one_frame_outlier",
                                     "one-frame outlier with no intentional annotation", source=source,
                                     scene=_scene_at(scenes, f), frame=f, prop=name, observed=obs))
        steps = [i for i, d in enumerate(deltas) if abs(d) > jump_t and i not in flagged_spike]
        periodic = _periodic(steps, deltas)
        for i, d in enumerate(deltas):
            if abs(d) <= jump_t or i in flagged_spike:
                continue
            window = [abs(x) for j, x in enumerate(deltas[max(0, i - 5): i + 6], max(0, i - 5)) if j != i]
            local = sorted(window)[len(window) // 2] if window else 0.0
            if abs(d) < JUMP_LOCAL_RATIO * local:
                continue  # part of a fast move, not a one-frame step
            f = first + i + 1
            if invisible(f - 1) and invisible(f):
                continue
            obs = "%g → %g" % (_r(vals[i]), _r(vals[i + 1]))
            ann = _annotation_for(annotations, name, f, "jump")
            near_cut = any(abs(f - b) <= 1 for b in boundaries)
            if ann or near_cut or periodic:
                why = ("%s annotation" % ann["kind"]) if ann else ("scene boundary (implicit hard cut)"
                                                                  if near_cut else "periodic steps (e.g. a blink)")
                found.append(finding(INFO, "jump_accepted", "one-frame jump accepted: %s" % why,
                                     source=source, scene=_scene_at(scenes, f), frame=f, prop=name,
                                     observed=obs))
            else:
                found.append(finding(WARNING, "suspicious_jump",
                                     "one-frame %s jump with no intentional annotation" % kind,
                                     source=source, scene=_scene_at(scenes, f), frame=f, prop=name,
                                     observed=obs))
    return found


def _periodic(steps: List[int], deltas: List[float]) -> bool:
    """>= 3 alternating steps at near-equal spacing (>= 3 frames apart): a
    deliberate stepped pattern such as a caret blink or strobe."""
    if len(steps) < 3:
        return False
    gaps = [b - a for a, b in zip(steps, steps[1:])]
    alternating = all(deltas[a] * deltas[b] < 0 for a, b in zip(steps, steps[1:]))
    return alternating and min(gaps) >= 3 and max(gaps) - min(gaps) <= max(1, 0.1 * min(gaps))


def dedupe_box(findings: List[Dict]) -> List[Dict]:
    """Drop a box.x/box.y finding when the element's own x/y already reports
    the same check at the same frame (the box is derived from it)."""
    own = {(split_track(f["property"])[0], f["frame"], f["code"]) for f in findings
           if f.get("property") and split_track(f["property"])[1] in ("x", "y")}
    return [f for f in findings if not (
        f.get("property") and split_track(f["property"])[1] in ("box.x", "box.y")
        and (split_track(f["property"])[0], f["frame"], f["code"]) in own)]


def _r(v: float) -> float:
    return round(v, 3)


# ---------------------------------------------------------------- structure

def check_structure(ctx: Dict, spec: Optional[Dict]) -> List[Dict]:
    """Frame ranges, scene coverage, spec/composition agreement, review frames."""
    found: List[Dict] = []
    frames, fps = ctx.get("frames") or 0, ctx.get("fps") or 0
    if not (_finite(fps) and fps > 0):
        found.append(finding(ERROR, "invalid_fps", "fps must be positive", source="structure", observed=fps))
    if frames <= 0:
        found.append(finding(ERROR, "invalid_duration", "composition has no frames", source="structure",
                             observed=frames))
        return found
    seen = set()
    for s in ctx.get("scenes") or []:
        if s["id"] in seen:
            found.append(finding(ERROR, "duplicate_scene", "scene id used twice", source="structure",
                                 scene=s["id"]))
        seen.add(s["id"])
        if s["start"] < 0 or s["end"] <= s["start"] or s["start"] >= frames or s["end"] > frames + 1:
            found.append(finding(ERROR, "impossible_frame_range", "scene frames %d..%d in a %d-frame video"
                                 % (s["start"], s["end"], frames), source="structure", scene=s["id"]))
    covered = sorted((max(0, s["start"]), min(frames, s["end"])) for s in ctx.get("scenes") or [])
    cursor = 0
    for lo, hi in covered:
        if lo - cursor > 2:
            found.append(finding(INFO, "uncovered_frames", "frames %d..%d belong to no scene"
                                 % (cursor, lo - 1), source="structure", frame=cursor))
        cursor = max(cursor, hi)
    if covered and frames - cursor > 2:
        found.append(finding(INFO, "uncovered_frames", "frames %d..%d belong to no scene"
                             % (cursor, frames - 1), source="structure", frame=cursor))
    if not spec:
        return found
    comp = {s["id"]: s for s in ctx.get("scenes") or []}
    for s in spec.get("scenes") or []:
        sid = s.get("id")
        lo, hi = s.get("frame_start"), s.get("frame_end")
        if not isinstance(lo, int) or not isinstance(hi, int) or lo < 0 or hi <= lo or hi > frames:
            found.append(finding(ERROR, "impossible_frame_range", "spec scene frames %r..%r (video has %d)"
                                 % (lo, hi, frames), source="spec", scene=sid))
            continue
        if sid not in comp:
            found.append(finding(WARNING, "spec_scene_missing", "spec scene not found in the composition",
                                 source="spec", scene=sid))
        elif abs(comp[sid]["start"] - lo) > 1 or abs(comp[sid]["end"] - hi) > 1:
            found.append(finding(WARNING, "spec_range_mismatch", "spec %d..%d, composition %d..%d"
                                 % (lo, hi, comp[sid]["start"], comp[sid]["end"]), source="spec", scene=sid))
        for f in s.get("review_frames") or []:
            if not isinstance(f, int) or not lo <= f < hi:
                found.append(finding(ERROR, "review_frame_out_of_scene", "review frame outside the scene",
                                     source="spec", scene=sid, frame=f))
    return found


def check_trace_runtime(trace: Dict, ctx: Dict, review_frames: Sequence[int]) -> List[Dict]:
    """Runtime-only facts from a browser trace: seek-order dependence, empty frames."""
    found: List[Dict] = []
    scenes = ctx.get("scenes") or []
    for m in trace.get("reseek_mismatches") or []:
        vis = any(isinstance(a, (int, float)) and a > INVISIBLE_ALPHA for a in (m.get("alpha") or []))
        found.append(finding(ERROR if vis else INFO, "seek_order_dependent",
                             "value depends on seek order (forward vs re-seek)" +
                             ("" if vis else "; element invisible, no visible effect"),
                             source="trace", scene=_scene_at(scenes, m["frame"]), frame=m["frame"],
                             prop=m["track"], observed="%s vs %s" % (m["forward"], m["reseek"])))
    if trace.get("reseek_overflow"):
        found.append(finding(ERROR, "seek_order_dependent", "%d more visible seek-order differences "
                             "(list capped)" % trace["reseek_overflow"], source="trace"))
    if trace.get("reseek_invisible"):
        found.append(finding(INFO, "seek_order_dependent_invisible", "%d seek-order differences on "
                             "invisible elements (no visible effect)" % trace["reseek_invisible"], source="trace"))
    vis = trace.get("stage_visible") or []
    fps = ctx.get("fps") or 30
    early = vis[: int(0.5 * fps) + 1]
    if early and not any(early):
        found.append(finding(ERROR, "empty_opening", "no traced element visible in the first 0.5 s "
                             "(Frame-0 rule)", source="trace", frame=0))
    for f in review_frames:
        if 0 <= f < len(vis) and not vis[f]:
            found.append(finding(ERROR, "empty_review_frame", "no traced element visible on a review frame",
                                 source="trace", scene=_scene_at(scenes, f), frame=f))
    run_start = None
    for f, n in enumerate(list(vis) + [1]):
        if not n and run_start is None:
            run_start = f
        elif n and run_start is not None:
            if f - run_start >= 2 and run_start > int(0.5 * fps):
                found.append(finding(WARNING, "empty_frames", "no traced element visible for frames %d..%d"
                                     % (run_start, f - 1), source="trace",
                                     scene=_scene_at(scenes, run_start), frame=run_start))
            run_start = None
    return found


def check_offstage(tracks: Dict[str, List[List[float]]], ctx: Dict,
                   alpha: Dict[str, Tuple[int, List[float]]]) -> List[Dict]:
    """Elements visible yet never on stage for their whole lifetime (trace boxes).
    One WARNING per scene, listing the elements."""
    by_scene: Dict[str, List[str]] = {}
    w, h = ctx.get("width") or 0, ctx.get("height") or 0
    for element, (a0, av) in alpha.items():
        names = ["%s.box.%s" % (element, p) for p in "xywh"]
        if not all(n in tracks for n in names) or not any(a > INVISIBLE_ALPHA for a in av):
            continue
        (x0, xs), (_, ys), (_, ws), (_, hs) = (densify(tracks[n]) for n in names)
        n = min(len(xs), len(ys), len(ws), len(hs))
        seen_on = False
        shown = 0
        for i in range(n):
            f = x0 + i
            if not 0 <= f - a0 < len(av) or av[f - a0] <= INVISIBLE_ALPHA or ws[i] <= 0 or hs[i] <= 0:
                continue
            shown += 1
            if xs[i] < w and xs[i] + ws[i] > 0 and ys[i] < h and ys[i] + hs[i] > 0:
                seen_on = True
                break
        if shown and not seen_on:
            by_scene.setdefault(element.split(">")[0], []).append(element)
    return [finding(WARNING, "always_offstage", "%d element(s) visible but never inside the stage: %s"
                    % (len(els), ", ".join(els[:8]) + (" …" if len(els) > 8 else "")),
                    source="trace", scene=scene, prop=els[0]) for scene, els in by_scene.items()]


# ---------------------------------------------------------------- determinism

_DETERMINISM = (
    (re.compile(r"\bMath\.random\s*\("), ERROR, "math_random",
     "unseeded Math.random(); use a seeded PRNG"),
    (re.compile(r"\b(Date\.now|performance\.now)\s*\(|\bnew\s+Date\s*\(\s*\)"), ERROR, "clock",
     "render-time clock drives state"),
    (re.compile(r"\brequestAnimationFrame\s*\("), ERROR, "raf", "requestAnimationFrame-driven visual"),
    (re.compile(r"\b(setTimeout|setInterval)\s*\("), WARNING, "timer",
     "timer in composition code; drive visuals from the timeline"),
    (re.compile(r"\brepeat\s*:\s*-1\b"), ERROR, "infinite_repeat", "repeat: -1 (infinite)"),
)
_CSS_TRANSITION = re.compile(r"(?<![-\w])transition(?:-property|-duration)?\s*:\s*(?!\s*(none|0s?)\s*[;}])[^;}]+")
_CSS_INFINITE = re.compile(r"(?<![-\w])animation(?:-iteration-count)?\s*:[^;}]*\binfinite\b")
_ALLOW = "ms:allow-nondeterminism"
_SKIP_FILES = re.compile(r"(\.min\.js$|(^|/)(gsap|three|lottie|anime)[^/]*\.js$)")


def _local_sources(project_dir: str) -> List[str]:
    """index.html plus local script/style files it references (vendored libs skipped)."""
    index = os.path.join(project_dir, "index.html")
    paths = [index] if os.path.isfile(index) else []
    if not paths:
        return paths
    with open(index, encoding="utf-8") as fh:
        html = fh.read()
    for ref in re.findall(r"""<(?:script[^>]*\bsrc|link[^>]*\bhref)\s*=\s*["']([^"']+)["']""", html):
        if re.match(r"^[a-z]+:|^//", ref) or _SKIP_FILES.search(ref):
            continue
        p = os.path.normpath(os.path.join(project_dir, ref))
        if p.startswith(os.path.abspath(project_dir)) or not os.path.isabs(ref):
            if os.path.isfile(p) and p.endswith((".js", ".mjs", ".css")) and p not in paths:
                paths.append(p)
    return paths


def scan_determinism(project_dir: str) -> List[Dict]:
    """Static scan for uncontrolled nondeterminism in composition code.

    A line containing ``ms:allow-nondeterminism`` is reported as INFO (an
    explicit, reviewed exception such as a seeded generator's fallback).
    Finite CSS @keyframes animations are seekable in HyperFrames and allowed.
    """
    found = []
    for path in _local_sources(project_dir):
        rel = os.path.relpath(path, project_dir)
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        for no, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue
            checks = list(_DETERMINISM)
            checks += [(_CSS_TRANSITION, WARNING, "css_transition",
                        "CSS transition is state-triggered, not seekable"),
                       (_CSS_INFINITE, ERROR, "css_infinite_animation", "infinite CSS animation")]
            for rx, sev, code, why in checks:
                if code.startswith("css_") and not (path.endswith(".css") or _in_style(lines, no)):
                    continue
                if rx.search(line):
                    allowed = _ALLOW in line
                    found.append(finding(INFO if allowed else sev, "nondeterminism_" + code,
                                         why + (" (allowed by annotation)" if allowed else ""),
                                         source="static", prop="%s:%d" % (rel, no), observed=stripped[:120]))
    return found


def _in_style(lines: List[str], no: int) -> bool:
    """True when line ``no`` (1-based) sits inside a <style> block or a style attribute."""
    if "style=" in lines[no - 1]:
        return True
    for line in reversed(lines[: no - 1]):
        if "</style>" in line:
            return False
        if "<style" in line:
            return True
    return False


# ---------------------------------------------------------------- summary

def summarize(findings: List[Dict], warnings_block: bool = False) -> Dict:
    counts = {ERROR: 0, WARNING: 0, INFO: 0}
    for f in findings:
        counts[f["severity"]] += 1
    blocking = counts[ERROR] + (counts[WARNING] if warnings_block else 0)
    status = "FAIL" if blocking else ("WARN" if counts[WARNING] else "PASS")
    return {"status": status, "errors": counts[ERROR], "warnings": counts[WARNING],
            "info": counts[INFO], "blocking": blocking}


def format_finding(f: Dict) -> str:
    parts = [f["severity"]]
    for key, label in (("scene", "scene"), ("frame", "frame"), ("property", "property"),
                       ("observed", "change")):
        if f.get(key) is not None:
            parts.append("%s: %s" % (label, f[key]))
    parts.append("reason: %s [%s/%s]" % (f["reason"], f["source"], f["code"]))
    return "\n  ".join(parts)
