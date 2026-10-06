"""Read-only integrated status across the four subsystems.

`inspect()` returns a single dict describing the workflow state for a project.
It performs no paid calls, no rendering, and no project writes.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from costgate import gate as cost_gate
from narration import plan as nar_plan
from reference import analyzer as ref_analyzer
from review import analyzer as rev_analyzer
from review import reviewer as rev_reviewer
from review import revision as rev_revision

_COST_STATUS = {
    "awaiting_approval": "AWAITING_APPROVAL",
    "approved": "APPROVED",
    "rejected": "REJECTED",
    "budget_exceeded": "BUDGET_EXCEEDED",
}


def cost_gate_state(gate: Optional[Dict], reason: str = None) -> Dict:
    """Map a cost-gate document to the workflow status vocabulary."""
    if gate is None:
        return {"gate_id": None, "status": "BLOCKED", "allowed": False,
                "cost_status": "not_run", "unknown_cost": False,
                "reason": reason or "no cost gate run"}
    wf = _COST_STATUS.get(gate.get("status"), "BLOCKED")
    cs = gate.get("cost_status", "unknown")
    unknown = cs in ("unknown", "partial")
    allowed = bool(cost_gate.generation_allowed(gate))
    return {
        "gate_id": gate.get("gate_id"),
        "status": wf,
        "cost_status": cs,
        "unknown_cost": unknown,
        "allowed": allowed,
        "estimated_total_usd": gate.get("estimated_total_usd"),
        "approved_cost_limit_usd": gate.get("approved_cost_limit_usd"),
        "reason": None if allowed else "paid generation blocked; human cost approval required",
    }


def inspect(project_dir: str, reference_id: Optional[str] = None,
            plan_path: Optional[str] = None,
            pricing_path: Optional[str] = None) -> Dict:
    # 1) Reference style context (optional, read-only)
    if reference_id:
        profile = ref_analyzer.load_profile(reference_id)
        if profile:
            reference = {"status": "loaded", "profile_id": profile["reference_id"],
                         "source_type": profile["source_type"],
                         "observed_keys": sorted(profile["observed"].keys()),
                         "inferred_keys": [k for k, v in profile["inferred"].items() if v]}
        else:
            reference = {"status": "missing", "profile_id": reference_id}
    else:
        reference = {"status": "skipped"}

    # 2) Cost gate (pure build when a plan is given; else load saved gate)
    plan_file = plan_path or os.path.join(project_dir, "asset-plan.json")
    built = None
    if plan_path:
        pricing = cost_gate.load_pricing(pricing_path) if pricing_path else cost_gate.load_pricing()
        built = cost_gate.build_gate(cost_gate.load_json(plan_path), pricing,
                                     project_dir, created_at="")
    saved = cost_gate.load_gate(cost_gate.gate_id_for(project_dir))
    cost = cost_gate_state(built or saved,
                           reason="no asset plan supplied" if not plan_path and not saved else None)
    if plan_path:
        cost["plan"] = plan_path

    # 3) Word-level timing + captions (read-only, normalized only)
    model = rev_analyzer.htmlmodel.parse(project_dir)
    timings_doc, timings_path, timings_err = rev_analyzer._load_word_timings(project_dir)
    captions, captions_path = rev_analyzer._load_captions(project_dir, model)
    timing = {
        "word_timings": bool(timings_doc),
        "path": timings_path,
        "word_count": len((timings_doc or {}).get("words", [])),
        "captions": len(captions) if captions else 0,
        "captions_path": captions_path,
        "error": timings_err,
    }

    # 4) Review V1 (measure + propose only; nothing is applied or saved here)
    report = rev_analyzer.analyze(project_dir)
    proposals, notes = rev_reviewer.review(project_dir, report)
    by_cat: Dict[str, int] = {}
    for f in report["findings"]:
        by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
    statuses: Dict[str, int] = {}
    for p in proposals:
        statuses[p["status"]] = statuses.get(p["status"], 0) + 1
    review = {
        "revision": report["revision"],
        "findings": len(report["findings"]),
        "findings_by_category": by_cat,
        "proposals": len(proposals),
        "proposal_status": statuses,
        "unavailable": [u["check"] for u in report["unavailable"]],
        "notes": notes,
    }

    pending = sum(v for k, v in statuses.items() if k == "awaiting_review")

    # 5) Narration mode + gated pipeline (read-only)
    nar = nar_plan.plan(project_dir)
    narration = {
        "mode": nar["mode"],
        "enabled": nar["enabled"],
        "blocked": nar["blocked"],
        "speech_steps": {s["id"]: s["status"] for s in nar["steps"]},
        "scene_requirements": nar["scene_requirements"],
    }

    return {
        "project": rev_revision.slug_for(project_dir),
        "reference": reference,
        "cost_gate": cost,
        "timing": timing,
        "review": review,
        "narration": narration,
        "gates": {
            "gate1_cost": {"status": cost["status"], "allowed": cost["allowed"]},
            "gate2_review": {"pending_proposals": pending, "requires_human_approval": True},
        },
        "paid_generation_allowed": cost["allowed"],
        "review_auto_applied": False,
    }


def render_report_md(state: Dict) -> str:
    c = state["cost_gate"]
    t = state["timing"]
    r = state["review"]
    L = ["VIDEO STUDIO — INTEGRATED STATUS", "", "Project: %s" % state["project"], ""]
    L.append("Reference style context (optional): %s" % state["reference"]["status"])
    if state["reference"]["status"] == "loaded":
        L.append("  profile: %s (%s)" % (state["reference"]["profile_id"],
                                         state["reference"]["source_type"]))
    L.append("")
    L.append("GATE 1 — Cost approval (before paid generation)")
    L.append("  Status: %s" % c["status"])
    L.append("  Cost status: %s" % c["cost_status"])
    if c.get("estimated_total_usd") is not None:
        L.append("  Estimated total: USD %.4f" % c["estimated_total_usd"])
    if c.get("unknown_cost"):
        L.append("  Note: pricing is UNKNOWN/partial — surfaced, never invented")
    L.append("  Paid generation allowed: %s" % c["allowed"])
    L.append("")
    L.append("Word-level timing")
    L.append("  word timings present: %s" % t["word_timings"])
    L.append("  words: %d, captions: %d" % (t["word_count"], t["captions"]))
    if t["error"]:
        L.append("  timing error: %s" % t["error"])
    L.append("")
    L.append("Review V1 (measure → finding → proposal)")
    L.append("  revision: %s" % r["revision"])
    L.append("  findings: %d %s" % (r["findings"], r["findings_by_category"] or ""))
    L.append("  proposals: %d %s" % (r["proposals"], r["proposal_status"] or ""))
    if r["unavailable"]:
        L.append("  unavailable checks: %s" % ", ".join(r["unavailable"]))
    L.append("")
    n = state.get("narration", {})
    L.append("Narration mode")
    L.append("  Mode: %s (%s)" % (n.get("mode", "off"),
                                  "enabled" if n.get("enabled") else "disabled"))
    if n.get("enabled"):
        for s in n.get("scene_requirements", []):
            flag = "  <-- lengthen" if s["needs_lengthen"] else ""
            L.append("  Scene %d: current %.3fs, required %.3fs%s"
                     % (s["index"], s["current_duration_s"], s["required_duration_s"], flag))
        for sid, st in (n.get("speech_steps") or {}).items():
            L.append("  %-11s %s" % (st, sid))
        L.append("  Pipeline blocked: %s" % n.get("blocked"))
    L.append("")
    L.append("GATE 2 — Creative/technical approval (before applying proposals)")
    L.append("  Pending proposals: %d" % state["gates"]["gate2_review"]["pending_proposals"])
    L.append("  Requires explicit human approval: yes")
    L.append("  Auto-applied: %s" % state["review_auto_applied"])
    L.append("")
    L.append("No project, render, brand profile, or paid resource was modified.")
    return "\n".join(L) + "\n"