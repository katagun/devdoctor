from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import JSONResponse

from diskdoctor import discovery, history, history_log, registry
from diskdoctor.types import Report, ScanFilters
from diskdoctor.web.models import SnapshotCreate, SnapshotMeta

router = APIRouter(prefix="/api")


@router.get("/snapshots")
def list_snapshots(
    limit: int | None = Query(default=None, ge=1),
    kind: Literal["auto", "manual", "all"] = Query(default="all"),
) -> list[SnapshotMeta]:
    out: list[SnapshotMeta] = []
    directory = history.default_snapshot_dir()
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            report = Report.from_json(path.read_text())
        except Exception:
            # Malformed file — skip, don't fail the whole listing.
            continue
        if kind not in ("all", report.kind.value):
            continue
        out.append(
            SnapshotMeta(
                name=path.name,
                path=str(path),
                scanned_at=report.scanned_at.isoformat(),
                hostname=report.hostname,
                platform=report.platform,
                note=report.note,
                total_bytes=report.total_bytes(),
                kind=report.kind.value,
                duration_ms=report.duration_ms,
                entry_count=len(report.entries) if report.kind.value == "manual" else None,
                per_provider=[
                    {
                        "name": pt.name,
                        "bytes": pt.bytes,
                        "entries": pt.entries,
                        "duration_ms": pt.duration_ms,
                    }
                    for pt in report.per_provider
                ]
                if report.per_provider
                else None,
            )
        )
        if limit is not None and len(out) >= limit:
            break
    return out


@router.post("/snapshots")
def create_snapshot(body: SnapshotCreate, request: Request) -> dict[str, str]:
    providers_list = registry.load_providers(request.app.state.shell)
    report = discovery.scan(providers_list, ScanFilters(), datetime.now(UTC))
    if body.note:
        report.note = body.note
    target = history.write_snapshot(report, history.default_snapshot_dir())
    return {"name": target.name, "path": str(target)}


@router.get("/snapshots/{name}")
def get_snapshot(name: str) -> JSONResponse:
    path = history.default_snapshot_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="snapshot not found")
    return JSONResponse(content=json.loads(path.read_text()))


@router.get("/history")
def history_timeline(limit: int = 200) -> JSONResponse:
    """Merged audit timeline: cleanup events + snapshot creations, newest-first."""
    events: list[dict[str, object]] = []
    for ev in history_log.read_events(limit=limit):
        events.append(ev)

    directory = history.default_snapshot_dir()
    if directory.exists():
        for path in directory.glob("*.json"):
            try:
                report = Report.from_json(path.read_text())
            except Exception:
                continue
            events.append(
                {
                    "type": "snapshot",
                    "at": report.scanned_at.isoformat(),
                    "name": path.name,
                    "total_bytes": report.total_bytes(),
                    "entry_count": len(report.entries),
                    "note": report.note,
                }
            )

    # Sort newest-first; events without `at` sink to the bottom.
    events.sort(key=lambda e: str(e.get("at", "")), reverse=True)
    return JSONResponse(content={"events": events[:limit]})


@router.get("/diff")
def diff(from_: str, to_: str, request: Request) -> JSONResponse:
    base_dir = history.default_snapshot_dir()
    before_path = base_dir / from_
    if not before_path.is_file():
        raise HTTPException(status_code=404, detail=f"unknown snapshot: {from_}")
    before = Report.from_json(before_path.read_text())

    if to_ == "live":
        providers_list = registry.load_providers(request.app.state.shell)
        after = discovery.scan(providers_list, ScanFilters(), datetime.now(UTC))
    else:
        after_path = base_dir / to_
        if not after_path.is_file():
            raise HTTPException(status_code=404, detail=f"unknown snapshot: {to_}")
        after = Report.from_json(after_path.read_text())

    result = history.diff(before, after)
    # DiffReport is not JSON-serializable directly; build the payload.
    return JSONResponse(
        content={
            "before_at": result.before_at.isoformat(),
            "after_at": result.after_at.isoformat(),
            "rows": [
                {
                    "provider": r.provider,
                    "before_bytes": r.before_bytes,
                    "after_bytes": r.after_bytes,
                    "delta_bytes": r.delta_bytes,
                    "delta_pct": r.delta_pct,
                }
                for r in result.rows
            ],
        }
    )
