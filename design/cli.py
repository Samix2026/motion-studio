"""CLI for design-system checks (read-only).

Usage:
  python3 design/cli.py grammars
  python3 design/cli.py signature   <project_dir>
  python3 design/cli.py validate    <project_dir>
  python3 design/cli.py novelty     <project_dir> [--runs runs] [--videos videos] [--window 3]
  python3 design/cli.py fonts       <project_dir> [--render]
  python3 design/cli.py readability <project_dir>
  python3 design/cli.py preflight   <project_dir>
  python3 design/cli.py visual      <project_dir>
  python3 design/cli.py brand       <project_dir>   # advisory: palette reach

Prints JSON. Never writes to a project. `fonts --render` loads the composition
in the HyperFrames render browser with vision description disabled.
`preflight` enforces the context-scope manifest (`CONTEXT_SCOPE.md`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from design import brand_reach, context_scope, grammar, typography, visual_story  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="design", description="Motion Studio design-system checks")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("grammars")
    for name in ("signature", "validate", "readability", "preflight", "visual", "brand"):
        sub.add_parser(name).add_argument("project")
    p = sub.add_parser("novelty")
    p.add_argument("project")
    p.add_argument("--runs", default=os.path.join(_ROOT, "runs"))
    p.add_argument("--videos", default=os.path.join(_ROOT, "videos"))
    p.add_argument("--window", type=int, default=3)
    p = sub.add_parser("fonts")
    p.add_argument("project")
    p.add_argument("--render", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "grammars":
        reg = grammar.load_registry()
        problems = grammar.validate_registry(reg)
        _print({"valid": not problems, "problems": problems,
                "grammars": {k: {"suitable_for": v["suitable_for"], "variants": v["variants"]}
                             for k, v in reg["grammars"].items()},
                "motions": sorted(reg["motions"]), "choreography": sorted(reg["choreography"])})
        return 1 if problems else 0
    if args.cmd == "signature":
        _print(grammar.layout_signature(args.project))
        return 0
    if args.cmd == "validate":
        res = grammar.validate_project(args.project)
        _print(res)
        return 1 if res["errors"] else 0
    if args.cmd == "novelty":
        _print(grammar.novelty_advisory(args.project, args.runs, args.videos, args.window))
        return 0  # advisory only
    if args.cmd == "fonts":
        res = typography.render_font_check(args.project) if args.render \
            else typography.static_font_report(args.project)
        _print(res)
        bad = res.get("status") in ("fallback", "wrong_family") or res.get("fallback_risk") is True
        return 1 if bad else 0
    if args.cmd == "readability":
        _print(typography.mobile_readability(args.project))
        return 0
    if args.cmd == "brand":
        _print(brand_reach.reach(args.project))
        return 0  # advisory only
    if args.cmd == "visual":
        res = visual_story.check(args.project)
        _print(res)
        return 1 if res["errors"] else 0
    if args.cmd == "preflight":
        res = context_scope.preflight(args.project)
        _print(res)
        return 0 if res["ok"] else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
