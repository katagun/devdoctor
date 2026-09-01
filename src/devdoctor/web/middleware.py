from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp


class HostHeaderMiddleware:
    """Reject any request whose Host header isn't in the allow-list.

    Defeats DNS-rebinding attacks on 127.0.0.1-bound servers: an attacker
    webpage could resolve `attacker.com` to `127.0.0.1` then post destructive
    requests via the browser. Checking Host on the server refuses them before
    any handler runs.
    """

    def __init__(self, app: ASGIApp, *, allowed_hosts: set[str]) -> None:
        self.app = app
        self.allowed_hosts = {h.lower() for h in allowed_hosts}

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        host = (request.headers.get("host") or "").lower()
        if host not in self.allowed_hosts:
            response = JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "bad_host",
                        "message": f"Host header {host!r} not allowed",
                    }
                },
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
