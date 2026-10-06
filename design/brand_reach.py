"""Advisory: does the declared brand palette reach the scene content? (read-only)

A brand is more than a logo and one accent colour. For the project's brand
profile this counts which palette colours are referenced by the composition
OUTSIDE the `brand:start … brand:end` token block — directly as a hex value, or
through a `--brand-*` custom property whose value contains that colour.

Deterministic and never blocking: it reports reach, it does not judge design.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

BRANDS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "templates", "tech-news-ar", "brands")
_BLOCK = re.compile(r"/\*\s*brand:start.*?brand:end\s*\*/", re.S)
_VAR = re.compile(r"(--brand-[\w-]+)\s*:\s*([^;]+);")


def palette(profile: Dict) -> List[str]:
    colours = ((profile.get("identity") or {}).get("palette")
               or (profile.get("officialColors") or {}).get("palette") or [])
    return [c.lower() for c in colours if isinstance(c, str) and c.startswith("#")]


def load_profile(project_dir: str, brands_dir: str = BRANDS_DIR) -> Optional[Dict]:
    try:
        with open(os.path.join(project_dir, "meta.json"), encoding="utf-8") as fh:
            brand = json.load(fh).get("brand")
        with open(os.path.join(brands_dir, "%s.json" % brand), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, TypeError):
        return None


def reach(project_dir: str, profile: Optional[Dict] = None) -> Dict:
    profile = profile if profile is not None else load_profile(project_dir)
    colours = palette(profile or {})
    if len(colours) < 2:
        return {"status": "not_applicable", "palette": colours, "reached": [], "advisory": None}
    with open(os.path.join(project_dir, "index.html"), encoding="utf-8") as fh:
        html = fh.read().lower()
    block = "\n".join(_BLOCK.findall(html))
    content = _BLOCK.sub(" ", html)
    reached = []
    for colour in colours:
        carriers = [name for name, value in _VAR.findall(block) if colour in value]
        if colour in content or any(re.search(r"var\(\s*%s\b" % re.escape(n), content) for n in carriers):
            reached.append(colour)
    want = min(3, len(colours))
    advisory = None
    if len(reached) < want:
        advisory = ("%d of %d brand palette colours reach the scene content (%s); the identity is carried by "
                    "little more than an accent colour — consider the profile's palette, shapes and motifs "
                    "inside the scenes" % (len(reached), len(colours), ", ".join(reached) or "none"))
    return {"status": "measured", "brand": (profile or {}).get("id"), "palette": colours,
            "reached": reached, "advisory": advisory}
