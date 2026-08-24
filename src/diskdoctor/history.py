from __future__ import annotations

import contextlib
import os
from pathlib import Path

from diskdoctor._storage import default_data_dir
from diskdoctor.types import DiffReport, DiffRow, Report


def write_snapshot(report: Report, directory: Path) -> Path:
    """Write a snapshot atomically.

    Filename includes a --<kind>.json suffix so retention (and Snapshot-page
    filtering) can glob without reading contents.
    """
    directory.mkdir(parents=True, exist_ok=True)
    # Microseconds keep same-second snapshots distinct — without them two scans
    # in the same second produce the same filename and os.replace silently
    # clobbers the earlier one. Fixed-width, so lexical sort stays chronological.
    stamp = report.scanned_at.strftime("%Y-%m-%dT%H-%M-%S-%f")
    target = directory / f"{stamp}--{report.kind.value}.json"
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(report.to_json())
        os.replace(tmp, target)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    return target


AUTO_SNAPSHOT_RETENTION = 50


def prune_auto_snapshots(directory: Path, keep: int = AUTO_SNAPSHOT_RETENTION) -> list[Path]:
    """Delete oldest auto-snapshots beyond ``keep``. Manual snapshots are
    never touched; pre-feature (v1) snapshots without a kind suffix aren't
    matched by the ``*--auto.json`` glob and so are also safe.

    Returns the list of deleted paths (for logging / tests).
    """
    if not directory.exists():
        return []
    autos = sorted(directory.glob("*--auto.json"), reverse=True)  # newest first
    victims = autos[keep:]
    deleted: list[Path] = []
    for p in victims:
        try:
            p.unlink()
            deleted.append(p)
        except (FileNotFoundError, PermissionError):
            pass
    return deleted


def load_snapshot(path: Path) -> Report:
    return Report.from_json(path.read_text())


def _totals_by_provider(report: Report) -> dict[str, int]:
    """Prefer per_provider totals (v2) when present; fall back to summing
    entries (v1 files, or any Report built without timings). Returns a
    provider-name → bytes dict covering every provider seen in the report.
    """
    if report.per_provider:
        return {pt.name: pt.bytes for pt in report.per_provider}
    return {p: sum(e.size_bytes for e in es) for p, es in report.by_provider().items()}


def diff(before: Report, after: Report) -> DiffReport:
    before_by = _totals_by_provider(before)
    after_by = _totals_by_provider(after)
    providers = sorted(set(before_by) | set(after_by))
    rows: list[DiffRow] = []
    for name in providers:
        b = before_by.get(name, 0)
        a = after_by.get(name, 0)
        delta = a - b
        pct = 0.0 if b == 0 else (delta / b) * 100.0
        rows.append(
            DiffRow(
                provider=name,
                before_bytes=b,
                after_bytes=a,
                delta_bytes=delta,
                delta_pct=pct,
            )
        )
    return DiffReport(before_at=before.scanned_at, after_at=after.scanned_at, rows=rows)


def latest_snapshots(directory: Path, n: int = 2) -> list[Path]:
    if not directory.exists():
        return []
    files = sorted(directory.glob("*.json"))
    return files[-n:]


def default_snapshot_dir() -> Path:
    return default_data_dir() / "snapshots"
