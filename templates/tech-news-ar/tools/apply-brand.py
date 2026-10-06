#!/usr/bin/env python3
"""Apply a brand profile's tokens to a tech-news-ar composition.

Usage:
  python3 tools/apply-brand.py <brand.json> <index.html> [meta.json]

- Replaces the CSS custom-property block between the
  /* brand:start ... */ and /* brand:end */ markers in index.html.
- Sets "brand" and "brandCompany" in meta.json (default: meta.json next to
  index.html, if it exists).

Standard library only. This is a plain JSON -> CSS text transform, not a
styling framework.
"""
import json
import os
import re
import sys

START = "/* brand:start"
END = "/* brand:end */"
KEY_RE = re.compile(r"(?<!^)(?=[A-Z])")


def kebab(name: str) -> str:
    return KEY_RE.sub("-", name).lower()


def build_block(tokens: dict) -> str:
    return "\n".join(f"  --brand-{kebab(k)}: {v};" for k, v in tokens.items())


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    brand_path, html_path = sys.argv[1], sys.argv[2]
    meta_path = sys.argv[3] if len(sys.argv) > 3 else os.path.join(
        os.path.dirname(os.path.abspath(html_path)), "meta.json"
    )

    brand = json.load(open(brand_path, encoding="utf-8"))
    for field in ("id", "company", "tokens"):
        if field not in brand:
            print(f"FAIL: {brand_path} missing '{field}'")
            return 1
    block = build_block(brand["tokens"])
    # identity.palette (optional) → --brand-palette-1..n, so every brand colour is usable in scenes
    for i, colour in enumerate((brand.get("identity") or {}).get("palette") or [], 1):
        block += f"\n  --brand-palette-{i}: {colour};"

    html = open(html_path, encoding="utf-8").read()
    pattern = re.compile(
        r"(" + re.escape(START) + r"[^\n]*\n)(.*?)(\n\s*" + re.escape(END) + r")",
        re.S,
    )
    if not pattern.search(html):
        print(f"FAIL: brand markers not found in {html_path}")
        return 1
    updated = pattern.sub(lambda m: m.group(1) + block + m.group(3), html, count=1)
    open(html_path, "w", encoding="utf-8").write(updated)

    if os.path.isfile(meta_path):
        meta = json.load(open(meta_path, encoding="utf-8"))
        meta["brand"] = brand["id"]
        meta["brandCompany"] = brand["company"]
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"meta: {meta_path} -> brand={brand['id']}")

    print(f"OK: applied '{brand['id']}' ({len(brand['tokens'])} tokens) to {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
