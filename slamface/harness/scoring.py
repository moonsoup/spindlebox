"""Weighted tier scoring: criteria × weights profile → 0-100 score.

Each criterion earns partial credit (fraction of its relevant stage records that
passed). Criteria with no relevant records (e.g. cargo absent, no dispatch targets)
drop out of the denominator instead of penalizing or inflating the score.
"""

from __future__ import annotations

_CRITERIA_STAGES = {
    "index_success": ("index",),
    "validate_expected": ("validate",),
    "generate_compiles": ("cargo_check",),
    "dispatch_roundtrip": ("dispatch",),
    "aux_probes": ("gaps_probe", "workflows_probe"),
}


def score_run(records: list[dict], profile: dict[str, int]) -> dict:
    criteria: dict[str, dict] = {}
    total_weight = 0.0
    earned = 0.0
    for criterion, weight in profile.items():
        if criterion == "zero_tracebacks":
            relevant = records
            passed = [r for r in relevant if r.get("status") != "error"]
        else:
            stages = _CRITERIA_STAGES.get(criterion, ())
            relevant = [r for r in records
                        if r.get("stage") in stages and r.get("status") != "skip"]
            passed = [r for r in relevant if r.get("status") == "ok"]
        if not relevant:
            criteria[criterion] = {"weight": weight, "evaluated": False}
            continue
        fraction = len(passed) / len(relevant)
        criteria[criterion] = {
            "weight": weight, "evaluated": True,
            "passed": len(passed), "total": len(relevant),
            "fraction": round(fraction, 4),
        }
        total_weight += weight
        earned += weight * fraction
    score = round(100.0 * earned / total_weight, 2) if total_weight else 0.0
    return {"score": score, "criteria": criteria}
