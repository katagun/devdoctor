from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Literal

from diskdoctor.memory.types import MemoryActionKind
from diskdoctor.ports import Shell

MemoryActionStatus = Literal["ok", "error", "unsupported"]


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
        return _terminate_pid(shell, action_id=action_id, target_id=target_id)
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


def _terminate_pid(shell: Shell, *, action_id: str, target_id: str) -> MemoryActionResult:
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
    result = shell.run(["kill", "-TERM", str(pid)], check=False, timeout=10)
    return _shell_result(action_id, result.returncode, f"sent TERM to pid {pid}")


def _shell_result(action_id: str, returncode: int, ok_message: str) -> MemoryActionResult:
    if returncode == 0:
        return MemoryActionResult(action_id=action_id, status="ok", message=ok_message)
    return MemoryActionResult(
        action_id=action_id,
        status="error",
        message=f"command exited with status {returncode}",
    )
