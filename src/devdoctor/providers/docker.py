from __future__ import annotations

import json
import logging
import re
import shlex

from devdoctor.providers.base import Provider
from devdoctor.types import Entry, Risk

logger = logging.getLogger(__name__)

_SIZE_UNITS = {
    "B": 1,
    "KB": 1_000,
    "MB": 1_000_000,
    "GB": 1_000_000_000,
    "TB": 1_000_000_000_000,
    "PB": 1_000_000_000_000_000,
}
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB|PB)", re.IGNORECASE)

_ANONYMOUS_VOLUME_LABEL = "com.docker.volume.anonymous"
_VOLUME_DETAILS_COMMAND = [
    "docker",
    "system",
    "df",
    "--verbose",
    "--format",
    "{{json .Volumes}}",
]


# Canonical non-volume category id -> prune recipe, in display order. Volumes
# deliberately do not use `docker volume prune`: before Engine API 1.42 that
# command removed all unused volumes, while newer daemons remove only anonymous
# volumes unless `--all` is passed. Neither behavior is safe to pair with
# Docker's aggregate Local Volumes reclaimable byte count.
_CATEGORIES = [
    ("images", "docker image prune -a -f"),
    ("containers", "docker container prune -f"),
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
        "from images, stopped containers, unused volumes, and the build cache. "
        "Unused volumes are listed individually; named volumes are marked dangerous."
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

        volume_reclaimable = _sum_reclaimable(items_by_id.get("volumes", []))
        if volume_reclaimable > 0:
            entries.extend(self._discover_unused_volumes(volume_reclaimable))
        return entries

    def _discover_unused_volumes(self, aggregate_bytes: int) -> list[Entry]:
        """Return exact, individually removable unused volumes.

        The summary `Local Volumes` row mixes named and anonymous volumes, but
        modern `docker volume prune` treats those classes differently. Query
        Docker's verbose JSON for per-volume sizes and reference counts instead
        of attaching the mixed aggregate to a version-dependent bulk command.

        A missing anonymous marker is intentionally classified as named. Older
        daemons did not mark every anonymous volume consistently, and treating
        an uncertain volume as dangerous is the safe failure mode.
        """
        result = self._shell.run(list(_VOLUME_DETAILS_COMMAND), check=False)
        if result.returncode != 0 or not result.stdout.strip():
            self._note_volume_details_failure(
                aggregate_bytes,
                f"command failed (exit {result.returncode})",
                result.stderr,
            )
            return []

        rows = _parse_volume_details(result.stdout)
        if rows is None:
            self._note_volume_details_failure(
                aggregate_bytes,
                "output was not a JSON volume array",
            )
            return []

        entries: list[Entry] = []
        skipped_unused = 0
        for row in rows:
            if not _volume_is_unused(row):
                continue
            name = row.get("Name")
            raw_size = row.get("Size")
            if (
                not isinstance(name, str)
                or not name
                or _SIZE_RE.search(str(raw_size or "")) is None
            ):
                skipped_unused += 1
                continue
            size_bytes = _parse_size(raw_size)
            # Empty volumes are valid Docker records, but they recover no disk
            # space and should not produce a misleading parse warning.
            if size_bytes <= 0:
                continue

            anonymous = _volume_is_anonymous(row)
            kind = "anonymous" if anonymous else "named"
            entries.append(
                Entry(
                    provider=self.name,
                    id=f"volume:{name}",
                    path=None,
                    label=f"docker {kind} volume {name}",
                    size_bytes=size_bytes,
                    mtime=None,
                    risk=Risk.RECLAIMABLE if anonymous else Risk.DANGEROUS,
                    # Remove only the volume the user reviewed. If it becomes
                    # referenced before execution, Docker refuses the removal.
                    recipe=[f"docker volume rm {shlex.quote(name)}"],
                )
            )

        detailed_bytes = sum(entry.size_bytes for entry in entries)
        if not entries:
            self._note_volume_details_failure(
                aggregate_bytes,
                "no individually sized unused volumes were parseable",
            )
        elif skipped_unused:
            msg = (
                f"docker: skipped {skipped_unused} unused volume(s) whose name or size "
                "could not be read; they will not be offered for cleanup"
            )
            logger.warning("%s", msg)
            self.diagnostics.append(msg)

        # Both values are human-readable rounded sizes from Docker, and the two
        # commands are separate snapshots. Allow a small tolerance before
        # surfacing a useful drift/omission diagnostic.
        tolerance = max(1_000_000, aggregate_bytes // 100)
        if entries and abs(detailed_bytes - aggregate_bytes) > tolerance:
            msg = (
                "docker: detailed unused volumes total "
                f"{detailed_bytes} bytes, but the summary reported {aggregate_bytes}; "
                "cleanup uses only the individually reviewed volumes"
            )
            logger.warning("%s", msg)
            self.diagnostics.append(msg)
        return entries

    def _note_volume_details_failure(
        self,
        aggregate_bytes: int,
        reason: str,
        stderr: str = "",
    ) -> None:
        msg = (
            f"docker: {aggregate_bytes} volume bytes look reclaimable, but detailed "
            f"volume discovery {reason}; volume cleanup was disabled"
        )
        logger.warning("%s: %s", msg, stderr.strip() or "no stderr")
        self.diagnostics.append(msg)


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
    return sum(_parse_size(it.get("Reclaimable") or it.get("Size")) for it in items)


def _parse_size(raw: object) -> int:
    m = _SIZE_RE.search(str(raw or ""))
    if not m:
        return 0
    value = float(m.group(1))
    unit = m.group(2).upper()
    return int(value * _SIZE_UNITS[unit])


def _parse_volume_details(stdout: str) -> list[dict[str, object]] | None:
    try:
        raw = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(raw, dict):
        raw = raw.get("Volumes")
    if not isinstance(raw, list):
        return None
    return [row for row in raw if isinstance(row, dict)]


def _volume_is_unused(row: dict[str, object]) -> bool:
    raw_links = row.get("Links")
    if raw_links is None:
        usage = row.get("UsageData")
        if isinstance(usage, dict):
            raw_links = usage.get("RefCount")
    try:
        return int(str(raw_links)) == 0
    except (TypeError, ValueError):
        return False


def _volume_is_anonymous(row: dict[str, object]) -> bool:
    labels = row.get("Labels")
    if isinstance(labels, dict):
        return _ANONYMOUS_VOLUME_LABEL in labels
    if isinstance(labels, str):
        return any(
            item.strip().partition("=")[0] == _ANONYMOUS_VOLUME_LABEL for item in labels.split(",")
        )
    if isinstance(labels, list):
        return any(
            isinstance(item, str) and item.strip().partition("=")[0] == _ANONYMOUS_VOLUME_LABEL
            for item in labels
        )
    return False
