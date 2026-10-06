"""Deterministic analyzer.

Produces measured facts about a composition. It never judges and never
invents data: any check it cannot measure is reported under `unavailable`
instead of becoming a finding.
"""

from __future__ import annotations

import json
import os
import re
import statistics
from typing import Dict, List, Optional

from . import htmlmodel, inputs as review_inputs, pixels, process, revision

try:  # typography system (bundled font, type scale, phone readability)
    from design import typography as _typography
except Exception:  # pragma: no cover - design package always present in-repo
    _typography = None

_RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules", "defaults.json")


def load_rules() -> Dict:
    with open(_RULES_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- probes

def _ffprobe(path: str) -> Optional[Dict]:
    """Probe a local render. A missing tool or probe failure returns None and
    is reported as an unavailable check - never as an empty-success measure."""
    if not path or not os.path.isfile(path):
        return None
    try:
        data = process.probe_media(path)
    except process.ProcessError:
        return None
    streams = data.get("streams", [])
    return {
        "duration": float(data.get("format", {}).get("duration", 0) or 0),
        "size": int(data.get("format", {}).get("size", 0) or 0),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "has_video": any(s.get("codec_type") == "video" for s in streams),
        "video": next(({k: s.get(k) for k in
                        ("codec_name", "width", "height", "r_frame_rate", "pix_fmt")}
                       for s in streams if s.get("codec_type") == "video"), None),
        "audio": next(({k: s.get(k) for k in
                        ("codec_name", "sample_rate", "channels", "channel_layout")}
                       for s in streams if s.get("codec_type") == "audio"), None),
    }


def _silence_regions(path: str, min_seconds: float) -> Optional[List[Dict]]:
    if not path or not os.path.isfile(path):
        return None
    try:
        return process.silence_regions(path, min_seconds)
    except process.ProcessError:
        return None


def _snapshots(project_dir: str) -> List[Dict]:
    snap_dir = os.path.join(project_dir, "snapshots")
    out = []
    if os.path.isdir(snap_dir):
        for fn in sorted(os.listdir(snap_dir)):
            m = re.search(r"at-([0-9.]+)s\.png$", fn)
            if m:
                out.append({"file": fn, "at": float(m.group(1))})
    return out


def _snapshots_from_paths(paths) -> List[Dict]:
    out = []
    for path in sorted(paths or []):
        name = os.path.basename(path)
        m = re.search(r"at-([0-9.]+)s\.png$", name)
        out.append({"file": name, "at": float(m.group(1)) if m else None})
    return out


def _render_path(project_dir: str) -> Optional[str]:
    """Find the project's rendered video, preferring renders/video.mp4."""
    d = os.path.join(project_dir, "renders")
    if not os.path.isdir(d):
        return None
    cands = [f for f in sorted(os.listdir(d))
             if f.lower().endswith((".mp4", ".mov", ".m4v"))]
    if not cands:
        return None
    if "video.mp4" in cands:
        return os.path.join(d, "video.mp4")
    return os.path.join(d, cands[0])


# ---------------------------------------------------------------- timing inputs

try:  # canonical word-timing layer (Phase C); optional for older projects
    from timing import schema as _timing_schema
except Exception:  # pragma: no cover - timing package always present in-repo
    _timing_schema = None


def _load_word_timings(project_dir: str):
    """Return (doc, path, error). Prefers a project-root file, then caches that
    live next to a voice asset (``*.word-timings.json``). Never estimates."""
    candidates = []
    root_file = os.path.join(project_dir, "word-timings.json")
    if os.path.isfile(root_file):
        candidates.append(root_file)
    assets = os.path.join(project_dir, "assets")
    if os.path.isdir(assets):
        for base, _dirs, names in os.walk(assets):
            for fn in sorted(names):
                if fn.endswith(".word-timings.json"):
                    candidates.append(os.path.join(base, fn))
    if not candidates:
        return None, None, None
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
            if _timing_schema is not None:
                doc = _timing_schema.validate(doc)
            return doc, path, None
        except Exception as exc:
            return None, path, str(exc)
    return None, None, None


def _load_captions(project_dir: str, model):
    """Return (captions, path). Canonical captions.json, else data-role captions."""
    for path in (os.path.join(project_dir, "captions.json"),
                 os.path.join(project_dir, "assets", "captions.json")):
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                return None, path
            caps = data.get("captions") if isinstance(data, dict) else data
            if isinstance(caps, list):
                return caps, path
            return None, path
    if 'data-role="caption"' in model.html:
        caps = []
        for tag in re.findall(r"<[^>]*data-role=\"caption\"[^>]*>", model.html):
            a = htmlmodel._tag_attrs(tag)
            start = float(a.get("data-start", 0) or 0) * 1000.0
            dur = float(a.get("data-duration", 0) or 0) * 1000.0
            caps.append({"start_ms": start, "end_ms": start + dur,
                         "text": a.get("data-text", "")})
        return caps, "dom:data-role=caption"
    return None, None


def narration_for(project_dir: str, model) -> tuple:
    """Load canonical word timings + captions and attach them to the model.

    Word timings and captions are the authoritative narration timing; the
    narration-lock guards read them from the model. Returns the same values the
    caption-sync check consumes: (timings_doc, timings_path, err, captions,
    captions_path). No estimation, no provider call.
    """
    doc, path, err = _load_word_timings(project_dir)
    caps, caps_path = _load_captions(project_dir, model)
    model.narration_words = (doc or {}).get("words", [])
    model.captions = caps or []
    return doc, path, err, caps, caps_path


def current_review_fingerprint(project_dir: str, rules: Optional[Dict] = None) -> Dict:
    """Content-based fingerprint of the currently selected (legacy) inputs.

    Read-only; does not initialize state, probe media, or write anything. Used
    by freshness-aware consumers to tell whether a saved report still matches.
    """
    rules = rules or load_rules()
    selected = review_inputs.ReviewInputs.legacy(project_dir)
    model = htmlmodel.parse(project_dir)
    timings_doc, _timings_path, timings_err, captions, captions_path = \
        narration_for(project_dir, model)
    if captions is None:
        caption_source = "none"
    elif isinstance(captions_path, str) and captions_path.startswith("dom:"):
        caption_source = "dom"
    else:
        caption_source = "file"
    declared = list(selected.css_paths) + list(selected.dependencies)
    descriptor = selected.descriptor(
        rules=rules, rules_source="default", render_present=bool(selected.render_path),
        timings_doc=timings_doc, timings_error=timings_err,
        captions=captions, caption_source=caption_source,
        tools=process.tool_identities(),
        dependency_provenance=review_inputs.dependency_provenance(project_dir, declared))
    return {"fingerprint": review_inputs.ReviewInputs.fingerprint(descriptor),
            "descriptor": descriptor}


# ---------------------------------------------------------------- findings

def _fid(n: int) -> str:
    return "finding-%03d" % n


def _validate_explicit_context(project_dir: str, selected: review_inputs.ReviewInputs) -> None:
    """In explicit mode, the consumed inputs must equal the declared selection."""
    if selected.project_dir != os.path.abspath(project_dir):
        raise review_inputs.ReviewInputError(
            "ReviewInputs project context does not match the analyzer project_dir")
    expected = os.path.join(selected.project_dir, "index.html")
    if os.path.normpath(selected.composition_path) != expected:
        raise review_inputs.ReviewInputError(
            "explicit composition must be the project's index.html")
    consumed = sorted(os.path.normpath(p) for p in review_inputs.discover_css(project_dir))
    declared_css = sorted(os.path.normpath(p) for p in selected.css_paths)
    if consumed != declared_css:
        raise review_inputs.ReviewInputError(
            "declared CSS must exactly match the local stylesheets the composition consumes")
    required = review_inputs.discover_dependencies(project_dir)
    declared_refs = set(declared_css) | {os.path.normpath(p) for p in selected.dependencies}
    undeclared = [os.path.relpath(p, project_dir) for p in required
                  if os.path.normpath(p) not in declared_refs]
    if undeclared:
        raise review_inputs.ReviewInputError(
            "undeclared required local dependencies: %s" % ", ".join(sorted(undeclared)))


def analyze(project_dir: str, rules: Optional[Dict] = None,
            inputs: Optional[review_inputs.ReviewInputs] = None) -> Dict:
    """Analyze a composition.

    Read-only: state is viewed, never initialised. When ``inputs`` is given it
    is the explicit selection (exact render, composition, CSS, timing/caption
    files); otherwise legacy discovery is used for backward compatibility.
    """
    rules_source = "supplied" if rules is not None else "default"
    rules = rules or load_rules()
    model = htmlmodel.parse(project_dir)
    state = revision.load_state_view(project_dir)
    selected = inputs if inputs is not None else review_inputs.ReviewInputs.legacy(project_dir)
    if selected.explicit:
        _validate_explicit_context(project_dir, selected)
        timings_doc, timings_path, timings_err = selected.load_timings()
        captions, captions_path = selected.load_captions()
        caption_source = "file" if captions is not None and selected.caption_path else "none"
    else:
        # Attach narration timing once; word timings/captions are authoritative.
        timings_doc, timings_path, timings_err, captions, captions_path = \
            narration_for(project_dir, model)
        if captions is None:
            caption_source = "none"
        elif isinstance(captions_path, str) and captions_path.startswith("dom:"):
            caption_source = "dom"
        else:
            caption_source = "file"
    model.narration_words = (timings_doc or {}).get("words", [])
    model.captions = captions or []
    render_path = selected.render_path
    if selected.explicit:
        snapshot_measurements = _snapshots_from_paths(selected.snapshot_paths)
    else:
        snapshot_measurements = _snapshots(project_dir)

    findings: List[Dict] = []
    unavailable: List[Dict] = []
    measurement_status: Dict[str, str] = {}
    n = {"i": 0}

    def add(category, severity, scene, value, unit, source, desc, confidence, measured=True):
        n["i"] += 1
        findings.append({
            "id": _fid(n["i"]),
            "category": category,
            "severity": severity,
            "scene": scene,
            "evidence": {"measured_value": value, "unit": unit, "source": source},
            "description": desc,
            "confidence": confidence,
            "measured": measured,
        })

    t = rules["timing"]
    model.narration_tail_padding_s = float(t.get("narration_tail_padding_seconds", 0.0))

    # ---- scene pacing: static holds + outliers
    scene_measures = []
    for s in model.scenes:
        evs = model.events_in_scene(s)
        last_end = max([e.end for e in evs], default=s.start)
        hold = round(max(s.end - last_end, 0.0), 3)
        scene_measures.append({"index": s.index, "id": s.id, "start": s.start,
                               "duration": s.duration, "end": s.end,
                               "last_motion_end": round(last_end, 3), "static_hold": hold,
                               "motion_state": model.motion_state(s),
                               "static_hold_verified": model.is_static_hold_verified(s),
                               "narration_locked": s.narration_locked,
                               "narration_min_duration_s":
                                   model.narration_min_duration_s(s)
                                   if s.narration_locked else None})
    if model.unparsed_motion:
        unavailable.append({
            "check": "static_hold_verified",
            "reason": ("helper-driven motion could not be fully parsed (%d construct(s)); "
                       "timeline static holds are not asserted; pixel freeze detection "
                       "remains authoritative" % len(model.unparsed_motion)),
        })
    if model.scenes:
        measurement_status["scene_pacing"] = "complete"
        measurement_status["static_hold_verified"] = (
            "partial" if model.unparsed_motion else "complete")
        durs = [s.duration for s in model.scenes]
        median = statistics.median(durs)
        for s in model.scenes:
            m = next(x for x in scene_measures if x["index"] == s.index)
            hold = m["static_hold"]
            # Only a verified hold may become a timeline finding. When motion
            # is unknown (unparsed helper calls), parser absence is not static
            # evidence; the pixel freeze check still reports real holds.
            if m["static_hold_verified"] and hold > t["max_static_hold_seconds"]:
                sev = "high" if hold >= 2.0 else "medium"
                add("scene_pacing", sev, s.index, hold, "seconds", "timeline",
                    "Final visual state remains static for %.2fs." % hold,
                    0.95)
            ratio = (s.duration / median) if median else 1.0
            if (ratio >= t["scene_outlier_ratio_high"] or ratio <= t["scene_outlier_ratio_low"]) \
                    and abs(s.duration - median) >= t["scene_outlier_min_delta_seconds"]:
                add("scene_pacing", "low", s.index, round(s.duration, 3), "seconds", "scene",
                    "Scene duration %.2fs deviates from the median %.2fs." % (s.duration, median),
                    0.9)
    else:
        measurement_status["scene_pacing"] = "unavailable"

    # ---- sfx timing vs nearest visible motion event
    if model.sfx() and model.events:
        measurement_status["sfx_timing"] = "complete"
        for cue in model.sfx():
            nearest = min(model.events, key=lambda e: abs(e.start - cue.start))
            offset = round(cue.start - nearest.start, 3)
            if abs(offset) > t["sfx_offset_tolerance_seconds"]:
                add("sfx_timing", "medium" if abs(offset) >= 0.3 else "low", None,
                    offset, "seconds", "audio+timeline",
                    "SFX '%s' is %.0fms off the nearest visual event (%.2fs)."
                    % (cue.id, offset * 1000, nearest.start),
                    0.9)
    elif not model.sfx():
        measurement_status["sfx_timing"] = "unavailable"
        unavailable.append({"check": "sfx_timing", "reason": "no SFX audio elements"})
    else:
        measurement_status["sfx_timing"] = "unavailable"
        unavailable.append({"check": "sfx_timing", "reason": "no timeline events parsed"})

    # ---- music / silence gaps
    music = model.music()
    if music:
        measurement_status["music_silence_gaps"] = "complete"
        primary = music[0]
        lead = round(primary.start, 3)
        tail = round(max(model.duration - primary.end, 0.0), 3)
        if lead > t["music_gap_tolerance_seconds"]:
            add("music_silence_gaps", "low", None, lead, "seconds", "audio+composition",
                "Music starts %.2fs after the composition begins." % lead, 0.9)
        if tail > t["music_gap_tolerance_seconds"]:
            add("music_silence_gaps", "low", None, tail, "seconds", "audio+composition",
                "Music ends %.2fs before the composition ends." % tail, 0.9)
        if model.sfx():
            duck_events = [e for e in model.events
                           if e.is_volume and e.selector.strip("#.") in
                           (primary.id, primary.id.replace("au-", ""))]
            if not duck_events:
                add("music_silence_gaps", "medium", None, 0, "count", "timeline",
                    "No music ducking detected while SFX cues exist.", 0.85)
    else:
        measurement_status["music_silence_gaps"] = "unavailable"
        unavailable.append({"check": "music_silence_gaps",
                            "reason": "no music element (music is optional)"})

    probe_error = None
    if render_path:
        render = _ffprobe(render_path)
        if render is None:
            probe_error = "ffprobe failed or produced no usable metadata"
    else:
        render = None
    if render and render.get("has_audio"):
        regions = _silence_regions(render_path, t["silence_min_seconds"])
        if regions is None:
            measurement_status["silence_regions"] = "unavailable"
            unavailable.append({"check": "silence_regions", "reason": "silencedetect failed"})
        else:
            measurement_status["silence_regions"] = "complete"
            for r in regions:
                d = r.get("duration")
                if d and d >= t["silence_min_seconds"]:
                    add("music_silence_gaps", "low", None, round(d, 3), "seconds",
                        "silencedetect",
                        "Silence of %.2fs detected at %.2fs." % (d, r["start"]), 0.8)
    else:
        measurement_status["silence_regions"] = "unavailable"
        unavailable.append({"check": "silence_regions",
                            "reason": probe_error or "no rendered audio to analyze"})

    # ---- text readability
    bg = model.background or rules["readability"]["background_hint"]
    readability_missing = 0
    for cls in rules["readability"]["secondary_classes"]:
        st = model.class_styles.get(cls)
        if not st:
            readability_missing += 1
            unavailable.append({"check": "text_readability:%s" % cls,
                                "reason": "class .%s not found in composition CSS" % cls})
            continue
        fs = st.get("font_size_px")
        if fs is not None and fs < rules["readability"]["min_secondary_font_px"]:
            add("text_readability", "medium", None, fs, "px", "css",
                "Secondary text .%s is %.0fpx (below %.0fpx for 1080p)."
                % (cls, fs, rules["readability"]["min_secondary_font_px"]), 0.9)
        color = st.get("color")
        if color:
            ratio = htmlmodel.contrast_ratio(color, bg)
            if ratio is not None and ratio < rules["readability"]["min_contrast_ratio"]:
                add("text_readability", "medium", None, ratio, "ratio", "css",
                    "Text .%s contrast %.2f:1 is below AA %.1f:1."
                    % (cls, ratio, rules["readability"]["min_contrast_ratio"]), 0.9)
    if not model.class_styles:
        measurement_status["text_readability"] = "unavailable"
    elif readability_missing:
        measurement_status["text_readability"] = "partial"
    else:
        measurement_status["text_readability"] = "complete"

    # ---- caption / audio synchronization (requires real word timings)
    words = (timings_doc or {}).get("words", [])
    if timings_err:
        measurement_status["caption_audio_sync"] = "unavailable"
        unavailable.append({"check": "caption_audio_sync",
                            "reason": "word timings could not be validated: %s" % timings_err})
    elif not timings_doc:
        measurement_status["caption_audio_sync"] = "unavailable"
        unavailable.append({"check": "caption_audio_sync",
                            "reason": "no word-timings.json or *.word-timings.json; timing unavailable"})
    elif not captions:
        measurement_status["caption_audio_sync"] = "unavailable"
        unavailable.append({"check": "caption_audio_sync",
                            "reason": "word timings present but no caption timing "
                                      "(captions.json or data-role=\"caption\")"})
    else:
        tol = float(t.get("caption_sync_tolerance_ms", 150))
        usable = 0
        for i, c in enumerate(captions):
            try:
                cs, ce = float(c["start_ms"]), float(c["end_ms"])
            except Exception:
                continue
            if ce <= cs:
                continue
            usable += 1
            cover = [w for w in words if w["start_ms"] < ce and w["end_ms"] > cs]
            if not cover:
                continue
            first = min(cover, key=lambda w: w["start_ms"])
            last = max(cover, key=lambda w: w["end_ms"])
            lead = round(first["start_ms"] - cs, 1)   # >0: caption appears before speech
            tail = round(ce - last["end_ms"], 1)      # <0: caption ends before the phrase
            if lead > tol:
                add("caption_audio_sync", "medium" if lead >= 400 else "low", None,
                    lead, "milliseconds", "word-timings+captions",
                    "Caption %d begins %.0fms before the first spoken word." % (i + 1, lead),
                    0.9)
            if tail < -tol:
                off = abs(tail)
                add("caption_audio_sync", "medium" if off >= 400 else "low", None,
                    off, "milliseconds", "word-timings+captions",
                    "Caption %d ends %.0fms before the spoken phrase ends." % (i + 1, off),
                    0.9)
        measurement_status["caption_audio_sync"] = (
            "complete" if usable == len(captions) else "partial")

    # ---- rendered output: frame 0, frozen content, shot diversity (pixels)
    px = rules.get("pixels", {})
    rendered = {"frame_zero": None, "freezes": None, "shot_hashes": None}
    if render_path and render and render.get("has_video"):
        vid = render.get("video") or {}
        vw, vh = model.width or vid.get("width") or 0, model.height or vid.get("height") or 0
        frame_rule = dict(_typography.load_scale()["frame_zero"]) if _typography is not None else {}
        frame_rule.update(px.get("frame_zero") or {})
        fz = pixels.frame_zero(render_path, vw, vh, frame_rule)
        rendered["frame_zero"] = fz
        if fz is None:
            measurement_status["frame_zero"] = "unavailable"
            unavailable.append({"check": "frame_zero",
                                "reason": "frame 0 or the deadline frame could not be decoded"})
        elif not fz["meaningful_by_deadline"]:
            measurement_status["frame_zero"] = "complete"
            add("frame_zero", "high", 1, fz["at_0"]["content_coverage"], "coverage", "pixels",
                "Frame 0 is near-empty: content coverage %.3f at 0s and %.3f at %.1fs (minimum %.3f)."
                % (fz["at_0"]["content_coverage"], fz["at_deadline"]["content_coverage"],
                   fz["deadline_seconds"], fz["min_content_coverage"]), 0.9)
        elif not fz["meaningful_at_0"]:
            measurement_status["frame_zero"] = "complete"
            add("frame_zero", "low", 1, fz["at_0"]["content_coverage"], "coverage", "pixels",
                "Hook content appears only after frame 0 (coverage %.3f at 0s)."
                % fz["at_0"]["content_coverage"], 0.85)
        else:
            measurement_status["frame_zero"] = "complete"

        freezes = pixels.freeze_regions(render_path, float(px.get("freeze_min_seconds", 2.5)),
                                        float(px.get("freeze_noise_db", -60)),
                                        px.get("freeze_content_crop"), render.get("duration"))
        rendered["freezes"] = freezes
        if freezes is None:
            measurement_status["rendered_freeze"] = "unavailable"
            unavailable.append({"check": "rendered_freeze", "reason": "freezedetect failed"})
        else:
            measurement_status["rendered_freeze"] = "complete"
            for fr in freezes:
                sc = model.scene_containing(fr["start"])
                sev = "high" if fr["duration"] >= float(px.get("freeze_high_seconds", 4.0)) else "medium"
                add("rendered_freeze", sev, sc.index if sc else None, fr["duration"], "seconds",
                    "pixels:freezedetect",
                    "Rendered content area is frozen for %.2fs from %.2fs." % (fr["duration"], fr["start"]),
                    0.9)

        if len(model.scenes) >= 2:
            hashes = [pixels.frame_hash(render_path, s.start + s.duration / 2.0) for s in model.scenes]
            rendered["shot_hashes"] = ["%064x" % h if h is not None else None for h in hashes]
            missing = [i for i, h in enumerate(hashes) if h is None]
            if len(missing) == len(hashes):
                measurement_status["shot_diversity"] = "unavailable"
                unavailable.append({"check": "shot_diversity",
                                    "reason": "all midpoint frame samples failed"})
            else:
                if missing:
                    measurement_status["shot_diversity"] = "partial"
                    rendered["shot_hash_coverage"] = {"sampled": len(hashes) - len(missing),
                                                      "total": len(hashes),
                                                      "failed_scenes": [i + 1 for i in missing]}
                else:
                    measurement_status["shot_diversity"] = "complete"
                for pair in pixels.similar_pairs(hashes, int(px.get("duplicate_max_bits", 28))):
                    add("shot_diversity", "medium" if pair["similarity"] >= 0.93 else "low", pair["b"],
                        pair["similarity"], "similarity", "pixels:dhash-midpoint",
                        "Scene %d midpoint frame is %.0f%% similar to scene %d (%d/%d bits differ)."
                        % (pair["b"], pair["similarity"] * 100, pair["a"], pair["distance_bits"],
                           pixels.HASH_BITS), 0.8)
        else:
            measurement_status["shot_diversity"] = "unavailable"
            unavailable.append({"check": "shot_diversity", "reason": "fewer than two scenes"})

        # ---- advisory diagnostics: near-still time, long holds, empty frames,
        # boundary coverage dips. Context for humans and the optional visual
        # critic; never a hard fail and never a source of proposals.
        diag = px.get("diagnostics") or {}
        dfps = float(diag.get("fps", 10))
        still = pixels.near_still(render_path, vw, vh, fps=dfps,
                                  threshold=float(diag.get("near_still_threshold", 0.05)),
                                  min_hold=float(diag.get("hold_report_seconds", 0.6)),
                                  content_crop=px.get("freeze_content_crop"))
        rendered["near_still"] = still
        if still is None:
            measurement_status["long_hold"] = "unavailable"
            unavailable.append({"check": "long_hold", "reason": "motion measurement failed"})
        else:
            measurement_status["long_hold"] = "complete"
            for hold in still["holds"]:
                if hold["duration"] > float(diag.get("long_hold_seconds", 2.0)):
                    sc = model.scene_containing(hold["start"])
                    add("long_hold", "low", sc.index if sc else None, hold["duration"], "seconds",
                        "pixels:tblend",
                        "Advisory: content is near-still for %.1fs (%.1f-%.1fs); may be intended reading time."
                        % (hold["duration"], hold["start"], hold["end"]), 0.8)
        coverage = pixels.coverage_series(render_path, vw, vh, render.get("duration") or model.duration,
                                          fps=dfps)
        if coverage is None:
            for check in ("empty_frame", "boundary_dip"):
                measurement_status[check] = "unavailable"
                unavailable.append({"check": check, "reason": "frame sequence decode failed"})
        else:
            skip = float(frame_rule.get("deadline_seconds", 0.5))  # frame 0 has its own check
            spans = pixels.empty_spans(coverage, dfps, float(diag.get("empty_frame_coverage", 0.01)), skip)
            rendered["empty_frames"] = spans
            measurement_status["empty_frame"] = "complete"
            for sp in spans:
                sc = model.scene_containing(sp["start"])
                add("empty_frame", "medium", sc.index if sc else None, sp["min_coverage"], "coverage",
                    "pixels:coverage",
                    "Advisory: near-empty frames from %.1fs to %.1fs (coverage %.4f)."
                    % (sp["start"], sp["end"], sp["min_coverage"]), 0.85)
            dips = pixels.boundary_dips(coverage, dfps, [s.start for s in model.scenes[1:]],
                                        window=float(diag.get("boundary_window_seconds", 0.6)),
                                        ratio=float(diag.get("boundary_dip_ratio", 0.35)))
            rendered["boundary_dips"] = dips
            measurement_status["boundary_dip"] = "complete"
            for d in dips:
                if d["dip"]:
                    sc = model.scene_containing(d["boundary"])
                    add("boundary_dip", "low", sc.index if sc else None, d["min_coverage"], "coverage",
                        "pixels:coverage",
                        "Advisory: coverage dips to %.4f at %.1fs around the %.1fs scene boundary "
                        "(%.4f nearby)." % (d["min_coverage"], d["at"], d["boundary"],
                                            d["reference_coverage"]), 0.75)
    else:
        for check in ("frame_zero", "rendered_freeze", "shot_diversity",
                      "long_hold", "empty_frame", "boundary_dip"):
            measurement_status[check] = "unavailable"
            unavailable.append({"check": check,
                                "reason": probe_error or "no rendered video to analyze"})

    # ---- text density (visible words per scene, from the DOM)
    density = pixels.text_density(model.scenes)
    measurement_status["text_density"] = "complete" if density else "unavailable"
    for d in density:
        wps = d["words_per_second"]
        if wps is None:
            continue
        if wps > float(px.get("max_words_per_second", 4.0)) or d["words"] > int(px.get("max_words_per_scene", 26)):
            add("text_density", "medium" if wps > float(px.get("high_words_per_second", 5.0)) else "low",
                d["index"], wps, "words/second", "dom",
                "Scene %d shows %d words in %.1fs (%.1f words/s)." % (d["index"], d["words"], d["duration"], wps),
                0.85)

    # ---- mobile readability (rendered text size at phone scale)
    mobile = _typography.mobile_readability(project_dir) if _typography is not None else None
    if not mobile or mobile.get("status") != "measured":
        measurement_status["mobile_readability"] = "unavailable"
        unavailable.append({"check": "mobile_readability",
                            "reason": (mobile or {}).get("reason", "typography module unavailable")})
    else:
        measurement_status["mobile_readability"] = "complete"
        phone = _typography.load_scale()["phone_viewport_css_px"]
        for item in mobile["items"]:
            if item["ok"]:
                continue
            add("mobile_readability", "medium", None, item["phone_px"], "px@phone", "css*phone-scale",
                "Text .%s renders at %.1fpx on a %dpx-wide phone (minimum %spx for %s text)."
                % (item["class"], item["phone_px"], phone, item["min_phone_px"], item["role"]), 0.85)
            findings[-1]["evidence"].update({"class": item["class"], "css_px": item["css_px"],
                                             "threshold": item["min_phone_px"],
                                             "phone_viewport_css_px": phone})

    content_hash = revision.content_hash(project_dir)
    declared = list(selected.css_paths) + list(selected.dependencies)
    descriptor = selected.descriptor(
        rules=rules, rules_source=rules_source, render_present=bool(render_path),
        timings_doc=timings_doc, timings_error=timings_err,
        captions=captions, caption_source=caption_source,
        tools=process.tool_identities(),
        dependency_provenance=review_inputs.dependency_provenance(project_dir, declared))
    fingerprint = review_inputs.ReviewInputs.fingerprint(descriptor)
    return {
        "project": revision.slug_for(project_dir),
        "project_dir": os.path.abspath(project_dir),
        "revision": state["revision"],
        "content_hash": content_hash,
        "review_inputs": descriptor,
        "review_fingerprint": fingerprint,
        "review_fingerprint_version": review_inputs.FINGERPRINT_VERSION,
        "measurement_status": measurement_status,
        "composition": {"duration": model.duration, "width": model.width,
                        "height": model.height, "fps": model.fps, "id": model.comp_id},
        "measurements": {
            "scenes": scene_measures,
            "audio": [{"id": a.id, "kind": a.kind, "start": a.start,
                       "duration": a.duration, "end": a.end, "volume": a.volume}
                      for a in model.audio],
            "motion_events": [{"selector": e.selector, "start": e.start,
                               "duration": e.duration, "end": round(e.end, 3),
                               "is_volume": e.is_volume, "source": e.source}
                              for e in model.events],
            "motion": {"parse_complete": model.motion_parse_complete,
                       "unparsed": list(model.unparsed_motion)},
            "render": render,
            "render_path": render_path,
            "word_timings": ({"path": timings_path, "count": len(words)}
                             if timings_doc else None),
            "captions": ({"path": captions_path, "count": len(captions)}
                         if captions else None),
            "snapshots": snapshot_measurements,
            "rendered": rendered,
            "text_density": density,
            "mobile_readability": mobile,
            "text_styles": model.class_styles,
            "background": bg,
        },
        "findings": findings,
        "unavailable": unavailable,
    }
