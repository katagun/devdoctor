from __future__ import annotations

import json
import logging
import re

from devdoctor.providers.base import Provider
from devdoctor.types import Entry, Risk

logger = logging.getLogger(__name__)

_SIZE_UNITS = {"B": 1, "KB": 1_000, "MB": 1_000_000, "GB": 1_000_000_000, "TB": 1_000_000_000_000}
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)")


# Canonical category id -> prune recipe, in display order.
_CATEGORIES = [
    ("images", "docker image prune -a -f"),
    ("containers", "docker container prune -f"),
    ("volumes", "docker volume prune -f"),
    ("build-cache", "docker builder prune -a -f"),
]

# Maps both the modern NDJSON `Type` field and the legacy single-object keys
# of `docker system df --format json` onto our canonical category ids. Modern
# Docker reports "Local Volumes" / "Build Cache"; older/alternate shapes use
# "Volumes" / "BuildCache".
_TYPE_TO_ID = {
    "Images": "images",
    "Containers": "containers",
    "Local Volumes": "volumes",
    "Volumes": "volumes",
    "Build Cache": "build-cache",
    "BuildCache": "build-cache",
}


class DockerProvider(Provider):
    name = "docker"
    description = "Docker images, containers, volumes, build cache"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    required_binary = "docker"
    details = (
        "Reads `docker system df --format json` and surfaces reclaimable bytes "
        "from images, stopped containers, dangling volumes, and the build cache. "
        "Each category becomes its own entry with the corresponding `docker ... prune` recipe."
    )

    def discover(self) -> list[Entry]:
        result = self._shell.run(["docker", "system", "df", "--format", "json"], check=False)
        if result.returncode != 0 or not result.stdout.strip():
            # `available()` already confirmed the docker binary exists, so a
            # non-zero exit here means docker is installed but not usable right
            # now (daemon down, permission denied). Worth a warning rather than
            # a silent empty scan.
            msg = (
                f"docker: `docker system df` failed (exit {result.returncode}); "
                "reporting no reclaimable docker space"
            )
            logger.warning("%s: %s", msg, result.stderr.strip() or "no stderr")
            self.diagnostics.append(msg)
            return []
        items_by_id = _parse_df(result.stdout)
        if not items_by_id:
            logger.debug("docker: `docker system df` output had no parseable rows")

        entries: list[Entry] = []
        for id_, cmd in _CATEGORIES:
            reclaimable = _sum_reclaimable(items_by_id.get(id_, []))
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


def _parse_df(stdout: str) -> dict[str, list[dict[str, object]]]:
    """Group reclaimable rows by canonical category id.

    `docker system df --format json` has shipped in two shapes:

      * Modern NDJSON — one aggregate object per line, keyed by ``Type``
        (e.g. ``{"Type": "Images", "Reclaimable": "20.8GB (51%)"}``). This is
        what current Docker emits; the previous implementation parsed the
        whole payload with a single ``json.loads`` and silently reported
        nothing on the ``JSONDecodeError`` that multi-line input raises.
      * Legacy single object — ``{"Images": [...], "Containers": [...], ...}``.

    Both are handled; unparseable lines are skipped. Returns an empty mapping
    (never raises) when nothing usable was found.
    """
    items: dict[str, list[dict[str, object]]] = {}

    def absorb_object(obj: dict[str, object]) -> None:
        type_ = obj.get("Type")
        if isinstance(type_, str):
            # NDJSON aggregate row: the object itself carries Reclaimable/Size.
            id_ = _TYPE_TO_ID.get(type_)
            if id_ is not None:
                items.setdefault(id_, []).append(obj)
            return
        # Legacy shape: each known key maps to a list of per-item dicts.
        for key, value in obj.items():
            id_ = _TYPE_TO_ID.get(key)
            if id_ is not None and isinstance(value, list):
                items.setdefault(id_, []).extend(v for v in value if isinstance(v, dict))

    parsed_any = False
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            parsed_any = True
            absorb_object(obj)

    if not parsed_any:
        # Fallback: some CLIs pretty-print a single JSON document across lines.
        try:
            obj = json.loads(stdout)
        except json.JSONDecodeError:
            return items
        if isinstance(obj, dict):
            absorb_object(obj)
    return items


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
