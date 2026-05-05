from __future__ import annotations

from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from diskdoctor.config import load_app_settings
from diskdoctor.ports import Shell
from diskdoctor.storage import build_storage
from diskdoctor.web.middleware import HostHeaderMiddleware
from diskdoctor.web.routes_clean import router as clean_router
from diskdoctor.web.routes_disk_usage import router as disk_usage_router
from diskdoctor.web.routes_history import router as history_router
from diskdoctor.web.routes_memory import router as memory_router
from diskdoctor.web.routes_scan import router as scan_router
from diskdoctor.web.routes_settings import router as settings_router
from diskdoctor.web.runner_registry import RunnerRegistry

API_PREFIX = "/api"
_API_ROOT = API_PREFIX.lstrip("/")

_HTTP_404_NOT_FOUND = 404


class _SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html for client-side routes.

    Two invariants:
      - Unknown /api/* paths always return JSON 404 (never index.html). This
        prevents API consumers from seeing HTML when they mistype a route.
      - Any other unknown path returns index.html so the SPA router can handle
        client-side routes. `html=True` alone only does this for directory
        paths; true SPA catch-all needs this subclass.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != _HTTP_404_NOT_FOUND:
                raise
            if path == _API_ROOT or path.startswith(f"{_API_ROOT}/"):
                return JSONResponse(
                    status_code=_HTTP_404_NOT_FOUND,
                    content={
                        "error": {
                            "code": "not_found",
                            "message": f"No such API route: /{path}",
                        }
                    },
                )
            return await super().get_response("index.html", scope)


def build_app(
    shell: Shell,
    *,
    allowed_hosts: set[str],
    static_dir: Path | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Routing order is strict:
      1. Host-header middleware (rejects anything before routing)
      2. /api/* routes (explicit; registered via include_router or @app.get —
         see below for ordering details)
      3. StaticFiles at / with SPA fallback (serves the built SPA; unknown
         paths return index.html for client-side routing; unknown /api/*
         paths return JSON 404 instead)

    The SPA mount is always kept at the end of the route table: any route
    added via FastAPI's decorators (@app.get, app.include_router) after
    build_app returns is automatically re-inserted before the mount, so
    explicit /api routes win over the StaticFiles catch-all.
    """
    app = FastAPI(title="DevDoctor", version="0.1.0")
    app.add_middleware(HostHeaderMiddleware, allowed_hosts=allowed_hosts)
    app.state.shell = shell
    app.state.app_settings = load_app_settings()
    app.state.storage = build_storage(app.state.app_settings)

    # Single-slot registry for the active cleanup job.
    app.state.runner_registry = RunnerRegistry()

    # /api routers — subsequent tasks attach additional routers the same way.
    app.include_router(scan_router)
    app.include_router(history_router)
    app.include_router(clean_router)
    app.include_router(disk_usage_router)
    app.include_router(memory_router)
    app.include_router(settings_router)

    # Mount the SPA at /. Placed manually via Mount so we can keep a reference
    # and ensure it stays last in the route table as new routes are added.
    resolved_static = _resolve_static(static_dir)
    spa_mount = Mount(
        "/",
        app=_SPAStaticFiles(directory=str(resolved_static), html=True),
        name="spa",
    )
    app.router.routes.append(spa_mount)

    _install_spa_last_hook(app, spa_mount)

    return app


def _install_spa_last_hook(app: FastAPI, spa_mount: Mount) -> None:
    """Wrap the app's route-registration methods so the SPA mount stays last.

    Without this, @app.get("/api/foo") (or include_router) added after
    build_app returns would be appended *after* the / mount, which in
    Starlette's route dispatch means the mount catches the request first.
    Reordering on every add keeps the invariant: explicit routes win over
    the SPA catch-all, in the order they were declared.
    """
    routes = app.router.routes

    def _reorder_spa_last() -> None:
        if spa_mount in routes and routes[-1] is not spa_mount:
            routes.remove(spa_mount)
            routes.append(spa_mount)

    def _wrap(method_name: str) -> None:
        original: Callable[..., Any] = getattr(app.router, method_name)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            _reorder_spa_last()
            return result

        setattr(app.router, method_name, wrapper)

    for name in ("add_api_route", "add_route", "add_websocket_route", "add_api_websocket_route"):
        _wrap(name)


def _resolve_static(override: Path | None) -> Path:
    if override is not None:
        return override
    # Bundled built SPA
    with resources.as_file(resources.files("diskdoctor.web._static") / "dist") as p:
        return Path(p)
