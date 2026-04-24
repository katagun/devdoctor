from __future__ import annotations

import dataclasses
import json
import re
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import JSONResponse

from diskdoctor import cleanup as cleanup_mod
from diskdoctor import discovery, history, registry
from diskdoctor.providers.base import PathProvider
from diskdoctor.types import Report, Risk, ScanFilters, SnapshotKind
from diskdoctor.web.models import ProviderInfo, RecipeRequest, RecipeResponse

router = APIRouter(prefix="/api")


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
def scan(
    request: Request,
    min_size: str | None = Query(default=None),
    risk: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    snapshot: bool = Query(default=False),
) -> JSONResponse:
    filters = ScanFilters(
        min_size_bytes=_parse_size(min_size) if min_size else 0,
        risks=_parse_risks(risk),
        providers=frozenset(provider.split(",")) if provider else None,
    )
    providers_list = registry.load_providers(request.app.state.shell)
    report = discovery.scan(providers_list, filters, datetime.now(UTC))
    if snapshot:
        auto_report = dataclasses.replace(report, kind=SnapshotKind.AUTO)
        try:
            history.write_snapshot(auto_report, history.default_snapshot_dir())
            history.prune_auto_snapshots(
                history.default_snapshot_dir(),
                keep=history.AUTO_SNAPSHOT_RETENTION,
            )
        except OSError:
            # Disk full / permission denied / whatever — don't fail the
            # scan response because the auto-snapshot write choked. Client
            # still gets the scan; next scan will try again.
            pass
    return JSONResponse(content=_report_to_dict(report))


@router.get("/providers")
def providers(request: Request) -> list[ProviderInfo]:
    providers_list = registry.load_providers(request.app.state.shell)
    out: list[ProviderInfo] = []
    for p in providers_list:
        kind: Literal["class", "yaml"] = "yaml" if isinstance(p, PathProvider) else "class"
        out.append(
            ProviderInfo(
                name=p.name,
                description=p.description,
                risk=p.risk.value,
                platforms=list(p.platforms),
                available=p.available(),
                required_binary=p.required_binary,
                kind=kind,
            )
        )
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
