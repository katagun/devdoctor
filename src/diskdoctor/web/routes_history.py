from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse

from diskdoctor import discovery, history, registry
from diskdoctor.types import Report, ScanFilters
from diskdoctor.web.models import SnapshotCreate, SnapshotMeta

router = APIRouter(prefix="/api")


@router.get("/snapshots")
def list_snapshots() -> list[SnapshotMeta]:
    out: list[SnapshotMeta] = []
    directory = history.default_snapshot_dir()
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.json"), reverse=True):
        report = Report.from_json(path.read_text())
        out.append(
            SnapshotMeta(
                name=path.name,
                path=str(path),
                scanned_at=report.scanned_at.isoformat(),
                hostname=report.hostname,
                platform=report.platform,
                note=report.note,
                total_bytes=report.total_bytes(),
            )
        )
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
