from __future__ import annotations

from datetime import UTC, datetime

from devdoctor.memory.planner import plan_workload
from devdoctor.memory.types import (
    MemoryAction,
    MemoryConsumer,
    MemoryReport,
    MemorySuggestion,
    MemoryWorkload,
    SystemMemory,
)


def _report(available_bytes: int) -> MemoryReport:
    return MemoryReport(
        scanned_at=datetime(2026, 5, 4, tzinfo=UTC),
        hostname="h",
        platform="darwin",
        system=SystemMemory(
            total_bytes=16 * 1024**3,
            available_bytes=available_bytes,
            used_bytes=16 * 1024**3 - available_bytes,
            swap_used_bytes=0,
            compressed_bytes=0,
            pressure="ok",
        ),
        consumers=[
            MemoryConsumer(
                id="pid:1",
                pid=1,
                parent_pid=0,
                name="Firefox",
                kind="browser",
                rss_bytes=2 * 1024**3,
                private_bytes=None,
                command="firefox",
            )
        ],
    )


def _workload(required_bytes: int) -> MemoryWorkload:
    return MemoryWorkload(
        id="test",
        label="Test workload",
        kind="custom",
        required_bytes=required_bytes,
        description="test",
    )


def test_plan_fits_when_usable_headroom_exceeds_required() -> None:
    plan = plan_workload(
        _report(available_bytes=8 * 1024**3),
        _workload(required_bytes=2 * 1024**3),
        [],
        safety_margin_bytes=1 * 1024**3,
    )

    assert plan.fits_now is True
    assert plan.deficit_bytes == 0
    assert plan.actions == []


def test_plan_selects_lowest_risk_actions_until_deficit_is_covered() -> None:
    suggestions = [
        MemorySuggestion(
            id="danger",
            title="danger",
            reason="danger",
            estimated_bytes=10 * 1024**3,
            confidence="high",
            actions=[
                MemoryAction(
                    id="kill",
                    kind="terminate_process",
                    label="Kill process",
                    target_id="pid:1",
                    estimated_bytes=10 * 1024**3,
                    risk="dangerous",
                )
            ],
        ),
        MemorySuggestion(
            id="docker",
            title="docker",
            reason="docker",
            estimated_bytes=4 * 1024**3,
            confidence="medium",
            actions=[
                MemoryAction(
                    id="stop-docker",
                    kind="stop_service",
                    label="Stop Docker",
                    target_id="docker",
                    estimated_bytes=4 * 1024**3,
                    risk="reclaimable",
                )
            ],
        ),
    ]

    plan = plan_workload(
        _report(available_bytes=2 * 1024**3),
        _workload(required_bytes=4 * 1024**3),
        suggestions,
        safety_margin_bytes=1 * 1024**3,
    )

    assert plan.fits_now is False
    assert plan.actions[0].action_id == "stop-docker"
    assert plan.remaining_deficit_bytes == 0
