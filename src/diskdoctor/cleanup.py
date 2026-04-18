from __future__ import annotations

from diskdoctor.ports import Shell
from diskdoctor.types import (
    CleanResult,
    CleanupOpts,
    Confirm,
    Entry,
    PromptChoice,
    Report,
)


def run(
    report: Report,
    *,
    shell: Shell,
    prompt_choice: PromptChoice,
    confirm: Confirm,
    opts: CleanupOpts,
) -> list[CleanResult]:
    """Drive the cleanup flow. Preview (opts.execute=False) returns dry-run
    results without any prompt or shell calls. Execute mode will be added in
    Task 10.
    """
    candidates = _select_candidates(report, opts)

    if not opts.execute:
        return [
            CleanResult(entry_id=e.id, status="dry_run", freed_bytes=e.size_bytes)
            for e in candidates
        ]

    raise NotImplementedError("execute mode lands in Task 10")


def _select_candidates(report: Report, opts: CleanupOpts) -> list[Entry]:
    entries = report.entries
    if opts.providers is not None:
        entries = [e for e in entries if e.provider in opts.providers]
    return entries
