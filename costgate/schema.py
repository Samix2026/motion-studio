"""Validation for cost-gate plans and gate objects (stdlib only).

No pricing is defined here. Prices live only in an explicit pricing catalog
(``pricing.json`` or a file passed on the CLI) with a recorded source.
"""

from __future__ import annotations

from typing import Dict, List

ASSET_TYPES = {"video", "image", "tts", "sfx", "music", "external_api"}
UNIT_BASES = {"request", "character", "second", "minute", "image", "1k_tokens"}
CONFIDENCE = {"verified", "estimated", "unknown"}
GATE_STATUS = {"awaiting_approval", "approved", "rejected", "budget_exceeded"}


class CostGateError(ValueError):
    pass


def _need(obj: Dict, key: str, types, where: str):
    if key not in obj:
        raise CostGateError("%s: missing field '%s'" % (where, key))
    if obj[key] is not None and not isinstance(obj[key], types):
        raise CostGateError("%s: field '%s' wrong type" % (where, key))


def validate_plan_item(item: Dict) -> Dict:
    w = "plan item"
    _need(item, "asset_type", str, w)
    _need(item, "provider", str, w)
    _need(item, "unit_basis", str, w)
    if item["asset_type"] not in ASSET_TYPES:
        raise CostGateError("%s: unsupported asset_type '%s'" % (w, item["asset_type"]))
    if item["unit_basis"] not in UNIT_BASES:
        raise CostGateError("%s: unsupported unit_basis '%s'" % (w, item["unit_basis"]))
    for k in ("scene", "model", "requests", "quantity", "pricing_ref"):
        if k in item and item[k] is not None:
            if k in ("scene", "requests"):
                if not isinstance(item[k], int) or item[k] < 0:
                    raise CostGateError("%s: '%s' must be a non-negative int" % (w, k))
            elif k == "quantity":
                if not isinstance(item[k], (int, float)) or item[k] < 0:
                    raise CostGateError("%s: 'quantity' must be a non-negative number" % w)
            elif not isinstance(item[k], str):
                raise CostGateError("%s: '%s' must be a string" % (w, k))
    if not item.get("quantity") and not item.get("requests"):
        raise CostGateError("%s: needs 'quantity' or 'requests'" % w)
    return item


def validate_plan(plan: Dict) -> Dict:
    if not isinstance(plan, dict) or "items" not in plan or not isinstance(plan["items"], list):
        raise CostGateError("plan: must be an object with an 'items' array")
    for it in plan["items"]:
        validate_plan_item(it)
    return plan


def validate_pricing(pricing: Dict) -> Dict:
    if not isinstance(pricing, dict):
        raise CostGateError("pricing: must be an object")
    prices = pricing.get("prices")
    if prices is None:
        raise CostGateError("pricing: missing 'prices'")
    if not isinstance(prices, dict):
        raise CostGateError("pricing: 'prices' must be an object")
    for key, entry in prices.items():
        if not isinstance(entry, dict):
            raise CostGateError("pricing[%s]: must be an object" % key)
        conf = entry.get("confidence", "unknown")
        if conf not in CONFIDENCE:
            raise CostGateError("pricing[%s]: bad confidence '%s'" % (key, conf))
        if entry.get("unit_price") is not None and not isinstance(entry["unit_price"], (int, float)):
            raise CostGateError("pricing[%s]: unit_price must be a number or null" % key)
    return pricing


def validate_gate(gate: Dict) -> Dict:
    if not isinstance(gate, dict):
        raise CostGateError("gate: must be an object")
    for k in ("gate_id", "project", "items", "status", "cost_status"):
        _need(gate, k, (str, list, dict), "gate")
    if gate["status"] not in GATE_STATUS:
        raise CostGateError("gate: bad status '%s'" % gate["status"])
    if not isinstance(gate["items"], list):
        raise CostGateError("gate: 'items' must be a list")
    return gate
