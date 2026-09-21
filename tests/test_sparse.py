from pathlib import Path

import pytest

from devdoctor.sparse import sparse_findings
from devdoctor.types import DiskUsage, Entry, Risk

GIB = 1024**3


def _entry(label: str, allocated: int | None, apparent: int | None) -> Entry:
    return Entry(
        provider="docker-vm-disk",
        id=label,
        path=Path(f"/{label}"),
        label=label,
        size_bytes=allocated or 0,
        mtime=None,
        risk=Risk.RECLAIMABLE,
        recipe=[],
        usage=DiskUsage(allocated, allocated, apparent_bytes=apparent),
    )


def test_a_sparse_image_is_reported_with_both_sizes():
    image = _entry("Docker.raw", 34 * GIB, 80 * GIB)
    (finding,) = sparse_findings([image])
    assert (finding.entry, finding.allocated_bytes, finding.apparent_bytes) == (
        image,
        34 * GIB,
        80 * GIB,
    )
    assert finding.unused_bytes == 46 * GIB


@pytest.mark.parametrize(
    ("allocated", "apparent"),
    [
        pytest.param(5 * GIB, None, id="apparent-size-not-measured"),
        pytest.param(None, 80 * GIB, id="footprint-unknown"),
        pytest.param(5 * GIB, 5 * GIB + 1000, id="ordinary-directory"),
        pytest.param(5 * GIB, 5 * GIB + GIB // 2, id="gap-under-a-gibibyte"),
        pytest.param(100 * GIB, 102 * GIB, id="gap-under-a-tenth-of-the-whole"),
    ],
)
def test_ordinary_entries_are_not_findings(allocated, apparent):
    assert sparse_findings([_entry("x", allocated, apparent)]) == []


def test_findings_come_largest_gap_first():
    small = _entry("small", 1 * GIB, 4 * GIB)
    large = _entry("large", 10 * GIB, 90 * GIB)
    assert [f.entry.label for f in sparse_findings([small, large])] == ["large", "small"]
