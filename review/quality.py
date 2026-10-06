"""Quality score (QUALITY_SCORE.md) with independently sourced visual quality.

Measured categories (accuracy, hook/editorial, assets, brand, Arabic/RTL,
technical) are scored as before. Visual quality (15) can no longer be
self-scored by the producing agent: it comes from a multimodal review or a
human reviewer. Without one it is `not_independently_reviewed`, and the run
cannot be marked ready to publish. AI judgment can never trigger a hard fail.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional

from .proposal_schema import AI_JUDGMENT

MAXIMA = {
    "accuracy_sourcing": 30,
    "hook_editorial_clarity": 20,
    "visual_quality": 15,
    "asset_quality": 10,
    "brand_identity_fit": 10,
    "arabic_rtl_quality": 10,
    "technical_validation": 5,
}
MEASURED_KEYS = [k for k in MAXIMA if k != "visual_quality"]
MEASURED_MAX = sum(MAXIMA[k] for k in MEASURED_KEYS)  # 85
VISUAL_SOURCES = {"multimodal_review", "human_review"}


class QualityError(ValueError):
    pass


def _decision(total: float) -> str:
    if total >= 90:
        return "ready_to_publish"
    if total >= 80:
        return "minor_review_required"
    return "do_not_publish"


def score(breakdown: Dict[str, Optional[float]], visual: Optional[Dict] = None,
          hard_fails: Iterable[Dict] = ()) -> Dict:
    """breakdown: the six measured categories. visual: {"score", "source"} from
    an independent review, or None. hard_fails: [{"reason", "basis"}]."""
    for key in MEASURED_KEYS:
        value = breakdown.get(key)
        if not isinstance(value, (int, float)) or not (0 <= value <= MAXIMA[key]):
            raise QualityError("%s must be a number within 0..%d" % (key, MAXIMA[key]))
    if breakdown.get("visual_quality") is not None:
        raise QualityError("visual_quality cannot be self-scored; pass visual="
                           "{'score': .., 'source': 'multimodal_review'|'human_review'}")
    fails = list(hard_fails)
    for hf in fails:
        if hf.get("basis") == AI_JUDGMENT:
            raise QualityError("AI judgment cannot trigger a hard fail: %s" % hf.get("reason"))
    measured = round(sum(float(breakdown[k]) for k in MEASURED_KEYS), 2)

    out_breakdown = {k: breakdown[k] for k in MEASURED_KEYS}
    if visual is not None:
        if visual.get("source") not in VISUAL_SOURCES:
            raise QualityError("visual quality source must be one of %s (never self)"
                               % sorted(VISUAL_SOURCES))
        v = visual.get("score")
        if not isinstance(v, (int, float)) or not (0 <= v <= MAXIMA["visual_quality"]):
            raise QualityError("visual score must be within 0..15")
        out_breakdown["visual_quality"] = v
        total = round(measured + float(v), 2)
        decision = _decision(total)
        status, normalized = "independently_reviewed", None
    else:
        out_breakdown["visual_quality"] = None
        total = None
        normalized = round(measured / MEASURED_MAX * 100.0, 1)
        decision = _decision(normalized)
        if decision == "ready_to_publish":
            decision = "minor_review_required"  # visual not independently reviewed
        status = "not_independently_reviewed"

    hard = bool(fails)
    if hard:
        decision = "do_not_publish"
    return {
        "quality_score": total,
        "measured_score": measured,
        "measured_max": MEASURED_MAX,
        "normalized_without_visual": normalized,
        "quality_breakdown": out_breakdown,
        "visual_quality_source": visual.get("source") if visual else None,
        "visual_quality_status": status,
        "hard_fail_triggered": hard,
        "hard_fail_reasons": [hf.get("reason") for hf in fails],
        "decision": decision,
        "ready_to_publish": decision == "ready_to_publish",
    }
