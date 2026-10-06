"""Integrated workflow CLI.

Usage:
  python3 studio/cli.py status <project_dir> [--reference ID] [--plan plan.json] [--pricing p.json]
  python3 studio/cli.py production <project_dir>   # gated pipeline (PRODUCTION.md)

`status` prints the state of the four subsystems and the two human gates. It
exits 2 when a cost gate is active and paid generation is not approved; it
never writes to a project, never renders, never calls a provider. The
production subcommands (brief, validate, trace, stills, critics, critic-record,
render, qa, production, report) write only under <project>/production/ and the
render output, and are documented in PRODUCTION.md.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from studio import status  # noqa: E402
from studio import contracts  # noqa: E402
from studio import run_cli  # noqa: E402
from studio import production_cli  # noqa: E402
from studio import cleanup as cleanup_cli  # noqa: E402


def cmd_status(args) -> int:
    state = status.inspect(args.project, reference_id=args.reference,
                           plan_path=args.plan, pricing_path=args.pricing)
    print(status.render_report_md(state))
    if args.require_cost_approval and not state["paid_generation_allowed"]:
        print("BLOCKED: paid generation is not approved (Gate 1).")
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="studio", description="Video Studio workflow status and gated production")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status", help="integrated read-only workflow status")
    p.add_argument("project")
    p.add_argument("--reference", default=None, help="reference profile id (optional)")
    p.add_argument("--plan", default=None, help="asset plan JSON for the cost gate (optional)")
    p.add_argument("--pricing", default=None, help="pricing catalog (optional)")
    p.add_argument("--require-cost-approval", action="store_true",
                   help="exit non-zero when paid generation is not approved")
    p.set_defaults(func=cmd_status)
    run_cli.register_subcommands(sub)
    production_cli.register_subcommands(sub)
    cleanup_cli.register_subcommands(sub)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except contracts.ContractError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())