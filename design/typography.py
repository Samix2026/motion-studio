"""Typography checks (stdlib only).

- static_font_report: is the primary Arabic family the REQUIRED one (the
  project's type-scale / brief), and is it a bundled local file, a
  system-only face (falls back in headless Chrome), or undeclared?
- render_font_check: prove the face loads in the real render browser by
  parsing `hyperframes snapshot` font diagnostics (no vision call, no writes
  to the project).
- mobile_readability: rendered size of text roles at phone scale.

Reads project files only; never modifies them.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(_ROOT, "templates", "tech-news-ar")
SCALE_PATH = os.path.join(TEMPLATE_DIR, "lib", "type-scale.json")

# CSS class -> type role. `t-*` classes come from lib/type.css; the rest are
# the legacy template classes so older projects are measured too.
CLASS_ROLES = {
    "t-secondary": "secondary", "sub": "secondary", "note": "secondary",
    "shotcap": "secondary", "wcap": "secondary",
    "t-caption": "caption", "chip": "caption",
    # Timed subtitles only: the `subtitle` role has a lower phone-scale floor
    # (see type-scale.json -> readability_policy). This is a caption-specific
    # exception; general secondary UI text keeps the `secondary` floor.
    "subtitle": "subtitle",
    "t-credit": "credit", "credit": "credit", "src": "credit",
    "t-headline": "headline", "headline": "headline",
}


def load_scale(path: str = SCALE_PATH) -> Dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def format_for(width: int, height: int) -> str:
    return "landscape" if width > height else "portrait"


# ---------------------------------------------------------------- css collection

def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def collect_css(project_dir: str) -> List[Tuple[str, str]]:
    """Return [(base_dir, css_text)] for inline <style> blocks and linked local
    stylesheets. Remote stylesheets are ignored (they are not deterministic).
    url() in a linked stylesheet resolves against that stylesheet's directory
    (browser semantics), which is why bundled @font-face rules stay inline."""
    html = _read(os.path.join(project_dir, "index.html"))
    out = [(project_dir, s) for s in re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)]
    for tag in re.findall(r"<link\b[^>]*>", html):
        if "stylesheet" not in tag:
            continue
        m = re.search(r'href="([^"]+)"', tag)
        if not m or re.match(r"^(https?:)?//", m.group(1)):
            continue
        path = os.path.normpath(os.path.join(project_dir, m.group(1)))
        if os.path.isfile(path):
            out.append((os.path.dirname(path), _read(path)))
    return out


def composition_size(project_dir: str) -> Tuple[int, int]:
    html = _read(os.path.join(project_dir, "index.html"))
    for tag in re.findall(r"<div\b[^>]*>", html):
        if "data-composition-id" in tag:
            w = re.search(r'data-width="([0-9.]+)"', tag)
            h = re.search(r'data-height="([0-9.]+)"', tag)
            if w and h:
                return int(float(w.group(1))), int(float(h.group(1)))
    return 0, 0


def _strip_family(value: str) -> str:
    return value.strip().strip("\"'").strip()


def font_faces(css: List[Tuple[str, str]]) -> List[Dict]:
    faces = []
    for base, text in css:
        for body in re.findall(r"@font-face\s*\{(.*?)\}", text, re.S):
            fam = re.search(r"font-family\s*:\s*([^;]+)(?:;|$)", body)
            if not fam:
                continue
            src_m = re.search(r"src\s*:\s*([^;]+)(?:;|$)", body)
            src = src_m.group(1) if src_m else ""
            urls = [os.path.normpath(os.path.join(base, u))
                    for u in re.findall(r"url\(\s*[\"']?([^\"')]+)[\"']?\s*\)", src)
                    if not re.match(r"^(https?:|data:)", u)]
            weight = re.search(r"font-weight\s*:\s*([0-9]+)", body)
            faces.append({
                "family": _strip_family(fam.group(1)),
                "weight": int(weight.group(1)) if weight else 400,
                "urls": urls,
                "local": re.findall(r"local\(\s*[\"']?([^\"')]+)[\"']?\s*\)", src),
            })
    return faces


def primary_family(css: List[Tuple[str, str]]) -> Optional[str]:
    """First family of --font-ar / --ms-font, else of body font-family."""
    joined = "\n".join(t for _b, t in css)
    for var in ("--font-ar", "--ms-font"):
        m = re.search(r"%s\s*:\s*([^;}]+)" % re.escape(var), joined)
        if m:
            first = m.group(1).split(",")[0]
            if not first.strip().startswith("var("):
                return _strip_family(first)
    m = re.search(r"body\s*\{[^}]*font-family\s*:\s*([^;}]+)", joined, re.S)
    if m and not m.group(1).strip().startswith("var("):
        return _strip_family(m.group(1).split(",")[0])
    return None


def required_family(project_dir: str) -> Tuple[Optional[str], Optional[str]]:
    """(family, source) the project must use as its primary Arabic family.

    `meta.json` → `production.typography` (a family name, or {"family": ...}) is
    an explicit override; otherwise the project's own `lib/type-scale.json`
    (copied from its template) declares it. (None, None) for legacy projects
    that declare neither."""
    try:
        with open(os.path.join(project_dir, "meta.json"), encoding="utf-8") as fh:
            typo = (json.load(fh).get("production") or {}).get("typography")
    except (OSError, ValueError, AttributeError):
        typo = None
    if isinstance(typo, dict):
        typo = typo.get("family")
    if isinstance(typo, str) and typo.strip():
        return typo.strip(), "meta.production.typography"
    try:
        family = load_scale(os.path.join(project_dir, "lib", "type-scale.json"))["font"]["family"]
        return family, "lib/type-scale.json"
    except (OSError, ValueError, KeyError, TypeError):
        return None, None


def static_font_report(project_dir: str) -> Dict:
    css = collect_css(project_dir)
    faces = font_faces(css)
    family = primary_family(css)
    required, required_source = required_family(project_dir)
    mine = [f for f in faces if f["family"] == family]
    missing = [u for f in mine for u in f["urls"] if not os.path.isfile(u)]
    with_files = [f for f in mine if f["urls"]]
    if with_files and not missing:
        status = "bundled"
    elif missing:
        status = "missing_file"
    elif mine:
        status = "system_only"
    else:
        status = "undeclared"
    # required → declared primary → bundled → (render check) loaded
    wrong = bool(required) and family != required
    if wrong:
        status = "wrong_family"
    return {
        "required_family": required,
        "required_source": required_source,
        "primary_family": family,
        "status": status,
        "fallback_risk": status != "bundled",
        "weights": sorted({f["weight"] for f in with_files}),
        "missing_files": missing,
        "system_faces": sorted({n for f in faces for n in f["local"]}),
    }


# ---------------------------------------------------------------- render check

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_FONTS = re.compile(r"Fonts:\s*(\d+)\s+loaded(?:,\s*(\d+)\s+failed)?")
_FAILED = re.compile(r"Fonts FAILED:\s*(.+)")


def parse_snapshot_font_log(text: str) -> Optional[Dict]:
    """Parse `hyperframes snapshot` font diagnostics. None when absent."""
    text = _ANSI.sub("", text or "")
    m = _FONTS.search(text)
    if not m:
        return None
    failed = []
    fm = _FAILED.search(text)
    if fm:
        failed = [name.strip() for name, _desc in
                  re.findall(r"([^,()]+?)\s*\(([^)]*)\)", fm.group(1))]
    return {"loaded": int(m.group(1)), "failed": int(m.group(2) or 0),
            "failed_families": failed}


def render_font_check(project_dir: str, at: float = 0.5, timeout: int = 300) -> Dict:
    """Load the composition in the HyperFrames render browser and report whether
    the required family is the primary one, is bundled, and every declared face loaded. Snapshots go to a temp dir that is deleted.
    `--describe false` and a GEMINI-free environment guarantee no vision call."""
    npx = shutil.which("npx")
    static = static_font_report(project_dir)
    if not npx:
        return {"status": "unavailable", "reason": "npx not found", "static": static}
    from studio import trace  # the project's pinned runtime, else the known-good one
    version = trace.pinned_version(project_dir) or trace.HYPERFRAMES_VERSION
    env = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI")}
    out_dir = tempfile.mkdtemp(prefix="ms-fontcheck-")
    try:
        res = subprocess.run(
            [npx, "--yes", "hyperframes@%s" % version, "snapshot", os.path.abspath(project_dir),
             "--at", str(at), "--no-end", "--describe", "false", "-o", out_dir],
            capture_output=True, text=True, timeout=timeout, env=env)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    log = parse_snapshot_font_log((res.stdout or "") + (res.stderr or ""))
    if log is None:
        return {"status": "unavailable", "reason": "no font diagnostics in snapshot output",
                "static": static}
    primary = static["primary_family"] or ""
    primary_failed = any(f == primary for f in log["failed_families"])
    loaded = log["loaded"] > 0 and log["failed"] == 0 and static["status"] == "bundled"
    status = "wrong_family" if static["status"] == "wrong_family" else ("loaded" if loaded else "fallback")
    return {"status": status, "primary_failed": primary_failed, "log": log, "static": static}


# ---------------------------------------------------------------- readability

def _class_font_value(css: List[Tuple[str, str]], cls: str) -> Optional[str]:
    for _base, text in css:
        for m in re.finditer(r"\.%s(?![\w-])[^{]*\{(.*?)\}" % re.escape(cls), text, re.S):
            fs = re.search(r"font-size\s*:\s*([^;}]+)", m.group(1))
            if fs:
                return fs.group(1).strip()
    return None


def resolve_px(value: str, fmt: str, scale: Dict) -> Optional[float]:
    """px literal, var(--ts-role), or calc(var(--ts-role) * k [* var(--x, 1)])."""
    if value is None:
        return None
    m = re.fullmatch(r"([0-9.]+)px", value)
    if m:
        return float(m.group(1))
    v = re.search(r"var\(--ts-([\w-]+)\)", value)
    if not v:
        return None
    base = scale["formats"][fmt]["scale"].get(v.group(1).replace("-", "_"))
    if base is None:
        return None
    k = re.search(r"\*\s*([0-9.]+)(?!\s*px)", value)
    return float(base) * (float(k.group(1)) if k else 1.0)


def phone_px(css_px: float, comp_width: int, scale: Dict) -> float:
    return round(css_px * scale["phone_viewport_css_px"] / float(comp_width), 2)


def mobile_readability(project_dir: str, scale: Optional[Dict] = None) -> Dict:
    """Phone-scale size of each checked text class in the composition."""
    scale = scale or load_scale()
    width, height = composition_size(project_dir)
    if not width or not height:
        return {"status": "unavailable", "reason": "composition size not found", "items": []}
    fmt = format_for(width, height)
    mins = scale["formats"][fmt]["min_phone_px"]
    css = collect_css(project_dir)
    html = _read(os.path.join(project_dir, "index.html"))
    items = []
    for cls, role in CLASS_ROLES.items():
        if role not in mins:
            continue
        if not re.search(r'class="[^"]*(?<![\w-])%s(?![\w-])' % re.escape(cls), html):
            continue
        px = resolve_px(_class_font_value(css, cls), fmt, scale)
        if px is None:
            continue
        ph = phone_px(px, width, scale)
        items.append({"class": cls, "role": role, "css_px": round(px, 2), "phone_px": ph,
                      "min_phone_px": mins[role], "ok": ph >= mins[role]})
    return {"status": "measured", "format": fmt, "width": width, "items": items}


def scale_meets_minimums(scale: Optional[Dict] = None) -> List[str]:
    """Problems in the type scale itself (empty list = valid)."""
    scale = scale or load_scale()
    problems = []
    for fmt, spec in scale["formats"].items():
        s, mins = spec["scale"], spec["min_phone_px"]
        for role, minimum in mins.items():
            if phone_px(s[role], spec["width"], scale) < minimum:
                problems.append("%s.%s below %spx at phone scale" % (fmt, role, minimum))
        if not (s["display"] > s["headline"] > s["secondary"] > s["caption"] > s["credit"]):
            problems.append("%s: hierarchy display>headline>secondary>caption>credit broken" % fmt)
        if s["headline"] < 1.6 * s["secondary"]:
            problems.append("%s: headline/secondary contrast below 1.6x" % fmt)
    return problems
