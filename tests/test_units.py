import pytest

from devdoctor.units import (
    estimated_bytes,
    human_bytes,
    human_bytes_or_unknown,
    parse_duration,
)


def test_human_bytes_uses_1024_units_with_one_decimal() -> None:
    assert human_bytes(0) == "0B"
    assert human_bytes(512) == "512B"
    assert human_bytes(1536) == "1.5K"
    assert human_bytes(5_600_000_000) == "5.2G"
    assert human_bytes(-2048) == "-2.0K"


def test_unknown_and_estimate_variants() -> None:
    assert human_bytes_or_unknown(None) == "unknown"
    assert human_bytes_or_unknown(2048) == "2.0K"
    assert estimated_bytes(None) == "unknown"
    assert estimated_bytes(2048) == "~2.0K"


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("12h", 12 * 3600),
        ("90d", 90 * 86400),
        ("2w", 14 * 86400),
        ("6mo", 180 * 86400),
        ("1y", 365 * 86400),
        (" 30D ", 30 * 86400),
    ],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "90", "d", "-3d", "1.5d", "3m", "3 months", "0d"])
def test_parse_duration_rejects_what_it_cannot_read(text):
    """``m`` is refused outright: minutes and months are both plausible readings."""
    with pytest.raises(ValueError, match=r"use e\.g\. 12h, 90d, 2w, 6mo, 1y"):
        parse_duration(text)
