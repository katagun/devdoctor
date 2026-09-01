from __future__ import annotations

import re
import sys
from pathlib import Path

from devdoctor.memory.types import MemoryPressure, SystemMemory
from devdoctor.ports import Shell

_VM_STAT_RE = re.compile(r"^(.+?):\s+([\d.]+)\.?$")
_PAGE_SIZE_RE = re.compile(r"page size of (\d+) bytes")
_SWAP_USED_RE = re.compile(r"used\s*=\s*([\d.]+)([KMGTP]?)", re.IGNORECASE)
_UNIT_MULT = {
    "": 1,
    "K": 1024,
    "M": 1024**2,
    "G": 1024**3,
    "T": 1024**4,
    "P": 1024**5,
}
_CRITICAL_FREE_RATIO = 0.08
_WARN_FREE_RATIO = 0.18
_CRITICAL_SWAP_RATIO = 0.25
_WARN_SWAP_RATIO = 0.10


def collect_system_memory(shell: Shell, platform: str | None = None) -> SystemMemory:
    current = platform or sys.platform
    if current == "darwin":
        return _collect_darwin(shell)
    if current.startswith("linux"):
        return _collect_linux()
    return SystemMemory(
        total_bytes=0,
        available_bytes=0,
        used_bytes=0,
        swap_used_bytes=None,
        compressed_bytes=None,
        pressure="unknown",
    )


def _collect_darwin(shell: Shell) -> SystemMemory:
    total = _collect_hw_memsize(shell)
    vm_result = shell.run(["vm_stat"], check=False)
    vm = parse_vm_stat(vm_result.stdout) if vm_result.returncode == 0 else {}
    swap_result = shell.run(["sysctl", "vm.swapusage"], check=False)
    swap_used = parse_swapusage(swap_result.stdout) if swap_result.returncode == 0 else None
    return system_memory_from_vm_stat(total, vm, swap_used)


def _collect_hw_memsize(shell: Shell) -> int:
    result = shell.run(["sysctl", "-n", "hw.memsize"], check=False)
    if result.returncode != 0:
        return 0
    raw = result.stdout.strip()
    try:
        return int(raw)
    except ValueError:
        return 0


def _collect_linux() -> SystemMemory:
    meminfo = parse_proc_meminfo(_read_proc_meminfo())
    total = meminfo.get("MemTotal", 0)
    available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
    swap_used = max(meminfo.get("SwapTotal", 0) - meminfo.get("SwapFree", 0), 0)
    compressed = meminfo.get("Zswap", 0) or None
    return SystemMemory(
        total_bytes=total,
        available_bytes=available,
        used_bytes=max(total - available, 0),
        swap_used_bytes=swap_used,
        compressed_bytes=compressed,
        pressure=classify_pressure(total, available, swap_used),
    )


def _read_proc_meminfo() -> str:
    try:
        return Path("/proc/meminfo").read_text()
    except OSError:
        return ""


def parse_vm_stat(output: str) -> dict[str, int]:
    page_size = 4096
    out: dict[str, int] = {}
    for line in output.splitlines():
        page_match = _PAGE_SIZE_RE.search(line)
        if page_match:
            page_size = int(page_match.group(1))
            continue
        match = _VM_STAT_RE.match(line.strip())
        if not match:
            continue
        key = _normalize_vm_key(match.group(1))
        pages = int(float(match.group(2)))
        out[key] = pages * page_size
    return out


def _normalize_vm_key(raw: str) -> str:
    key = raw.lower().replace("pages ", "").replace("pageouts", "pageouts")
    return re.sub(r"[^a-z0-9]+", "_", key).strip("_")


def parse_swapusage(output: str) -> int | None:
    match = _SWAP_USED_RE.search(output)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).upper()
    return int(value * _UNIT_MULT[unit])


def parse_proc_meminfo(output: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in output.splitlines():
        key, sep, rest = line.partition(":")
        if not sep:
            continue
        parts = rest.strip().split()
        if not parts:
            continue
        try:
            value = int(parts[0])
        except ValueError:
            continue
        unit = parts[1].lower() if len(parts) > 1 else "b"
        mult = 1024 if unit == "kb" else 1
        out[key] = value * mult
    return out


def system_memory_from_vm_stat(
    total_bytes: int,
    vm: dict[str, int],
    swap_used_bytes: int | None,
) -> SystemMemory:
    free = vm.get("free", 0)
    inactive = vm.get("inactive", 0)
    speculative = vm.get("speculative", 0)
    purgeable = vm.get("purgeable", 0)
    available = min(free + inactive + speculative + purgeable, total_bytes) if total_bytes else 0
    compressed = vm.get("occupied_by_compressor") or vm.get("stored_in_compressor")
    used = max(total_bytes - available, 0)
    return SystemMemory(
        total_bytes=total_bytes,
        available_bytes=available,
        used_bytes=used,
        swap_used_bytes=swap_used_bytes,
        compressed_bytes=compressed,
        pressure=classify_pressure(total_bytes, available, swap_used_bytes),
    )


def classify_pressure(
    total_bytes: int,
    available_bytes: int,
    swap_used_bytes: int | None = None,
) -> MemoryPressure:
    if total_bytes <= 0:
        return "unknown"
    free_ratio = available_bytes / total_bytes
    swap_ratio = (swap_used_bytes or 0) / total_bytes
    if free_ratio < _CRITICAL_FREE_RATIO or swap_ratio > _CRITICAL_SWAP_RATIO:
        return "critical"
    if free_ratio < _WARN_FREE_RATIO or swap_ratio > _WARN_SWAP_RATIO:
        return "warn"
    return "ok"
