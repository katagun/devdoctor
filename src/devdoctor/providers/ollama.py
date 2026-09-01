from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from devdoctor.providers.base import Provider, _stat_kwargs
from devdoctor.sizer import size_path
from devdoctor.types import Entry, Risk

_SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)", re.IGNORECASE)
_OLLAMA_LIST_MIN_COLS = 3  # name, id, size, ...

# Manifest path shapes for `ollama list` NAMEs:
# 1 part  → bare repo on default registry/library
# 2 parts → org/repo on default registry, or two-part custom registry
# 3+      → fully-qualified registry/org/repo (or deeper)
_MANIFEST_PARTS_BARE = 1
_MANIFEST_PARTS_NAMESPACED = 2
_MANIFEST_PARTS_FULLY_QUALIFIED = 3


class OllamaProvider(Provider):
    name = "ollama"
    description = "Ollama local LLM models"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    required_binary = "ollama"
    details = (
        "Models pulled with `ollama pull` live under ~/.ollama/models. "
        "Each model is a few GB; multi-billion-parameter models can exceed 30 GB. "
        "Cleanup uses `ollama rm <name>` per model when the daemon is reachable, "
        "otherwise falls back to deleting the models directory wholesale."
    )

    def discover(self) -> list[Entry]:
        result = self._shell.run(["ollama", "list"], check=False)
        if result.returncode == 0 and result.stdout.strip():
            return self._parse_list(result.stdout)
        return self._walk_models_dir()

    def _parse_list(self, output: str) -> list[Entry]:
        entries: list[Entry] = []
        lines = [line for line in output.splitlines() if line.strip()]
        for line in lines[1:]:  # skip header
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts) < _OLLAMA_LIST_MIN_COLS:
                continue
            name = parts[0]
            size_str = parts[2]
            size_bytes = _parse_size(size_str)
            # Each model has a manifest file on disk whose stat fields give us
            # real mtime / owner / perms — without this lookup the row would
            # show blank stale/owner/perms because `ollama list` doesn't
            # surface that data. Falls back gracefully when the manifest can't
            # be located (cloud-only models, custom registries, etc.).
            manifest = _manifest_path(name)
            stat_kwargs = _stat_kwargs(manifest) if manifest is not None else {}
            mtime: float | None = None
            if manifest is not None:
                try:
                    mtime = manifest.lstat().st_mtime
                except OSError:
                    mtime = None
            entries.append(
                Entry(
                    provider=self.name,
                    id=name,
                    path=manifest,
                    label=name,
                    size_bytes=size_bytes,
                    mtime=mtime,
                    risk=self.risk,
                    recipe=[f"ollama rm {shlex.quote(name)}"],
                    **stat_kwargs,
                )
            )
        return entries

    def _walk_models_dir(self) -> list[Entry]:
        models = Path(os.path.expanduser("~/.ollama/models"))
        if not models.exists():
            return []
        total, _skipped = size_path(models)
        return [
            Entry(
                provider=self.name,
                id=str(models),
                path=models,
                label=str(models),
                size_bytes=total,
                mtime=None,
                risk=self.risk,
                recipe=[f"rm -rf {shlex.quote(str(models))}"],
                **_stat_kwargs(models),
            )
        ]


def _parse_size(s: str) -> int:
    m = _SIZE_RE.search(s)
    if not m:
        return 0
    value = float(m.group(1))
    unit = m.group(2).upper()
    return int(value * _SIZE_UNITS[unit])


def _manifest_path(name: str) -> Path | None:
    """Resolve an `ollama list` NAME to its on-disk manifest file.

    Layout: ``~/.ollama/models/manifests/<registry>/<namespace>/<repo>/<tag>``.
    Default registry is ``registry.ollama.ai/library`` for bare names.
    Returns None when nothing exists at any candidate path (e.g. cloud-only
    models that have no local manifest).
    """
    repo, _, tag = name.partition(":")
    if not tag:
        tag = "latest"
    base = Path(os.path.expanduser("~/.ollama/models/manifests"))
    parts = repo.split("/") if repo else []
    candidates: list[Path] = []
    if len(parts) == _MANIFEST_PARTS_BARE:
        candidates.append(base / "registry.ollama.ai" / "library" / parts[0] / tag)
    elif len(parts) == _MANIFEST_PARTS_NAMESPACED:
        # Namespaced (org/repo) on default registry, or two-part custom registry.
        candidates.append(base / "registry.ollama.ai" / parts[0] / parts[1] / tag)
        candidates.append(base / parts[0] / parts[1] / tag)
    elif len(parts) >= _MANIFEST_PARTS_FULLY_QUALIFIED:
        candidates.append(base.joinpath(*parts) / tag)
    for c in candidates:
        if c.is_file():
            return c
    return None
