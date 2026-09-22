"""Sparse files: what an entry occupies versus what it reserves (#86).

A VM disk image such as Docker Desktop's ``Docker.raw`` is a sparse file. It has a
length, the most the guest may ever write, and an allocation, the blocks written
so far. DevDoctor counts the allocation, because that is what the disk gives up.
The length still matters to the reader for two reasons: other tools show it, and
space freed *inside* the image comes back to the host only when the image is
compacted, which is not what deleting files elsewhere on the disk does.

The gap between the two is address space that was never on the disk. It is not
reclaimable, and nothing here says it is.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from devdoctor.types import Entry

# Below either bound the gap is ordinary: block rounding, a few compressed files.
_MIN_GAP_BYTES = 1024**3
_MIN_GAP_SHARE = 0.10


@dataclass(frozen=True)
class SparseFinding:
    entry: Entry
    allocated_bytes: int
    apparent_bytes: int

    @property
    def unused_bytes(self) -> int:
        """Address space the file reserves and has never written."""
        return self.apparent_bytes - self.allocated_bytes


def sparse_findings(entries: Iterable[Entry]) -> list[SparseFinding]:
    """Entries that reserve far more than they occupy, largest gap first."""
    findings: list[SparseFinding] = []
    for entry in entries:
        allocated, apparent = entry.footprint_bytes, entry.apparent_bytes
        if allocated is None or apparent is None:
            continue
        gap = apparent - allocated
        if gap >= _MIN_GAP_BYTES and gap >= apparent * _MIN_GAP_SHARE:
            findings.append(SparseFinding(entry, allocated, apparent))
    findings.sort(key=lambda finding: finding.unused_bytes, reverse=True)
    return findings
