"""Visual-first check (read-only, deterministic).

Text captions the visual; text is not the visual. This check does not judge
quality. It only verifies that the visual decision was made and declared:

- `storyboard.md` carries the visual-story block: a `Source assets` record
  (a list, or "none usable") and a SEE / DOES / READ triple for every scene;
- every scene (`<section class="clip">`) declares `data-visual="<role>"`;
- at most `max_text_only` scenes are text-only (`data-visual="text"`);
- a scene that declares a non-text role actually contains something other than
  text: media (`img`, `svg`, `canvas`, `video`, `picture`) or a constructed
  element marked `data-object`.

Roles are open: any lower-case token is accepted, so new kinds of visuals need
no code change. Only `text` has a fixed meaning.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

TEXT_ROLE = "text"
KNOWN_ROLES = ("source-image", "screenshot", "interface", "object", "diagram", "data", "footage", TEXT_ROLE)
MAX_TEXT_ONLY = 1

_ROLE = re.compile(r"^[a-z][a-z0-9-]*$")
_SECTION = re.compile(r"<section\b[^>]*>")
_MEDIA = re.compile(r"<(img|svg|canvas|video|picture)\b", re.I)
_OBJECT = re.compile(r"<[a-z][^>]*\sdata-object\b", re.I)
_ASSETS = re.compile(r"(?im)^\s*(?:#+\s*|[-*]\s*)?\**source assets\**\s*:?\s*(.*)$")
_PLACEHOLDER = re.compile(r"\[\[.*?\]\]|<!--.*?-->", re.S)


def _attrs(tag: str) -> Dict[str, str]:
    return dict(re.findall(r'([\w-]+)\s*=\s*"([^"]*)"', tag))


def scenes(project_dir: str) -> List[Dict]:
    """Top-level clips with their declared visual roles and whether they hold a non-text visual."""
    with open(os.path.join(project_dir, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    out = []
    for m in _SECTION.finditer(html):
        a = _attrs(m.group(0))
        if "clip" not in a.get("class", "").split():
            continue
        end = html.find("</section>", m.end())
        body = html[m.end(): end if end != -1 else len(html)]
        out.append({
            "index": len(out) + 1, "id": a.get("id"),
            "roles": a.get("data-visual", "").split(),
            "has_visual": bool(_MEDIA.search(body) or _OBJECT.search(body)),
        })
    return out


def _filled(text: str, key: str) -> int:
    """Count `KEY: <something>` lines whose value is not an unfilled placeholder."""
    n = 0
    for value in re.findall(r"(?im)^[\s>*|-]*\**%s\**\s*:\s*(.*)$" % key, text):
        if _PLACEHOLDER.sub("", value).strip(" *|"):
            n += 1
    return n


def storyboard_block(project_dir: str, scene_count: int) -> List[str]:
    """Problems with the visual-story block in storyboard.md (empty list = present and complete)."""
    path = os.path.join(project_dir, "storyboard.md")
    if not os.path.isfile(path):
        return ["storyboard.md is missing (it must carry the visual-story block)"]
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    problems = []
    m = _ASSETS.search(text)
    if not m:
        problems.append('no "Source assets" record (list what the primary source offers, or "none usable")')
    else:
        rest = m.group(1) + "\n" + text[m.end():].split("\n#", 1)[0]
        if not _PLACEHOLDER.sub("", rest).strip(" \n*-|"):
            problems.append('"Source assets" is empty (list the assets found, or write "none usable")')
    for key in ("SEE", "DOES", "READ"):
        n = _filled(text, key)
        if n < scene_count:
            problems.append("%s is filled for %d of %d scenes" % (key, n, scene_count))
    return problems


def check(project_dir: str, max_text_only: int = MAX_TEXT_ONLY) -> Dict:
    """Errors and advisories. `enforced` is False for legacy projects that have
    neither a storyboard.md nor any `data-visual` attribute."""
    sc = scenes(project_dir)
    has_storyboard = os.path.isfile(os.path.join(project_dir, "storyboard.md"))
    enforced = has_storyboard or any(s["roles"] for s in sc)
    errors: List[Dict] = []
    advisories: List[str] = []

    def err(code: str, message: str, scene: Optional[Dict] = None) -> None:
        errors.append({"code": code, "message": message, "scene": (scene["id"] or scene["index"]) if scene else None})

    if not enforced:
        return {"enforced": False, "errors": [], "advisories": [
            "no storyboard.md and no data-visual attributes: the visual-first check did not run"], "scenes": sc}

    for problem in storyboard_block(project_dir, len(sc)):
        err("visual_story_missing", problem)
    text_only = []
    for s in sc:
        label = "scene %s" % (s["id"] or s["index"])
        if not s["roles"]:
            err("visual_role_missing", '%s declares no data-visual role' % label, s)
            continue
        bad = [r for r in s["roles"] if not _ROLE.match(r)]
        if bad:
            err("visual_role_invalid", "%s: invalid role %s (use a lower-case token)" % (label, ", ".join(bad)), s)
        for r in s["roles"]:
            if _ROLE.match(r) and r not in KNOWN_ROLES:
                advisories.append("%s: role %r is not a common one (%s)" % (label, r, ", ".join(KNOWN_ROLES)))
        if s["roles"] == [TEXT_ROLE]:
            text_only.append(s)
        elif not s["has_visual"]:
            err("visual_role_unbacked",
                "%s declares %s but contains only text: add the asset (img/svg/canvas/video) or mark the "
                "constructed element with data-object, or declare data-visual=\"text\""
                % (label, " ".join(s["roles"])), s)
    if len(text_only) > max_text_only:
        err("too_many_text_scenes",
            "%d text-only scenes (%s); at most %d is allowed — text captions the visual, it is not the visual"
            % (len(text_only), ", ".join(str(s["id"] or s["index"]) for s in text_only), max_text_only))
    return {"enforced": True, "errors": errors, "advisories": advisories, "scenes": sc}
