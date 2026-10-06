"""Strict schemas for findings and proposals.

Validation is intentionally dependency-free (stdlib) and conservative: it
rejects malformed objects and any operation type outside the whitelist.

Every finding has a basis:
  MEASURED_FACT — deterministic measurement with a numeric measured_value.
  AI_JUDGMENT   — multimodal visual review; no measured_value, never a hard fail,
                  and it may only propose VISION_OPERATIONS.
"""

from __future__ import annotations

from typing import Dict, List

MEASURED_FACT = "MEASURED_FACT"
AI_JUDGMENT = "AI_JUDGMENT"

CATEGORIES = {
    "scene_pacing",
    "text_readability",
    "caption_audio_sync",
    "sfx_timing",
    "music_silence_gaps",
    # rendered-output checks (deterministic)
    "frame_zero",
    "rendered_freeze",
    "shot_diversity",
    "text_density",
    "mobile_readability",
    # advisory rendered diagnostics (deterministic, never hard fail)
    "long_hold",
    "empty_frame",
    "boundary_dip",
    # multimodal review (AI judgment)
    "visual_judgment",
}

JUDGMENT_CATEGORIES = {"visual_judgment"}

VISION_DIMENSIONS = (
    "hook_strength",
    "visual_hierarchy",
    "composition_balance",
    "empty_space",
    "visual_repetition",
    "screenshot_treatment",
    "brand_consistency",
    "transition_quality",
    "mobile_readability",
)

SEVERITIES = {"low", "medium", "high"}

STATUSES = {"awaiting_review", "approved", "rejected", "applied", "stale"}

# Layout operations: attribute / custom-property edits on scene-grammar scenes
# only. They are the ONLY operations a multimodal (AI judgment) proposal may use.
VISION_OPERATIONS = {
    "swap_layout_variant",
    "add_push_in",
    "enlarge_secondary_text",
    "increase_media_scale",
    "reduce_empty_space",
}

# Whitelist. No shell, no arbitrary source edits.
OPERATIONS = {
    "adjust_scene_duration",
    "trim_static_hold",
    "move_caption",
    "adjust_caption_end",
    "shift_sfx",
    "adjust_music_ducking",
    "remove_silence",
    "change_text_size",
    "change_text_contrast",
    "adjust_animation_start",
    "adjust_animation_duration",
} | VISION_OPERATIONS

ORIGINS = {"deterministic", "multimodal"}


class SchemaError(ValueError):
    pass


def _need(obj: Dict, key: str, types, where: str):
    if key not in obj:
        raise SchemaError("%s: missing field '%s'" % (where, key))
    if not isinstance(obj[key], types):
        raise SchemaError("%s: field '%s' has wrong type (%s)"
                          % (where, key, type(obj[key]).__name__))
    return obj[key]


def validate_finding(f: Dict) -> Dict:
    where = "finding"
    _need(f, "id", str, where)
    _need(f, "category", str, where)
    _need(f, "severity", str, where)
    _need(f, "description", str, where)
    _need(f, "confidence", (int, float), where)
    _need(f, "evidence", dict, where)
    if f["category"] not in CATEGORIES:
        raise SchemaError("finding: unsupported category '%s'" % f["category"])
    if f["severity"] not in SEVERITIES:
        raise SchemaError("finding: unsupported severity '%s'" % f["severity"])
    basis = f.get("basis", MEASURED_FACT)
    if basis not in (MEASURED_FACT, AI_JUDGMENT):
        raise SchemaError("finding: unsupported basis '%s'" % basis)
    if f["category"] in JUDGMENT_CATEGORIES and basis != AI_JUDGMENT:
        raise SchemaError("finding: %s findings must have basis AI_JUDGMENT" % f["category"])
    ev = f["evidence"]
    _need(ev, "unit", str, where + ".evidence")
    _need(ev, "source", str, where + ".evidence")
    if basis == AI_JUDGMENT:
        if f["category"] not in JUDGMENT_CATEGORIES:
            raise SchemaError("finding: AI_JUDGMENT is only allowed for visual_judgment")
        if f.get("measured") is not False:
            raise SchemaError("finding: AI judgment must be marked measured=false")
        if ev.get("measured_value") is not None:
            raise SchemaError("finding: AI judgment must not carry a measured_value")
        if f.get("hard_fail"):
            raise SchemaError("finding: AI judgment can never be a hard fail")
        j = _need(f, "judgment", dict, where)
        if j.get("dimension") not in VISION_DIMENSIONS:
            raise SchemaError("finding: unsupported judgment dimension '%s'" % j.get("dimension"))
        _need(j, "rationale", str, where + ".judgment")
        score = _need(j, "score", (int, float), where + ".judgment")
        if not (1 <= float(score) <= 5):
            raise SchemaError("finding: judgment score must be within 1..5")
    else:
        _need(ev, "measured_value", (int, float), where + ".evidence")
    if "scene" not in f:
        raise SchemaError("finding: missing field 'scene'")
    if not isinstance(f["confidence"], (int, float)) or not (0.0 <= float(f["confidence"]) <= 1.0):
        raise SchemaError("finding: confidence must be within 0..1")
    return f


def validate_proposal(p: Dict) -> Dict:
    where = "proposal"
    _need(p, "id", str, where)
    _need(p, "project_revision", int, where)
    _need(p, "finding_id", str, where)
    _need(p, "title", str, where)
    _need(p, "rationale", str, where)
    _need(p, "operation", dict, where)
    _need(p, "duration_before", (int, float), where)
    _need(p, "duration_after", (int, float), where)
    _need(p, "warnings", list, where)
    _need(p, "confidence", (int, float), where)
    _need(p, "status", str, where)
    op = p["operation"]
    _need(op, "type", str, where + ".operation")
    if op["type"] not in OPERATIONS:
        raise SchemaError("proposal: unsupported operation '%s'" % op["type"])
    origin = p.get("origin", "deterministic")
    if origin not in ORIGINS:
        raise SchemaError("proposal: unsupported origin '%s'" % origin)
    if origin == "multimodal" and op["type"] not in VISION_OPERATIONS:
        raise SchemaError("proposal: multimodal proposals may only use %s"
                          % sorted(VISION_OPERATIONS))
    if p["status"] not in STATUSES:
        raise SchemaError("proposal: unsupported status '%s'" % p["status"])
    if not (0.0 <= float(p["confidence"]) <= 1.0):
        raise SchemaError("proposal: confidence must be within 0..1")
    for w in p["warnings"]:
        if not isinstance(w, str):
            raise SchemaError("proposal: warnings must be strings")
    return p


def validate_all(findings: List[Dict], proposals: List[Dict]):
    for f in findings:
        validate_finding(f)
    for p in proposals:
        validate_proposal(p)
