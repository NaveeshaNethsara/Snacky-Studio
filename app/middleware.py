"""Local access checks that preserve attachment errors and disconnects."""
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse


class LocalAccessMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)

        async def with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
                headers["Cross-Origin-Opener-Policy"] = "same-origin"
            await send(message)

        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if (origin and origin != str(request.base_url).rstrip("/")) or request.headers.get("sec-fetch-site") == "cross-site":
                response = JSONResponse({"detail": "Open Snacky Studio locally to use this action."}, status_code=403)
                return await response(scope, receive, with_headers)
        # Stream directly: a failed attachment must not get a successful end marker.
        await self.app(scope, receive, with_headers)
