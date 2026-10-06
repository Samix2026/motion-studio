"""CLI for the review layer.

Usage:
  python3 review/cli.py review  <project_dir>
  python3 review/cli.py report  <project_dir>
  python3 review/cli.py approve <project_dir> [--proposal ID ...] [--index N ...]
  python3 review/cli.py reject  <project_dir> [--proposal ID ...] [--index N ...]
  python3 review/cli.py apply   <project_dir> [--proposal ID ...] [--preview]
  python3 review/cli.py status  <project_dir>

Review and report are read-only. apply writes only to a NEW version dir.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from review import analyzer, apply_proposal, proposal_schema, reviewer, revision  # noqa: E402
from review import inputs as review_inputs  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROPOSALS = os.path.join(_HERE, "proposals")
_REPORTS = os.path.join(_HERE, "reports")


def _proposals_path(key: str, rev: int) -> str:
    return os.path.join(_PROPOSALS, "%s-rev%d.json" % (key, rev))


def _reports_base(key: str, rev: int) -> str:
    return os.path.join(_REPORTS, "%s-rev%d" % (key, rev))


def _save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _load_latest_proposals(key: str):
    files = sorted(glob.glob(os.path.join(_PROPOSALS, "%s-rev*.json" % key)))
    if not files:
        return None, None
    latest = files[-1]
    with open(latest, encoding="utf-8") as fh:
        return latest, json.load(fh)


# ---------------------------------------------------------------- report text

def render_report_md(report: dict, proposals: list, evidence_status: str = None) -> str:
    comp = report.get("composition", {})
    lines = []
    lines.append("AI VIDEO REVIEW")
    lines.append("")
    lines.append("Project:")
    lines.append(report.get("project", ""))
    lines.append("")
    lines.append("Revision:")
    lines.append(str(report.get("revision", "")))
    lines.append("")
    if evidence_status:
        lines.append("Proposal evidence: %s" % str(evidence_status).upper())
        if evidence_status != "current":
            lines.append("WARNING: saved proposals are %s relative to the current review "
                         "inputs and are NOT current; re-run review before relying on them."
                         % evidence_status)
        lines.append("")
    lines.append("Findings: %d" % len(report.get("findings", [])))
    lines.append("")
    prop_by_finding = {p["finding_id"]: p for p in proposals}
    for i, f in enumerate(report.get("findings", []), 1):
        ev = f["evidence"]
        lines.append("[%d] %s" % (i, f["category"].replace("_", " ").title()))
        lines.append("Severity: %s" % f["severity"])
        if f.get("scene") is not None:
            lines.append("Scene %s" % f["scene"])
        lines.append("Measured: %s %s (%s)" % (ev["measured_value"], ev["unit"], ev["source"]))
        p = prop_by_finding.get(f["id"])
        if p:
            op = p["operation"]
            label = "Proposal" if not evidence_status or evidence_status == "current" \
                else "Proposal (%s)" % evidence_status.upper()
            lines.append("%s: %s" % (label, p["title"]))
            lines.append("Operation: %s" % json.dumps(op, ensure_ascii=False))
            lines.append("Impact: %.1fs -> %.1fs" % (p["duration_before"], p["duration_after"]))
            if p.get("warnings"):
                lines.append("Warnings: %s" % "; ".join(p["warnings"]))
            lines.append("Confidence: %.2f" % p["confidence"])
            lines.append("Status: %s" % p["status"])
        else:
            lines.append("Status: No safe proposal in V1")
        lines.append("")
    if report.get("unavailable"):
        lines.append("Unavailable checks:")
        for u in report["unavailable"]:
            lines.append("- %s: %s" % (u["check"], u["reason"]))
        lines.append("")
    lines.append("No changes have been applied.")
    lines.append("(duration: %.1fs, %sx%s @%s fps)"
                 % (comp.get("duration", 0), comp.get("width", 0),
                    comp.get("height", 0), comp.get("fps", 0)))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- commands

def _explicit_inputs(project: str, args):
    """Build explicit review inputs when the caller selected them, else None."""
    provided = any([args.render, args.composition, args.css, args.timings,
                    args.captions, args.dependency, args.snapshots])
    if not provided:
        return None
    if not (args.render and args.composition):
        raise review_inputs.ReviewInputError(
            "explicit review requires both --render and --composition; "
            "no render is auto-selected")
    return review_inputs.ReviewInputs.from_explicit(
        project, render=args.render, composition=args.composition,
        css=args.css, timings=args.timings, captions=args.captions,
        dependencies=args.dependency, snapshots=args.snapshots,
        narration_enabled=args.narration)


def cmd_review(args) -> int:
    project = args.project
    try:
        selected = _explicit_inputs(project, args)
        report = analyzer.analyze(project, inputs=selected)
    except review_inputs.ReviewInputError as exc:
        print("Review input error: %s" % exc)
        return 1
    # An explicit review command may initialize/save revision state.
    revision.get_or_init_state(project)
    proposals, notes = reviewer.review(project, report, inputs=selected)
    proposal_schema.validate_all(report["findings"], proposals)
    slug, rev = report["project"], report["revision"]
    key = revision.state_key(project)

    _save_json(_proposals_path(key, rev), {
        "project": slug, "revision": rev, "content_hash": report["content_hash"],
        "review_inputs": report.get("review_inputs"),
        "review_fingerprint": report.get("review_fingerprint"),
        "review_fingerprint_version": report.get("review_fingerprint_version"),
        "proposals": proposals})
    base = _reports_base(key, rev)
    _save_json(base + ".json", report)
    with open(base + ".md", "w", encoding="utf-8") as fh:
        fh.write(render_report_md(report, proposals, evidence_status="current"))

    print(render_report_md(report, proposals, evidence_status="current"))
    if notes:
        print("Notes:")
        for n in notes:
            print("- %s" % n)
    print("Wrote %s.json / .md and %s" % (base, _proposals_path(key, rev)))
    return 0


def cmd_report(args) -> int:
    key = revision.state_key(args.project)
    _, data = _load_latest_proposals(key)
    if not data:
        print("No proposals found for %s; run `review` first." % revision.slug_for(args.project))
        return 1
    report = analyzer.analyze(args.project)
    try:
        status = review_inputs.freshness_for_saved(args.project, data).get("status")
    except Exception:
        status = "unverified"
    print(render_report_md(report, data["proposals"], evidence_status=status))
    return 0


def _decide(args, status: str) -> int:
    key = revision.state_key(args.project)
    path, data = _load_latest_proposals(key)
    if not data:
        print("No proposals found for %s; run `review` first." % revision.slug_for(args.project))
        return 1
    props = data["proposals"]
    targets = set(args.proposal or [])
    for idx in (args.index or []):
        if 1 <= idx <= len(props):
            targets.add(props[idx - 1]["id"])
    if not targets:
        print("Specify --proposal <id> and/or --index <n>.")
        return 1
    changed = 0
    for p in props:
        if p["id"] in targets:
            p["status"] = status
            changed += 1
    _save_json(path, data)
    print("%d proposal(s) marked %s." % (changed, status))
    return 0


def cmd_approve(args) -> int:
    return _decide(args, "approved")


def cmd_reject(args) -> int:
    return _decide(args, "rejected")


def cmd_apply(args) -> int:
    key = revision.state_key(args.project)
    _, data = _load_latest_proposals(key)
    if not data:
        print("No proposals found for %s; run `review` first." % revision.slug_for(args.project))
        return 1
    props = data["proposals"]
    approved = [p["id"] for p in props if p["status"] == "approved"]
    if args.proposal:
        approved = [i for i in approved if i in set(args.proposal)]
    if not approved:
        print("No approved proposals to apply.")
        return 1
    try:
        result = apply_proposal.apply_approved(args.project, props, approved,
                                               dry_run=args.preview)
    except apply_proposal.StaleRevisionError as exc:
        print("STALE — proposal cannot be applied: %s" % exc)
        return 2
    except apply_proposal.ApplyError as exc:
        print("Apply failed (no changes made): %s" % exc)
        return 3
    if args.preview or result.get("dry_run"):
        print("PREVIEW (dry run) — no project written. Expected duration: %.1fs"
              % result["expected_duration"])
        for step in result["plan"]:
            print("- %s -> %s" % (step["proposal"], json.dumps(step["operation"], ensure_ascii=False)))
        print("To render V2 locally (V1 does not render):")
        print("  (cd %s && npm run render -- . -o ./renders/video.mp4)" % (result.get("new_dir") or "<new-dir>"))
        return 0
    print("Applied %d proposal(s) -> new version: %s" % (len(result["applied"]), result["new_dir"]))
    print("Reminder: the new version has no render yet; render it explicitly. Source project untouched.")
    return 0


def cmd_vision(args) -> int:
    from review import vision
    project = args.project
    render = args.render or analyzer._render_path(project)
    state = revision.get_or_init_state(project)
    key, rev = revision.state_key(project), int(state["revision"])
    out_dir = os.path.join(vision.INPUTS_DIR, "%s-rev%d" % (key, rev))
    try:
        manifest = vision.build_inputs(project, render, out_dir)
    except (ValueError, RuntimeError) as exc:
        print("Visual review unavailable: %s" % exc)
        return 1
    print("Vision inputs (%d images): %s" % (vision.image_count(manifest), out_dir))
    if not args.fixture:
        print("No provider selected. A paid multimodal provider requires an approved Cost Gate;")
        print("pricing is UNKNOWN until verified. Plan item for costgate:")
        print(json.dumps(vision.cost_plan_items(manifest, "<provider>", "<model>"), ensure_ascii=False))
        print("Offline review: --fixture <judgments.json>")
        return 0
    result = vision.run_visual_review(project, manifest, vision.FixtureProvider(args.fixture))
    path = _proposals_path(key, rev)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        data = {"project": revision.slug_for(project), "revision": rev,
                "content_hash": state["content_hash"], "proposals": []}
    data["proposals"] = [p for p in data["proposals"] if p.get("origin") != "multimodal"] \
        + result["proposals"]
    _save_json(path, data)
    base = _reports_base(key, rev)
    _save_json(base + ".vision.json", result)
    text = vision.render_vision_md(result)
    with open(base + ".vision.md", "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    print("Wrote %s.vision.json / .md and merged %d proposal(s) into %s"
          % (base, len(result["proposals"]), path))
    return 0


def cmd_critic_pack(args) -> int:
    from review import vision
    key = revision.state_key(args.project)
    out_dir = args.out or os.path.join(vision.INPUTS_DIR, "%s-%s" % (key, "pair" if args.pair else "critic"))
    try:
        if args.pair:
            pack = vision.build_pair_pack(args.project, args.render, args.pair, out_dir)
        else:
            pack = vision.build_critic_pack(args.project, args.render, out_dir)
    except (ValueError, RuntimeError) as exc:
        print("Critic pack unavailable: %s" % exc)
        return 1
    if args.pair:
        print("Blind pairwise pack: %s" % pack["dir"])
        print("Mapping sealed (not shown): %s" % pack["mapping_path"])
    else:
        print("Critic pack for %s: %s" % (pack["render"], pack["dir"]))
    for name in pack["files"]:
        print("  %s" % name)
    files = ", ".join(pack["files"])
    print("Optional critic prompt (visual-critic agent):")
    print("  Pack: %s/ · Read in one turn: %s" % (pack["dir"], files))
    return 0


def cmd_status(args) -> int:
    key = revision.state_key(args.project)
    state = revision.load_state_view(args.project)
    print("project: %s" % revision.slug_for(args.project))
    print("revision: %s" % state["revision"])
    print("content_hash: %s" % state["content_hash"][:12])
    if state.get("history"):
        print("history entries: %d" % len(state["history"]))
    _, data = _load_latest_proposals(key)
    if data:
        counts = {}
        for p in data["proposals"]:
            counts[p["status"]] = counts.get(p["status"], 0) + 1
        print("proposals: %s" % counts)
    else:
        print("proposals: none (run `review`)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="review", description="AI Video Review & Approval Layer (V1)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("review", help="analyze + propose (read-only)")
    p.add_argument("project")
    p.add_argument("--render", help="explicit render path (never auto-selected)")
    p.add_argument("--composition", help="explicit composition index.html")
    p.add_argument("--css", action="append", default=None,
                   help="explicit local stylesheet (repeatable)")
    p.add_argument("--timings", default=None, help="explicit word-timings file")
    p.add_argument("--captions", default=None, help="explicit captions file")
    p.add_argument("--dependency", action="append", default=None,
                   help="declared local composition dependency (repeatable)")
    p.add_argument("--snapshots", action="append", default=None,
                   help="explicit snapshot file (repeatable)")
    p.add_argument("--narration", action="store_true",
                   help="explicit review configuration: narration enabled")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("report", help="print the latest report")
    p.add_argument("project")
    p.set_defaults(func=cmd_report)

    for name, fn in (("approve", cmd_approve), ("reject", cmd_reject)):
        p = sub.add_parser(name, help="%s proposals" % name)
        p.add_argument("project")
        p.add_argument("--proposal", action="append", default=[])
        p.add_argument("--index", type=int, action="append", default=[])
        p.set_defaults(func=fn)

    p = sub.add_parser("apply", help="apply approved proposals to a NEW version")
    p.add_argument("project")
    p.add_argument("--proposal", action="append", default=[])
    p.add_argument("--preview", action="store_true", help="dry run; no project written")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("vision", help="rendered-frame visual review (AI judgment; offline fixture only)")
    p.add_argument("project")
    p.add_argument("--render", help="preview render (default: renders/)")
    p.add_argument("--fixture", help="recorded judgments JSON (no provider call)")
    p.set_defaults(func=cmd_vision)

    p = sub.add_parser("critic-pack", help="lean 3-image pack for the optional visual critic")
    p.add_argument("project")
    p.add_argument("--render", required=True, help="explicit render path (never auto-selected)")
    p.add_argument("--pair", help="second explicit render: build a blind pairwise pack instead")
    p.add_argument("--out", help="output directory (default: review/vision_inputs/<key>-critic|pair)")
    p.set_defaults(func=cmd_critic_pack)

    p = sub.add_parser("status", help="show revision and proposal state")
    p.add_argument("project")
    p.set_defaults(func=cmd_status)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
