from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from devdoctor.providers.base import Provider
from devdoctor.types import CommandAction, DiskUsage, Entry, Risk

logger = logging.getLogger(__name__)

_LIST_ARGV = ("tmutil", "listlocalsnapshots", "/")

# Matches `com.apple.TimeMachine.<YYYY-MM-DD-HHMMSS>.local`. Everything else —
# in particular `com.apple.os.update-*` snapshots — must never be touched.
_SNAPSHOT_RE = re.compile(r"com\.apple\.TimeMachine\.(\d{4}-\d{2}-\d{2}-\d{6})\.local")
_TIMESTAMP_FORMAT = "%Y-%m-%d-%H%M%S"
# A lone snapshot needs no bundle: there is nothing to delete while keeping
# the newest restore point, so only the per-snapshot entry is emitted.
_BUNDLE_MIN_SNAPSHOTS = 2


class TimeMachineSnapshotsProvider(Provider):
    name = "time-machine-local-snapshots"
    family = "system"
    description = "Time Machine local snapshots"
    platforms = ("darwin",)
    risk = Risk.RECLAIMABLE
    required_binary = "tmutil"
    details = (
        "Hourly Time Machine local snapshots hold blocks other cleanups cannot "
        "free. The bundle keeps the newest restore point; deleting them never "
        "touches the external backup."
    )

    def discover(self) -> list[Entry]:
        result = self._shell.run(list(_LIST_ARGV), check=False)
        if result.returncode != 0:
            msg = (
                f"{self.name}: `tmutil listlocalsnapshots /` failed "
                f"(exit {result.returncode}); reporting no Time Machine snapshots"
            )
            logger.warning("%s: %s", msg, result.stderr.strip() or "no stderr")
            self.diagnostics.append(msg)
            return []
        snapshots = _parse_snapshots(result.stdout)
        if not snapshots:
            msg = (
                f"{self.name}: `tmutil listlocalsnapshots /` reported no local "
                "snapshots; nothing to offer for cleanup"
            )
            logger.warning("%s", msg)
            self.diagnostics.append(msg)
            return []
        entries = [_snapshot_entry(self, ts, epoch) for ts, epoch in snapshots]
        if len(snapshots) >= _BUNDLE_MIN_SNAPSHOTS:
            # Bundle goes last: the core selection rule prompts the covering
            # entry before the entries it covers regardless of scan order.
            entries.append(_bundle_entry(self, snapshots))
        return entries


def _parse_snapshots(output: str) -> list[tuple[str, float]]:
    """Return ``(timestamp, epoch)`` pairs oldest-first from tmutil output."""
    found: list[tuple[str, float]] = []
    for line in output.splitlines():
        match = _SNAPSHOT_RE.fullmatch(line.strip())
        if match is None:
            continue
        ts = match.group(1)
        try:
            epoch = datetime.strptime(ts, _TIMESTAMP_FORMAT).replace(tzinfo=UTC).timestamp()
        except ValueError:
            continue
        found.append((ts, epoch))
    found.sort(key=lambda item: item[0])
    return found


def _snapshot_entry(provider: Provider, ts: str, epoch: float) -> Entry:
    dt = datetime.strptime(ts, _TIMESTAMP_FORMAT)
    return Entry(
        provider=provider.name,
        id=f"snapshot-{ts}",
        path=None,
        label=f"Time Machine local snapshot {dt.strftime('%Y-%m-%d %H:%M:%S')}",
        size_bytes=0,
        mtime=epoch,
        risk=provider.risk,
        recipe=[f"tmutil deletelocalsnapshots {ts}"],
        usage=DiskUsage(None, None),
        actions=(CommandAction(("tmutil", "deletelocalsnapshots", ts)),),
    )


def _bundle_entry(provider: Provider, snapshots: list[tuple[str, float]]) -> Entry:
    covered = tuple(f"snapshot-{ts}" for ts, _ in snapshots)
    # Newest-first: if the oldest snapshot expires mid-run, only the last
    # command fails.
    older_newest_first = [ts for ts, _ in snapshots[-2::-1]]
    oldest_epoch = snapshots[0][1]
    return Entry(
        provider=provider.name,
        id="all-but-newest",
        label=f"Time Machine local snapshots, all but the newest ({len(snapshots)})",
        path=None,
        size_bytes=0,
        mtime=oldest_epoch,
        risk=provider.risk,
        recipe=[f"tmutil deletelocalsnapshots {ts}" for ts in older_newest_first],
        usage=DiskUsage(None, None),
        actions=tuple(
            CommandAction(("tmutil", "deletelocalsnapshots", ts)) for ts in older_newest_first
        ),
        covers=covered,
    )
