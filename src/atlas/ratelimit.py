"""A small per-client rate limit for the API (used when no WAF sits in front of it).

Counts requests per client in a sliding one-minute window, in memory. That is exact for a
single API process and a per-process limit when several run. The client is identified by
CloudFront's CloudFront-Viewer-Address header when present (CloudFront sets it from the real
connection, so visitors can't spoof it), else by the connecting address.
"""

import time
from collections import defaultdict, deque

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

WINDOW_SECONDS = 60


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, per_minute: int, path_prefix: str = "/api/"):
        self.app = app
        self.per_minute = per_minute
        self.path_prefix = path_prefix
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    @staticmethod
    def client_key(scope: Scope) -> str:
        for name, value in scope.get("headers", []):
            if name == b"cloudfront-viewer-address":
                # "ip:port" (IPv6 addresses contain colons too): drop the port.
                return value.decode().rsplit(":", 1)[0]
        client = scope.get("client")
        return client[0] if client else "unknown"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self.path_prefix):
            await self.app(scope, receive, send)
            return

        now = time.monotonic()
        window = self.hits[self.client_key(scope)]
        while window and now - window[0] > WINDOW_SECONDS:
            window.popleft()
        if len(window) >= self.per_minute:
            retry = int(WINDOW_SECONDS - (now - window[0])) + 1
            response = JSONResponse(
                {"detail": "Too many requests; slow down and try again shortly"},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
            await response(scope, receive, send)
            return
        window.append(now)
        if len(self.hits) > 50_000:  # forget idle clients so memory stays bounded
            for key in [k for k, v in self.hits.items() if not v or now - v[-1] > WINDOW_SECONDS]:
                del self.hits[key]
        await self.app(scope, receive, send)
