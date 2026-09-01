from __future__ import annotations

import socket
import sys
from collections.abc import Iterable
from datetime import UTC, datetime

from devdoctor.memory.collectors.processes import collect_process_memory
from devdoctor.memory.collectors.system import collect_system_memory
from devdoctor.memory.types import MemoryReport
from devdoctor.ports import Shell


def scan_memory(
    shell: Shell,
    now: datetime | None = None,
    *,
    provider_ids: Iterable[str] | None = None,
) -> MemoryReport:
    scanned_at = now or datetime.now(UTC)
    return MemoryReport(
        scanned_at=scanned_at,
        hostname=socket.gethostname(),
        platform=_platform(),
        system=collect_system_memory(shell),
        consumers=collect_process_memory(shell, provider_ids=provider_ids),
    )


def _platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    return sys.platform
