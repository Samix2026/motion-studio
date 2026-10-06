"""Deterministic parser for a HyperFrames Arabic tech-news composition.

Reads index.html and extracts, without executing anything:
  - composition meta (id, duration, width, height, fps)
  - scenes (.clip sections with data-start / data-duration)
  - audio elements (<audio ... data-start / data-duration / data-volume>)
  - GSAP timeline events (tl.fromTo / tl.to / tl.from / tl.set with positions)
  - scene-grammar motion (MS.* helpers from lib/motion.js) as timeline events
  - CSS class font-size / color and the resolved background
  - per-selector element counts (for stagger end estimation)

Motion state is explicit per scene: "detected" (>=1 parsed event), "none"
(no events and every motion construct in the file was parsed) or "unknown"
(no events but some motion construct could not be parsed confidently). The
parser never silently treats unknown as static: helper-driven scenes that it
cannot fully resolve are reported as unknown so callers do not shorten them
on parser absence alone.

Everything here is measurement from the project's own files; nothing is
invented and nothing is written.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------- selectors

def _count_selector(html: str, selector: str) -> int:
    """Best-effort count of elements a simple selector matches (id/class/tag)."""
    tokens = [t for t in selector.strip().split() if t]
    if not tokens:
        return 1
    last = tokens[-1]
    if last.startswith("#"):
        n = len(re.findall(r'id="%s"' % re.escape(last[1:]), html))
    elif last.startswith("."):
        n = len(re.findall(r'class="[^"]*\b%s\b[^"]*"' % re.escape(last[1:]), html))
    else:
        n = len(re.findall(r"<%s[\s>]" % re.escape(last), html))
    return max(n, 1)


# ---------------------------------------------------------------- css

def _extract_style(html: str) -> str:
    m = re.search(r"<style[^>]*>(.*?)</style>", html, re.DOTALL)
    return m.group(1) if m else ""


def _parse_root_vars(style: str) -> Dict[str, str]:
    m = re.search(r":root\s*\{(.*?)\}", style, re.DOTALL)
    if not m:
        return {}
    out: Dict[str, str] = {}
    for name, val in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1)):
        out[name.strip()] = val.strip()
    return out


def _resolve_value(value: str, root_vars: Dict[str, str]) -> Optional[str]:
    v = value.strip()
    m = re.match(r"var\((--[\w-]+)(?:,[^)]*)?\)", v)
    if m:
        return root_vars.get(m.group(1), "").strip() or None
    return v or None


def _parse_class_style(style: str, cls: str, root_vars: Dict[str, str]) -> Dict[str, object]:
    out: Dict[str, object] = {}
    m = re.search(r"\.%s\b[^{]*\{(.*?)\}" % re.escape(cls), style, re.DOTALL)
    if not m:
        return out
    body = m.group(1)
    fm = re.search(r"font-size\s*:\s*([0-9.]+)px", body)
    if fm:
        out["font_size_px"] = float(fm.group(1))
    cm = re.search(r"(?<!-)color\s*:\s*([^;]+);", body)
    if cm:
        resolved = _resolve_value(cm.group(1), root_vars)
        if resolved and resolved.startswith("#"):
            out["color"] = resolved
    return out


def hex_to_rgb(value: str) -> Optional[tuple]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        return None
    try:
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def relative_luminance(rgb: tuple) -> float:
    def lin(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> Optional[float]:
    f, b = hex_to_rgb(fg), hex_to_rgb(bg)
    if not f or not b:
        return None
    l1, l2 = relative_luminance(f), relative_luminance(b)
    hi, lo = max(l1, l2), min(l1, l2)
    return round((hi + 0.05) / (lo + 0.05), 2)


# ---------------------------------------------------------------- tags

def _tag_attrs(tag: str) -> Dict[str, str]:
    return {k: v for k, v in re.findall(r'([\w:-]+)\s*=\s*"([^"]*)"', tag)}


# ---------------------------------------------------------------- timeline

def _split_top_level(s: str) -> List[str]:
    parts, depth, buf, quote = [], 0, [], None
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in "{[(":
            depth += 1
            buf.append(ch)
        elif ch in "}])":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return parts


_OBJ_NUM = re.compile(r"([\w-]+)\s*:\s*(-?[0-9.]+)")


def _obj_fields(text: str) -> Dict[str, str]:
    return {k: v for k, v in _OBJ_NUM.findall(text)}


@dataclass
class Scene:
    id: str
    index: int
    start: float
    duration: float
    end: float
    text: str = ""
    raw: str = ""
    # data-narration-locked="true": the scene duration is bound to narration /
    # caption timing and must not be shortened below it.
    narration_locked: bool = False


@dataclass
class AudioCue:
    id: str
    src: str
    start: float
    duration: float
    end: float
    volume: Optional[float]
    kind: str  # "music" | "sfx" | "ambient"
    raw: str = ""


@dataclass
class TimelineEvent:
    selector: str
    start: float
    duration: float
    stagger: float
    count: int
    end: float
    is_volume: bool
    raw: str = ""
    # "literal" for tl.* calls; "helper:<path>" for a known lib/motion.js
    # helper; "attribute:push-in" for MS.applyReviewAttributes + data-push-in.
    source: str = "literal"


# Motion-state vocabulary (per scene).
MOTION_DETECTED = "detected"
MOTION_NONE = "none"
MOTION_UNKNOWN = "unknown"


@dataclass
class CompositionModel:
    project_dir: str
    index_path: str
    html: str
    comp_id: str = "main"
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: int = 0
    scenes: List[Scene] = field(default_factory=list)
    audio: List[AudioCue] = field(default_factory=list)
    events: List[TimelineEvent] = field(default_factory=list)
    class_styles: Dict[str, Dict[str, object]] = field(default_factory=dict)
    root_vars: Dict[str, str] = field(default_factory=dict)
    background: str = ""
    # Motion constructs the parser could not resolve confidently (unknown
    # helper path, dynamic/non-literal call, unreadable duration, ...). Empty
    # means every motion construct in the file was parsed.
    unparsed_motion: List[str] = field(default_factory=list)
    # Narration timing attached by the analyzer/reviewer (canonical word timings
    # and caption ranges). Authoritative for narration-locked scene lengths.
    narration_words: List[Dict] = field(default_factory=list)
    captions: List[Dict] = field(default_factory=list)
    # Tail padding required after the last spoken word / caption (seconds).
    narration_tail_padding_s: float = 0.0

    # -- helpers used by the engine/analyzer -----------------------------
    def scene_by_index(self, index: int) -> Optional[Scene]:
        for s in self.scenes:
            if s.index == index:
                return s
        return None

    def scene_containing(self, t: float) -> Optional[Scene]:
        for s in self.scenes:
            if s.start <= t < s.end:
                return s
        return None

    def music(self) -> List[AudioCue]:
        return [a for a in self.audio if a.kind == "music"]

    def sfx(self) -> List[AudioCue]:
        return [a for a in self.audio if a.kind == "sfx"]

    def events_in_scene(self, scene: Scene) -> List[TimelineEvent]:
        return [e for e in self.events if scene.start <= e.start < scene.end]

    @property
    def motion_parse_complete(self) -> bool:
        """True when every motion construct in the file was parsed."""
        return not self.unparsed_motion

    def motion_state(self, scene: Scene) -> str:
        """detected | none | unknown for one scene.

        Unknown is returned when a scene has no parsed motion but the file
        contains motion the parser could not resolve (helper-driven scenes).
        It is never reported as 'none'.
        """
        if self.events_in_scene(scene):
            return MOTION_DETECTED
        return MOTION_NONE if self.motion_parse_complete else MOTION_UNKNOWN

    def is_static_hold_verified(self, scene: Scene) -> bool:
        """Whether the timeline-derived static hold is trustworthy.

        A verified hold requires that every motion construct was parsed, so
        parser absence is real evidence of stillness (not a missed helper).
        An unverified scene must not drive a shortening proposal.
        """
        if self.motion_state(scene) == MOTION_UNKNOWN:
            return False
        return self.motion_parse_complete

    # -- narration lock ---------------------------------------------------
    def narration_ends_ms(self, scene: Scene) -> List[float]:
        """Absolute end times (ms) of spoken words and caption ranges that
        overlap this scene. Word timings/captions are the authoritative
        narration timing."""
        lo, hi = scene.start * 1000.0, scene.end * 1000.0
        ends: List[float] = []
        for w in self.narration_words:
            try:
                s, e = float(w["start_ms"]), float(w["end_ms"])
            except (KeyError, TypeError, ValueError):
                continue
            if s < hi and e > lo:
                ends.append(e)
        for c in self.captions:
            try:
                s, e = float(c["start_ms"]), float(c["end_ms"])
            except (KeyError, TypeError, ValueError):
                continue
            if s < hi and e > lo:
                ends.append(e)
        return ends

    def narration_min_end_ms(self, scene: Scene) -> Optional[float]:
        """Absolute end (ms) the scene must reach: max(narration audio end,
        final spoken word end, final caption end). Falls back to a narration
        audio element that starts inside the scene when no words/captions are
        available. None when narration timing cannot be determined."""
        ends = self.narration_ends_ms(scene)
        if ends:
            return max(ends)
        for a in self.audio:
            hay = (a.id + " " + a.src).lower()
            if ("narration" in hay or "voice" in hay) and scene.start <= a.start < scene.end:
                return a.end * 1000.0
        return None

    def narration_min_duration_s(self, scene: Scene,
                                 tail_padding_s: Optional[float] = None) -> Optional[float]:
        """Minimum scene duration that still covers narration/caption end plus
        the required tail padding. None when narration timing is unavailable."""
        min_end = self.narration_min_end_ms(scene)
        if min_end is None:
            return None
        pad = self.narration_tail_padding_s if tail_padding_s is None else tail_padding_s
        return max(0.0, (min_end + pad * 1000.0 - scene.start * 1000.0) / 1000.0)

    def narration_required_end_s(self, scene: Scene,
                                 tail_padding_s: Optional[float] = None) -> Optional[float]:
        """Absolute end (seconds) a narration-locked scene must reach."""
        min_end = self.narration_min_end_ms(scene)
        if min_end is None:
            return None
        pad = self.narration_tail_padding_s if tail_padding_s is None else tail_padding_s
        return (min_end + pad * 1000.0) / 1000.0


# ---------------------------------------------------------------- motion helpers
#
# lib/motion.js exposes one motion API (MS.*). The literal tl.* parser above
# cannot see it, so scene-grammar motion is parsed here from the helper call
# sites. Each entry maps a helper path to:
#   (target_arg, at_arg, default_duration, default_stagger, duration_arg)
# `duration_arg` is the positional duration for helpers that take one
# (camera.pushIn, shot.zoomToDetail, shot.panBetween); otherwise duration and
# stagger come from the options object after `at`.
_MOTION_HELPERS = {
    "enter.fadeScale":    (1, 2, 0.6, 0.0, None),
    "enter.rtlSlide":     (1, 2, 0.7, 0.0, None),
    "enter.maskReveal":   (1, 2, 0.8, 0.0, None),
    "enter.staggerBuild": (1, 2, 0.5, 0.14, None),
    "enter.lineDraw":     (1, 2, 0.6, 0.0, None),
    "enter.hardCut":      (1, 2, 0.0, 0.0, None),
    "exit.fadeOut":       (1, 2, 0.35, 0.0, None),
    "exit.maskOut":       (1, 2, 0.45, 0.0, None),
    "exit.hardCut":       (1, 2, 0.0, 0.0, None),
    "camera.pushIn":      (1, 2, 0.0, 0.0, 3),
    "shot.cropTo":        (1, 3, 0.0, 0.0, None),
    "shot.zoomToDetail":  (1, 3, 0.0, 0.0, 4),
    "shot.panBetween":    (1, 4, 0.0, 0.0, 5),
    "shot.highlightBox":  (1, 2, 0.45, 0.0, None),
    "shot.spotlight":     (1, 2, 0.5, 0.0, None),
    "shot.calloutLine":   (1, 2, 0.5, 0.0, None),
}

# MS.* members that are utilities or attribute-driven, not timeline motion.
_NON_MOTION_MS = {
    "applyReviewAttributes", "parseRegion", "regionTransform", "shot.place",
}

_MS_CALL = re.compile(r"\bMS\.((?:\w+\.)*\w+)\s*\(")
_MS_DYNAMIC = re.compile(r"\bMS\.(?:\w+\.)*\w+\s*\[|\bMS\s*\[")
_MOTION_SCRIPT = re.compile(r"""<script\b[^>]*\bsrc\s*=\s*["'][^"']*motion\.js["']""")
_NUM = re.compile(r"-?[0-9.]+")


def _iter_ms_calls(script: str):
    """Yield (helper_path, raw_args) for every MS.*(...) call using a
    parenthesis-balanced scan (so nested calls like MS.parseRegion(...) inside
    an argument do not truncate the outer call)."""
    for m in _MS_CALL.finditer(script):
        path = m.group(1)
        i, depth, quote = m.end(), 1, None
        start = i
        while i < len(script) and depth > 0:
            ch = script[i]
            if quote is not None:
                if ch == "\\":
                    i += 2
                    continue
                if ch == quote:
                    quote = None
            elif ch in "\"'`":
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        yield path, script[start:i]


def _is_str_literal(token: str) -> bool:
    token = token.strip()
    return len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'"


def _parse_motion_helpers(script: str, html: str, model: "CompositionModel") -> int:
    """Append timeline events for every resolvable MS.* motion call. Returns
    the number of helper events parsed; unresolved constructs are recorded in
    model.unparsed_motion (never silently ignored)."""
    unparsed = model.unparsed_motion
    parsed = 0
    for path, args_text in _iter_ms_calls(script):
        if path in _NON_MOTION_MS:
            continue
        spec = _MOTION_HELPERS.get(path)
        if spec is None:
            unparsed.append("unrecognized motion helper MS.%s" % path)
            continue
        sel_arg, at_arg, def_dur, def_stag, dur_arg = spec
        args = _split_top_level(args_text)
        if len(args) <= max(sel_arg, at_arg):
            unparsed.append("MS.%s: too few arguments" % path)
            continue
        sel_raw = args[sel_arg].strip()
        if not _is_str_literal(sel_raw):
            unparsed.append("MS.%s: non-literal target" % path)
            continue
        at_raw = args[at_arg].strip()
        if not _NUM.fullmatch(at_raw):
            unparsed.append("MS.%s: non-numeric time" % path)
            continue
        selector = sel_raw.strip("\"'")
        start = float(at_raw)
        duration, stagger = def_dur, def_stag
        bad = False
        if dur_arg is not None:
            if len(args) <= dur_arg or not _NUM.fullmatch(args[dur_arg].strip()):
                unparsed.append("MS.%s: non-numeric duration" % path)
                continue
            duration = float(args[dur_arg].strip())
        else:
            opts_idx = at_arg + 1
            if len(args) > opts_idx and args[opts_idx].strip().startswith("{"):
                opts = args[opts_idx]
                fields = _obj_fields(opts)
                if re.search(r"(?<![\w-])duration\s*:", opts):
                    if "duration" in fields:
                        duration = float(fields["duration"])
                    else:
                        unparsed.append("MS.%s: non-numeric duration option" % path)
                        bad = True
                if re.search(r"(?<![\w-])stagger\s*:", opts):
                    if "stagger" in fields:
                        stagger = float(fields["stagger"])
                    else:
                        unparsed.append("MS.%s: non-numeric stagger option" % path)
                        bad = True
        if bad:
            continue
        count = _count_selector(html, selector)
        end = start + duration + stagger * (count - 1)
        model.events.append(TimelineEvent(
            selector=selector, start=start, duration=duration, stagger=stagger,
            count=count, end=end, is_volume=False,
            raw="MS.%s(%s)" % (path, args_text), source="helper:%s" % path))
        parsed += 1
    return parsed


def _parse_push_in_attributes(script: str, html: str, model: "CompositionModel") -> int:
    """MS.applyReviewAttributes turns [data-push-in] into a camera push-in
    across the element's scene. Parse those deterministically so applied
    review attributes still count as motion. Returns the number of events."""
    if not re.search(r"MS\.applyReviewAttributes\s*\(", script):
        return 0
    added = 0
    spans = []
    for m in re.finditer(r"<section\b[^>]*>", html):
        a = _tag_attrs(m.group(0))
        if "clip" not in a.get("class", ""):
            continue
        start = float(a.get("data-start", 0) or 0)
        dur = float(a.get("data-duration", 0) or 0)
        spans.append((m.start(), start, dur))
    for m in re.finditer(r"<[^>]*\bdata-push-in\s*=\s*\"([^\"]*)\"[^>]*>", html):
        scale = m.group(1).strip()
        if not _NUM.fullmatch(scale):
            model.unparsed_motion.append("data-push-in: non-numeric scale")
            continue
        enclosing = [s for s in spans if s[0] < m.start()]
        if not enclosing:
            model.unparsed_motion.append("data-push-in: no enclosing clip scene")
            continue
        _tag_pos, start, dur = max(enclosing, key=lambda s: s[0])
        if dur <= 0:
            continue
        model.events.append(TimelineEvent(
            selector="#%s" % (_tag_attrs(m.group(0)).get("id", "") or "scene"),
            start=start, duration=dur, stagger=0.0, count=1, end=start + dur,
            is_volume=False, raw=m.group(0), source="attribute:push-in"))
        added += 1
    return added


def parse(project_dir: str) -> CompositionModel:
    index_path = os.path.join(project_dir, "index.html")
    with open(index_path, "r", encoding="utf-8") as fh:
        html = fh.read()
    model = CompositionModel(project_dir=project_dir, index_path=index_path, html=html)

    # composition meta
    root_tag = ""
    for m in re.finditer(r"<div\b[^>]*>", html):
        if "data-composition-id" in m.group(0):
            root_tag = m.group(0)
            break
    attrs = _tag_attrs(root_tag)
    model.comp_id = attrs.get("data-composition-id", "main")
    model.duration = float(attrs.get("data-duration", 0) or 0)
    model.width = int(float(attrs.get("data-width", 0) or 0))
    model.height = int(float(attrs.get("data-height", 0) or 0))
    model.fps = int(float(attrs.get("data-fps", 0) or 0))

    # scenes
    idx = 0
    for m in re.finditer(r"<section\b[^>]*>", html):
        tag = m.group(0)
        a = _tag_attrs(tag)
        if "clip" not in (a.get("class", "")):
            continue
        idx += 1
        start = float(a.get("data-start", 0) or 0)
        dur = float(a.get("data-duration", 0) or 0)
        sid = a.get("id", "scene%d" % idx)
        locked_raw = a.get("data-narration-locked")
        narration_locked = (locked_raw is not None
                            and locked_raw.strip().lower() not in ("false", "0", "no"))
        end_tag = html.find("</section>", m.end())
        inner = html[m.end():end_tag] if end_tag != -1 else ""
        text = re.sub(r"<[^>]+>", " ", inner)
        text = re.sub(r"\s+", " ", text).strip()
        model.scenes.append(Scene(id=sid, index=idx, start=start, duration=dur,
                                  end=start + dur, text=text, raw=tag,
                                  narration_locked=narration_locked))

    # audio
    for m in re.finditer(r"<audio\b[^>]*>", html):
        tag = m.group(0)
        a = _tag_attrs(tag)
        src = a.get("src", "")
        start = float(a.get("data-start", 0) or 0)
        dur = float(a.get("data-duration", 0) or 0)
        vol = a.get("data-volume")
        hay = (a.get("id", "") + " " + src).lower()
        if "music" in hay or "bed" in hay:
            kind = "music"
        elif "ambient" in hay:
            kind = "ambient"
        else:
            kind = "sfx"
        model.audio.append(AudioCue(id=a.get("id", ""), src=src, start=start,
                                    duration=dur, end=start + dur,
                                    volume=float(vol) if vol not in (None, "") else None,
                                    kind=kind, raw=tag))

    # css
    style = _extract_style(html)
    model.root_vars = _parse_root_vars(style)
    for cls in ("sub", "note", "shotcap", "wcap", "src", "headline", "hookline",
                "chip", "chipsm", "step", "wmain"):
        st = _parse_class_style(style, cls, model.root_vars)
        if st:
            model.class_styles[cls] = st
    root_bg = model.root_vars.get("--brand-background")
    model.background = (root_bg if root_bg and root_bg.startswith("#") else "")

    # timeline
    script = html
    consts: Dict[str, str] = {}
    for name, val in re.findall(r"const\s+([A-Za-z_]\w*)\s*=\s*(\{[^}]*\}|\"[^\"]*\"|-?[0-9.]+)\s*;", script):
        consts[name] = val

    def dur_of(token: str) -> tuple:
        token = token.strip()
        if token.startswith("{"):
            f = _obj_fields(token)
            return (float(f.get("duration", 0) or 0),
                    float(f.get("stagger", 0) or 0),
                    "volume:" in token)
        if token in consts and consts[token].startswith("{"):
            f = _obj_fields(consts[token])
            return (float(f.get("duration", 0) or 0),
                    float(f.get("stagger", 0) or 0),
                    "volume:" in token)
        return (0.0, 0.0, False)

    for m in re.finditer(r"tl\.(\w+)\((.*?)\);", script, re.DOTALL):
        fn, body = m.group(1), m.group(2)
        args = _split_top_level(body)
        if len(args) < 2:
            continue
        sel_raw = args[0].strip()
        if not (sel_raw.startswith('"') or sel_raw.startswith("'")):
            continue
        selector = sel_raw.strip("\"'")
        if fn == "fromTo" and len(args) >= 3:
            obj, pos = args[2], (args[3] if len(args) >= 4 else "0")
        elif fn in ("to", "from", "set") and len(args) >= 2:
            obj, pos = args[1], (args[2] if len(args) >= 3 else "0")
        else:
            continue
        pos = pos.strip()
        if not re.fullmatch(r"-?[0-9.]+", pos):
            continue  # `acc` progress lines and non-numeric positions
        start = float(pos)
        dur, stagger, is_vol = dur_of(obj)
        count = _count_selector(html, selector)
        end = start + dur + stagger * (count - 1)
        model.events.append(TimelineEvent(selector=selector, start=start, duration=dur,
                                          stagger=stagger, count=count, end=end,
                                          is_volume=is_vol, raw=m.group(0)))

    # scene-grammar motion (lib/motion.js helpers). Additive: literal parsing
    # above is unchanged. Anything unresolved is recorded, never assumed static.
    helper_events = _parse_motion_helpers(script, html, model)
    helper_events += _parse_push_in_attributes(script, html, model)
    if _MOTION_SCRIPT.search(html) and helper_events == 0:
        model.unparsed_motion.append(
            "lib/motion.js loaded but no resolvable motion helper call was parsed")
    if _MS_DYNAMIC.search(script):
        model.unparsed_motion.append("dynamic MS[...] motion invocation")

    return model
