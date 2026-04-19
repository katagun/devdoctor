from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from starlette.responses import JSONResponse, Response

from diskdoctor import discovery, registry
from diskdoctor.types import CleanupOpts, ScanFilters, ShellResult
from diskdoctor.web.cleanup_runner import CleanupRunner
from diskdoctor.web.models import CleanJobCreate, ConfirmAnswer, PromptAnswer
from diskdoctor.web.subprocess_stream import OnChunk, run_line_streaming

router = APIRouter(prefix="/api/clean")


@router.post("/jobs")
async def start_job(body: CleanJobCreate, request: Request) -> Response:
    providers_list = registry.load_providers(request.app.state.shell)
    report = discovery.scan(providers_list, ScanFilters(), datetime.now(UTC))
    known_ids = {e.id for e in report.entries}
    unknown = [eid for eid in body.entry_ids if eid not in known_ids]
    if unknown:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "unknown_entry", "ids": unknown}},
        )
    # Filter the report down to just the selected entries — cleanup walks candidates from there.
    selected = set(body.entry_ids)
    report.entries = [e for e in report.entries if e.id in selected]

    registry_obj = request.app.state.runner_registry

    async def run_line(line: str) -> ShellResult:
        # Dummy default; the runner uses run_line_with_chunks below.
        return await run_line_streaming(line, on_chunk=_noop_chunk)

    try:
        runner = registry_obj.create(
            lambda: CleanupRunner(
                report=report,
                opts=CleanupOpts(
                    execute=True,
                    yes_safe=body.yes_safe,
                    allow_dangerous=body.allow_dangerous,
                ),
                run_line=run_line,
            )
        )
    except RuntimeError:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "job_in_progress",
                    "message": "a cleanup is already active",
                }
            },
        )

    async def run_line_with_chunks(line: str, on_chunk: OnChunk) -> ShellResult:
        return await run_line_streaming(line, on_chunk=on_chunk)

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
        while True:
            ev = await runner.events.get()
            yield {"event": ev["event"], "data": json.dumps(ev["data"])}
            if ev["event"] in ("done", "error"):
                return

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
