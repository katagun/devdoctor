from __future__ import annotations

from devdoctor.memory.collectors.system import (
    classify_pressure,
    parse_proc_meminfo,
    parse_swapusage,
    parse_vm_stat,
    system_memory_from_vm_stat,
)


def test_parse_vm_stat_uses_reported_page_size() -> None:
    vm = parse_vm_stat(
        """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               100.
Pages active:                             200.
Pages inactive:                            50.
Pages speculative:                         25.
Pages occupied by compressor:              10.
Pages purgeable:                            5.
"""
    )

    assert vm["free"] == 100 * 16384
    assert vm["inactive"] == 50 * 16384
    assert vm["speculative"] == 25 * 16384
    assert vm["occupied_by_compressor"] == 10 * 16384
    assert vm["purgeable"] == 5 * 16384


def test_parse_swapusage_extracts_used_bytes() -> None:
    used = parse_swapusage(
        "vm.swapusage: total = 2048.00M  used = 512.50M  free = 1535.50M  (encrypted)"
    )

    assert used == int(512.5 * 1024 * 1024)


def test_system_memory_from_vm_stat_derives_available_and_pressure() -> None:
    total = 16 * 1024**3
    vm = {
        "free": 1 * 1024**3,
        "inactive": 1 * 1024**3,
        "speculative": 512 * 1024**2,
        "purgeable": 512 * 1024**2,
        "occupied_by_compressor": 2 * 1024**3,
    }

    system = system_memory_from_vm_stat(total, vm, swap_used_bytes=0)

    assert system.available_bytes == 3 * 1024**3
    assert system.used_bytes == 13 * 1024**3
    assert system.compressed_bytes == 2 * 1024**3
    assert system.pressure == "ok"


def test_classify_pressure_uses_available_and_swap_ratio() -> None:
    total = 16 * 1024**3

    assert classify_pressure(total, 4 * 1024**3, 0) == "ok"
    assert classify_pressure(total, 2 * 1024**3, 0) == "warn"
    assert classify_pressure(total, 512 * 1024**2, 0) == "critical"
    assert classify_pressure(total, 4 * 1024**3, 5 * 1024**3) == "critical"
    assert classify_pressure(0, 0, 0) == "unknown"


def test_parse_proc_meminfo_converts_kib_to_bytes() -> None:
    parsed = parse_proc_meminfo(
        """MemTotal:       16384000 kB
MemAvailable:    4096000 kB
SwapTotal:       1024000 kB
SwapFree:         512000 kB
"""
    )

    assert parsed["MemTotal"] == 16_384_000 * 1024
    assert parsed["MemAvailable"] == 4_096_000 * 1024
    assert parsed["SwapTotal"] == 1_024_000 * 1024
