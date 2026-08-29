from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from diskdoctor import cleanup as cleanup_mod
from diskdoctor import history_log
from diskdoctor.storage.base import StorageBackend
from diskdoctor.types import (
    AsyncRunLine,
    Choice,
    CleanResult,
    CleanupOpts,
    Entry,
    Report,
    ShellResult,
)
from diskdoctor.web.subprocess_stream import OnChunk

logger = logging.getLogger(__name__)


@dataclass
class CleanupRunner:
    """Drives the cleanup state machine with web-side callables and emits events.

    Events are dicts of the shape expected by the SSE route:
      {"event": str, "data": dict}

    Iterates ``cleanup.iter_cleanup_events`` directly (rather than going through
    ``cleanup.run_async``) so that ``ExecuteStep.entry`` is available at the
    moment each recipe line runs. This keeps per-entry event attribution correct
    across multi-entry jobs where the selection phase (all prompts) completes
    before any execute phase starts.
    """

    report: Report
    opts: CleanupOpts
    run_line: AsyncRunLine
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    storage: StorageBackend | None = None
    events: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    _pending_prompts: dict[str, asyncio.Future[Choice]] = field(default_factory=dict)
    _pending_confirm: asyncio.Future[bool] | None = None
    _task: asyncio.Task[list[CleanResult]] | None = None
    _cancelled: bool = False

    async def run(self) -> list[CleanResult]:
        results: list[CleanResult] = []
        outcome: str = "ok"
        try:
            gen = cleanup_mod.iter_cleanup_events(self.report, self.opts)
            try:
                event = next(gen)
                while True:
                    if isinstance(event, cleanup_mod.PromptRequired):
                        choice = await self._prompt_choice(event.entry)
                        event = gen.send(choice)
                    elif isinstance(event, cleanup_mod.ConfirmRequired):
                        summary = (
                            f"Execute cleanup for {len(event.approved)} entries, "
                            f"freeing ~{event.total_bytes} bytes?"
                        )
                        confirmed = await self._confirm(summary)
                        event = gen.send(confirmed)
                    elif isinstance(event, cleanup_mod.ExecuteStep):
                        result = await self._run_execute_step(event.entry, event.line)
                        event = gen.send(result)
                    elif isinstance(event, cleanup_mod.EntryResolved):
                        results.append(event.result)
                        event = next(gen)
            except StopIteration:
                pass
            await self._emit_results(results)
        except asyncio.CancelledError:
            outcome = "cancelled"
            await self.events.put(
                {
                    "event": "done",
                    "data": {
                        "results": [
                            {
                                "entry_id": r.entry_id,
                                "status": r.status,
                                "freed_bytes": r.freed_bytes,
                                "message": r.message,
                            }
                            for r in results
                        ],
                        "cancelled": True,
                    },
                }
            )
            self._write_audit(results, outcome)
            raise
        except Exception as exc:  # surface anything as an SSE job_error event
            # Named 'job_error' (not 'error') to avoid colliding with the
            # browser EventSource's built-in 'error' event for connection issues.
            outcome = "error"
            await self.events.put(
                {
                    "event": "job_error",
                    "data": {"code": "internal", "message": str(exc)},
                }
            )
            self._write_audit(results, outcome, error=str(exc))
            return results
        self._write_audit(results, outcome)
        return results

    def _write_audit(
        self,
        results: list[CleanResult],
        outcome: str,
        *,
        error: str | None = None,
    ) -> None:
        """Persist the job outcome to the audit log. Errors here are non-fatal."""
        try:
            payload: dict[str, Any] = {
                "type": "cleanup",
                "job_id": self.id,
                "outcome": outcome,
                "total_freed_bytes": sum(r.freed_bytes for r in results),
                "results": [
                    {
                        "entry_id": r.entry_id,
                        "status": r.status,
                        "freed_bytes": r.freed_bytes,
                        "message": r.message,
                    }
                    for r in results
                ],
            }
            if error is not None:
                payload["error"] = error
            if self.storage is not None:
                self.storage.append_audit_event(payload)
            else:
                history_log.append_event(payload)
        except Exception:
            # Never let audit logging break the job outcome — but a silently
            # dropped AUDIT record is exactly the kind of failure that must not
            # vanish, so log it (with traceback) before swallowing.
            logger.warning(
                "cleanup audit write failed for job %s (outcome=%s); event not persisted",
                self.id,
                outcome,
                exc_info=True,
            )

    async def _run_execute_step(self, entry: Entry, line: str) -> ShellResult:
        """Emit execute_start, stream progress, return the final ShellResult."""
        await self.events.put(
            {
                "event": "execute_start",
                "data": {"entry_id": entry.id, "cmd": line},
            }
        )

        async def on_chunk(stream: str, text: str) -> None:
            await self.events.put(
                {
                    "event": "execute_progress",
                    "data": {"entry_id": entry.id, "stream": stream, "chunk": text},
                }
            )

        return await self.run_line_with_chunks(line, on_chunk)

    async def run_line_with_chunks(self, line: str, on_chunk: OnChunk) -> ShellResult:
        """Default impl: ignore chunks and call run_line.

        The web route (Task 10) replaces this method post-construction with one
        that wires on_chunk through ``subprocess_stream.run_line_streaming``.
        """
        return await self.run_line(line)

    async def _prompt_choice(self, entry: Entry) -> Choice:
        fut: asyncio.Future[Choice] = asyncio.get_running_loop().create_future()
        self._pending_prompts[entry.id] = fut
        await self.events.put(
            {
                "event": "prompt",
                "data": {
                    "entry_id": entry.id,
                    "label": entry.label,
                    "risk": entry.risk.value,
                    "size_bytes": entry.size_bytes,
                    "recipe": list(entry.recipe),
                },
            }
        )
        return await fut

    async def _confirm(self, message: str) -> bool:
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending_confirm = fut
        await self.events.put(
            {
                "event": "awaiting_confirm",
                "data": {"summary": message},
            }
        )
        return await fut

    async def _emit_results(self, results: list[CleanResult]) -> None:
        for r in results:
            await self.events.put(
                {
                    "event": "execute_result",
                    "data": {
                        "entry_id": r.entry_id,
                        "status": r.status,
                        "freed_bytes": r.freed_bytes,
                        "message": r.message,
                    },
                }
            )
        await self.events.put(
            {
                "event": "done",
                "data": {
                    "results": [
                        {
                            "entry_id": r.entry_id,
                            "status": r.status,
                            "freed_bytes": r.freed_bytes,
                            "message": r.message,
                        }
                        for r in results
                    ],
                },
            }
        )

    async def answer_prompt(self, entry_id: str, choice: Choice) -> None:
        fut = self._pending_prompts.get(entry_id)
        if fut and not fut.done():
            fut.set_result(choice)

    async def answer_confirm(self, confirmed: bool) -> None:
        if self._pending_confirm and not self._pending_confirm.done():
            self._pending_confirm.set_result(confirmed)

    async def cancel(self) -> None:
        self._cancelled = True
        if self._task is not None:
            self._task.cancel()
        # Unblock any pending awaits with safe defaults so run() can unwind.
        for fut in self._pending_prompts.values():
            if not fut.done():
                fut.set_result("q")
        if self._pending_confirm and not self._pending_confirm.done():
            self._pending_confirm.set_result(False)
