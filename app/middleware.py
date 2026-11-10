"""Local and standalone web access checks with origin verification."""
from urllib.parse import urlsplit
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
            if origin:
                origin_host = (urlsplit(origin).hostname or "").lower()
                req_host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(":")[0].lower()
                base_host = (urlsplit(str(request.base_url)).hostname or "").lower()
                is_same_origin = (origin_host == req_host) or (origin_host == base_host) or (origin == str(request.base_url).rstrip("/"))
                if not is_same_origin or request.headers.get("sec-fetch-site") == "cross-site":
                    response = JSONResponse({"detail": "Open Snacky Studio locally or on its domain to use this action."}, status_code=403)
                    return await response(scope, receive, with_headers)
        # Stream directly: a failed attachment must not get a successful end marker.
        await self.app(scope, receive, with_headers)

