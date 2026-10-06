"""Scene-grammar registry, layout signature, and the no-repeat advisory.

stdlib only. Reads project files and run records; never writes them.
"""

from __future__ import annotations

import glob
import json
import os
import re
from typing import Dict, List, Optional

from . import typography

REGISTRY_PATH = os.path.join(typography.TEMPLATE_DIR, "lib", "grammars.json")
REQUIRED_GRAMMARS = (
    "full_bleed_media", "split_media_text", "big_number", "kinetic_word",
    "screenshot_detail", "progressive_list", "comparison", "quote_or_statement",
)
LEGACY = "legacy_card"
_FIELDS = ("name", "layout", "media_treatment", "typography", "rtl", "variants", "formats",
           "entry", "exit", "camera", "callouts", "suitable_for", "unsuitable_for",
           "use_cases", "avoid")


def load_registry(path: str = REGISTRY_PATH) -> Dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_registry(reg: Dict) -> List[str]:
    """Problems in the registry (empty list = valid)."""
    problems: List[str] = []
    grammars, motions = reg.get("grammars", {}), reg.get("motions", {})
    chore, kinds = reg.get("choreography", {}), set(reg.get("beat_kinds", []))
    for gid in REQUIRED_GRAMMARS:
        if gid not in grammars:
            problems.append("missing grammar %s" % gid)
    for gid, g in grammars.items():
        if not re.fullmatch(r"[a-z][a-z_]*", gid):
            problems.append("%s: invalid id" % gid)
        missing = [f for f in _FIELDS if f not in g]
        if missing:
            problems.extend("%s: missing field %s" % (gid, f) for f in missing)
            continue
        for role, key in (("entry", "entry"), ("exit", "exit"), ("camera", "camera")):
            for m in g[key]:
                if m not in motions:
                    problems.append("%s: unknown motion %s" % (gid, m))
                elif role not in motions[m]["role"]:
                    problems.append("%s: motion %s is not an %s motion" % (gid, m, role))
        if not g["entry"] or not g["exit"]:
            problems.append("%s: needs at least one entry and one exit motion" % gid)
        if len(g["entry"]) > 3 or len(g["exit"]) > 2:
            problems.append("%s: too many motion options (restraint: <=3 entry, <=2 exit)" % gid)
        for c in g["callouts"]:
            if c not in chore:
                problems.append("%s: unknown choreography %s" % (gid, c))
        if not g["variants"]:
            problems.append("%s: no variants" % gid)
        if not str(g["rtl"]).strip():
            problems.append("%s: missing RTL behavior" % gid)
        if set(g["formats"]) - {"portrait", "landscape"}:
            problems.append("%s: unknown format" % gid)
        bad = (set(g["suitable_for"]) | set(g["unsuitable_for"])) - kinds
        if bad:
            problems.append("%s: unknown beat kinds %s" % (gid, sorted(bad)))
        if set(g["suitable_for"]) & set(g["unsuitable_for"]):
            problems.append("%s: beat kind both suitable and unsuitable" % gid)
        if not g["suitable_for"]:
            problems.append("%s: no suitable beat kinds" % gid)
    return problems


def candidates(beat_kind: str, reg: Optional[Dict] = None) -> List[str]:
    """Grammars suited to a beat kind, in registry order (deterministic)."""
    reg = reg or load_registry()
    return [gid for gid, g in reg["grammars"].items() if beat_kind in g["suitable_for"]]


# ---------------------------------------------------------------- project reading

def _attrs(tag: str) -> Dict[str, str]:
    return dict(re.findall(r'([\w:-]+)\s*=\s*"([^"]*)"', tag))


def scene_grammars(project_dir: str) -> List[Dict]:
    with open(os.path.join(project_dir, "index.html"), "r", encoding="utf-8") as fh:
        html = fh.read()
    out = []
    for tag in re.findall(r"<section\b[^>]*>", html):
        a = _attrs(tag)
        if "clip" not in a.get("class", "").split():
            continue
        out.append({
            "index": len(out) + 1, "id": a.get("id"),
            "grammar": a.get("data-grammar"), "variant": a.get("data-variant"),
            "beat_kind": a.get("data-beat-kind"),
            "start": float(a.get("data-start", 0) or 0),
            "duration": float(a.get("data-duration", 0) or 0),
        })
    return out


def layout_signature(project_dir: str) -> Dict:
    """Ordered grammar ids of a composition. Unannotated clips are legacy_card."""
    scenes = scene_grammars(project_dir)
    sig = [s["grammar"] or LEGACY for s in scenes]
    annotated = sum(1 for s in scenes if s["grammar"])
    source = ("data-grammar" if scenes and annotated == len(scenes)
              else "legacy_unannotated" if annotated == 0 else "mixed")
    return {"signature": sig, "source": source}


def validate_project(project_dir: str, reg: Optional[Dict] = None) -> Dict:
    """Errors (unknown ids/variants) and advisories (beat kind fit)."""
    reg = reg or load_registry()
    width, height = typography.composition_size(project_dir)
    fmt = typography.format_for(width, height) if width else None
    errors, advisories = [], []
    for s in scene_grammars(project_dir):
        gid = s["grammar"]
        if not gid:
            continue
        g = reg["grammars"].get(gid)
        if g is None:
            errors.append("scene %d: unknown grammar %s" % (s["index"], gid))
            continue
        if s["variant"] and s["variant"] not in g["variants"]:
            errors.append("scene %d: variant %s not in %s" % (s["index"], s["variant"], g["variants"]))
        if fmt and fmt not in g["formats"]:
            errors.append("scene %d: %s does not support %s" % (s["index"], gid, fmt))
        kind = s["beat_kind"]
        if kind and kind not in reg["beat_kinds"]:
            errors.append("scene %d: unknown beat kind %s" % (s["index"], kind))
        elif kind in g["unsuitable_for"]:
            advisories.append("scene %d: %s is unsuitable for a %s beat; consider %s"
                              % (s["index"], gid, kind, ", ".join(candidates(kind, reg)) or "another grammar"))
    return {"format": fmt, "errors": errors, "advisories": advisories}


# ---------------------------------------------------------------- novelty

def similarity(a: List[str], b: List[str]) -> float:
    """Ordered similarity: longest common subsequence / longest length."""
    if not a or not b:
        return 0.0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return round(prev[-1] / float(max(len(a), len(b))), 3)


def _slug(run_id: str) -> str:
    return re.sub(r"^\d{4}-\d{2}-\d{2}-", "", run_id or "")


def _same_story(a: str, b: str) -> bool:
    base = lambda s: re.sub(r"-(v\d+|rev\d+)$", "", s)
    return base(a) == base(b)


def novelty_advisory(project_dir: str, runs_dir: str, videos_dir: Optional[str] = None,
                     window: int = 3, threshold: float = 0.75,
                     reg: Optional[Dict] = None) -> Dict:
    """Advisory only: does this layout sequence repeat the last `window`
    comparable videos (same format, different story)? Never a hard fail."""
    reg = reg or load_registry()
    mine = layout_signature(project_dir)
    sig = mine["signature"]
    width, height = typography.composition_size(project_dir)
    fmt = typography.format_for(width, height)
    slug = os.path.basename(os.path.abspath(project_dir))
    kinds = [s["beat_kind"] for s in scene_grammars(project_dir)]

    compared = []
    for path in sorted(glob.glob(os.path.join(runs_dir, "*.json")), reverse=True):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                run = json.load(fh)
        except (OSError, ValueError):
            continue
        run_id = run.get("run_id") or os.path.splitext(os.path.basename(path))[0]
        rslug = _slug(run_id)
        if _same_story(rslug, slug):
            continue
        other, ofmt = run.get("layout_signature"), run.get("format")
        pdir = os.path.join(videos_dir, rslug) if videos_dir else None
        if pdir and os.path.isfile(os.path.join(pdir, "index.html")):
            if not other:
                other = layout_signature(pdir)["signature"]
            if not ofmt:
                w, h = typography.composition_size(pdir)
                ofmt = typography.format_for(w, h) if w else None
        if not other or ofmt != fmt:
            continue
        compared.append({"run_id": run_id, "signature": other, "similarity": similarity(sig, other)})
        if len(compared) >= window:
            break

    advisories, suggestions = [], []
    for c in compared:
        if c["signature"] == sig:
            advisories.append({"type": "repeat", "run_id": c["run_id"],
                               "message": "Same layout sequence as %s." % c["run_id"]})
        elif c["similarity"] >= threshold:
            advisories.append({"type": "near_repeat", "run_id": c["run_id"],
                               "message": "Layout sequence %.0f%% similar to %s."
                                          % (c["similarity"] * 100, c["run_id"])})
    if sig and len(compared) == window and all(c["signature"][:1] == sig[:1] for c in compared):
        advisories.append({"type": "hook_repeat", "run_id": None,
                           "message": "Opening grammar %s matches the last %d videos." % (sig[0], window)})
    if advisories:
        repeated = {i for c in compared for i, g in enumerate(sig)
                    if i < len(c["signature"]) and c["signature"][i] == g}
        for i in sorted(repeated):
            kind = kinds[i] if i < len(kinds) else None
            alts = [g for g in candidates(kind, reg) if g != sig[i]] if kind else []
            if alts:
                suggestions.append({"scene": i + 1, "beat_kind": kind, "current": sig[i],
                                    "alternatives": alts})
    return {"signature": sig, "signature_source": mine["source"], "format": fmt,
            "window": window, "compared": compared, "advisories": advisories,
            "suggestions": suggestions, "advisory_only": True}
