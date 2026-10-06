"""Proposal simulation engine.

Simulates a whitelisted operation against an in-memory model and returns the
resulting duration, side-effect warnings, and an edit plan. It never writes to
the project and never touches the real timeline.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import htmlmodel, proposal_schema


class SimulationError(ValueError):
    pass


def _audio_by_id(model: htmlmodel.CompositionModel, audio_id: str):
    for a in model.audio:
        if a.id == audio_id:
            return a
    return None


def _event_match(model: htmlmodel.CompositionModel, selector: str, occurrence: int = 0):
    matches = [e for e in model.events if e.selector == selector]
    if occurrence < 0 or occurrence >= len(matches):
        return None
    return matches[occurrence]


_FACTOR_LIMITS = {
    "enlarge_secondary_text": ("--secondary-scale", 1.05, 1.3),
    "increase_media_scale": ("--media-scale", 1.05, 1.25),
}


def _registry() -> Dict:
    from design import grammar  # local import: review stays usable without design
    return grammar.load_registry()


def _scene_inner(model: htmlmodel.CompositionModel, scene) -> str:
    start = model.html.find(scene.raw)
    end = model.html.find("</section>", start)
    return model.html[start:end] if start != -1 and end != -1 else ""


def _layout_edits(model: htmlmodel.CompositionModel, op: str, operation: Dict) -> List[Dict]:
    """Attribute / custom-property edits on one scene-grammar scene. Legacy
    scenes (no data-grammar) are rejected: these are layout-system knobs."""
    scene = model.scene_by_index(int(operation.get("scene", -1)))
    if scene is None:
        raise SimulationError("scene %s not found" % operation.get("scene"))
    attrs = htmlmodel._tag_attrs(scene.raw)
    gid = attrs.get("data-grammar")
    if not gid:
        raise SimulationError("scene %d has no data-grammar; layout operations need a "
                              "scene-grammar composition" % scene.index)
    spec = _registry()["grammars"].get(gid)
    if spec is None:
        raise SimulationError("scene %d: unknown grammar %s" % (scene.index, gid))

    if op == "swap_layout_variant":
        to = operation.get("to")
        if to not in spec["variants"]:
            raise SimulationError("variant %r not in %s" % (to, spec["variants"]))
        if to == attrs.get("data-variant"):
            raise SimulationError("scene %d already uses variant %s" % (scene.index, to))
        return [{"kind": "scene_attr", "scene": scene.index, "attr": "data-variant",
                 "from": attrs.get("data-variant"), "to": to}]
    if op == "reduce_empty_space":
        if attrs.get("data-density") == "tight":
            raise SimulationError("scene %d is already tight" % scene.index)
        return [{"kind": "scene_attr", "scene": scene.index, "attr": "data-density",
                 "from": attrs.get("data-density"), "to": "tight"}]
    if op in _FACTOR_LIMITS:
        prop, lo, hi = _FACTOR_LIMITS[op]
        factor = float(operation.get("factor", 0))
        if not (lo <= factor <= hi):
            raise SimulationError("%s factor must be within %.2f..%.2f" % (op, lo, hi))
        return [{"kind": "scene_style_var", "scene": scene.index, "property": prop,
                 "to": round(factor, 3)}]
    # add_push_in
    if "push_in" not in spec["camera"]:
        raise SimulationError("%s does not allow push_in" % gid)
    target = str(operation.get("target", ""))
    if not target.startswith("#") or len(target) < 2:
        raise SimulationError("add_push_in target must be an element id (#id)")
    inner = _scene_inner(model, scene)
    import re
    tag = re.search(r'<(img|video|figure)\b[^>]*\bid="%s"[^>]*>' % re.escape(target[1:]), inner)
    if not tag:
        raise SimulationError("%s is not an img/video/figure inside scene %d" % (target, scene.index))
    scale = float(operation.get("scale", 1.06))
    if not (1.02 <= scale <= 1.12):
        raise SimulationError("push-in scale must be within 1.02..1.12")
    return [{"kind": "element_attr", "id": target[1:], "attr": "data-push-in",
             "to": "%.2f" % scale}]


def simulate(model: htmlmodel.CompositionModel, operation: Dict) -> Dict:
    op = operation.get("type")
    if op not in proposal_schema.OPERATIONS:
        raise SimulationError("unsupported operation '%s'" % op)

    before = model.duration
    after = before
    warnings: List[str] = []
    edits: List[Dict] = []

    if op == "adjust_scene_duration":
        scene = model.scene_by_index(int(operation.get("scene", -1)))
        if scene is None:
            raise SimulationError("scene %s not found" % operation.get("scene"))
        frm = float(operation.get("from", scene.duration))
        to = float(operation.get("to", 0))
        if to <= 0.2:
            raise SimulationError("target duration must be > 0.2s")
        # Narration lock: a shortening edit must still cover the narration /
        # caption end plus the required tail padding. Lengthening is allowed.
        if scene.narration_locked and to < frm - 1e-6:
            required_end = model.narration_required_end_s(scene)
            if required_end is None:
                raise SimulationError(
                    "scene %d is narration-locked but has no word/caption timing "
                    "to verify the target duration" % scene.index)
            if scene.start + to < required_end - 1e-6:
                raise SimulationError(
                    "scene %d is narration-locked: target %.3fs ends before the "
                    "required narration/caption end + tail padding (%.3fs)."
                    % (scene.index, to, required_end - scene.start))
        # Eligibility: shortening requires verified motion state. When helper
        # motion could not be parsed, the timeline cannot justify a trim; the
        # pixel freeze check is the authoritative evidence in that case.
        if to < frm - 1e-6 and not model.is_static_hold_verified(scene):
            raise SimulationError(
                "scene %d motion state '%s': cannot shorten without verified static "
                "state (motion not fully parsed); pixel freeze evidence stays advisory"
                % (scene.index, model.motion_state(scene)))
        ripple = bool(operation.get("ripple", True))
        delta = round(to - frm, 3)
        if ripple:
            after = round(before + delta, 3)
        else:
            warnings.append("Non-ripple edit leaves a gap or overlap; V1 expects ripple.")
        if after <= 0.2:
            raise SimulationError("resulting composition duration would be <= 0.2s")
        if ripple and model.music():
            latest_music_end = max(a.end for a in model.music()) + delta
            if latest_music_end < after - 0.05:
                warnings.append("Music bed may no longer cover the new timeline.")
        edits.append({"kind": "scene_duration", "scene": scene.index,
                      "from": frm, "to": to, "delta": delta, "ripple": ripple})

    elif op == "trim_static_hold":
        # Distinct from adjust_scene_duration: the target duration is DERIVED
        # from the measured idle tail (last in-scene motion end + a small keep
        # hold). In-scene animation timing is preserved; only the trailing
        # static hold is removed (with the same ripple semantics downstream).
        scene = model.scene_by_index(int(operation.get("scene", -1)))
        if scene is None:
            raise SimulationError("scene %s not found" % operation.get("scene"))
        if scene.narration_locked:
            raise SimulationError(
                "scene %d is narration-locked; trim_static_hold cannot shorten it"
                % scene.index)
        if not model.is_static_hold_verified(scene):
            raise SimulationError(
                "scene %d motion state '%s': no verified static hold to trim"
                % (scene.index, model.motion_state(scene)))
        evs = model.events_in_scene(scene)
        last_end = max([e.end for e in evs], default=scene.start)
        keep = float(operation.get("keep_hold_ms", 300)) / 1000.0
        to = round(max((last_end - scene.start) + keep, 0.4), 3)
        if to >= scene.duration - 0.001:
            raise SimulationError("no measurable static hold to trim in scene %d" % scene.index)
        delta = round(to - scene.duration, 3)
        after = round(before + delta, 3)
        if model.music():
            latest_music_end = max(a.end for a in model.music()) + delta
            if latest_music_end < after - 0.05:
                warnings.append("Music bed may no longer cover the new timeline.")
        edits.append({"kind": "scene_duration", "scene": scene.index,
                      "from": scene.duration, "to": to, "delta": delta, "ripple": True})

    elif op == "shift_sfx":
        cue = _audio_by_id(model, operation.get("audio_id", ""))
        if cue is None:
            raise SimulationError("audio '%s' not found" % operation.get("audio_id"))
        delta = float(operation.get("delta_seconds", 0))
        new_start = round(cue.start + delta, 3)
        if new_start < 0:
            raise SimulationError("shift would move SFX before 0s")
        edits.append({"kind": "audio_start", "audio_id": cue.id,
                      "from": cue.start, "to": new_start, "delta": round(delta, 3)})

    elif op == "adjust_music_ducking":
        if not model.music():
            raise SimulationError("no music element to duck")
        windows = operation.get("windows") or []
        for w in windows:
            at = float(w.get("at", 0))
            dur = float(w.get("duration", 0.5))
            depth = float(w.get("depth", 0.05))
            if depth < 0 or depth > 0.9:
                warnings.append("Duck depth %.2f is outside a safe range." % depth)
            if at < 0 or (at + dur) > after + 0.001:
                warnings.append("Duck window at %.2fs extends outside the timeline." % at)
        edits.append({"kind": "music_ducking", "audio_id": model.music()[0].id,
                      "windows": windows})

    elif op in ("change_text_size", "change_text_contrast"):
        cls = operation.get("class", "")
        if cls not in model.class_styles:
            raise SimulationError("text class '.%s' not found" % cls)
        if op == "change_text_size":
            to = float(operation.get("to", 0))
            if to <= 0:
                raise SimulationError("font size must be > 0")
            edits.append({"kind": "text_size", "class": cls,
                          "from": model.class_styles[cls].get("font_size_px"), "to": to})
        else:
            to = str(operation.get("to", ""))
            if not to.startswith("#"):
                raise SimulationError("contrast target must be a hex color")
            ratio = htmlmodel.contrast_ratio(to, model.background or "#131416")
            if ratio is not None and ratio < 4.5:
                warnings.append("New color still below AA contrast (%.2f:1)." % ratio)
            edits.append({"kind": "text_contrast", "class": cls,
                          "from": model.class_styles[cls].get("color"), "to": to})

    elif op in ("adjust_animation_start", "adjust_animation_duration"):
        selector = operation.get("selector", "")
        ev = _event_match(model, selector, int(operation.get("occurrence", 0)))
        if ev is None:
            raise SimulationError("animation '%s' not found" % selector)
        if op == "adjust_animation_start":
            to = float(operation.get("to", ev.start))
            if to < 0:
                raise SimulationError("animation start cannot be negative")
            edits.append({"kind": "animation_start", "selector": selector,
                          "occurrence": int(operation.get("occurrence", 0)),
                          "from": ev.start, "to": to})
        else:
            to = float(operation.get("to", ev.duration))
            if to <= 0:
                raise SimulationError("animation duration must be > 0")
            edits.append({"kind": "animation_duration", "selector": selector,
                          "occurrence": int(operation.get("occurrence", 0)),
                          "from": ev.duration, "to": to})

    elif op in ("move_caption", "adjust_caption_end"):
        if 'data-role="caption"' not in model.html:
            raise SimulationError("no caption elements in this project")
        edits.append({"kind": "caption", "subt": op, **operation})

    elif op in proposal_schema.VISION_OPERATIONS:
        edits.extend(_layout_edits(model, op, operation))

    elif op == "remove_silence":
        cue = _audio_by_id(model, operation.get("audio_id", ""))
        if cue is None:
            raise SimulationError("audio '%s' not found" % operation.get("audio_id"))
        to_start = float(operation.get("to_start", cue.start))
        to_duration = float(operation.get("to_duration", cue.duration))
        if to_start < 0 or to_duration <= 0:
            raise SimulationError("invalid silence trim")
        edits.append({"kind": "audio_region", "audio_id": cue.id,
                      "from_start": cue.start, "from_duration": cue.duration,
                      "to_start": to_start, "to_duration": to_duration})

    return {
        "ok": True,
        "operation": op,
        "duration_before": round(before, 3),
        "duration_after": round(after, 3),
        "delta": round(after - before, 3),
        "warnings": warnings,
        "edits": edits,
    }
