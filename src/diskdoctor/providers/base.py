from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from typing import ClassVar

from diskdoctor.ports import Shell
from diskdoctor.types import Entry, Risk


class Provider(ABC):
    """Base class for all providers. A Provider's single job is to discover
    entries. Execution is handled uniformly by cleanup.run against
    entry.recipe — providers do not execute their own recipes.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    platforms: ClassVar[tuple[str, ...]]
    risk: ClassVar[Risk]
    required_binary: ClassVar[str | None] = None

    def __init__(self, shell: Shell) -> None:
        self._shell = shell

    def available(self) -> bool:
        current = _normalize_platform(sys.platform)
        if current not in self.platforms:
            return False
        if self.required_binary is None:
            return True
        return self._shell.which(self.required_binary) is not None

    @abstractmethod
    def discover(self) -> list[Entry]: ...


def _normalize_platform(raw: str) -> str:
    if raw.startswith("linux"):
        return "linux"
    if raw == "darwin":
        return "darwin"
    return raw
