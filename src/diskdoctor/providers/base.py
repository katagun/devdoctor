from __future__ import annotations

import glob
import os
import shlex
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path as _Path
from typing import Any, ClassVar

from diskdoctor.ports import Shell
from diskdoctor.sizer import size_path, stat_fields
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


_ALLOWED_PLATFORMS = frozenset({"darwin", "linux"})


def _stat_kwargs(path: _Path) -> dict[str, object]:
    """Return the stat-field kwargs for Entry(...) construction.

    Empty dict when stat fails, so callers can use
    `Entry(..., **_stat_kwargs(p))` unconditionally and let Entry's
    defaults (None) fill in for missing / permission-denied paths.
    """
    fields = stat_fields(path)
    if fields is None:
        return {}
    return {
        "uid": fields.uid,
        "gid": fields.gid,
        "mode": fields.mode,
        "owner": fields.owner,
        "group": fields.group,
        "perms": fields.perms,
    }


@dataclass
class PathProvider(Provider):
    """A provider backed by a YAML entry. One instance per YAML record.

    Emits one Entry per resolved path. Labels use the absolute path so globbed
    entries remain distinguishable. Recipes are templated with shlex.quote on
    the resolved path to prevent shell injection from filename content.
    """

    # Instance-level attrs (Provider expects these as ClassVar on subclasses; we
    # override them per instance for YAML-driven providers).
    name: str = ""  # type: ignore[misc]
    description: str = ""  # type: ignore[misc]
    platforms: tuple[str, ...] = ()  # type: ignore[misc]
    risk: Risk = Risk.SAFE  # type: ignore[misc]
    required_binary: str | None = None  # type: ignore[misc]

    raw_paths: tuple[str, ...] = field(default_factory=tuple)
    recipe_template: list[str] = field(default_factory=list)

    def __init__(
        self,
        shell: Shell,
        *,
        name: str,
        description: str,
        platforms: tuple[str, ...],
        risk: Risk,
        raw_paths: tuple[str, ...],
        recipe_template: list[str],
    ) -> None:
        super().__init__(shell)
        self.name = name
        self.description = description
        self.platforms = platforms
        self.risk = risk
        self.required_binary = None
        self.raw_paths = raw_paths
        self.recipe_template = recipe_template

    @classmethod
    def from_yaml(cls, spec: dict[str, Any], shell: Shell) -> PathProvider:
        try:
            name = str(spec["name"])
            description = str(spec.get("description", ""))
            risk_raw = str(spec["risk"])
            platforms_raw = tuple(spec["platforms"])
            paths_raw = tuple(str(p) for p in spec["paths"])
            recipe_raw = spec["recipe"]
        except KeyError as e:
            raise ValueError(f"paths.yaml entry missing required key: {e}") from e

        try:
            risk = Risk(risk_raw)
        except ValueError as e:
            raise ValueError(f"paths.yaml entry {name!r}: unknown risk {risk_raw!r}") from e

        bad = set(platforms_raw) - _ALLOWED_PLATFORMS
        if bad:
            raise ValueError(
                f"paths.yaml entry {name!r}: unknown platform(s) {sorted(bad)}; "
                f"allowed: {sorted(_ALLOWED_PLATFORMS)}"
            )

        if isinstance(recipe_raw, str):
            recipe_template = [recipe_raw]
        elif isinstance(recipe_raw, list):
            recipe_template = [str(line) for line in recipe_raw]
        else:
            raise ValueError(
                f"paths.yaml entry {name!r}: recipe must be a string or list of strings"
            )

        return cls(
            shell,
            name=name,
            description=description,
            platforms=platforms_raw,
            risk=risk,
            raw_paths=paths_raw,
            recipe_template=recipe_template,
        )

    def available(self) -> bool:
        # Platform only; PathProviders never declare required binaries.
        return _normalize_platform(sys.platform) in self.platforms

    def discover(self) -> list[Entry]:
        entries: list[Entry] = []
        for raw in self.raw_paths:
            expanded = os.path.expanduser(os.path.expandvars(raw))
            matches = glob.glob(expanded) if any(c in expanded for c in "*?[") else [expanded]
            for m in matches:
                p = _Path(m)
                if not p.exists():
                    continue
                size, _skipped = size_path(p)
                quoted = shlex.quote(str(p))
                recipe = [line.format(path=quoted) for line in self.recipe_template]
                try:
                    mtime: float | None = p.lstat().st_mtime
                except OSError:
                    mtime = None
                entries.append(
                    Entry(
                        provider=self.name,
                        id=str(p),
                        path=p,
                        label=str(p),
                        size_bytes=size,
                        mtime=mtime,
                        risk=self.risk,
                        recipe=recipe,
                        **_stat_kwargs(p),
                    )
                )
        return entries
