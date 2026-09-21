"""Byte formatting and duration parsing shared by the core and every presentation layer."""

from __future__ import annotations

import re

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


_DURATION_RE = re.compile(r"^(\d+)(h|d|w|mo|y)$")
_SECONDS_PER = {"h": 3600, "d": 86400, "w": 7 * 86400, "mo": 30 * 86400, "y": 365 * 86400}


def parse_duration(text: str) -> int:
    """Seconds in an age like ``90d``: whole hours, days, weeks, months (30d) or years.

    ``m`` is refused rather than guessed at, since minutes and months both fit.
    """
    match = _DURATION_RE.match(text.strip().lower())
    if match is None or int(match.group(1)) == 0:
        raise ValueError(f"invalid duration {text!r}; use e.g. 12h, 90d, 2w, 6mo, 1y")
    return int(match.group(1)) * _SECONDS_PER[match.group(2)]
