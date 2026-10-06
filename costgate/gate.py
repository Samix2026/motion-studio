"""Cost-gate computation, approval, and reporting.

Pure functions over dicts: build a gate from a plan, decide approval, record
actuals, and render a report. No network, no provider calls, no project writes.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, List, Optional, Tuple

from . import schema

_DEFAULT_PRICING = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pricing.json")
_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
_REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


# ---------------------------------------------------------------- io helpers

def load_json(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_pricing(path: Optional[str] = None) -> Dict:
    return schema.validate_pricing(load_json(path or _DEFAULT_PRICING))


def gate_id_for(project: str) -> str:
    digest = hashlib.sha1(project.encode("utf-8")).hexdigest()[:8]
    return "%s-%s" % (os.path.basename(os.path.normpath(project)), digest)


# ---------------------------------------------------------------- pricing

def _price_for(item: Dict, pricing: Dict) -> Tuple[Optional[float], Optional[Dict]]:
    prices = pricing.get("prices", {})
    ref = item.get("pricing_ref")
    if ref and ref in prices:
        entry = prices[ref]
    else:
        key = ".".join(str(x) for x in (item["provider"], item.get("model") or "",
                                        item["unit_basis"]))
        entry = prices.get(key)
    if not entry:
        return None, None
    if entry.get("confidence", "unknown") == "unknown" or entry.get("unit_price") is None:
        return None, entry
    return float(entry["unit_price"]), entry


def _quantity(item: Dict) -> float:
    if item.get("quantity") is not None:
        return float(item["quantity"])
    return float(item.get("requests") or 1)


# ---------------------------------------------------------------- build

def build_gate(plan: Dict, pricing: Dict, project: str, created_at: str,
               currency: str = None) -> Dict:
    """Compute estimated costs. Unknown pricing stays UNKNOWN."""
    schema.validate_plan(plan)
    schema.validate_pricing(pricing)
    currency = currency or pricing.get("currency") or "USD"

    items: List[Dict] = []
    known_sum = 0.0
    known_count = 0
    sources: List[str] = []

    for it in plan["items"]:
        unit_price, entry = _price_for(it, pricing)
        qty = _quantity(it)
        if unit_price is not None:
            estimated = round(qty * unit_price, 6)
            confidence = entry.get("confidence", "estimated")
            cost_status = "known" if confidence == "verified" else "estimated"
            src = entry.get("source")
            known_sum += estimated
            known_count += 1
            if src:
                sources.append(src)
        else:
            estimated = None
            confidence = (entry or {}).get("confidence", "unknown")
            cost_status = "unknown"
            src = (entry or {}).get("source")

        items.append({
            "scene": it.get("scene"),
            "asset_type": it["asset_type"],
            "provider": it["provider"],
            "model": it.get("model"),
            "requests": it.get("requests"),
            "unit_basis": it["unit_basis"],
            "quantity": qty,
            "unit_price": unit_price,
            "estimated_cost_usd": estimated,
            "pricing_source": src,
            "pricing_confidence": confidence,
            "cost_status": cost_status,
        })

    total = round(known_sum, 6)
    if known_count == len(items) and items:
        overall = "known"
        estimated_total: Optional[float] = total
    elif known_count == 0:
        overall = "unknown"
        estimated_total = None
    else:
        overall = "partial"
        estimated_total = None

    warnings: List[str] = []
    unknown_n = len(items) - known_count
    if unknown_n:
        warnings.append("%d item(s) have no verified pricing and are UNKNOWN." % unknown_n)
    if not items:
        warnings.append("Plan has no paid items.")

    return {
        "gate_id": gate_id_for(project),
        "project": project,
        "created_at": created_at,
        "currency": currency,
        "items": items,
        "known_count": known_count,
        "unknown_count": unknown_n,
        "estimated_known_subtotal_usd": total,
        "estimated_total_usd": estimated_total,
        "approved_cost_limit_usd": None,
        "provider_billed_cost_usd": None,
        "session_reported_cost_usd": None,
        "cost_variance_usd": None,
        "cost_status": overall,
        "status": "awaiting_approval",
        "pricing_checked_at": pricing.get("checked_at"),
        "pricing_source": sorted(set(sources)) or pricing.get("sources") or [],
        "warnings": warnings,
        "history": [],
    }


# ---------------------------------------------------------------- decisions

def set_decision(gate: Dict, decision: str, limit: Optional[float] = None,
                 at: Optional[str] = None) -> Dict:
    g = json.loads(json.dumps(gate))
    if decision not in ("approve", "reject"):
        raise schema.CostGateError("decision must be 'approve' or 'reject'")

    history = {"at": at, "action": decision, "limit": limit}
    g.setdefault("history", []).append(history)

    if decision == "reject":
        g["status"] = "rejected"
        g["approved_cost_limit_usd"] = None
        return g

    g["approved_cost_limit_usd"] = limit
    total = g.get("estimated_total_usd")
    if limit is not None and total is not None and total > limit:
        g["status"] = "budget_exceeded"
        g["warnings"] = list(g.get("warnings", [])) + [
            "Estimated total %.4f exceeds the approved limit %.4f." % (total, limit)]
        return g
    if total is None and g.get("unknown_count", 0) > 0:
        g["warnings"] = list(g.get("warnings", [])) + [
            "Approved with UNKNOWN cost items; spend is not bounded by a verified estimate."]
    g["status"] = "approved"
    return g


def record_actuals(gate: Dict, provider_billed_usd: Optional[float] = None,
                   session_reported_usd: Optional[float] = None) -> Dict:
    g = json.loads(json.dumps(gate))
    g["provider_billed_cost_usd"] = provider_billed_usd
    g["session_reported_cost_usd"] = session_reported_usd
    est = g.get("estimated_total_usd")
    if provider_billed_usd is not None and est is not None:
        g["cost_variance_usd"] = round(provider_billed_usd - est, 6)
    else:
        g["cost_variance_usd"] = None
    return g


def generation_allowed(gate: Dict) -> bool:
    """Paid generation may start only after approval and within budget."""
    return gate.get("status") == "approved"


# ---------------------------------------------------------------- report

def render_report_md(gate: Dict) -> str:
    L = ["COST GATE", "", "Project:", gate["project"], "",
         "Currency: %s" % gate["currency"], ""]
    for it in gate["items"]:
        L.append("Scene %s" % (it["scene"] if it["scene"] is not None else "-"))
        L.append("Provider: %s" % it["provider"])
        L.append("Type: %s" % it["asset_type"])
        if it.get("model"):
            L.append("Model: %s" % it["model"])
        if it["unit_basis"] == "request" and it.get("requests") is not None:
            L.append("Requests: %d" % it["requests"])
        else:
            L.append("Quantity: %g %s" % (it["quantity"], it["unit_basis"]))
        if it["estimated_cost_usd"] is None:
            L.append("Estimated cost: UNKNOWN")
        else:
            L.append("Estimated cost: %s %.2f" % (gate["currency"], it["estimated_cost_usd"]))
        L.append("Pricing: %s (%s)" % (it.get("pricing_source") or "none",
                                       it.get("pricing_confidence")))
        L.append("")
    if gate.get("estimated_total_usd") is None:
        L.append("Estimated total:")
        L.append("UNKNOWN (known subtotal %s %.4f; %d unknown item(s))"
                 % (gate["currency"], gate["estimated_known_subtotal_usd"],
                    gate["unknown_count"]))
    else:
        L.append("Estimated total:")
        L.append("%s %.2f" % (gate["currency"], gate["estimated_total_usd"]))
    L.append("")
    if gate.get("approved_cost_limit_usd") is not None:
        L.append("Approved limit: %s %.2f" % (gate["currency"], gate["approved_cost_limit_usd"]))
        L.append("")
    if gate.get("provider_billed_cost_usd") is not None:
        L.append("Provider billed: %s %.4f" % (gate["currency"], gate["provider_billed_cost_usd"]))
    if gate.get("session_reported_cost_usd") is not None:
        L.append("Session reported: %s %.4f" % (gate["currency"], gate["session_reported_cost_usd"]))
    if gate.get("cost_variance_usd") is not None:
        L.append("Variance: %s %.4f" % (gate["currency"], gate["cost_variance_usd"]))
    if any(gate.get(k) is not None for k in ("provider_billed_cost_usd",
                                             "session_reported_cost_usd", "cost_variance_usd")):
        L.append("")
    L.append("Status:")
    L.append(gate["status"].upper())
    if gate.get("warnings"):
        L.append("")
        L.append("Warnings:")
        for w in gate["warnings"]:
            L.append("- %s" % w)
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- persistence

def save_gate(gate: Dict) -> Tuple[str, str]:
    os.makedirs(_STATE_DIR, exist_ok=True)
    os.makedirs(_REPORT_DIR, exist_ok=True)
    gid = gate["gate_id"]
    state_path = os.path.join(_STATE_DIR, "%s.json" % gid)
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(gate, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    report_path = os.path.join(_REPORT_DIR, "%s.md" % gid)
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(render_report_md(gate))
    return state_path, report_path


def load_gate(gate_id: str) -> Optional[Dict]:
    path = os.path.join(_STATE_DIR, "%s.json" % gate_id)
    if not os.path.isfile(path):
        return None
    return load_json(path)
