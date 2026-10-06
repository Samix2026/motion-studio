"""CLI for the Reference Analyzer (offline).

Usage:
  python3 reference/cli.py analyze <path> [--id ID] [--no-scene-detection] [--out DIR]
  python3 reference/cli.py analyze --manual <observations.json> [--id ID]
  python3 reference/cli.py show <reference_id>
  python3 reference/cli.py list

Analysis is local and read-only with respect to video projects; only
reference/profiles and reference/reports are written.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reference import analyzer  # noqa: E402


def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def cmd_analyze(args) -> int:
    manual = _load(args.manual) if args.manual else None
    profile = analyzer.analyze(args.path, manual=manual, reference_id=args.id,
                               allow_scene_detection=not args.no_scene_detection)
    saved = analyzer.save_profile(profile)
    print(analyzer.render_report_md(profile))
    print("Saved: %s" % saved)
    return 0


def cmd_show(args) -> int:
    p = analyzer.load_profile(args.reference_id)
    if not p:
        print("No profile '%s'." % args.reference_id)
        return 1
    print(analyzer.render_report_md(p))
    return 0


def cmd_list(_args) -> int:
    d = analyzer._PROFILE_DIR
    names = sorted(f[:-5] for f in os.listdir(d)) if os.path.isdir(d) else []
    for n in names:
        print(n)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="reference", description="Reference style analyzer (V1)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("analyze", help="analyze a local video/image set or manual notes")
    p.add_argument("path", nargs="?", default=None)
    p.add_argument("--manual", default=None, help="JSON with observed/inferred notes")
    p.add_argument("--id", default=None)
    p.add_argument("--no-scene-detection", action="store_true")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("show", help="print a saved style profile")
    p.add_argument("reference_id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("list", help="list saved profiles")
    p.set_defaults(func=cmd_list)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
