from __future__ import annotations

from pathlib import Path

from diskdoctor.types import DiffReport, DiffRow, Report


def write_snapshot(report: Report, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    # Filename-safe ISO timestamp (no ':' which is problematic on some FS).
    stamp = report.scanned_at.strftime("%Y-%m-%dT%H-%M-%S")
    target = directory / f"{stamp}.json"
    target.write_text(report.to_json())
    return target


def load_snapshot(path: Path) -> Report:
    return Report.from_json(path.read_text())


def diff(before: Report, after: Report) -> DiffReport:
    before_by = {p: sum(e.size_bytes for e in es) for p, es in before.by_provider().items()}
    after_by = {p: sum(e.size_bytes for e in es) for p, es in after.by_provider().items()}
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
    from os import environ

    base = environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "diskdoctor" / "snapshots"
