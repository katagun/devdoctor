from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from diskdoctor.providers.base import Provider
from diskdoctor.sizer import size_path
from diskdoctor.types import Entry, Risk

_SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)", re.IGNORECASE)
_OLLAMA_LIST_MIN_COLS = 3  # name, id, size, ...


class OllamaProvider(Provider):
    name = "ollama"
    description = "Ollama local LLM models"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    required_binary = "ollama"

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
            entries.append(
                Entry(
                    provider=self.name,
                    id=name,
                    path=None,
                    label=name,
                    size_bytes=size_bytes,
                    mtime=None,
                    risk=self.risk,
                    recipe=[f"ollama rm {name}"],
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
            )
        ]


def _parse_size(s: str) -> int:
    m = _SIZE_RE.search(s)
    if not m:
        return 0
    value = float(m.group(1))
    unit = m.group(2).upper()
    return int(value * _SIZE_UNITS[unit])
