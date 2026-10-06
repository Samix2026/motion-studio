"""Style-profile schema (stdlib only).

A profile contains exactly two evidence sections — ``observed`` (measured or
explicitly provided) and ``inferred`` (interpretation) — plus ``unavailable``
entries for anything not measurable. It has no field for scripts, wording,
scene order, logos, or assets, by construction.
"""

from __future__ import annotations

from typing import Dict, List

SCHEMA_VERSION = 1
SOURCE_TYPES = {"video", "images", "manual"}

# Only these keys may appear in `observed` (no text/script/branding fields exist).
OBSERVED_KEYS = {
    "duration_seconds", "scene_count", "average_scene_duration", "cut_density",
    "first_cut_seconds", "text_density", "dominant_aspect_ratio", "width", "height",
    "fps", "image_count", "audio_present", "audio_duration_seconds",
    "integrated_loudness_lufs",
}

INFERRED_KEYS = {
    "pacing", "hook_speed", "layout_style", "camera_motion", "transition_style",
    "headline_scale", "secondary_scale", "contrast", "music_energy", "sfx_density",
    "content_pattern",
}

CUT_DENSITY = {"low", "medium", "high"}
TEXT_DENSITY = {"low", "medium", "high"}
PACING = {"slow", "moderate", "fast"}


class StyleProfileError(ValueError):
    pass


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(profile: Dict) -> Dict:
    if not isinstance(profile, dict):
        raise StyleProfileError("profile: must be an object")
    if profile.get("schema_version") != SCHEMA_VERSION:
        raise StyleProfileError("profile: schema_version must be %d" % SCHEMA_VERSION)
    if not isinstance(profile.get("reference_id"), str) or not profile["reference_id"]:
        raise StyleProfileError("profile: reference_id must be a non-empty string")
    if profile.get("source_type") not in SOURCE_TYPES:
        raise StyleProfileError("profile: bad source_type '%s'" % profile.get("source_type"))
    for section in ("observed", "inferred"):
        if not isinstance(profile.get(section), dict):
            raise StyleProfileError("profile: '%s' must be an object" % section)
    if not isinstance(profile.get("unavailable"), list):
        raise StyleProfileError("profile: 'unavailable' must be a list")

    for k, v in profile["observed"].items():
        if k not in OBSERVED_KEYS:
            raise StyleProfileError("observed: unsupported key '%s'" % k)
        if v is None:
            continue
        if k in ("cut_density", "text_density"):
            if v not in CUT_DENSITY:
                raise StyleProfileError("observed.%s: bad value '%s'" % (k, v))
        elif k in ("dominant_aspect_ratio",):
            if not isinstance(v, str):
                raise StyleProfileError("observed.%s must be a string" % k)
        elif k == "audio_present":
            if not isinstance(v, bool):
                raise StyleProfileError("observed.audio_present must be a bool")
        elif not _is_num(v):
            raise StyleProfileError("observed.%s must be numeric" % k)

    for k, v in profile["inferred"].items():
        if k not in INFERRED_KEYS:
            raise StyleProfileError("inferred: unsupported key '%s'" % k)
        if v is not None and not isinstance(v, str):
            raise StyleProfileError("inferred.%s must be a string or null" % k)
    if "pacing" in profile["inferred"] and profile["inferred"]["pacing"] is not None:
        if profile["inferred"]["pacing"] not in PACING:
            raise StyleProfileError("inferred.pacing: bad value")

    for u in profile["unavailable"]:
        if not isinstance(u, dict) or "field" not in u or "reason" not in u:
            raise StyleProfileError("unavailable entries need 'field' and 'reason'")
    return profile


def make(reference_id: str, source_type: str, observed: Dict, inferred: Dict,
         unavailable: List[Dict]) -> Dict:
    return validate({
        "schema_version": SCHEMA_VERSION,
        "reference_id": reference_id,
        "source_type": source_type,
        "observed": observed,
        "inferred": inferred,
        "unavailable": unavailable,
    })


def whitelist(source: Dict, allowed) -> Dict:
    """Keep only allowed keys — drops scripts, transcripts, logos, branding."""
    if not isinstance(source, dict):
        return {}
    return {k: v for k, v in source.items() if k in allowed}
