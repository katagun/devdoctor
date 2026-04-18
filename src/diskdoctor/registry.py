from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

import yaml

from diskdoctor.ports import Shell
from diskdoctor.providers.base import PathProvider, Provider
from diskdoctor.providers.ollama import OllamaProvider


class DuplicateProviderError(ValueError):
    """Two providers share a name."""


# Class providers — populated when Task 16+ add them. Keep the import list
# here and registry code will auto-include any class in _CLASS_PROVIDERS.
_CLASS_PROVIDERS: list[type[Provider]] = [OllamaProvider]


def load_providers(shell: Shell) -> list[Provider]:
    """Load and sort all providers. Fails on duplicate names."""
    providers: list[Provider] = [cls(shell) for cls in _CLASS_PROVIDERS]

    yaml_path = _locate_paths_yaml()
    yaml_text = yaml_path.read_text()
    yaml_docs = yaml.safe_load(yaml_text) or []
    if not isinstance(yaml_docs, list):
        raise ValueError(f"{yaml_path}: expected a top-level list of provider specs")

    for spec in yaml_docs:
        if not isinstance(spec, dict):
            raise ValueError(f"{yaml_path}: every entry must be a mapping; got {type(spec).__name__}")
        providers.append(PathProvider.from_yaml(spec, shell))

    _check_unique_names(providers)
    providers.sort(key=lambda p: p.name)
    return providers


def _locate_paths_yaml() -> Path:
    override = os.environ.get("DISKDOCTOR_PATHS_YAML")
    if override:
        return Path(override)
    # Package-bundled default.
    with resources.as_file(resources.files("diskdoctor.data") / "paths.yaml") as p:
        return Path(p)


def _check_unique_names(providers: list[Provider]) -> None:
    seen: dict[str, Provider] = {}
    dupes: dict[str, list[str]] = {}
    for p in providers:
        if p.name in seen:
            dupes.setdefault(p.name, [type(seen[p.name]).__name__]).append(type(p).__name__)
        else:
            seen[p.name] = p
    if dupes:
        msg = "; ".join(f"{name}: {sources}" for name, sources in dupes.items())
        raise DuplicateProviderError(f"duplicate provider name(s): {msg}")
