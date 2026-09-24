"""Colima (Lima) VM disks and the Colima image cache (#85)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from devdoctor.registry import load_providers
from devdoctor.sparse import sparse_findings
from devdoctor.types import AdviceAction, DeletePathAction, Risk
from tests.conftest import FakeShell

GIB = 1024**3
MIB = 1024**2


def _provider(name: str):
    return next(p for p in load_providers(FakeShell()) if p.name == name)


def _sparse(path: Path, *, length: int, written: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(b"x" * written)
        fh.truncate(length)


def test_colima_providers_are_in_the_containers_family() -> None:
    disk, cache = _provider("colima-vm-disk"), _provider("colima-cache")
    assert (disk.family, disk.risk) == ("containers", Risk.RECLAIMABLE)
    assert (cache.family, cache.risk) == ("containers", Risk.SAFE)


@pytest.mark.skipif(os.name != "posix", reason="sparse files")
def test_lima_disks_are_advice_only_and_report_what_they_reserve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    lima = home / ".colima" / "_lima"
    # The data disk is a raw image: 100 GiB long on a real machine, a few GiB written.
    _sparse(lima / "_disks" / "colima" / "datadisk", length=4 * GIB, written=2 * MIB)
    _sparse(lima / "colima" / "diffdisk", length=512 * MIB, written=MIB)
    (lima / "_config").mkdir()
    (lima / "_config" / "user").write_bytes(b"k")

    entries = sorted(_provider("colima-vm-disk").discover(), key=lambda e: str(e.path))

    assert [e.path for e in entries] == [lima / "_disks" / "colima", lima / "colima" / "diffdisk"]
    for entry in entries:
        # Deleting a Lima disk destroys the VM's containers and volumes: guidance, never rm.
        assert entry.risk is Risk.RECLAIMABLE
        assert all(isinstance(action, AdviceAction) for action in entry.actions)
        assert entry.reclaimable_bytes is None
        assert "colima delete" in " ".join(a.message for a in entry.actions)
    datadisk = entries[0]
    assert datadisk.footprint_bytes is not None and datadisk.footprint_bytes < 64 * MIB
    assert datadisk.apparent_bytes == 4 * GIB
    (finding,) = sparse_findings(entries)
    assert finding.entry is datadisk


def test_colima_cache_is_a_plain_deletion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    cache = home / "Library" / "Caches" / "colima"
    cache.mkdir(parents=True)
    (cache / "ubuntu.img").write_bytes(b"x" * 4096)

    entries = _provider("colima-cache").discover()

    assert [e.path for e in entries] == [cache]
    assert entries[0].actions == (DeletePathAction(cache),)
    assert entries[0].reclaimable_bytes == entries[0].footprint_bytes
