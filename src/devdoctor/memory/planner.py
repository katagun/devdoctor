from __future__ import annotations

from devdoctor.memory.types import (
    MemoryActionRisk,
    MemoryPlan,
    MemoryPlanAction,
    MemoryReport,
    MemorySuggestion,
    MemoryWorkload,
)

_GIB = 1024**3
_DEFAULT_SAFETY_MARGIN_BYTES = 1 * _GIB
_MIN_OS_RESERVE_BYTES = 1 * _GIB
_OS_RESERVE_FRACTION = 0.10
_RISK_ORDER: dict[MemoryActionRisk, int] = {
    "safe": 0,
    "reclaimable": 1,
    "dangerous": 2,
}
_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def default_safety_margin_bytes() -> int:
    return _DEFAULT_SAFETY_MARGIN_BYTES


def os_reserve_bytes(total_bytes: int) -> int:
    return max(_MIN_OS_RESERVE_BYTES, int(total_bytes * _OS_RESERVE_FRACTION))


def plan_workload(
    report: MemoryReport,
    workload: MemoryWorkload,
    suggestions: list[MemorySuggestion],
    *,
    safety_margin_bytes: int | None = None,
) -> MemoryPlan:
    margin = _DEFAULT_SAFETY_MARGIN_BYTES if safety_margin_bytes is None else safety_margin_bytes
    reserve = os_reserve_bytes(report.system.total_bytes)
    usable = max(0, report.system.available_bytes - reserve - margin)
    deficit = max(0, workload.required_bytes - usable)
    actions = _rank_actions(suggestions)
    selected: list[MemoryPlanAction] = []
    reclaimed = 0
    if deficit > 0:
        for action in actions:
            selected.append(action)
            if action.estimated_bytes is not None:
                reclaimed += action.estimated_bytes
            if reclaimed >= deficit:
                break
    remaining = max(0, deficit - reclaimed)
    return MemoryPlan(
        workload=workload,
        fits_now=deficit == 0,
        required_bytes=workload.required_bytes,
        available_bytes=report.system.available_bytes,
        os_reserve_bytes=reserve,
        safety_margin_bytes=margin,
        usable_bytes=usable,
        deficit_bytes=deficit,
        planned_reclaim_bytes=reclaimed,
        remaining_deficit_bytes=remaining,
        actions=selected,
    )


def _rank_actions(suggestions: list[MemorySuggestion]) -> list[MemoryPlanAction]:
    actions: list[MemoryPlanAction] = []
    for suggestion in suggestions:
        for action in suggestion.actions:
            estimate = action.estimated_bytes
            if estimate is None:
                estimate = suggestion.estimated_bytes
            actions.append(
                MemoryPlanAction(
                    suggestion_id=suggestion.id,
                    action_id=action.id,
                    label=action.label,
                    estimated_bytes=estimate,
                    risk=action.risk,
                    confidence=suggestion.confidence,
                )
            )
    actions.sort(
        key=lambda action: (
            _RISK_ORDER[action.risk],
            _CONFIDENCE_ORDER[action.confidence],
            -(action.estimated_bytes or 0),
            action.label,
        )
    )
    return actions
