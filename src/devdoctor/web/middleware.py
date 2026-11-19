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
        # The server speaks plain http on loopback, so its own pages have exactly
        # these origins.
        self.allowed_origins = {f"http://{h}" for h in self.allowed_hosts}

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
        if scope["path"].startswith("/api/") and not self._own_page(request):
            response = JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "bad_origin",
                        "message": "API requests must come from the DevDoctor page itself",
                    }
                },
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _own_page(self, request: Request) -> bool:
        """False when a browser says another page sent this request.

        The Host check stops DNS rebinding, not a page on another site (or another
        local port) posting here through the user's browser. Browsers attach
        ``Origin`` to cross-origin and to every non-GET request, and
        ``Sec-Fetch-Site`` to all of them; a client that sends neither is not a
        browser acting for some other page. "same-site" is refused too: every
        port on localhost is the same site.
        """
        origin = request.headers.get("origin")
        if origin is not None and origin.lower() not in self.allowed_origins:
            return False
        return request.headers.get("sec-fetch-site", "same-origin") in {"same-origin", "none"}
