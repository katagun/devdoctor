from __future__ import annotations

import dataclasses
import json
import logging
import re
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import JSONResponse

from devdoctor import cleanup as cleanup_mod
from devdoctor import discovery, history, registry
from devdoctor.providers.base import PathProvider
from devdoctor.storage.base import StorageBackend
from devdoctor.types import Report, Risk, ScanFilters, SnapshotKind
from devdoctor.web.models import ProviderInfo, RecipeRequest, RecipeResponse

router = APIRouter(prefix="/api")

logger = logging.getLogger(__name__)


_SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([KMGT]?)$", re.IGNORECASE)
_SIZE_MULT = {"": 1, "K": 1_000, "M": 1_000_000, "G": 1_000_000_000, "T": 1_000_000_000_000}


def _parse_size(s: str) -> int:
    m = _SIZE_RE.match(s)
    if not m:
        raise HTTPException(status_code=422, detail=f"invalid size {s!r}")
    return int(float(m.group(1)) * _SIZE_MULT[m.group(2).upper()])


def _parse_risks(csv: str | None) -> frozenset[Risk] | None:
    if not csv:
        return None
    try:
        return frozenset(Risk(v.strip()) for v in csv.split(",") if v.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scan")
@router.get("/disk/scan")
def scan(
    request: Request,
    min_size: str | None = Query(default=None),
    risk: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    snapshot: bool = Query(default=False),
    snapshot_min_interval_ms: int | None = Query(default=None, ge=0),
) -> JSONResponse:
    filters = ScanFilters(
        min_size_bytes=_parse_size(min_size) if min_size else 0,
        risks=_parse_risks(risk),
        providers=frozenset(provider.split(",")) if provider else None,
    )
    providers_list = registry.load_providers(request.app.state.shell)
    report = discovery.scan(providers_list, filters, datetime.now(UTC))
    storage: StorageBackend = request.app.state.storage
    if filters.min_size_bytes == 0 and filters.risks is None and filters.providers is None:
        try:
            storage.write_disk_dashboard_summary(report)
        except OSError as exc:
            logger.warning("scan: failed to write dashboard summary: %s", exc)
    if snapshot and _should_write_auto_snapshot(storage, snapshot_min_interval_ms):
        auto_report = dataclasses.replace(report, kind=SnapshotKind.AUTO)
        try:
            storage.write_disk_snapshot(auto_report)
            storage.prune_auto_disk_snapshots(keep=history.AUTO_SNAPSHOT_RETENTION)
        except OSError as exc:
            # Disk full / permission denied / whatever — don't fail the
            # scan response because the auto-snapshot write choked. Client
            # still gets the scan; next scan will try again.
            logger.warning("scan: auto-snapshot write failed: %s", exc)
    return JSONResponse(content=_report_to_dict(report))


def _should_write_auto_snapshot(
    storage: StorageBackend,
    min_interval_ms: int | None,
) -> bool:
    """Honour the client's cadence by skipping auto-snapshot writes that
    fall inside `min_interval_ms` of the most recent auto-snapshot.

    Without this, every filter-chip change on the Scan page writes a fresh
    auto-snapshot — the cadence's TanStack staleTime only blocks time-based
    refetches, not new query keys. Returns True when the directory has no
    prior auto-snapshot, when no rate-limit was requested (None or 0), or
    when the most recent auto-snapshot is older than the requested window.
    """
    if min_interval_ms is None or min_interval_ms <= 0:
        return True
    autos = storage.list_disk_snapshots(limit=1, kind=SnapshotKind.AUTO)
    if not autos:
        return True
    try:
        last_seen = datetime.fromisoformat(autos[0].scanned_at).timestamp()
    except ValueError:
        return True
    age_ms = (datetime.now(UTC).timestamp() - last_seen) * 1000
    return age_ms >= min_interval_ms


@router.get("/providers")
def providers(request: Request) -> list[ProviderInfo]:
    providers_list = registry.load_providers(request.app.state.shell)
    out: list[ProviderInfo] = []
    for p in providers_list:
        if isinstance(p, PathProvider):
            kind: Literal["class", "yaml"] = "yaml"
            details = None
            raw_paths = list(p.raw_paths)
            resolved_paths = [str(rp) for rp in p.resolve_paths()]
            recipe_template = list(p.recipe_template)
        else:
            kind = "class"
            details = p.details
            raw_paths = None
            resolved_paths = None
            recipe_template = None
        info = ProviderInfo(
            name=p.name,
            description=p.description,
            risk=p.risk.value,
            platforms=list(p.platforms),
            available=p.available(),
            required_binary=p.required_binary,
            kind=kind,
            details=details,
            raw_paths=raw_paths,
            resolved_paths=resolved_paths,
            recipe_template=recipe_template,
        )
        out.append(info)
    return out


@router.post("/recipe", response_model=RecipeResponse)
def recipe(request: Request, body: RecipeRequest) -> RecipeResponse:
    filters = ScanFilters(providers=frozenset(body.providers) if body.providers else None)
    providers_list = registry.load_providers(request.app.state.shell)
    report = discovery.scan(providers_list, filters, datetime.now(UTC))
    return RecipeResponse(script=cleanup_mod.build_script(report))


def _report_to_dict(report: Report) -> dict[str, object]:
    data: dict[str, object] = json.loads(report.to_json())
    return data
