from __future__ import annotations

import shutil
import subprocess
from typing import Protocol

from diskdoctor.types import ShellResult


class Shell(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
    ) -> ShellResult: ...
    def which(self, binary: str) -> str | None: ...


class RealShell:
    def run(
        self,
        argv: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
    ) -> ShellResult:
        proc = subprocess.run(
            argv,
            capture_output=True,
            check=check,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
        )
        return ShellResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def which(self, binary: str) -> str | None:
        return shutil.which(binary)
