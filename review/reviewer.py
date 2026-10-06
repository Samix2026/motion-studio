"""Deterministic reviewer.

Turns measured findings into structured proposals. It interprets the
analyzer's measurements; it never re-measures and never invents data, and it
always separates MEASURED FACT from AI JUDGMENT.
"""

from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Tuple

from . import analyzer, htmlmodel, inputs as review_inputs, proposal_engine

_DUCK_DEPTH = 0.05
_DUCK_PAD = 0.4
_DUCK_LEN = 0.9


def _basis(facts: List[str], judgment: str) -> Dict:
    return {"measured_facts": facts, "judgment": judgment}


def review(project_dir: str, report: Dict, rules: Dict = None,
           inputs: Optional[review_inputs.ReviewInputs] = None) -> Tuple[List[Dict], List[str]]:
    rules = rules or analyzer.load_rules()
    model = htmlmodel.parse(project_dir)
    # Narration timing is authoritative for narration-locked scene lengths.
    if inputs is not None and inputs.explicit:
        if inputs.project_dir != os.path.abspath(project_dir):
            raise review_inputs.ReviewInputError(
                "ReviewInputs project context does not match the reviewer project_dir")
        timings_doc, _tp, _te = inputs.load_timings()
        captions, _cp = inputs.load_captions()
        model.narration_words = (timings_doc or {}).get("words", [])
        model.captions = captions or []
    else:
        analyzer.narration_for(project_dir, model)
    model.narration_tail_padding_s = float(
        rules["timing"].get("narration_tail_padding_seconds", 0.0))
    findings = report.get("findings", [])
    revision_no = int(report.get("revision", 1))
    project_hash = report.get("content_hash", "")
    review_fingerprint = report.get("review_fingerprint")
    review_fingerprint_version = report.get("review_fingerprint_version")
    review_descriptor = report.get("review_inputs")
    proposals: List[Dict] = []
    notes: List[str] = []

    def emit(finding: Dict, title: str, rationale: str, operation: Dict,
             basis: Dict) -> None:
        try:
            sim = proposal_engine.simulate(model, operation)
        except proposal_engine.SimulationError as exc:
            notes.append("No proposal for %s: %s" % (finding["id"], exc))
            return
        proposals.append({
            "id": "proposal-%03d" % (len(proposals) + 1),
            "project_revision": revision_no,
            "project_hash": project_hash,
            "review_fingerprint": review_fingerprint,
            "review_fingerprint_version": review_fingerprint_version,
            "review_inputs": review_descriptor,
            "finding_id": finding["id"],
            "scene": finding.get("scene"),
            "title": title,
            "rationale": rationale,
            "operation": operation,
            "duration_before": sim["duration_before"],
            "duration_after": sim["duration_after"],
            "warnings": sim["warnings"],
            "confidence": finding["confidence"],
            "status": "awaiting_review",
            "basis": basis,
        })

    for f in findings:
        cat = f["category"]
        val = f["evidence"]["measured_value"]

        if cat == "scene_pacing" and "static" in f["description"].lower():
            scene = model.scene_by_index(int(f["scene"])) if f["scene"] is not None else None
            if scene is None:
                continue
            # Narration lock: the hold is reading time bound to the spoken
            # words / captions. It must never be shortened, so no timeline
            # static-hold proposal is emitted (pixel freeze findings remain
            # valid measurements, but never drive a destructive trim here).
            if scene.narration_locked:
                notes.append(
                    "No proposal for %s: scene %d is narration-locked; the %.2fs hold "
                    "is reading time bound to narration/caption timing."
                    % (f["id"], scene.index, float(val)))
                continue
            # Eligibility: a static hold may only be shortened when the motion
            # state is verified. If helper-driven motion could not be parsed,
            # parser absence is not evidence of stillness, so no proposal is
            # emitted (pixel freeze findings remain the authoritative fallback).
            if not model.is_static_hold_verified(scene):
                notes.append(
                    "No proposal for %s: scene %d motion state '%s'; timeline static "
                    "hold not verified, not shortening on parser absence."
                    % (f["id"], scene.index, model.motion_state(scene)))
                continue
            target = float(rules["timing"]["target_static_hold_seconds"])
            to = round(max(scene.duration - (float(val) - target), 0.4), 3)
            if to >= scene.duration:
                continue
            emit(f, "Tighten scene %d" % scene.index,
                 "The final state stays static for %.2fs; trim the hold toward %.2fs."
                 % (float(val), target),
                 {"type": "adjust_scene_duration", "scene": scene.index,
                  "from": scene.duration, "to": to, "ripple": True},
                 _basis(["static hold = %.2fs (timeline)" % float(val),
                         "scene %d duration = %.2fs" % (scene.index, scene.duration)],
                        "trim %.2fs to a ~%.1fs hold" % (scene.duration - to, target)))

        elif cat == "sfx_timing":
            offset = float(val)
            audio_id = None
            for token in f["description"].split("'"):
                if token.startswith("au-"):
                    audio_id = token
                    break
            if audio_id is None:
                # fall back: the SFX whose offset matches
                for cue in model.sfx():
                    nearest = min(model.events, key=lambda e: abs(e.start - cue.start))
                    if abs((cue.start - nearest.start) - offset) < 0.001:
                        audio_id = cue.id
                        break
            if audio_id is None:
                continue
            emit(f, "Align SFX '%s' with the visible event" % audio_id,
                 "Measured offset %.0fms; shift the cue to land on the event." % (offset * 1000),
                 {"type": "shift_sfx", "audio_id": audio_id, "delta_seconds": round(-offset, 3)},
                 _basis(["offset = %.0fms (audio vs timeline)" % (offset * 1000)],
                        "shift the SFX by %.0fms to zero the offset" % (-offset * 1000)))

        elif cat == "music_silence_gaps" and "ducking" in f["description"].lower():
            windows = []
            for cue in model.sfx():
                at = max(0.0, round(cue.start - _DUCK_PAD, 2))
                windows.append({"at": at, "duration": _DUCK_LEN, "depth": _DUCK_DEPTH})
            if not windows:
                continue
            emit(f, "Duck the music under cues",
                 "No music ducking found; add gentle ducks at the %d SFX cues." % len(windows),
                 {"type": "adjust_music_ducking", "windows": windows},
                 _basis(["SFX cues = %d (timeline)" % len(windows)],
                        "duck to %.2f for %.1fs around each cue" % (_DUCK_DEPTH, _DUCK_LEN)))

        elif cat == "text_readability" and f["evidence"]["unit"] == "px":
            cls = _class_from_description(f["description"])
            if not cls:
                continue
            to = max(rules["readability"]["min_secondary_font_px"], float(val) + 4.0)
            emit(f, "Increase .%s text size" % cls,
                 "Measured %.0fpx; raise to %.0fpx for readability." % (float(val), to),
                 {"type": "change_text_size", "class": cls, "from": float(val), "to": to},
                 _basis(["font-size .%s = %.0fpx (css)" % (cls, float(val))],
                        "raise to %.0fpx, preserving hierarchy" % to))

        elif cat == "mobile_readability":
            ev = f["evidence"]
            cls = ev.get("class")
            current = (model.class_styles.get(cls or "") or {}).get("font_size_px")
            if current is None:
                continue  # var()-based sizes are layout-system knobs, not px edits
            if any(p["operation"].get("type") == "change_text_size"
                   and p["operation"].get("class") == cls for p in proposals):
                continue
            width = model.width or report.get("composition", {}).get("width") or 0
            if not width:
                continue
            to = float(math.ceil(float(ev["threshold"]) * width / float(ev["phone_viewport_css_px"])))
            if to <= current:
                continue
            emit(f, "Enlarge .%s for phone viewing" % cls,
                 "Renders at %.1fpx on a phone; raise to %.0fpx." % (float(val), to),
                 {"type": "change_text_size", "class": cls, "from": current, "to": to},
                 _basis(["phone size .%s = %.1fpx (css*phone-scale)" % (cls, float(val))],
                        "raise to %.0fpx to reach %spx at phone scale" % (to, ev["threshold"])))

        elif cat == "text_readability" and f["evidence"]["unit"] == "ratio":
            cls = _class_from_description(f["description"])
            if not cls:
                continue
            emit(f, "Improve .%s text contrast" % cls,
                 "Measured %.2f:1; raise toward AA with a brighter secondary tone." % float(val),
                 {"type": "change_text_contrast", "class": cls, "to": "#c9c9c9"},
                 _basis(["contrast .%s = %.2f:1 (css)" % (cls, float(val))],
                        "use #c9c9c9 for secondary text"))

    return proposals, notes


def _class_from_description(description: str):
    for token in description.split():
        if token.startswith("."):
            name = token.strip(".,;:()").lstrip(".")
            if name and (name.replace("_", "a").isalnum()):
                return name
    return None
