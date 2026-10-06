"""CLI for the cost gate.

Usage:
  python3 costgate/cli.py build   <project> --plan <plan.json> [--pricing <p.json>] [--at ISO]
  python3 costgate/cli.py show    <project>
  python3 costgate/cli.py approve <project> --limit <usd> [--at ISO]
  python3 costgate/cli.py reject  <project> [--at ISO]
  python3 costgate/cli.py actuals <project> [--provider-billed <usd>] [--session-reported <usd>]
  python3 costgate/cli.py status  <project>
  python3 costgate/cli.py check   <project>

build/approve/reject/actuals write only under costgate/state and costgate/reports.
No provider is contacted. `check` exits non-zero when generation is not allowed.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from costgate import gate  # noqa: E402


def _now() -> str:
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def cmd_build(args) -> int:
    pricing = gate.load_pricing(args.pricing) if args.pricing else gate.load_pricing()
    plan = gate.load_json(args.plan)
    g = gate.build_gate(plan, pricing, args.project, args.at or _now(),
                        currency=args.currency)
    gate.save_gate(g)
    print(gate.render_report_md(g))
    print("Gate saved. Paid generation is BLOCKED until `approve` (or `reject`).")
    return 0


def _load_or_fail(project: str):
    g = gate.load_gate(gate.gate_id_for(project))
    if not g:
        print("No cost gate for %s; run `build` first." % project)
        return None
    return g


def cmd_show(args) -> int:
    g = _load_or_fail(args.project)
    if not g:
        return 1
    print(gate.render_report_md(g))
    return 0


def cmd_approve(args) -> int:
    g = _load_or_fail(args.project)
    if not g:
        return 1
    g2 = gate.set_decision(g, "approve", limit=args.limit, at=args.at or _now())
    gate.save_gate(g2)
    print(gate.render_report_md(g2))
    if not gate.generation_allowed(g2):
        print("BLOCKED: status=%s" % g2["status"])
        return 2
    return 0


def cmd_reject(args) -> int:
    g = _load_or_fail(args.project)
    if not g:
        return 1
    g2 = gate.set_decision(g, "reject", at=args.at or _now())
    gate.save_gate(g2)
    print(gate.render_report_md(g2))
    return 0


def cmd_actuals(args) -> int:
    g = _load_or_fail(args.project)
    if not g:
        return 1
    g2 = gate.record_actuals(g, provider_billed_usd=args.provider_billed,
                             session_reported_usd=args.session_reported)
    gate.save_gate(g2)
    print(gate.render_report_md(g2))
    return 0


def cmd_status(args) -> int:
    g = _load_or_fail(args.project)
    if not g:
        return 1
    print("project: %s" % g["project"])
    print("gate_id: %s" % g["gate_id"])
    print("status: %s" % g["status"])
    print("cost_status: %s" % g["cost_status"])
    print("estimated_total_usd: %s" % g["estimated_total_usd"])
    print("approved_cost_limit_usd: %s" % g["approved_cost_limit_usd"])
    print("generation_allowed: %s" % gate.generation_allowed(g))
    return 0


def cmd_check(args) -> int:
    g = _load_or_fail(args.project)
    if not g:
        return 2
    if gate.generation_allowed(g):
        print("Cost gate APPROVED (%s). Paid generation may proceed within the limit."
              % g["cost_status"])
        return 0
    print("Cost gate BLOCKED: status=%s, cost_status=%s." % (g["status"], g["cost_status"]))
    return 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="costgate", description="Pre-generation cost approval gate")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="estimate costs from a plan")
    p.add_argument("project")
    p.add_argument("--plan", required=True)
    p.add_argument("--pricing", default=None)
    p.add_argument("--currency", default=None)
    p.add_argument("--at", default=None)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("show", help="print the current gate")
    p.add_argument("project")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("approve", help="approve (optionally within a limit)")
    p.add_argument("project")
    p.add_argument("--limit", type=float, default=None)
    p.add_argument("--at", default=None)
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("reject", help="reject the gate")
    p.add_argument("project")
    p.add_argument("--at", default=None)
    p.set_defaults(func=cmd_reject)

    p = sub.add_parser("actuals", help="record provider/session actuals and variance")
    p.add_argument("project")
    p.add_argument("--provider-billed", type=float, default=None)
    p.add_argument("--session-reported", type=float, default=None)
    p.set_defaults(func=cmd_actuals)

    for name, fn in (("status", cmd_status), ("check", cmd_check)):
        p = sub.add_parser(name, help="show status" if name == "status" else "exit non-zero if blocked")
        p.add_argument("project")
        p.set_defaults(func=fn)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
