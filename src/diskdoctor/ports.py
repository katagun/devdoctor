from __future__ import annotations

import shutil
import subprocess
from typing import Protocol

from diskdoctor.types import ShellResult


class Shell(Protocol):
    def run(self, argv: list[str], *, check: bool = False) -> ShellResult: ...
    def which(self, binary: str) -> str | None: ...


class RealShell:
    def run(self, argv: list[str], *, check: bool = False) -> ShellResult:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=check,
        )
        return ShellResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def which(self, binary: str) -> str | None:
        return shutil.which(binary)
