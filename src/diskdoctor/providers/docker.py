from __future__ import annotations

import json
import re

from diskdoctor.providers.base import Provider
from diskdoctor.types import Entry, Risk


_SIZE_UNITS = {"B": 1, "KB": 1_000, "MB": 1_000_000, "GB": 1_000_000_000, "TB": 1_000_000_000_000}
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)")


_CATEGORIES = [
    ("Images", "images", "docker image prune -a -f"),
    ("Containers", "containers", "docker container prune -f"),
    ("Volumes", "volumes", "docker volume prune -f"),
    ("BuildCache", "build-cache", "docker builder prune -a -f"),
]


class DockerProvider(Provider):
    name = "docker"
    description = "Docker images, containers, volumes, build cache"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    required_binary = "docker"

    def discover(self) -> list[Entry]:
        result = self._shell.run(["docker", "system", "df", "--format", "json"], check=False)
        if result.returncode != 0 or not result.stdout.strip():
            return []
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

        entries: list[Entry] = []
        for key, id_, cmd in _CATEGORIES:
            items = data.get(key, []) or []
            reclaimable = _sum_reclaimable(items)
            if reclaimable <= 0:
                continue
            entries.append(
                Entry(
                    provider=self.name,
                    id=id_,
                    path=None,
                    label=f"docker {id_}",
                    size_bytes=reclaimable,
                    mtime=None,
                    risk=self.risk,
                    recipe=[cmd],
                )
            )
        return entries


def _sum_reclaimable(items: list[dict[str, object]]) -> int:
    total = 0
    for it in items:
        raw = it.get("Reclaimable") or it.get("Size") or ""
        m = _SIZE_RE.search(str(raw))
        if not m:
            continue
        value = float(m.group(1))
        unit = m.group(2).upper()
        total += int(value * _SIZE_UNITS[unit])
    return total
