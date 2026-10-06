"""Narration pipeline plan (read-only).

Reports the state of the ten narration steps for a project and the required
scene durations:

  required_end = max(narration end, final caption end, visual minimum end)
                 + tail padding

It reuses the existing subsystem primitives — ``review.analyzer`` for canonical
word timings/captions and ``costgate`` for gate state — and never renders, never
calls a provider, and never writes to a project. Steps 1-2 (voice generation)
remain blocked until the cost gate is approved and are only executed by an
explicit command elsewhere.
"""

from __future__ import annotations

import glob
import json
import os
import re
from typing import Dict, List, Optional

from costgate import gate as cost_gate
from review import analyzer as rev_analyzer
from review import htmlmodel
from review import inputs as rev_inputs
from review import revision as rev_revision

from . import mode as mode_mod

DONE = "done"
PENDING = "pending"
BLOCKED = "blocked"
NA = "n/a"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (id, title, kind) in pipeline order.
STEP_DEFS = (
    ("tts_generate", "Generate TTS with Alice (provider timestamps in the same call)", "paid"),
    ("provider_timestamps", "Capture provider word/character timestamps", "paid"),
    ("normalize_timing", "Normalize timestamps into timing/ canonical schema", "offline"),
    ("phrase_groups", "Generate phrase groups (timing/phrases)", "offline"),
    ("mark_narrated_scenes", 'Mark narrated scenes data-narration-locked="true"', "offline"),
    ("kinetic_captions", "Generate kinetic captions", "composition"),
    ("scene_durations", "Set scene durations from narration/caption/visual max + tail", "offline"),
    ("caption_sync_review", "Run caption/audio sync review", "review"),
    ("render_preview", "Render preview", "render"),
    ("gate2_human", "Human Gate 2 approval", "gate"),
)

_TTS_COMMAND = ("ELEVENLABS_API_KEY=... python3 - <<'PY'\n"
                "POST /v1/text-to-speech/<alice-voice-id>/with-timestamps?output_format=mp3_44100_128\n"
                "PY")
_REVIEW_COMMAND = "python3 review/cli.py review <project>"
_RENDER_COMMAND = "npm run render -- . --skill=motion-graphics -q high -f 30 -o ./renders/preview.mp4"


def _rel(path: Optional[str], project_dir: str) -> Optional[str]:
    if not path:
        return None
    try:
        return os.path.relpath(path, project_dir)
    except ValueError:
        return path


def _narration_audio(project_dir: str) -> Optional[str]:
    root = os.path.join(project_dir, "narration.mp3")
    if os.path.isfile(root):
        return root
    patterns = ("assets/**/narration*.mp3", "assets/**/voice/*.mp3",
                "assets/**/*voice*.mp3", "assets/**/narration*.wav")
    for pat in patterns:
        hits = sorted(glob.glob(os.path.join(project_dir, pat), recursive=True))
        if hits:
            return hits[0]
    return None


def _render_path(project_dir: str) -> Optional[str]:
    for name in ("preview.mp4", "video.mp4"):
        p = os.path.join(project_dir, "renders", name)
        if os.path.isfile(p):
            return p
    hits = sorted(glob.glob(os.path.join(project_dir, "renders", "*.mp4")))
    return hits[0] if hits else None


def _caps_valid(captions: Optional[List[Dict]]) -> bool:
    if not captions:
        return False
    try:
        from timing import phrases as timing_phrases
        timing_phrases.validate_captions({"captions": captions})
        return True
    except Exception:
        return False


def _caption_texts_present(project_dir: str, captions: List[Dict]) -> bool:
    """True when every caption text appears in the composition's visible text."""
    path = os.path.join(project_dir, "index.html")
    if not os.path.isfile(path) or not captions:
        return False
    with open(path, "r", encoding="utf-8") as fh:
        html = fh.read()
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html))
    for c in captions:
        needle = re.sub(r"\s+", " ", str(c.get("text", ""))).strip()
        if needle and needle not in text:
            return False
    return True


def _cost_allowed(project_dir: str) -> bool:
    gate = cost_gate.load_gate(cost_gate.gate_id_for(project_dir))
    return bool(gate) and cost_gate.generation_allowed(gate)


def _latest_review_clean(project_dir: str) -> Optional[bool]:
    """True when the newest saved review report has no caption_audio_sync
    findings; False when it has some; None when no report exists or the report
    cannot be verified as current for the selected inputs.

    Read-only: never triggers review, TTS, or state writes. A saved report is
    only trusted when its review fingerprint matches the current selected
    inputs; stale or unverifiable evidence returns None (re-review required)."""
    key = rev_revision.state_key(project_dir)
    reports = sorted(glob.glob(os.path.join(_ROOT, "review", "reports", key + "-rev*.json")))
    if not reports:
        return None
    try:
        with open(reports[-1], "r", encoding="utf-8") as fh:
            report = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(report, dict):
        return None
    # Only trust evidence whose saved selection still matches current content.
    if rev_inputs.freshness_for_saved(project_dir, report).get("status") != "current":
        return None
    findings = report.get("findings")
    if not isinstance(findings, list):
        return None
    coverage = report.get("measurement_status")
    # The caption-sync check must have actually run and completed; an absent or
    # unavailable/partial measurement can never count as clean.
    if not isinstance(coverage, dict) or coverage.get("caption_audio_sync") != "complete":
        return None
    return not any(isinstance(f, dict) and f.get("category") == "caption_audio_sync"
                   for f in findings)


def scene_requirements(model, rules: Dict) -> List[Dict]:
    """Per-scene required duration = max(narration end, caption end, visual
    minimum end) + tail padding. Visual minimum end defaults to
    scene.start + rules.narration_visual_min_seconds."""
    timing = rules.get("timing", {})
    tail = float(timing.get("narration_tail_padding_seconds", 0.0))
    vmin = float(timing.get("narration_visual_min_seconds", 1.0))

    out: List[Dict] = []
    for s in model.scenes:
        lo, hi = s.start * 1000.0, s.end * 1000.0
        w_end = max([float(w["end_ms"]) for w in model.narration_words
                     if w["start_ms"] < hi and w["end_ms"] > lo], default=None)
        c_end = max([float(c["end_ms"]) for c in model.captions
                     if c["start_ms"] < hi and c["end_ms"] > lo], default=None)
        # Word timings are authoritative; only fall back to a narration audio
        # element's end when no spoken words overlap the scene.
        nar_end = w_end
        if nar_end is None:
            for a in model.audio:
                hay = (a.id + " " + a.src).lower()
                if ("narration" in hay or "voice" in hay) and s.start <= a.start < s.end:
                    nar_end = a.end * 1000.0

        visual_min_end = s.start + vmin
        terms = [visual_min_end]
        if nar_end is not None:
            terms.append(nar_end / 1000.0)
        if c_end is not None:
            terms.append(c_end / 1000.0)
        required_end = max(terms) + tail
        required = max(0.0, required_end - s.start)
        out.append({
            "index": s.index, "id": s.id,
            "narration_locked": s.narration_locked,
            "current_duration_s": round(s.duration, 3),
            "narration_end_s": round(nar_end / 1000.0, 3) if nar_end is not None else None,
            "caption_end_s": round(c_end / 1000.0, 3) if c_end is not None else None,
            "visual_min_end_s": round(terms[0], 3),
            "required_duration_s": round(required, 3),
            "delta_s": round(required - s.duration, 3),
            "needs_lengthen": required > s.duration + 1e-6,
        })
    return out


def _step(steps, sid, status, detail, command=None):
    title, kind = next((t, k) for i, t, k in STEP_DEFS if i == sid)
    entry = {"id": sid, "title": title, "kind": kind,
             "status": status, "detail": detail}
    if command:
        entry["command"] = command
    steps.append(entry)


def _build_steps(project_dir, mode, audio, timings_doc, timings_err, captions,
                 reqs, model) -> List[Dict]:
    steps: List[Dict] = []
    if not mode_mod.enabled(mode):
        for sid, _t, _k in STEP_DEFS:
            _step(steps, sid, NA, "narration mode is off")
        return steps

    required = mode == "required"
    have_timings = timings_doc is not None and timings_err is None
    caps_ok = _caps_valid(captions)
    composed = _caption_texts_present(project_dir, captions) if caps_ok else False
    cost_allowed = _cost_allowed(project_dir)
    render = _render_path(project_dir)
    narrated = [r for r in reqs
                if r["narration_end_s"] is not None or r["caption_end_s"] is not None]
    locked = [r for r in narrated if r["narration_locked"]]

    # 1-2 voice generation (paid, gated)
    if audio:
        _step(steps, "tts_generate", DONE, "narration audio: %s" % _rel(audio, project_dir))
        _step(steps, "provider_timestamps", DONE if have_timings else PENDING,
              "timestamps cached: %s" % ("yes" if have_timings else "no"),
              None if have_timings else _TTS_COMMAND)
    else:
        detail = "no narration audio; run the gated Alice TTS with timestamps"
        if required and not cost_allowed:
            detail += " (Gate 1 cost approval required first)"
            _step(steps, "tts_generate", BLOCKED, detail, _TTS_COMMAND)
            _step(steps, "provider_timestamps", BLOCKED, "blocked by step 1", None)
        else:
            _step(steps, "tts_generate", PENDING, detail, _TTS_COMMAND)
            _step(steps, "provider_timestamps", PENDING, "pending step 1", _TTS_COMMAND)

    # 3 normalize
    if have_timings:
        _step(steps, "normalize_timing", DONE,
              "canonical: %d words (provider=%s)" % (len(timings_doc.get("words", [])),
                                                     timings_doc.get("provider")))
    elif timings_err:
        _step(steps, "normalize_timing", BLOCKED, "timing invalid: %s" % timings_err)
    else:
        _step(steps, "normalize_timing", BLOCKED if required else PENDING,
              "no canonical word timings yet", _TTS_COMMAND)

    # 4 phrase groups
    if caps_ok:
        _step(steps, "phrase_groups", DONE, "%d phrase group(s)" % len(captions))
    elif have_timings:
        _step(steps, "phrase_groups", PENDING,
              "group words with timing/phrases (no overlapping phrases)")
    else:
        _step(steps, "phrase_groups", BLOCKED if required else PENDING,
              "needs normalized timings first")

    # 5 mark narrated scenes
    if not narrated:
        _step(steps, "mark_narrated_scenes", BLOCKED if required else PENDING,
              "no narration/caption span to lock yet")
    elif len(locked) == len(narrated):
        _step(steps, "mark_narrated_scenes", DONE,
              "all %d narrated scene(s) marked data-narration-locked=\"true\"" % len(narrated))
    else:
        missing = ", ".join(str(r["index"]) for r in narrated if not r["narration_locked"])
        _step(steps, "mark_narrated_scenes",
              BLOCKED if required else PENDING,
              'scene(s) %s not marked data-narration-locked="true"' % missing)

    # 6 kinetic captions
    if composed:
        _step(steps, "kinetic_captions", DONE,
              "all %d caption text(s) present in the composition" % len(captions))
    elif caps_ok or have_timings:
        _step(steps, "kinetic_captions", PENDING,
              "render one phrase at a time from the phrase groups")
    else:
        _step(steps, "kinetic_captions", BLOCKED if required else PENDING,
              "needs phrase groups first")

    # 7 scene durations
    if not reqs or not narrated:
        _step(steps, "scene_durations", BLOCKED if required else PENDING,
              "no narration span to size scenes against")
    else:
        needs = [r for r in reqs if r["needs_lengthen"]]
        if not needs:
            _step(steps, "scene_durations", DONE,
                  "all scene durations already cover narration/caption + tail")
        else:
            detail = "; ".join("scene %d: %.3f -> %.3fs" %
                               (r["index"], r["current_duration_s"], r["required_duration_s"])
                               for r in needs)
            _step(steps, "scene_durations", PENDING,
                  "lengthen to cover narration/caption + tail — " + detail)

    # 8 caption/audio sync review
    if not (have_timings and caps_ok):
        _step(steps, "caption_sync_review", BLOCKED if required else PENDING,
              "needs timings and captions")
    else:
        clean = _latest_review_clean(project_dir)
        if clean is True:
            _step(steps, "caption_sync_review", DONE, "newest review report has no caption sync findings")
        elif clean is False:
            _step(steps, "caption_sync_review", PENDING,
                  "caption sync findings present — re-run review", _REVIEW_COMMAND)
        else:
            _step(steps, "caption_sync_review", PENDING, "run the deterministic sync review", _REVIEW_COMMAND)

    # 9 render
    if render:
        _step(steps, "render_preview", DONE, "render: %s" % _rel(render, project_dir))
    else:
        # A missing preview is a step to run, not a narration prerequisite.
        _step(steps, "render_preview", PENDING, "no preview render yet", _RENDER_COMMAND)

    # 10 gate 2
    _step(steps, "gate2_human", PENDING,
          "human approval required before applying proposals; never auto-applied")
    return steps


def plan(project_dir: str, rules: Optional[Dict] = None) -> Dict:
    """Read-only narration pipeline plan for a project."""
    mode = mode_mod.load(project_dir)
    model = htmlmodel.parse(project_dir)
    timings_doc, timings_path, timings_err, captions, captions_path = \
        rev_analyzer.narration_for(project_dir, model)
    rules = rules or rev_analyzer.load_rules()
    audio = _narration_audio(project_dir)
    reqs = scene_requirements(model, rules) if mode_mod.enabled(mode) else []
    steps = _build_steps(project_dir, mode, audio, timings_doc, timings_err,
                         captions, reqs, model)
    blocked = any(s["status"] == BLOCKED for s in steps)
    return {
        "project": rev_revision.slug_for(project_dir),
        "project_dir": os.path.abspath(project_dir),
        "mode": mode,
        "enabled": mode_mod.enabled(mode),
        "blocked": blocked,
        "narration": {
            "audio": _rel(audio, project_dir),
            "timings": _rel(timings_path, project_dir),
            "word_count": len((timings_doc or {}).get("words", [])),
            "captions": len(captions) if captions else 0,
            "captions_path": _rel(captions_path, project_dir),
            "error": timings_err,
        },
        "scene_requirements": reqs,
        "steps": steps,
    }


def render_report_md(doc: Dict) -> str:
    L = ["NARRATION MODE", "", "Project: %s" % doc["project"],
         "Mode: %s (%s)" % (doc["mode"], "enabled" if doc["enabled"] else "disabled"), ""]
    if doc["enabled"]:
        n = doc["narration"]
        L.append("Narration: audio=%s words=%d captions=%d" %
                 (n["audio"] or "none", n["word_count"], n["captions"]))
        if n["error"]:
            L.append("  timing error: %s" % n["error"])
        L.append("")
        L.append("Scene durations (max(narration, caption, visual min) + tail):")
        for r in doc["scene_requirements"]:
            flag = "  <-- lengthen" if r["needs_lengthen"] else ""
            L.append("  scene %d: current %.3fs, required %.3fs (narration %s, caption %s)%s"
                     % (r["index"], r["current_duration_s"], r["required_duration_s"],
                        r["narration_end_s"], r["caption_end_s"], flag))
        L.append("")
    L.append("Pipeline:")
    for s in doc["steps"]:
        L.append("  [%-7s] %-22s %s" % (s["status"], s["id"], s["detail"]))
        if s.get("command"):
            L.append("            $ %s" % s["command"].replace("\n", " "))
    L.append("")
    L.append("Blocked: %s" % doc["blocked"])
    L.append("No provider was called; no project, render, or paid resource was modified.")
    return "\n".join(L) + "\n"
