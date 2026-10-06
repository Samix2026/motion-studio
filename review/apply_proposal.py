"""Apply approved proposals to a NEW project version.

Guarantees:
  - the source project is never modified
  - an existing published render is never overwritten
  - no new directory overwrites an existing one
  - edits are deterministic, whitelisted text transforms only
  - the edited composition is re-parsed and must match the simulated duration
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional

from . import htmlmodel, proposal_engine, revision


class StaleRevisionError(Exception):
    pass


class ApplyError(Exception):
    pass


# ---------------------------------------------------------------- formatting

def _fmt(x: float) -> str:
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return ("%.3f" % x).rstrip("0").rstrip(".")


def _set_attr(tag: str, attr: str, value: str) -> str:
    if re.search(r'\b%s="[^"]*"' % attr, tag):
        return re.sub(r'\b%s="[^"]*"' % attr, '%s="%s"' % (attr, value), tag, count=1)
    if tag.endswith("/>"):
        return tag[:-2].rstrip() + ' %s="%s" />' % (attr, value)
    return tag[:-1].rstrip() + ' %s="%s">' % (attr, value)


def _set_style_var(tag: str, prop: str, value: str) -> str:
    m = re.search(r'\bstyle="([^"]*)"', tag)
    style = m.group(1) if m else ""
    if re.search(r"%s\s*:" % re.escape(prop), style):
        style = re.sub(r"%s\s*:\s*[^;]*" % re.escape(prop), "%s: %s" % (prop, value), style, count=1)
    else:
        style = (style.rstrip().rstrip(";") + "; " if style.strip() else "") + "%s: %s" % (prop, value)
    return _set_attr(tag, "style", style)


def _apply_layout_edit(text: str, model, edit: Dict) -> str:
    if edit["kind"] == "element_attr":
        m = re.search(r'<[a-zA-Z][\w-]*\b[^>]*\bid="%s"[^>]*>' % re.escape(edit["id"]), text)
        if not m:
            raise ApplyError("element #%s not found" % edit["id"])
        return text.replace(m.group(0), _set_attr(m.group(0), edit["attr"], edit["to"]), 1)
    scene = model.scene_by_index(edit["scene"])
    tag = _find_section_tag(text, scene.id)
    if tag is None:
        raise ApplyError("scene tag %s not found" % scene.id)
    if edit["kind"] == "scene_attr":
        return text.replace(tag, _set_attr(tag, edit["attr"], edit["to"]), 1)
    return text.replace(tag, _set_style_var(tag, edit["property"], _fmt(edit["to"])), 1)


def _find_section_tag(text: str, scene_id: str) -> Optional[str]:
    m = re.search(r'<section\b[^>]*\bid="%s"[^>]*>' % re.escape(scene_id), text)
    return m.group(0) if m else None


def _find_audio_tag(text: str, audio_id: str) -> Optional[str]:
    m = re.search(r'<audio\b[^>]*\bid="%s"[^>]*>' % re.escape(audio_id), text)
    return m.group(0) if m else None


def _find_root_tag(text: str) -> Optional[str]:
    for m in re.finditer(r"<div\b[^>]*>", text):
        if "data-composition-id" in m.group(0):
            return m.group(0)
    return None


def _shift_trailing_position(line: str, delta: float) -> str:
    m = re.search(r",\s*(-?[0-9.]+)\s*\);\s*$", line)
    if not m:
        return line
    new = float(m.group(1)) + delta
    return line[:m.start(1)] + _fmt(new) + line[m.end(1):]


def _update_scenes_array(text: str, scene_index: int, new_value: float) -> str:
    def repl(m):
        vals = [v.strip() for v in m.group(1).split(",") if v.strip()]
        if 0 < scene_index <= len(vals):
            vals[scene_index - 1] = _fmt(new_value)
        return "const scenes = [%s];" % ", ".join(vals)
    return re.sub(r"const scenes = \[(.*?)\];", repl, text, count=1, flags=re.S)


# ---------------------------------------------------------------- model mutation

def _mutate_one(model: htmlmodel.CompositionModel, e: Dict) -> None:
    k = e["kind"]
    if k == "scene_duration":
        sc = model.scene_by_index(e["scene"])
        delta = e["delta"]
        sc.duration = e["to"]
        sc.end = sc.start + sc.duration
        if e["ripple"] and delta:
            for s in model.scenes:
                if s.index > sc.index:
                    s.start = round(s.start + delta, 3)
                    s.end = round(s.start + s.duration, 3)
            for a in model.audio:
                if a.start >= sc.end - delta - 1e-9:
                    a.start = round(a.start + delta, 3)
                    a.end = round(a.start + a.duration, 3)
            for ev in model.events:
                if ev.start >= sc.end - delta - 1e-9:
                    ev.start = round(ev.start + delta, 3)
                    ev.end = round(ev.start + ev.duration, 3)
            model.duration = round(model.duration + delta, 3)
    elif k == "audio_start":
        for a in model.audio:
            if a.id == e["audio_id"]:
                a.start = e["to"]
                a.end = round(a.start + a.duration, 3)
    elif k == "audio_region":
        for a in model.audio:
            if a.id == e["audio_id"]:
                a.start = e["to_start"]
                a.duration = e["to_duration"]
                a.end = round(a.start + a.duration, 3)
    elif k == "music_ducking":
        model.events.append(htmlmodel.TimelineEvent(
            selector="#%s" % e["audio_id"], start=0.0, duration=0.0,
            stagger=0.0, count=1, end=0.0, is_volume=True, raw="<ducking>"))
    elif k == "text_size":
        if e["class"] in model.class_styles:
            model.class_styles[e["class"]]["font_size_px"] = e["to"]
    elif k == "text_contrast":
        if e["class"] in model.class_styles:
            model.class_styles[e["class"]]["color"] = e["to"]


def _mutate(model: htmlmodel.CompositionModel, edits: List[Dict]) -> None:
    for e in edits:
        _mutate_one(model, e)


# ---------------------------------------------------------------- text edits

def _apply_text_size(text: str, edit: Dict) -> str:
    pattern = re.compile(r"(\.%s\b[^{]*\{)(.*?)(\})" % re.escape(edit["class"]), re.S)

    def repl(m):
        body = re.sub(r"font-size\s*:\s*[0-9.]+px",
                      "font-size: %spx" % _fmt(edit["to"]), m.group(2), count=1)
        return m.group(1) + body + m.group(3)
    new, cnt = pattern.subn(repl, text, count=1)
    if cnt == 0:
        raise ApplyError("could not edit font-size for .%s" % edit["class"])
    return new


def _apply_text_contrast(text: str, edit: Dict) -> str:
    pattern = re.compile(r"(\.%s\b[^{]*\{)(.*?)(\})" % re.escape(edit["class"]), re.S)

    def repl(m):
        body = re.sub(r"(?<![-\w])color\s*:\s*[^;]+;",
                      "color: %s;" % edit["to"], m.group(2), count=1)
        return m.group(1) + body + m.group(3)
    new, cnt = pattern.subn(repl, text, count=1)
    if cnt == 0:
        raise ApplyError("could not edit color for .%s" % edit["class"])
    return new


def _apply_line_edit(text: str, selector: str, occurrence: int, kind: str, to: float) -> str:
    lines = text.split("\n")
    seen = 0
    for i, ln in enumerate(lines):
        if re.search(r"\btl\.\w+\(", ln) and ('"%s"' % selector) in ln:
            if seen == occurrence:
                if kind == "animation_start":
                    new = _shift_trailing_position(ln, to - float(re.search(r",\s*(-?[0-9.]+)\s*\);\s*$", ln).group(1)))
                else:
                    new = re.sub(r"duration:\s*[0-9.]+", "duration: %s" % _fmt(to), ln, count=1)
                lines[i] = new
                return "\n".join(lines)
            seen += 1
    raise ApplyError("animation line not found: %s[%d]" % (selector, occurrence))


def _apply_music_ducking(text: str, model, edit: Dict) -> str:
    """Remove existing music volume tweens and write a fresh automation block."""
    music_id = edit["audio_id"]
    base = 0.10
    m = re.search(r'#%s"[^;\n]*volume:\s*([0-9.]+)' % re.escape(music_id), text)
    if m:
        base = float(m.group(1))
    lines = text.split("\n")
    kept = [ln for ln in lines
            if not (re.search(r"\btl\.\w+\(", ln) and ('#%s"' % music_id) in ln
                    and "volume:" in ln)]
    block = ['tl.fromTo("#%s", { volume: %s }, { volume: %s, duration: 0.01, ease: "none" }, 0);'
             % (music_id, _fmt(base), _fmt(base))]
    for w in edit["windows"]:
        at = float(w["at"])
        depth = float(w["depth"])
        dur = float(w["duration"])
        block.append('tl.to("#%s", { volume: %s, duration: 0.5, ease: "power2.out" }, %s);'
                     % (music_id, _fmt(depth), _fmt(at)))
        block.append('tl.to("#%s", { volume: %s, duration: 0.8, ease: "power2.in" }, %s);'
                     % (music_id, _fmt(base), _fmt(at + dur)))
    out = []
    inserted = False
    for ln in kept:
        if not inserted and re.search(r"const scenes =", ln):
            out.extend(block)
            inserted = True
        out.append(ln)
    if not inserted:
        out.extend(block)
    return "\n".join(out)


def _apply_scene_duration(text: str, model, edit: Dict) -> str:
    scene = model.scene_by_index(edit["scene"])
    tag = _find_section_tag(text, scene.id)
    if tag is None:
        raise ApplyError("scene tag %s not found" % scene.id)
    text = text.replace(tag, _set_attr(tag, "data-duration", _fmt(edit["to"])), 1)
    delta = edit["delta"]
    if edit["ripple"] and delta:
        for s in model.scenes:
            if s.index > scene.index:
                t2 = _find_section_tag(text, s.id)
                if t2 is None:
                    raise ApplyError("scene tag %s not found" % s.id)
                text = text.replace(t2, _set_attr(t2, "data-start", _fmt(s.start + delta)), 1)
        for a in model.audio:
            if a.start >= scene.end - 1e-9:
                t2 = _find_audio_tag(text, a.id)
                if t2 is None:
                    raise ApplyError("audio tag %s not found" % a.id)
                text = text.replace(t2, _set_attr(t2, "data-start", _fmt(a.start + delta)), 1)
        out = []
        for ln in text.split("\n"):
            if re.search(r"\btl\.\w+\(", ln):
                m = re.search(r",\s*(-?[0-9.]+)\s*\);\s*$", ln)
                if m and float(m.group(1)) >= scene.end - 1e-9:
                    ln = _shift_trailing_position(ln, delta)
            out.append(ln)
        text = "\n".join(out)
        root = _find_root_tag(text)
        text = text.replace(root, _set_attr(root, "data-duration", _fmt(model.duration + delta)), 1)
    return _update_scenes_array(text, scene.index, edit["to"])


def _apply_audio_region(text: str, model, edit: Dict) -> str:
    tag = _find_audio_tag(text, edit["audio_id"])
    if tag is None:
        raise ApplyError("audio tag %s not found" % edit["audio_id"])
    new = _set_attr(tag, "data-start", _fmt(edit["to_start"]))
    new = _set_attr(new, "data-duration", _fmt(edit["to_duration"]))
    return text.replace(tag, new, 1)


def _apply_audio_start(text: str, model, edit: Dict) -> str:
    tag = _find_audio_tag(text, edit["audio_id"])
    if tag is None:
        raise ApplyError("audio tag %s not found" % edit["audio_id"])
    return text.replace(tag, _set_attr(tag, "data-start", _fmt(edit["to"])), 1)


# ---------------------------------------------------------------- main

def _run_guard(new_dir: str) -> None:
    guard = os.path.join(new_dir, "tools", "check-tashkeel.py")
    if os.path.isfile(guard):
        res = subprocess.run(["python3", guard, new_dir], capture_output=True, text=True)
        if res.returncode != 0:
            raise ApplyError("no-tashkeel guard failed on the new version:\n%s"
                             % (res.stdout + res.stderr))


def _apply_edit(text: str, model, e: Dict) -> str:
    k = e["kind"]
    if k == "scene_duration":
        return _apply_scene_duration(text, model, e)
    if k == "audio_start":
        return _apply_audio_start(text, model, e)
    if k == "audio_region":
        return _apply_audio_region(text, model, e)
    if k == "music_ducking":
        return _apply_music_ducking(text, model, e)
    if k == "text_size":
        return _apply_text_size(text, e)
    if k == "text_contrast":
        return _apply_text_contrast(text, e)
    if k in ("animation_start", "animation_duration"):
        return _apply_line_edit(text, e["selector"], e["occurrence"], k, e["to"])
    if k in ("scene_attr", "scene_style_var", "element_attr"):
        return _apply_layout_edit(text, model, e)
    raise ApplyError("unsupported edit kind '%s'" % k)


def apply_approved(project_dir: str, proposals: List[Dict], approved_ids: List[str],
                   dry_run: bool = False) -> Dict:
    selected = [p for p in proposals if p["id"] in approved_ids]
    if not selected:
        return {"applied": [], "new_dir": None, "message": "no approved proposals"}

    # revision lock
    for p in selected:
        if revision.is_stale(p, project_dir):
            raise StaleRevisionError(
                "proposal %s targets revision %s but the project has changed"
                % (p["id"], p.get("project_revision")))

    model = htmlmodel.parse(project_dir)
    all_edits: List[Dict] = []
    plan: List[Dict] = []
    sims: List[Dict] = []
    for p in selected:
        sim = proposal_engine.simulate(model, p["operation"])
        sims.append(sim)
        all_edits.extend(sim["edits"])
        plan.append({"proposal": p["id"], "operation": p["operation"],
                     "edits": sim["edits"], "warnings": sim["warnings"]})
        _mutate(model, sim["edits"])
    expected_duration = model.duration

    if dry_run:
        return {"applied": [p["id"] for p in selected], "new_dir": None,
                "dry_run": True, "expected_duration": expected_duration,
                "plan": plan}

    parent_state = revision.get_or_init_state(project_dir)
    new_revision = int(parent_state["revision"]) + 1
    slug = revision.slug_for(project_dir)
    new_dir = os.path.join(os.path.dirname(os.path.abspath(project_dir)),
                           "%s-rev%d" % (slug, new_revision))
    if os.path.abspath(new_dir) == os.path.abspath(project_dir):
        raise ApplyError("refusing to write into the source project")
    if os.path.exists(new_dir):
        raise ApplyError("target version already exists: %s" % new_dir)

    shutil.copytree(project_dir, new_dir,
                    ignore=shutil.ignore_patterns("renders", "snapshots", ".DS_Store"))
    try:
        with open(os.path.join(new_dir, "index.html"), encoding="utf-8") as fh:
            text = fh.read()
        walk_model = htmlmodel.parse(project_dir)  # evolves in lockstep with text
        for sim in sims:
            for e in sim["edits"]:
                text = _apply_edit(text, walk_model, e)
                _mutate_one(walk_model, e)
        with open(os.path.join(new_dir, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(text)

        # verify the edited composition matches the simulation
        applied_model = htmlmodel.parse(new_dir)
        if abs(applied_model.duration - expected_duration) > 0.05:
            raise ApplyError("post-apply duration %.3f != simulated %.3f"
                             % (applied_model.duration, expected_duration))
        _run_guard(new_dir)
    except Exception:
        shutil.rmtree(new_dir, ignore_errors=True)
        raise

    # state: new revision + audit on the parent
    revision.save_state(revision.state_key(new_dir), {
        "slug": revision.slug_for(new_dir),
        "state_key": revision.state_key(new_dir),
        "project_dir": os.path.abspath(new_dir),
        "revision": new_revision,
        "content_hash": revision.content_hash(new_dir),
        "history": [],
        "derived_from": slug,
    })
    revision.record_audit(project_dir, {
        "action": "apply",
        "applied_proposals": [p["id"] for p in selected],
        "new_dir": os.path.basename(new_dir),
        "new_revision": new_revision,
        "expected_duration": expected_duration,
        "note": "source project untouched; new version carries no render (render it explicitly)",
    })

    return {"applied": [p["id"] for p in selected], "new_dir": new_dir,
            "new_revision": new_revision, "expected_duration": expected_duration,
            "plan": plan}
