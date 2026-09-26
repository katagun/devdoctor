from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from starlette.responses import JSONResponse, Response

from devdoctor import discovery, registry
from devdoctor.ports import Shell
from devdoctor.providers.base import Provider
from devdoctor.providers.git_worktrees import GitWorktreeProvider
from devdoctor.types import CleanupOpts, Report, ScanFilters, ShellResult
from devdoctor.web.cleanup_runner import CleanupRunner
from devdoctor.web.models import CleanJobCreate, ConfirmAnswer, PromptAnswer
from devdoctor.web.runner_registry import JobInProgressError
from devdoctor.web.subprocess_stream import OnChunk, run_argv_streaming

router = APIRouter(prefix="/api/clean")


def _owning_providers(entry_ids: list[str], providers: list[Provider]) -> frozenset[str] | None:
    """The providers named by the ``"{provider}:{id}"`` prefix of every selected id.

    ``None`` (scan everything) when any id has no such prefix, so an id this build
    cannot attribute is still looked for everywhere before it is called unknown.
    """
    names = {provider.name for provider in providers}
    owners: set[str] = set()
    for entry_id in entry_ids:
        owner = next((name for name in names if entry_id.startswith(f"{name}:")), None)
        if owner is None:
            return None
        owners.add(owner)
    return frozenset(owners) if owners else None


def _scan_selection(shell: Shell, entry_ids: list[str]) -> Report:
    """The current state of the providers that own ``entry_ids``.

    Blocking: it walks the disk, which takes minutes for a provider such as
    node_modules on a large machine, so the route runs it on a worker thread.
    """
    providers_list = registry.load_providers(shell)
    # Uncontained: this scan establishes current state for the selection, so every id
    # a filtered view could have shown still exists (spec §6.4).
    #
    # Only the providers that own a selected id are re-run (#92). Coverers and the
    # entries they cover share a provider, and execute-time worktree containment
    # only ever looks at selected entries, so nothing outside those providers can
    # affect the job.
    filters = ScanFilters(providers=_owning_providers(entry_ids, providers_list))
    return discovery.scan(providers_list, filters, datetime.now(UTC), contain=False)


@router.post("/jobs")
async def start_job(body: CleanJobCreate, request: Request) -> Response:
    registry_obj = request.app.state.runner_registry

    async def run_line(argv: tuple[str, ...]) -> ShellResult:
        # Dummy default; the runner uses run_line_with_chunks below.
        return await run_argv_streaming(argv, on_chunk=_noop_chunk)

    try:
        # Held from before the re-scan until the runner fills the slot, so a second
        # start (a repeated click on execute) is refused at once, not after a re-scan
        # of its own.
        with registry_obj.claim():
            # Off the event loop: there the scan would stall every other request, this
            # job's own event stream included, until it finished.
            report = await asyncio.to_thread(
                _scan_selection, request.app.state.shell, body.entry_ids
            )
            # Entry ids are globally unique (namespaced "{provider}:{id}" in
            # discovery.scan), so selecting by bare id can never cross providers.
            known_ids = {e.id for e in report.entries}
            unknown = [eid for eid in body.entry_ids if eid not in known_ids]
            if unknown:
                return JSONResponse(
                    status_code=400,
                    content={"error": {"code": "unknown_entry", "ids": unknown}},
                )
            # Filter the report down to just the selected entries — cleanup walks
            # candidates from there. Every selected entry stays in the job: the executor
            # skips an entry only once the worktree holding it has actually been
            # removed, so each one gets a result (spec §6.4).
            selected = set(body.entry_ids)
            report.entries = [e for e in report.entries if e.id in selected]
            runner = registry_obj.create(
                lambda: CleanupRunner(
                    report=report,
                    opts=CleanupOpts(
                        execute=True,
                        yes_safe=body.yes_safe,
                        allow_dangerous=body.allow_dangerous,
                    ),
                    run_line=run_line,
                    # Re-check each worktree immediately before removing it (#110).
                    verify=GitWorktreeProvider(request.app.state.shell).verify_removable,
                    storage=request.app.state.storage,
                )
            )
    except JobInProgressError:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "job_in_progress",
                    "message": "a cleanup is already active",
                }
            },
        )

    async def run_line_with_chunks(argv: tuple[str, ...], on_chunk: OnChunk) -> ShellResult:
        return await run_argv_streaming(argv, on_chunk=on_chunk)

    runner.run_line_with_chunks = run_line_with_chunks

    async def _execute() -> None:
        try:
            await runner.run()
        finally:
            registry_obj.release(runner)

    runner._task = asyncio.create_task(_execute())
    return JSONResponse(content={"job_id": runner.id})


@router.get("/jobs/{job_id}/events")
async def events(job_id: str, request: Request) -> EventSourceResponse:
    registry_obj = request.app.state.runner_registry
    runner = registry_obj.active()
    if runner is None or runner.id != job_id:
        raise HTTPException(status_code=404, detail="no active job with that id")

    async def _stream() -> Any:
        completed = False
        try:
            while True:
                ev = await runner.events.get()
                yield {"event": ev["event"], "data": json.dumps(ev["data"])}
                if ev["event"] in ("done", "job_error"):
                    completed = True
                    return
        finally:
            # If the client disconnected mid-job, cancel the runner so the
            # registry slot is released and no orphan task keeps it busy.
            if not completed:
                await runner.cancel()

    return EventSourceResponse(_stream(), ping=10)


@router.post("/jobs/{job_id}/answer")
async def answer(job_id: str, body: PromptAnswer, request: Request) -> Response:
    registry_obj = request.app.state.runner_registry
    runner = registry_obj.active()
    if runner is None or runner.id != job_id:
        raise HTTPException(status_code=404, detail="no active job with that id")
    await runner.answer_prompt(entry_id=body.entry_id, choice=body.choice)
    return Response(status_code=204)


@router.post("/jobs/{job_id}/confirm")
async def confirm(job_id: str, body: ConfirmAnswer, request: Request) -> Response:
    registry_obj = request.app.state.runner_registry
    runner = registry_obj.active()
    if runner is None or runner.id != job_id:
        raise HTTPException(status_code=404, detail="no active job with that id")
    await runner.answer_confirm(body.confirmed)
    return Response(status_code=204)


@router.post("/jobs/{job_id}/cancel")
async def cancel(job_id: str, request: Request) -> Response:
    registry_obj = request.app.state.runner_registry
    runner = registry_obj.active()
    if runner is None or runner.id != job_id:
        raise HTTPException(status_code=404, detail="no active job with that id")
    await runner.cancel()
    return Response(status_code=204)


async def _noop_chunk(stream: str, text: str) -> None:
    return None
