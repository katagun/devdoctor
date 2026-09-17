from devdoctor.units import estimated_bytes, human_bytes, human_bytes_or_unknown


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
