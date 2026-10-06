"""Multimodal visual review interface: rendered frames -> AI JUDGMENT.

Pipeline position:
  Preview render -> deterministic review (analyzer) -> build_inputs()
  -> provider.review(manifest) -> AI_JUDGMENT findings + whitelisted layout
  proposals -> existing Gate 2 (approve / reject / apply to a new revision).

Rules:
  - Findings are AI JUDGMENT (measured=false, no measured_value), never
    MEASURED FACT, and can never become a hard fail.
  - Proposals may only use proposal_schema.VISION_OPERATIONS and start as
    awaiting_review. Nothing is auto-applied.
  - No real provider ships here. Tests and offline runs use FixtureProvider.
    Any provider with requires_payment=True is blocked until the project's
    Cost Gate is approved; pricing stays UNKNOWN until verified.
  - Inputs are written outside the project; the project is never modified.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from typing import Callable, Dict, List, Optional

from . import htmlmodel, proposal_engine, proposal_schema, revision
from .proposal_schema import AI_JUDGMENT, VISION_DIMENSIONS, VISION_OPERATIONS

_HERE = os.path.dirname(os.path.abspath(__file__))
INPUTS_DIR = os.path.join(_HERE, "vision_inputs")
HOOK_TIMES = (0.0, 0.5, 1.0, 1.5)
TRANSITION_OFFSETS = (-0.25, 0.0, 0.25)

INSTRUCTIONS = (
    "Judge only what is visible in the frames. For each dimension return "
    "{dimension, score 1-5, rationale, frames, optional scene, optional "
    "suggested_operation from allowed_operations}. Your output is AI judgment: "
    "it is never a measured fact and never a hard fail. Do not judge factual "
    "accuracy, sources, or Arabic spelling; deterministic checks own those."
)


class CostGateBlocked(RuntimeError):
    pass


class VisionProvider:
    """Interface. `review(manifest)` returns {"provider_model", "judgments": [...]}."""

    name = "abstract"
    model: Optional[str] = None
    requires_payment = True

    def review(self, manifest: Dict) -> Dict:  # pragma: no cover - interface
        raise NotImplementedError


class FixtureProvider(VisionProvider):
    """Offline provider that returns recorded judgments from a JSON file."""

    name = "fixture"
    requires_payment = False

    def __init__(self, path: str):
        self.path = path
        self.model = "fixture"

    def review(self, manifest: Dict) -> Dict:
        with open(self.path, "r", encoding="utf-8") as fh:
            return json.load(fh)


# ---------------------------------------------------------------- inputs

def _run(cmd: List[str], out_path: str) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError("ffmpeg failed for %s: %s" % (os.path.basename(out_path), res.stderr[-300:]))


def _metadata(project_dir: str, model: htmlmodel.CompositionModel) -> Dict:
    meta = {}
    path = os.path.join(project_dir, "meta.json")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    try:
        from design import grammar
        signature = grammar.layout_signature(project_dir)
        scenes = grammar.scene_grammars(project_dir)
    except Exception:
        signature, scenes = None, []
    by_index = {s["index"]: s for s in scenes}
    return {
        "brand": meta.get("brand"),
        "brand_company": meta.get("brandCompany"),
        "format": "landscape" if model.width > model.height else "portrait",
        "width": model.width, "height": model.height, "duration": model.duration,
        "layout_signature": signature,
        "scenes": [{"index": s.index, "start": s.start, "duration": s.duration,
                    "grammar": by_index.get(s.index, {}).get("grammar"),
                    "variant": by_index.get(s.index, {}).get("variant"),
                    "beat_kind": by_index.get(s.index, {}).get("beat_kind"),
                    "text": s.text[:200]} for s in model.scenes],
    }


def build_inputs(project_dir: str, render_path: Optional[str], out_dir: str,
                 frame_width: int = 640) -> Dict:
    """Extract contact sheet, beat midpoints, hook frames (0-1.5s) and
    transition strips from a preview render into out_dir (outside the project)."""
    if not render_path or not os.path.isfile(render_path):
        raise ValueError("a preview render is required for visual review")
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found")
    project_abs, out_abs = os.path.abspath(project_dir), os.path.abspath(out_dir)
    if out_abs == project_abs or out_abs.startswith(project_abs + os.sep):
        raise ValueError("vision inputs must be written outside the project")
    os.makedirs(out_abs, exist_ok=True)
    model = htmlmodel.parse(project_dir)
    last = max(model.duration - 0.04, 0.0)

    def grab(t: float, name: str) -> str:
        out = os.path.join(out_abs, name)
        _run([exe, "-v", "error", "-y", "-ss", "%.3f" % min(max(t, 0.0), last), "-i", render_path,
              "-frames:v", "1", "-vf", "scale=%d:-2" % frame_width, out], out)
        return name

    midpoints = [grab(s.start + s.duration / 2.0, "midpoint-%02d.png" % s.index) for s in model.scenes]
    hooks = [grab(t, "hook-%.2f.png" % t) for t in HOOK_TIMES if t <= last]

    strips = []
    for s in model.scenes[:-1]:
        name = "transition-%02d-%02d.png" % (s.index, s.index + 1)
        cmd = [exe, "-v", "error", "-y"]
        for off in TRANSITION_OFFSETS:
            cmd += ["-ss", "%.3f" % min(max(s.end + off, 0.0), last), "-i", render_path]
        graph = ";".join("[%d:v]scale=%d:-2[v%d]" % (i, frame_width // 2, i) for i in range(3))
        cmd += ["-filter_complex", graph + ";[v0][v1][v2]hstack=inputs=3", "-frames:v", "1",
                os.path.join(out_abs, name)]
        _run(cmd, os.path.join(out_abs, name))
        strips.append(name)

    sheet = None
    if midpoints:
        cols = min(4, len(midpoints))
        rows = int(math.ceil(len(midpoints) / float(cols)))
        sheet = "contact-sheet.png"
        _run([exe, "-v", "error", "-y", "-framerate", "1",
              "-start_number", str(model.scenes[0].index),
              "-i", os.path.join(out_abs, "midpoint-%02d.png"),
              "-vf", "scale=%d:-2,tile=%dx%d:padding=8:color=black" % (frame_width // 2, cols, rows),
              "-frames:v", "1", os.path.join(out_abs, sheet)], os.path.join(out_abs, sheet))

    manifest = {
        "schema_version": 1,
        "project": revision.slug_for(project_dir),
        "render": os.path.basename(render_path),
        "dir": out_abs,
        "contact_sheet": sheet,
        "midpoints": midpoints,
        "hook_frames": hooks,
        "transition_strips": strips,
        "metadata": _metadata(project_dir, model),
        "dimensions": list(VISION_DIMENSIONS),
        "allowed_operations": sorted(VISION_OPERATIONS),
        "instructions": INSTRUCTIONS,
    }
    with open(os.path.join(out_abs, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    return manifest


# ---------------------------------------------------------------- lean critic pack
#
# Input for the optional read-only visual critic (.claude/agents/visual-critic.md):
# exactly three composite images plus a short fact digest. The critic reads
# only these files; it never browses the project. Deterministic diagnostics
# are handed over as measured facts so the critic spends no effort finding them.

SERIES_CONSTRAINTS = (
    "Arabic-first, RTL; no Arabic diacritics; English product/technical names may stay Latin.",
    "Primary distribution: X, watched on phones, often muted, in a feed.",
    "Official, owned or licensed assets only; no invented UI, facts or metrics; drawn graphics allowed.",
    "Silent by default unless the brief requests sound (sound is out of scope for the critic).",
)
CRITIC_SHEET_TILES = 30
CRITIC_KEYS_MAX = 8
CRITIC_BOUNDARIES_MAX = 8
CRITIC_STRIP_OFFSETS = (-0.2, -0.1, 0.0, 0.1, 0.2)


def _tile_times(exe: str, render_path: str, times: List[float], out_path: str,
                w: int, h: int, cols: int) -> None:
    rows = int(math.ceil(len(times) / float(cols)))
    cmd = [exe, "-v", "error", "-y"]
    for t in times:
        cmd += ["-ss", "%.3f" % t, "-i", render_path]
    graph = "".join("[%d:v]scale=%d:%d,setsar=1[v%d];" % (i, w, h, i) for i in range(len(times)))
    pads = cols * rows - len(times)
    if pads:
        cmd += ["-f", "lavfi", "-i", "color=c=black:s=%dx%d:d=0.1" % (w, h)]
        graph += "[%d:v]split=%d%s;" % (len(times), pads, "".join("[p%d]" % i for i in range(pads)))
    inputs = "".join("[v%d]" % i for i in range(len(times))) + "".join("[p%d]" % i for i in range(pads))
    graph += "%sxstack=inputs=%d:grid=%dx%d[o]" % (inputs, cols * rows, cols, rows)
    cmd += ["-filter_complex", graph, "-map", "[o]", "-frames:v", "1", "-q:v", "4", out_path]
    _run(cmd, out_path)


def _even(values: List[float], limit: int) -> List[float]:
    if len(values) <= limit:
        return values
    return [values[int(round(i * (len(values) - 1) / float(limit - 1)))] for i in range(limit)]


def _measured_facts(render_path: str, model: htmlmodel.CompositionModel, px: Dict) -> List[str]:
    from . import pixels
    diag = px.get("diagnostics") or {}
    fps = float(diag.get("fps", 10))
    facts = []
    still = pixels.near_still(render_path, model.width, model.height, fps=fps,
                              threshold=float(diag.get("near_still_threshold", 0.05)),
                              min_hold=float(diag.get("hold_report_seconds", 0.6)),
                              content_crop=px.get("freeze_content_crop"))
    if still:
        holds = sorted(still["holds"], key=lambda r: -r["duration"])[:6]
        facts.append("near-still %.1fs of %.1fs; holds > 0.6s: %s" % (
            still["near_still_seconds"], model.duration,
            ", ".join("%.1f-%.1f" % (r["start"], r["end"]) for r in holds) or "none"))
    cov = pixels.coverage_series(render_path, model.width, model.height, model.duration, fps=fps)
    if cov:
        spans = pixels.empty_spans(cov, fps, float(diag.get("empty_frame_coverage", 0.01)), 0.5)
        facts.append("near-empty frames: %s" % (
            ", ".join("%.1f-%.1f" % (sp["start"], sp["end"]) for sp in spans) or "none"))
        dips = [d for d in pixels.boundary_dips(
            cov, fps, [s.start for s in model.scenes[1:]],
            window=float(diag.get("boundary_window_seconds", 0.6)),
            ratio=float(diag.get("boundary_dip_ratio", 0.35))) if d["dip"]]
        facts.append("coverage dips at scene boundaries: %s" % (
            ", ".join("%.1fs" % d["at"] for d in dips) or "none"))
    return facts


def build_critic_pack(project_dir: str, render_path: str, out_dir: str) -> Dict:
    """Write 1_sheet.jpg, 2_keys.jpg, 3_transitions.jpg and pack.md to out_dir
    (outside the project) for one explicitly named render."""
    if not render_path or not os.path.isfile(render_path):
        raise ValueError("an explicit render is required for the critic pack")
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found")
    project_abs, out_abs = os.path.abspath(project_dir), os.path.abspath(out_dir)
    if out_abs == project_abs or out_abs.startswith(project_abs + os.sep):
        raise ValueError("critic pack must be written outside the project")
    os.makedirs(out_abs, exist_ok=True)
    model = htmlmodel.parse(project_dir)
    dur, last = model.duration, max(model.duration - 0.04, 0.0)
    landscape = model.width >= model.height
    tw, th = (320, 180) if landscape else (180, 320)
    kw, kh = (640, 360) if landscape else (360, 640)
    clamp = lambda t: min(max(t, 0.0), last)

    step = max(1.0, dur / float(CRITIC_SHEET_TILES))
    sheet_times = [clamp(i * step) for i in range(int(dur / step + 1e-6)) if i * step <= last]
    _tile_times(exe, render_path, sheet_times, os.path.join(out_abs, "1_sheet.jpg"), tw, th, 6)

    key_times = _even([0.0] + [clamp(s.start + s.duration / 2.0) for s in model.scenes], CRITIC_KEYS_MAX)
    _tile_times(exe, render_path, key_times, os.path.join(out_abs, "2_keys.jpg"), kw, kh,
                3 if landscape else 4)

    bounds = [s.start for s in model.scenes[1:]] or [dur * f for f in (0.25, 0.5, 0.75)]
    bounds = _even(bounds, CRITIC_BOUNDARIES_MAX)
    strip_times = [clamp(b + d) for b in bounds for d in CRITIC_STRIP_OFFSETS]
    _tile_times(exe, render_path, strip_times, os.path.join(out_abs, "3_transitions.jpg"), tw, th,
                len(CRITIC_STRIP_OFFSETS))

    meta = {}
    if os.path.isfile(os.path.join(project_dir, "meta.json")):
        with open(os.path.join(project_dir, "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
    manifest = meta.get("design_manifest") or {}
    vt, brand = manifest.get("video_type") or {}, manifest.get("brand") or {}
    try:
        from design import grammar
        kinds = {g["index"]: g.get("beat_kind") for g in grammar.scene_grammars(project_dir)}
    except Exception:
        kinds = {}
    from . import analyzer
    rules_px = analyzer.load_rules().get("pixels", {})
    lines = [
        "# Critic pack",
        "",
        "Read: 1_sheet.jpg, 2_keys.jpg, 3_transitions.jpg",
        "",
        "## Images",
        "- 1_sheet.jpg — one frame every %.1fs, left→right then top→bottom; tile n = t %.1f×n s." % (step, step),
        "- 2_keys.jpg — frames at t = %s s (left→right, top→bottom)." % ", ".join("%.2f" % t for t in key_times),
        "- 3_transitions.jpg — one row per boundary (%s s); each row = frames at %s s around it." % (
            ", ".join("%.2f" % b for b in bounds), ", ".join("%+.1f" % d for d in CRITIC_STRIP_OFFSETS)),
        "",
        "## Video",
        "- %s, %dx%d, %.1fs; type %s." % ("16:9" if landscape else "9:16", model.width, model.height, dur,
                                           vt.get("type") or "unknown"),
        "- Subject: %s" % (brand.get("subject") or brand.get("product") or "unknown"),
        "- Audience: %s" % (vt.get("primary_audience") or "unknown"),
        "- Job for the viewer: %s" % (vt.get("primary_job_to_be_done") or "unknown"),
        "",
        "## Beats (from the composition)",
    ]
    for s in model.scenes:
        lines.append("- %.1f-%.1fs · %s · %s" % (s.start, s.end, kinds.get(s.index) or "beat",
                                                  " ".join(s.text.split())[:110]))
    lines += ["", "## Series constraints"] + ["- " + c for c in SERIES_CONSTRAINTS]
    lines += ["", "## Measured facts (deterministic, not verdicts; any pixel change counts as motion)"]
    lines += ["- " + f for f in _measured_facts(render_path, model, rules_px)]
    with open(os.path.join(out_abs, "pack.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return {"dir": out_abs, "files": ["1_sheet.jpg", "2_keys.jpg", "3_transitions.jpg", "pack.md"],
            "render": os.path.basename(render_path), "sheet_step": step, "key_times": key_times,
            "boundaries": bounds}


PAIR_DIMENSIONS = ("Hook", "Visual storytelling", "Composition", "Meaningful motion", "Continuity",
                   "Pacing", "Visual hierarchy", "Scene variety", "Visual payoff", "Overall execution")


def _probe_duration(render_path: str) -> float:
    from . import process
    return float(process.probe_media(render_path).get("format", {}).get("duration") or 0)


def build_pair_pack(project_dir: str, render_a: str, render_b: str, out_dir: str,
                    swap: Optional[bool] = None) -> Dict:
    """Blind pairwise pack: a sheet and six evenly spaced key frames per render,
    labelled Video A / Video B in random order. The mapping is sealed in
    <out_dir>.mapping.json, outside the pack, and never printed."""
    import secrets
    for r in (render_a, render_b):
        if not r or not os.path.isfile(r):
            raise ValueError("two explicit renders are required for a pairwise pack")
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found")
    project_abs, out_abs = os.path.abspath(project_dir), os.path.abspath(out_dir).rstrip(os.sep)
    if out_abs == project_abs or out_abs.startswith(project_abs + os.sep):
        raise ValueError("pairwise pack must be written outside the project")
    os.makedirs(out_abs, exist_ok=True)
    model = htmlmodel.parse(project_dir)
    landscape = model.width >= model.height
    tw, th = (320, 180) if landscape else (180, 320)
    kw, kh = (640, 360) if landscape else (360, 640)
    if swap is None:
        swap = secrets.randbelow(2) == 1
    order = [render_b, render_a] if swap else [render_a, render_b]
    legend = []
    for label, render in zip("AB", order):
        dur = _probe_duration(render)
        last = max(dur - 0.04, 0.0)
        step = max(1.0, dur / float(CRITIC_SHEET_TILES))
        sheet = [min(i * step, last) for i in range(int(dur / step + 1e-6)) if i * step <= last]
        _tile_times(exe, render, sheet, os.path.join(out_abs, "%s_sheet.jpg" % label), tw, th, 6)
        keys = [min(dur * i / 6.0, last) for i in range(6)]
        _tile_times(exe, render, keys, os.path.join(out_abs, "%s_keys.jpg" % label), kw, kh,
                    3 if landscape else 6)
        legend.append("- Video %s: %.1fs. %s_sheet.jpg = one frame every %.1fs (left→right, top→bottom); "
                      "%s_keys.jpg = frames at t = %s s." % (label, dur, label, step, label,
                                                              ", ".join("%.1f" % t for t in keys)))
    meta = {}
    if os.path.isfile(os.path.join(project_dir, "meta.json")):
        with open(os.path.join(project_dir, "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
    vt = (meta.get("design_manifest") or {}).get("video_type") or {}
    lines = ["# Critic pack", "", "Mode: pairwise", "Read: A_sheet.jpg, A_keys.jpg, B_sheet.jpg, B_keys.jpg", "",
             "Two renders of the same video: same brief, same facts, different visual execution.", ""]
    lines += legend
    lines += ["", "## Video", "- Type %s. Job for the viewer: %s" % (
        vt.get("type") or "unknown", vt.get("primary_job_to_be_done") or "unknown"),
        "", "## Series constraints"] + ["- " + c for c in SERIES_CONSTRAINTS]
    lines += ["", "## Dimensions", ", ".join(PAIR_DIMENSIONS)]
    with open(os.path.join(out_abs, "pack.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    mapping_path = out_abs + ".mapping.json"
    with open(mapping_path, "w", encoding="utf-8") as fh:
        json.dump({"A": os.path.abspath(order[0]), "B": os.path.abspath(order[1])}, fh)
    return {"dir": out_abs, "mapping_path": mapping_path,
            "files": ["A_keys.jpg", "A_sheet.jpg", "B_keys.jpg", "B_sheet.jpg", "pack.md"]}


# ---------------------------------------------------------------- cost gate hook

def image_count(manifest: Dict) -> int:
    return (len(manifest["midpoints"]) + len(manifest["hook_frames"])
            + len(manifest["transition_strips"]) + (1 if manifest.get("contact_sheet") else 0))


def cost_plan_items(manifest: Dict, provider: str, model: str) -> List[Dict]:
    """Cost Gate plan items for a future paid multimodal review. Priced only
    from costgate/pricing.json; UNKNOWN until a verified price is recorded."""
    return [{"asset_type": "external_api", "provider": provider, "model": model,
             "unit_basis": "image", "quantity": image_count(manifest),
             "pricing_ref": "%s.%s.image" % (provider, model)}]


def require_cost_approval(project_dir: str) -> None:
    from costgate import gate as cost_gate
    doc = cost_gate.load_gate(cost_gate.gate_id_for(project_dir))
    if not doc or not cost_gate.generation_allowed(doc):
        raise CostGateBlocked("multimodal review is a paid call: approve the project's Cost Gate "
                              "first (pricing is UNKNOWN until verified)")


# ---------------------------------------------------------------- review

def visual_quality_score(findings: List[Dict]) -> Optional[float]:
    """0..15 visual quality from AI judgment scores (1..5). None when absent."""
    scores = [f["judgment"]["score"] for f in findings if f.get("basis") == AI_JUDGMENT]
    if not scores:
        return None
    return round(sum(scores) / len(scores) / 5.0 * 15.0, 1)


def run_visual_review(project_dir: str, manifest: Dict, provider: VisionProvider,
                      gate_check: Callable[[str], None] = require_cost_approval) -> Dict:
    if provider.requires_payment:
        gate_check(project_dir)
    raw = provider.review(manifest) or {}
    model = htmlmodel.parse(project_dir)
    state = revision.get_or_init_state(project_dir)
    findings: List[Dict] = []
    proposals: List[Dict] = []
    notes: List[str] = []

    for i, j in enumerate(raw.get("judgments", []), 1):
        dim = j.get("dimension")
        if dim not in VISION_DIMENSIONS:
            notes.append("judgment %d skipped: unsupported dimension %r" % (i, dim))
            continue
        try:
            score = float(j.get("score"))
        except (TypeError, ValueError):
            notes.append("judgment %d skipped: missing score" % i)
            continue
        if not 1 <= score <= 5:
            notes.append("judgment %d skipped: score outside 1..5" % i)
            continue
        if j.get("hard_fail"):
            notes.append("judgment %d: hard_fail ignored (AI judgment can never hard-fail)" % i)
        rationale = str(j.get("rationale", ""))
        confidence = min(max(float(j.get("confidence", 0.5)), 0.0), 1.0)
        finding = {
            "id": "visual-%03d" % (len(findings) + 1),
            "category": "visual_judgment",
            "basis": AI_JUDGMENT,
            "severity": "medium" if score <= 2 else "low",
            "scene": j.get("scene"),
            "evidence": {"measured_value": None, "unit": "judgment",
                         "source": "multimodal:%s" % provider.name},
            "description": "[AI JUDGMENT] %s: %s" % (dim, rationale),
            "confidence": confidence,
            "measured": False,
            "hard_fail": False,
            "judgment": {"dimension": dim, "score": score, "rationale": rationale,
                         "frames": [str(x) for x in j.get("frames", [])]},
        }
        proposal_schema.validate_finding(finding)
        findings.append(finding)

        op = j.get("suggested_operation")
        if not op:
            continue
        if not isinstance(op, dict) or op.get("type") not in VISION_OPERATIONS:
            notes.append("judgment %d: suggested operation %r rejected (not in the layout whitelist)"
                         % (i, op.get("type") if isinstance(op, dict) else op))
            continue
        try:
            sim = proposal_engine.simulate(model, op)
        except proposal_engine.SimulationError as exc:
            notes.append("judgment %d: no proposal (%s)" % (i, exc))
            continue
        proposal = {
            "id": "visual-proposal-%03d" % (len(proposals) + 1),
            "project_revision": int(state["revision"]),
            "project_hash": state["content_hash"],
            "finding_id": finding["id"],
            "scene": j.get("scene"),
            "title": "%s: %s" % (dim.replace("_", " "), op["type"].replace("_", " ")),
            "rationale": rationale,
            "operation": op,
            "duration_before": sim["duration_before"],
            "duration_after": sim["duration_after"],
            "warnings": sim["warnings"],
            "confidence": confidence,
            "status": "awaiting_review",
            "origin": "multimodal",
            "basis": {"measured_facts": [], "judgment": rationale, "kind": AI_JUDGMENT},
        }
        proposal_schema.validate_proposal(proposal)
        proposals.append(proposal)

    visual = visual_quality_score(findings)
    return {
        "provider": provider.name,
        "model": raw.get("provider_model") or provider.model,
        "findings": findings,
        "proposals": proposals,
        "notes": notes,
        "visual_quality": ({"score": visual, "max": 15, "source": "multimodal_review"}
                           if visual is not None else None),
        "auto_applied": False,
    }


def render_vision_md(result: Dict) -> str:
    L = ["AI VISUAL REVIEW (multimodal)", "",
         "Provider: %s (%s)" % (result["provider"], result.get("model")),
         "All findings below are AI JUDGMENT, not MEASURED FACT. None can hard-fail.", "",
         "Findings: %d" % len(result["findings"]), ""]
    by_finding = {p["finding_id"]: p for p in result["proposals"]}
    for i, f in enumerate(result["findings"], 1):
        j = f["judgment"]
        L.append("[%d] AI JUDGMENT — %s  score %.1f/5" % (i, j["dimension"], j["score"]))
        if f.get("scene") is not None:
            L.append("Scene %s" % f["scene"])
        L.append("Rationale: %s" % j["rationale"])
        p = by_finding.get(f["id"])
        if p:
            L.append("Proposal: %s — %s" % (p["id"], json.dumps(p["operation"], ensure_ascii=False)))
            L.append("Status: %s (requires human approval)" % p["status"])
        L.append("")
    if result.get("visual_quality"):
        vq = result["visual_quality"]
        L.append("Visual quality (from multimodal review): %.1f/%d" % (vq["score"], vq["max"]))
    if result["notes"]:
        L.append("Notes:")
        L.extend("- %s" % n for n in result["notes"])
    L.append("")
    L.append("No changes have been applied.")
    return "\n".join(L) + "\n"
