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
        env: Mapping[str, str | None] | None = None,
    ) -> ShellResult: ...
    def which(self, binary: str) -> str | None: ...


class RealShell:
    def run(
        self,
        argv: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
        env: Mapping[str, str | None] | None = None,
    ) -> ShellResult:
        # `env` changes the inherited environment rather than replacing it, so a caller
        # setting one variable never loses PATH or HOME. A None value removes a variable.
        child_env: dict[str, str] | None = None
        if env is not None:
            child_env = dict(os.environ)
            for name, value in env.items():
                if value is None:
                    child_env.pop(name, None)
                else:
                    child_env[name] = value
        proc = subprocess.run(
            argv,
            capture_output=True,
            check=check,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            env=child_env,
        )
        return ShellResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def which(self, binary: str) -> str | None:
        return shutil.which(binary)
