from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from diskdoctor.memory.types import MemoryActionKind
from diskdoctor.ports import Shell

MemoryActionStatus = Literal["ok", "error", "unsupported"]

# Ignore very short fragments when matching process names — they're too
# ambiguous to confirm two names refer to the same program.
_MIN_NAME_TOKEN_LEN = 3


@dataclass(frozen=True)
class MemoryActionResult:
    action_id: str
    status: MemoryActionStatus
    message: str


def execute_memory_action(
    shell: Shell,
    *,
    action_id: str,
    kind: MemoryActionKind,
    target_id: str,
    confirmed: bool,
    expected_name: str | None = None,
) -> MemoryActionResult:
    if not confirmed:
        return MemoryActionResult(
            action_id=action_id,
            status="error",
            message="confirmation required",
        )
    if action_id == "stop-docker" and target_id == "docker":
        return _stop_docker(shell, action_id=action_id)
    if action_id == "stop-llm-runtime" and target_id == "llm":
        return _stop_llm_runtime(shell, action_id=action_id)
    if kind in {"quit_app", "terminate_process"} and target_id.startswith("pid:"):
        return _terminate_pid(
            shell, action_id=action_id, target_id=target_id, expected_name=expected_name
        )
    return MemoryActionResult(
        action_id=action_id,
        status="unsupported",
        message="this memory action is not executable yet",
    )


def _stop_docker(shell: Shell, *, action_id: str) -> MemoryActionResult:
    if sys.platform == "darwin" and shell.which("osascript"):
        result = shell.run(
            ["osascript", "-e", 'tell application "Docker" to quit'],
            check=False,
            timeout=10,
        )
        return _shell_result(action_id, result.returncode, "requested Docker Desktop quit")
    docker = shell.which("docker")
    if docker:
        ps = shell.run([docker, "ps", "-q"], check=False, timeout=10)
        if ps.returncode != 0:
            return _shell_result(action_id, ps.returncode, "failed to list Docker containers")
        container_ids = [line.strip() for line in ps.stdout.splitlines() if line.strip()]
        if not container_ids:
            return MemoryActionResult(
                action_id=action_id,
                status="ok",
                message="Docker is available, but no running containers were found",
            )
        stopped = shell.run([docker, "stop", *container_ids], check=False, timeout=30)
        return _shell_result(action_id, stopped.returncode, "requested Docker containers stop")
    return MemoryActionResult(
        action_id=action_id,
        status="unsupported",
        message="Docker action needs osascript on macOS or a docker CLI",
    )


def _stop_llm_runtime(shell: Shell, *, action_id: str) -> MemoryActionResult:
    if sys.platform == "darwin" and shell.which("osascript"):
        results = [
            shell.run(
                ["osascript", "-e", 'tell application "Ollama" to quit'],
                check=False,
                timeout=10,
            ),
            shell.run(
                ["osascript", "-e", 'tell application "LM Studio" to quit'],
                check=False,
                timeout=10,
            ),
        ]
        if any(result.returncode == 0 for result in results):
            return MemoryActionResult(
                action_id=action_id,
                status="ok",
                message="requested local LLM app quit",
            )
    return MemoryActionResult(
        action_id=action_id,
        status="unsupported",
        message="local LLM action currently supports macOS app quit via osascript",
    )


def _terminate_pid(
    shell: Shell,
    *,
    action_id: str,
    target_id: str,
    expected_name: str | None = None,
) -> MemoryActionResult:
    raw_pid = target_id.removeprefix("pid:")
    try:
        pid = int(raw_pid)
    except ValueError:
        return MemoryActionResult(
            action_id=action_id,
            status="error",
            message=f"invalid process target {target_id!r}",
        )
    if pid <= 1:
        return MemoryActionResult(
            action_id=action_id,
            status="error",
            message="refusing to terminate a system process",
        )
    # PID-reuse guard: the pid came from a scan the UI may have held for a
    # while. Between scan and click the OS can recycle it onto an unrelated
    # process, so re-read the current command and refuse if it no longer
    # matches what the user was shown. Skipped only when the caller gave no
    # name to check against (e.g. an older client).
    if expected_name:
        current = _current_process_name(shell, pid)
        if current is None:
            return MemoryActionResult(
                action_id=action_id,
                status="error",
                message=f"pid {pid} is no longer running — re-scan before terminating",
            )
        if not _names_match(expected_name, current):
            return MemoryActionResult(
                action_id=action_id,
                status="error",
                message=(
                    f"pid {pid} now belongs to {current!r}, not {expected_name!r} — "
                    "re-scan before terminating"
                ),
            )
    result = shell.run(["kill", "-TERM", str(pid)], check=False, timeout=10)
    return _shell_result(action_id, result.returncode, f"sent TERM to pid {pid}")


def _current_process_name(shell: Shell, pid: int) -> str | None:
    """Return the command name currently backing `pid`, or None if it's gone."""
    result = shell.run(["ps", "-p", str(pid), "-o", "comm="], check=False, timeout=10)
    if result.returncode != 0:
        return None
    name = result.stdout.strip()
    return name or None


def _process_tokens(value: str) -> set[str]:
    """Alphanumeric tokens (>= 3 chars) of a process name's basename, lowercased."""
    base = Path(value.strip()).name.lower()
    return {tok for tok in re.split(r"[^a-z0-9]+", base) if len(tok) >= _MIN_NAME_TOKEN_LEN}


def _names_match(expected: str, current: str) -> bool:
    """True if two process names plausibly refer to the same program.

    Deliberately lenient — display names are transformed/truncated relative to
    `ps -o comm=` — so it matches when they share any meaningful token (e.g.
    "Chrome Helper" vs "Google Chrome Helper"). A recycled pid backing an
    unrelated program ("bash") shares no token and is rejected.
    """
    return bool(_process_tokens(expected) & _process_tokens(current))


def _shell_result(action_id: str, returncode: int, ok_message: str) -> MemoryActionResult:
    if returncode == 0:
        return MemoryActionResult(action_id=action_id, status="ok", message=ok_message)
    return MemoryActionResult(
        action_id=action_id,
        status="error",
        message=f"command exited with status {returncode}",
    )
