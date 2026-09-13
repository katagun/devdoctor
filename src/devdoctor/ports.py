from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from typing import Protocol

from devdoctor.types import ShellResult


class Shell(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ShellResult: ...
    def which(self, binary: str) -> str | None: ...


class RealShell:
    def run(
        self,
        argv: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ShellResult:
        proc = subprocess.run(
            argv,
            capture_output=True,
            check=check,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            # `env` adds to the inherited environment instead of replacing it, so a
            # caller setting one variable never loses PATH or HOME.
            env=None if env is None else {**os.environ, **env},
        )
        return ShellResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def which(self, binary: str) -> str | None:
        return shutil.which(binary)
