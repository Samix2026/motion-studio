"""Reference Analyzer (V1) — abstract style metadata from local references.

Observed values are measured (ffprobe/ffmpeg/headers) or explicitly provided.
Inferred values are interpretations and carry no factual weight. Anything not
measurable is listed under ``unavailable`` — never guessed.

Deliberately NOT produced: scripts, wording, scene order, shot sequence, logos,
branding, characters, or any asset derived from the reference.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, List, Optional

from . import images, schema, video

_PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")
_REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")

# Deterministic thresholds (documented in REFERENCE_ANALYZER.md)
_PACING_FAST_S = 2.5
_PACING_SLOW_S = 5.0
_HOOK_FAST_S = 1.5
_HOOK_SLOW_S = 3.0
_CUTS_PER_MIN_HIGH = 20.0
_CUTS_PER_MIN_MED = 8.0


def default_id(path: Optional[str], manual: Optional[Dict]) -> str:
    base = os.path.basename(os.path.normpath(path)) if path else "manual"
    raw = (os.path.abspath(path) if path else json.dumps(manual or {}, sort_keys=True))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return "%s-%s" % (os.path.splitext(base)[0], digest)


def _unavail(field: str, reason: str) -> Dict:
    return {"field": field, "reason": reason}


def _infer(observed: Dict, unavailable: List[Dict]) -> Dict:
    inferred: Dict = {k: None for k in sorted(schema.INFERRED_KEYS)}

    avg = observed.get("average_scene_duration")
    if isinstance(avg, (int, float)):
        if avg < _PACING_FAST_S:
            inferred["pacing"] = "fast"
        elif avg < _PACING_SLOW_S:
            inferred["pacing"] = "moderate"
        else:
            inferred["pacing"] = "slow"
    else:
        unavailable.append(_unavail("pacing", "no measured scene duration"))

    first = observed.get("first_cut_seconds")
    if isinstance(first, (int, float)):
        if first < _HOOK_FAST_S:
            inferred["hook_speed"] = "fast"
        elif first < _HOOK_SLOW_S:
            inferred["hook_speed"] = "moderate"
        else:
            inferred["hook_speed"] = "slow"
    else:
        unavailable.append(_unavail("hook_speed", "no measured first cut"))

    for field in ("layout_style", "camera_motion", "transition_style",
                  "headline_scale", "secondary_scale", "contrast",
                  "music_energy", "sfx_density", "content_pattern"):
        unavailable.append(_unavail(field, "not measurable offline in V1; provide via --manual"))
    return inferred


def _cut_density(cuts_per_min: float) -> str:
    if cuts_per_min >= _CUTS_PER_MIN_HIGH:
        return "high"
    if cuts_per_min >= _CUTS_PER_MIN_MED:
        return "medium"
    return "low"


def analyze(path: Optional[str] = None, manual: Optional[Dict] = None,
            reference_id: Optional[str] = None,
            allow_scene_detection: bool = True) -> Dict:
    rid = reference_id or default_id(path, manual)
    observed: Dict = {}
    inferred: Dict = {}
    unavailable: List[Dict] = []

    manual_observed = schema.whitelist((manual or {}).get("observed", manual or {}),
                                       schema.OBSERVED_KEYS)
    manual_inferred = schema.whitelist((manual or {}).get("inferred", {}),
                                       schema.INFERRED_KEYS)

    if manual is not None and not path:
        observed.update(manual_observed)
        for k, v in manual_inferred.items():
            inferred[k] = v
        source_type = "manual"

    elif path and os.path.isfile(path) and video.is_video(path):
        source_type = "video"
        info, err = video.probe(path)
        if info is None:
            unavailable.append(_unavail("duration_seconds", err or "probe failed"))
        else:
            observed.update(info)
        if "width" in observed and "height" in observed:
            observed["dominant_aspect_ratio"] = images.aspect_ratio(observed["width"],
                                                                    observed["height"])
        cuts = None
        if allow_scene_detection:
            cuts, cerr = video.scene_cuts(path)
            if cuts is None:
                unavailable.append(_unavail("scene_count", cerr or "scene detection unavailable"))
        else:
            unavailable.append(_unavail("scene_count", "scene detection disabled"))
        if cuts is not None:
            observed["scene_count"] = len(cuts) + 1
            if cuts:
                observed["first_cut_seconds"] = cuts[0]
            dur = observed.get("duration_seconds")
            if dur:
                observed["average_scene_duration"] = round(dur / observed["scene_count"], 3)
                observed["cut_density"] = _cut_density(observed["scene_count"] / dur * 60.0)
        if observed.get("audio_present"):
            loud = video.integrated_loudness(path)
            if loud is not None:
                observed["integrated_loudness_lufs"] = loud

    elif path and os.path.isdir(path) and images.find_images(path):
        source_type = "images"
        observed.update(images.collect(images.find_images(path)))
        for field, reason in (("scene_count", "not measurable from images"),
                              ("average_scene_duration", "not measurable from images"),
                              ("cut_density", "not measurable from images"),
                              ("duration_seconds", "not measurable from images"),
                              ("text_density", "not measured offline in V1")):
            unavailable.append(_unavail(field, reason))

    elif path and os.path.isfile(path) and images.is_image(path):
        source_type = "images"
        observed.update(images.collect([path]))
        unavailable.append(_unavail("scene_count", "not measurable from a single image"))

    else:
        source_type = "manual"
        observed.update(manual_observed)
        unavailable.append(_unavail("duration_seconds",
                                    "no local video/image supplied"))

    # manual values override / fill measured ones and any manual inference wins
    observed.update(manual_observed)
    observed = {k: v for k, v in observed.items() if v is not None and k in schema.OBSERVED_KEYS}
    if "text_density" not in observed:
        unavailable.append(_unavail("text_density", "not measured offline in V1"))

    if manual_inferred:
        merged = _infer(observed, list(unavailable))
        merged.update(manual_inferred)
        inferred = merged
        unavailable[:] = [u for u in unavailable
                          if not (u["field"] in manual_inferred)]
    elif not inferred:
        inferred = _infer(observed, unavailable)

    seen = set()
    uniq = []
    for u in unavailable:
        if u["field"] in seen:
            continue
        seen.add(u["field"])
        uniq.append(u)

    return schema.make(rid, source_type, observed, inferred, uniq)


# ---------------------------------------------------------------- persistence

def profile_path(reference_id: str) -> str:
    return os.path.join(_PROFILE_DIR, "%s.json" % reference_id)


def save_profile(profile: Dict) -> str:
    schema.validate(profile)
    os.makedirs(_PROFILE_DIR, exist_ok=True)
    os.makedirs(_REPORT_DIR, exist_ok=True)
    path = profile_path(profile["reference_id"])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    with open(os.path.join(_REPORT_DIR, "%s.md" % profile["reference_id"]),
              "w", encoding="utf-8") as fh:
        fh.write(render_report_md(profile))
    return path


def load_profile(reference_id: str) -> Optional[Dict]:
    path = profile_path(reference_id)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return schema.validate(json.load(fh))


def render_report_md(profile: Dict) -> str:
    L = ["REFERENCE STYLE PROFILE", "",
         "Reference: %s" % profile["reference_id"],
         "Source type: %s" % profile["source_type"], "",
         "OBSERVED (measured / provided):"]
    if profile["observed"]:
        for k, v in sorted(profile["observed"].items()):
            L.append("- %s: %s" % (k, v))
    else:
        L.append("- (none)")
    L.append("")
    L.append("INFERRED (interpretation, not fact):")
    for k, v in sorted(profile["inferred"].items()):
        L.append("- %s: %s" % (k, "unavailable" if v is None else v))
    if profile["unavailable"]:
        L.append("")
        L.append("UNAVAILABLE:")
        for u in profile["unavailable"]:
            L.append("- %s: %s" % (u["field"], u["reason"]))
    L.append("")
    L.append("Style metadata only. No source text, wording, scene order, branding, "
             "logos, or assets are copied.")
    return "\n".join(L) + "\n"
