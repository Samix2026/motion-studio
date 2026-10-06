"""Production pipeline subcommands for studio/cli.py.

  brief | validate | trace | stills | critics | critic-record | render | qa |
  production | report   <project_dir>

Each stage records PASS/WARN/FAIL/SKIPPED (critics: PENDING) bound to the
production hash; FAIL stops `production` before any later stage runs.
Exit codes: 0 ok, 1 blocked/failed, 3 escalate to a human, 4 awaiting critics.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional

from studio import prerender, production as P, trace as trace_mod

EXIT_OK, EXIT_BLOCKED, EXIT_ESCALATE, EXIT_AWAITING = 0, 1, 3, 4


def _print_findings(findings: List[Dict], limit: int = 40) -> None:
    shown = [f for f in findings if f["severity"] != prerender.INFO]
    for f in shown[:limit]:
        print(prerender.format_finding(f))
    if len(shown) > limit:
        print("... %d more (see production/*.json)" % (len(shown) - limit))
    info = len(findings) - len(shown)
    if info:
        print("(%d INFO finding(s), e.g. annotated or accepted discontinuities, in the stage file)" % info)


def _record(project, stage, findings, phash, policy, seconds=None, extra=None, status=None):
    s = prerender.summarize(findings, policy.get("warnings_block"))
    details = {"errors": s["errors"], "warnings": s["warnings"], "info": s["info"],
               "findings": [f for f in findings if f["severity"] != prerender.INFO][:25]}
    details.update(extra or {})
    status = status or s["status"]
    summary = "%d error(s), %d warning(s)" % (s["errors"], s["warnings"])
    P.record(project, stage, status, summary, phash=phash, details=details,
             seconds=None if seconds is None else round(seconds, 2))
    print("%s: %s — %s" % (stage, status, summary))
    return status


def _setup(project):
    brief, bf = P.load_brief(project)
    spec, sf = P.load_spec(project)
    return brief, bf, spec, sf, P.production_hash(project)


# ---------------------------------------------------------------- stage runners

def run_brief_spec_build(project) -> Optional[str]:
    """Returns the failing stage name, or None."""
    brief, bf, spec, sf, phash = _setup(project)
    pol = brief["policy"]
    if _record(project, "brief", bf, phash, pol, extra={"sources": brief["sources"]}) == P.FAIL:
        _print_findings(bf)
        return "brief"
    note = "spec.json" if spec else "inferred from the composition"
    if _record(project, "spec", sf, phash, pol, extra={"spec": note}) == P.FAIL:
        _print_findings(sf)
        return "spec"
    bld = P.check_build(project, brief)
    if _record(project, "build", bld, phash, pol) == P.FAIL:
        _print_findings(bld)
        return "build"
    return None


def run_validation(project, use_trace=True, refresh=False, hf_check=True) -> str:
    brief, _, spec, _, phash = _setup(project)
    t0 = time.monotonic()
    ctx = P.context(project, brief, spec)
    findings = prerender.check_structure(ctx, spec) + prerender.scan_determinism(project)
    if hf_check:
        findings += P.hyperframes_check(project)
    else:
        findings.append(prerender.finding(prerender.WARNING, "check_skipped", "hyperframes check skipped "
                                          "(--no-check): no layout/overflow/contrast verification",
                                          source="hyperframes"))
    t1 = time.monotonic()
    num, info = P.numeric_validation(project, ctx, spec, brief["policy"], use_trace, refresh)
    findings += num
    info["validator_seconds"] = round(time.monotonic() - t1 - (info.get("trace") or {}).get("seconds", 0), 3)
    P._write_json(os.path.join(P.prod_dir(project), "validation.json"),
                  {"hash": phash, "numeric": info, "findings": findings})
    _print_findings(findings)
    t = info.get("trace") or {}
    print("Numeric trace: %s%s" % (info["status"], (" — reason: %s" % info["reason"]) if info.get("reason")
                                   else " (%s, trace %s)" % ("+".join(info["sources"]), t.get("status"))))
    return _record(project, "validation", findings, phash, brief["policy"], time.monotonic() - t0,
                   extra={"numeric": info})


def run_stills(project) -> str:
    brief, _, spec, _, phash = _setup(project)
    t0 = time.monotonic()
    ctx = P.context(project, brief, spec)
    val = _load_validation(project, phash)
    tdoc = trace_mod.load_cached(project, trace_mod.cache_key(project, ctx, ((spec or {}).get("trace") or {})
                                                              .get("selectors") or {}))
    design = P.select_frames(ctx, spec, tdoc, val.get("findings", []), brief["policy"].get("stills", 6))
    motion = P.motion_strip_frames(ctx)
    base = os.path.join(P.prod_dir(project), "stills", P.pack_id(phash))
    d = P.snapshot(project, [x["time"] for x in design], os.path.join(base, "design"))
    m = P.snapshot(project, [x["time"] for x in motion], os.path.join(base, "motion")) if motion \
        else {"ok": True, "files": [], "sheets": []}
    manifest = {"hash": phash, "design": dict(frames=design, **d), "motion": dict(frames=motion, **m)}
    P._write_json(os.path.join(base, "stills.json"), manifest)
    findings = []
    for name, r in (("design", d), ("motion", m)):
        if not r["ok"]:
            findings.append(prerender.finding(prerender.ERROR, "snapshot_failed", "%s stills: %s"
                                              % (name, r.get("reason")), source="stills"))
    for x in design:
        print("still frame %d (%.3fs): %s" % (x["frame"], x["time"], "; ".join(x["reasons"])))
    print("design sheets: %s\nmotion sheets: %s" % (d.get("sheets"), m.get("sheets")))
    return _record(project, "stills", findings, phash, brief["policy"], time.monotonic() - t0,
                   extra={"design_sheets": d.get("sheets"), "motion_sheets": m.get("sheets"),
                          "frames": [x["frame"] for x in design]})


def _load_validation(project, phash) -> Dict:
    try:
        v = P._read_json(os.path.join(P.prod_dir(project), "validation.json"))
        return v if v.get("hash") == phash else {}
    except (OSError, ValueError):
        return {}


def run_critic_packs(project) -> Dict:
    brief, _, spec, _, phash = _setup(project)
    ctx = P.context(project, brief, spec)
    base = os.path.join(P.prod_dir(project), "stills", P.pack_id(phash), "stills.json")
    if not os.path.isfile(base):
        raise SystemExit("critics: no stills for the current project state; run `stills` first")
    stills = P._read_json(base)
    tdoc = trace_mod.load_cached(project, trace_mod.cache_key(project, ctx, ((spec or {}).get("trace") or {})
                                                              .get("selectors") or {}))
    packs = P.build_critic_packs(project, phash, brief, ctx, stills, _load_validation(project, phash), tdoc)
    state = P.load_state(project)
    for critic in ("motion", "design"):
        stage = "%s_critic" % critic
        if P.stage_status(state, stage, phash) not in (P.PASS, P.WARN, P.FAIL):
            P.record(project, stage, P.PENDING, "awaiting %s-critic verdict (pack %s)"
                     % (critic, P.pack_id(phash)), phash=phash, details={"pack": packs[critic]["dir"]})
        print(P.critic_prompt(critic, packs[critic]))
    print("Then: python3 studio/cli.py critic-record %s --critic <motion|design> --file <verdict.json>" % project)
    return packs


# ---------------------------------------------------------------- commands

def cmd_brief(args) -> int:
    brief, bf = P.load_brief(args.project)
    print(json.dumps(brief, ensure_ascii=False, indent=2))
    _print_findings(bf)
    return EXIT_BLOCKED if any(f["severity"] == prerender.ERROR for f in bf) else EXIT_OK


def cmd_validate(args) -> int:
    failed = run_brief_spec_build(args.project)
    if failed:
        print("BLOCKED at %s; validation not run." % failed)
        return EXIT_BLOCKED
    st = run_validation(args.project, not args.no_trace, args.refresh_trace, not args.no_check)
    return EXIT_BLOCKED if st == P.FAIL else EXIT_OK


def cmd_trace(args) -> int:
    ver = trace_mod.pinned_version(args.project)
    if args.install:
        if not ver:
            print("no pinned hyperframes version in package.json")
            return EXIT_BLOCKED
        r = trace_mod.install(ver)
        print("tracer install %s: %s" % ("ok" if r["ok"] else "FAILED", r.get("path") or r.get("reason")))
        if not r["ok"]:
            print(r.get("reason"))
            return EXIT_BLOCKED
    brief, _, spec, _, _ = _setup(args.project)
    ctx = P.context(args.project, brief, spec)
    res = trace_mod.get_trace(args.project, ctx, ((spec or {}).get("trace") or {}).get("selectors") or {},
                              refresh=args.refresh)
    if not res["trace"]:
        print("Numeric trace: SKIPPED\nReason: %s" % res["reason"])
        return EXIT_BLOCKED
    doc = res["trace"]
    size = os.path.getsize(trace_mod.trace_path(args.project))
    print("trace %s: %d frames @ %s fps, %d elements, %d tracks sampled, %d kept, %s s, %.1f KB (%s)"
          % (res["status"], doc["frames"], doc["fps"], doc["sampled"]["elements"],
             doc["sampled"]["tracks_sampled"], doc["sampled"]["tracks_kept"],
             doc.get("trace_seconds"), size / 1024.0, trace_mod.trace_path(args.project)))
    return EXIT_OK


def cmd_stills(args) -> int:
    return EXIT_BLOCKED if run_stills(args.project) == P.FAIL else EXIT_OK


def cmd_critics(args) -> int:
    run_critic_packs(args.project)
    return EXIT_AWAITING


def cmd_critic_record(args) -> int:
    phash = P.production_hash(args.project)
    with open(args.file, encoding="utf-8") as fh:
        doc = json.load(fh)
    rec, errs = P.validate_critic_record(doc, args.critic, P.pack_id(phash))
    if errs:
        print("REFUSED critic record:\n- " + "\n- ".join(errs))
        return EXIT_BLOCKED
    sev = [f["severity"] for f in rec["findings"]]
    summary = "%d finding(s): %d blocking, %d major, %d minor" % (
        len(sev), sev.count("BLOCKING"), sev.count("MAJOR"), sev.count("MINOR"))
    if rec["verdict"] != rec["stated"]:
        summary += " (stated %s, findings imply %s)" % (rec["stated"], rec["verdict"])
    P.record(args.project, "%s_critic" % args.critic, rec["verdict"], summary, phash=phash,
             details={"findings": rec["findings"], "reviewer": doc["reviewer"], "pack": doc["pack"],
                      "warnings": sev.count("MINOR"), "errors": len(sev) - sev.count("MINOR")})
    print("%s_critic: %s — %s" % (args.critic, rec["verdict"], summary))
    return EXIT_OK


def _do_render(project, override, overwrite, require_review=None) -> str:
    brief, _, spec, _, phash = _setup(project)
    ctx = P.context(project, brief, spec)
    r = P.render(project, brief, ctx, phash, override=override, overwrite=overwrite,
                 require_review=require_review)
    if r.get("blocked"):
        print("DO NOT RENDER — %s" % r["summary"])
        for x in r["reasons"]:
            print("  - %s" % x)
        P.record(project, "render", P.FAIL, r["summary"], phash=phash, details={"reasons": r["reasons"]})
        return P.FAIL
    if override:
        print("OVERRIDE: render gate bypassed (%s). Bypassed: %s" % (override, r["bypassed"] or "nothing"))
    P.record(project, "render", r["status"], r["summary"], phash=phash, seconds=r.get("seconds"),
             override=override, details={k: r.get(k) for k in ("output", "sha256", "bypassed", "reasons")})
    print("render: %s — %s" % (r["status"], r["summary"]))
    return r["status"]


def cmd_render(args) -> int:
    return EXIT_BLOCKED if _do_render(args.project, args.override, args.overwrite) == P.FAIL else EXIT_OK


def run_qa(project, path=None) -> str:
    brief, _, spec, _, phash = _setup(project)
    ctx = P.context(project, brief, spec)
    state = P.load_state(project)
    out = path or ((state["stages"].get("render") or {}).get("details") or {}).get("output") \
        or os.path.join(project, brief["delivery"]["file"])
    t0 = time.monotonic()
    findings = P.qa(out, brief, ctx)
    _print_findings(findings)
    st = _record(project, "qa", findings, phash, brief["policy"], time.monotonic() - t0, extra={"output": out})
    if st == P.FAIL:
        return st
    t0 = time.monotonic()
    ast, af = P.audio_qa(out, brief, ctx)
    _print_findings(af)
    _record(project, "audio", af, phash, brief["policy"], time.monotonic() - t0, status=ast)
    return P.FAIL if ast == P.FAIL else st


def cmd_qa(args) -> int:
    return EXIT_BLOCKED if run_qa(args.project, args.render) == P.FAIL else EXIT_OK


def cmd_report(args) -> int:
    print(P.report(args.project))
    return EXIT_OK


def cmd_production(args) -> int:
    """Run every allowed stage in order; stop at the first blocking gate.
    Fresh PASS/WARN results for the current production hash are reused.
    Default: validate (+ trace) → render → QA. Stills and the critics run only
    in strict mode (`--critics` or `policy.require_review`)."""
    project = args.project

    def done(code):
        print("\n" + P.report(project))
        return code

    def fresh(stage):
        return not args.rerun and P.stage_status(P.load_state(project), stage, P.production_hash(project)) \
            in (P.PASS, P.WARN)

    failed = run_brief_spec_build(project)
    if failed:
        return done(EXIT_BLOCKED)
    if not fresh("validation") and run_validation(project, not args.no_trace, args.refresh_trace,
                                                  not args.no_check) == P.FAIL:
        print("BLOCKED at validation: fix the ERROR findings; nothing downstream ran.")
        return done(EXIT_BLOCKED)
    strict = (args.critics or P.load_brief(project)[0]["policy"].get("require_review")) \
        and not args.skip_critics
    if strict and not fresh("stills") and run_stills(project) == P.FAIL:
        return done(EXIT_BLOCKED)
    phash = P.production_hash(project)
    state = P.load_state(project)
    if strict:
        critic = {c: P.stage_status(state, c, phash) for c in ("motion_critic", "design_critic")}
        if any(s not in (P.PASS, P.WARN, P.FAIL) for s in critic.values()):
            run_critic_packs(project)
            print("AWAITING CRITICS: run both critic agents on their packs, record the verdicts, "
                  "then re-run `production`.")
            return done(EXIT_AWAITING)
        if P.FAIL in critic.values():
            n = P.fix_iterations(P.load_state(project))
            limit = P.load_brief(project)[0]["policy"]["max_fix_iterations"]
            if n >= limit:
                print("ESCALATE: critics failed %d iteration(s) (limit %d). A human decides the next step."
                      % (n, limit))
                return done(EXIT_ESCALATE)
            print("FIX REQUIRED (iteration %d/%d): address the critic findings, then re-run `production`. "
                  "Any edit changes the production hash, so validation, stills and both critics re-run."
                  % (n, limit))
            return done(EXIT_BLOCKED)
    if args.no_render:
        return done(EXIT_OK)
    r = P.load_state(project)["stages"].get("render") or {}
    out = (r.get("details") or {}).get("output")
    reuse = r.get("hash") == phash and r.get("status") == P.PASS and out and os.path.isfile(out) \
        and P._sha(out) == r["details"].get("sha256") and not args.rerun
    if not reuse and _do_render(project, args.override, args.overwrite,
                                require_review=bool(strict)) == P.FAIL:
        return done(EXIT_BLOCKED)
    return done(EXIT_BLOCKED if run_qa(project) == P.FAIL else EXIT_OK)


def register_subcommands(sub) -> None:
    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("project")
        p.set_defaults(func=fn)
        return p

    add("brief", cmd_brief, "print the machine-readable production brief (inferred where absent)")
    for name, fn, h in (("validate", cmd_validate, "brief/spec/build + pre-render validation (no render)"),
                        ("production", cmd_production, "run the gated pipeline; stop at a blocking gate")):
        p = add(name, fn, h)
        p.add_argument("--no-trace", action="store_true", help="skip the numeric browser trace")
        p.add_argument("--refresh-trace", action="store_true", help="re-trace even if the cache is fresh")
        p.add_argument("--no-check", action="store_true", help="skip `hyperframes check` (reported)")
    p = sub.choices["production"]
    p.add_argument("--rerun", action="store_true", help="re-run stages even when fresh results exist")
    p.add_argument("--critics", action="store_true",
                   help="strict mode: stills + motion/design critics gate the render (off by default)")
    p.add_argument("--skip-critics", metavar="REASON",
                   help="force the default no-critics path even when the policy requires review")
    p.add_argument("--no-render", action="store_true", help="stop before the render")
    p.add_argument("--override", metavar="REASON", help="bypass the render gate (logged, reported)")
    p.add_argument("--overwrite", action="store_true", help="allow replacing an existing render")
    p = add("trace", cmd_trace, "numeric browser trace (cached; bound to the composition hash)")
    p.add_argument("--install", action="store_true", help="install the pinned tracer out of tree (npm)")
    p.add_argument("--refresh", action="store_true")
    add("stills", cmd_stills, "render 4–6 representative stills + motion strips (no video)")
    add("critics", cmd_critics, "build motion + design critic packs and print the agent prompts")
    p = add("critic-record", cmd_critic_record, "record a critic agent's JSON verdict")
    p.add_argument("--critic", required=True, choices=("motion", "design"))
    p.add_argument("--file", required=True)
    p = add("render", cmd_render, "full render behind the render gate")
    p.add_argument("--override", metavar="REASON", help="bypass the gate (logged, reported)")
    p.add_argument("--overwrite", action="store_true")
    p = add("qa", cmd_qa, "post-render QA + audio checks")
    p.add_argument("--render", help="explicit render path (default: the recorded render)")
    add("report", cmd_report, "print the production report")
