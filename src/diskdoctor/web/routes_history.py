from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import JSONResponse

from diskdoctor import discovery, history, registry
from diskdoctor.storage.base import StorageBackend, StoredSnapshotMeta
from diskdoctor.types import ScanFilters, SnapshotKind
from diskdoctor.web.models import SnapshotCreate, SnapshotMeta

router = APIRouter(prefix="/api")


@router.get("/snapshots")
def list_snapshots(
    request: Request,
    limit: int | None = Query(default=None, ge=1),
    kind: Literal["auto", "manual", "all"] = Query(default="all"),
) -> list[SnapshotMeta]:
    storage = _storage(request)
    filtered_kind = None if kind == "all" else _snapshot_kind(kind)
    return [
        _snapshot_meta_to_info(meta)
        for meta in storage.list_disk_snapshots(limit=limit, kind=filtered_kind)
    ]


@router.post("/snapshots")
def create_snapshot(body: SnapshotCreate, request: Request) -> dict[str, str]:
    providers_list = registry.load_providers(request.app.state.shell)
    report = discovery.scan(providers_list, ScanFilters(), datetime.now(UTC))
    if body.note:
        report.note = body.note
    target = _storage(request).write_disk_snapshot(report)
    return {"name": target.name, "path": target.path}


@router.get("/snapshots/{name}")
def get_snapshot(name: str, request: Request) -> JSONResponse:
    try:
        report = _storage(request).load_disk_snapshot(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="snapshot not found") from exc
    return JSONResponse(content=json.loads(report.to_json()))


@router.get("/history")
def history_timeline(request: Request, limit: int = 200) -> JSONResponse:
    """Merged audit timeline: cleanup events + snapshot creations, newest-first."""
    events: list[dict[str, object]] = []
    storage = _storage(request)
    for ev in storage.read_audit_events(limit=limit):
        events.append(ev)

    for meta in storage.list_disk_snapshots(limit=None, kind=None):
        events.append(
            {
                "type": "snapshot",
                "at": meta.scanned_at,
                "name": meta.name,
                "total_bytes": meta.total_bytes,
                "entry_count": meta.entry_count or 0,
                "note": meta.note,
            }
        )

    # Sort newest-first; events without `at` sink to the bottom.
    events.sort(key=lambda e: str(e.get("at", "")), reverse=True)
    return JSONResponse(content={"events": events[:limit]})


@router.get("/diff")
def diff(from_: str, to_: str, request: Request) -> JSONResponse:
    storage = _storage(request)
    try:
        before = storage.load_disk_snapshot(from_)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"unknown snapshot: {from_}") from exc

    if to_ == "live":
        providers_list = registry.load_providers(request.app.state.shell)
        after = discovery.scan(providers_list, ScanFilters(), datetime.now(UTC))
    else:
        try:
            after = storage.load_disk_snapshot(to_)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"unknown snapshot: {to_}") from exc

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


def _storage(request: Request) -> StorageBackend:
    return cast(StorageBackend, request.app.state.storage)


def _snapshot_kind(kind: Literal["auto", "manual"]) -> SnapshotKind:
    return SnapshotKind(kind)


def _snapshot_meta_to_info(meta: StoredSnapshotMeta) -> SnapshotMeta:
    return SnapshotMeta(
        name=meta.name,
        path=meta.path,
        scanned_at=meta.scanned_at,
        hostname=meta.hostname,
        platform=meta.platform,
        note=meta.note,
        total_bytes=meta.total_bytes,
        kind=cast(Literal["auto", "manual"], meta.kind),
        duration_ms=meta.duration_ms,
        entry_count=meta.entry_count,
        per_provider=meta.per_provider,
    )
