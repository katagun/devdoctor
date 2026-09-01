from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from devdoctor.types import ShellResult


@pytest.fixture(autouse=True)
def _isolate_xdg_data_home(tmp_path: Path, monkeypatch):
    """Pin XDG_DATA_HOME to a fresh tmp dir for every test so snapshot and
    audit writes (e.g. CleanupRunner's audit log) never touch the real
    ~/.local/share/devdoctor."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


@dataclass
class FakeShell:
    """Argv-keyed fake. Matches full argv tuple exactly.

    Unconfigured calls raise so tests surface unexpected commands.
    """

    responses: dict[tuple[str, ...], ShellResult] = field(default_factory=dict)
    which_table: dict[str, str | None] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)
    # Discovery runs providers concurrently (devdoctor.discovery.scan), and a
    # single shell instance can be shared across those providers, so record
    # calls under a lock to keep `calls` consistent under concurrent run().
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def run(
        self,
        argv: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
    ) -> ShellResult:
        # `check` and `timeout` are accepted for Protocol conformance but
        # not enforced by the fake — tests configure their responses explicitly.
        del check, timeout
        key = tuple(argv)
        with self._lock:
            self.calls.append(key)
        if key not in self.responses:
            raise AssertionError(f"FakeShell: unexpected call: {argv}")
        return self.responses[key]

    def which(self, binary: str) -> str | None:
        return self.which_table.get(binary)
