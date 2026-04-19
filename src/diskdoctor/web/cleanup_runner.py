from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from diskdoctor.cleanup import run_async
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


@dataclass
class CleanupRunner:
    """Drives cleanup.run_async with web-side callables and emits events.

    Events are dicts of the shape expected by the SSE route:
      {"event": str, "data": dict}

    Mutable state note: ``_current_entry`` is set inside ``_prompt_choice`` and
    read inside the ``run_line_emitting`` closure. This is safe because
    ``cleanup.iter_cleanup_events`` processes candidates sequentially — the
    state machine prompts for an entry, then (after the final confirm) runs
    its recipe lines, and only advances to the next entry once the previous
    one resolves. There is exactly one "current" entry in flight at any
    moment. Concurrent event-driven tests do not invalidate this because the
    events queue is consumed externally but the generator is still advanced
    by the single ``run()`` coroutine.
    """

    report: Report
    opts: CleanupOpts
    run_line: AsyncRunLine
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    events: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    _pending_prompts: dict[str, asyncio.Future[Choice]] = field(default_factory=dict)
    _pending_confirm: asyncio.Future[bool] | None = None
    _task: asyncio.Task[list[CleanResult]] | None = None
    _cancelled: bool = False
    _current_entry: Entry | None = None

    async def run(self) -> list[CleanResult]:
        results: list[CleanResult] = []
        try:
            # Wrap run_line so we emit execute_start/execute_progress/execute_result.
            async def run_line_emitting(line: str) -> ShellResult:
                # Identify which entry — stashed in _current_entry by _prompt_choice.
                entry = self._current_entry
                assert entry is not None, "run_line_emitting called outside an entry prompt cycle"
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

            results = await run_async(
                self.report,
                run_line=run_line_emitting,
                prompt_choice=self._prompt_choice,
                confirm=self._confirm,
                opts=self.opts,
            )
            await self._emit_results(results)
        except asyncio.CancelledError:
            await self.events.put(
                {
                    "event": "done",
                    "data": {"results": [], "cancelled": True},
                }
            )
            raise
        except Exception as exc:  # surface anything as an SSE error event
            await self.events.put(
                {
                    "event": "error",
                    "data": {"code": "internal", "message": str(exc)},
                }
            )
            return []
        return results

    async def run_line_with_chunks(self, line: str, on_chunk: OnChunk) -> ShellResult:
        """Default impl: ignore chunks and call run_line.

        The web route (Task 10) replaces this method post-construction with one
        that wires on_chunk through ``subprocess_stream.run_line_streaming``.
        """
        return await self.run_line(line)

    async def _prompt_choice(self, entry: Entry) -> Choice:
        self._current_entry = entry
        fut: asyncio.Future[Choice] = asyncio.get_event_loop().create_future()
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
        fut: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
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
