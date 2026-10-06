"""CLI for the narration mode layer (read-only).

Usage:
  python3 narration/cli.py mode   <project_dir>
  python3 narration/cli.py status <project_dir>
  python3 narration/cli.py plan   <project_dir> [--json]

Never renders, never calls a provider, never writes to a project.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from narration import mode as mode_mod  # noqa: E402
from narration import plan as plan_mod  # noqa: E402


def cmd_mode(args) -> int:
    print(mode_mod.load(args.project))
    return 0


def cmd_status(args) -> int:
    doc = plan_mod.plan(args.project)
    print(plan_mod.render_report_md(doc))
    return 0


def cmd_plan(args) -> int:
    doc = plan_mod.plan(args.project)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(plan_mod.render_report_md(doc))
    return 2 if args.require_unblocked and doc["blocked"] else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="narration", description="Narration mode (read-only)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("mode", help="print the project narration mode")
    p.add_argument("project")
    p.set_defaults(func=cmd_mode)

    p = sub.add_parser("status", help="print narration pipeline status")
    p.add_argument("project")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("plan", help="print the narration pipeline plan")
    p.add_argument("project")
    p.add_argument("--json", action="store_true")
    p.add_argument("--require-unblocked", action="store_true",
                   help="exit non-zero when a step is blocked")
    p.set_defaults(func=cmd_plan)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
