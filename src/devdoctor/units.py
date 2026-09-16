"""Byte formatting shared by the core and every presentation layer."""

from __future__ import annotations

_BYTES_UNIT_STEP = 1024


def human_bytes(n: int) -> str:
    sign = "-" if n < 0 else ""
    value: float = float(abs(n))
    for unit in ("B", "K", "M", "G", "T", "P"):
        if value < _BYTES_UNIT_STEP or unit == "P":
            return f"{sign}{value:.0f}{unit}" if unit == "B" else f"{sign}{value:.1f}{unit}"
        value /= _BYTES_UNIT_STEP
    return f"{sign}{value:.1f}P"


def human_bytes_or_unknown(n: int | None) -> str:
    return "unknown" if n is None else human_bytes(n)


def estimated_bytes(n: int | None) -> str:
    return "unknown" if n is None else f"~{human_bytes(n)}"
