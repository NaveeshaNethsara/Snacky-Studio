"""RFC 9457 Problem Details for HTTP APIs (application/problem+json)."""
from typing import Any
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR


class ProblemDetail(HTTPException):
    def __init__(
        self,
        status_code: int,
        title: str,
        detail: str,
        type_uri: str | None = None,
        invalid_params: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.title = title
        self.type_uri = type_uri or f"https://errors.snackystudio.io/http-{status_code}"
        self.invalid_params = invalid_params or []


async def problem_detail_handler(request: Request, exc: Exception) -> JSONResponse:
    path = request.url.path
    if isinstance(exc, ProblemDetail):
        content = {
            "type": exc.type_uri,
            "title": exc.title,
            "status": exc.status_code,
            "detail": exc.detail,
            "instance": path,
        }
        if exc.invalid_params:
            content["invalid_params"] = exc.invalid_params
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers or {},
            media_type="application/problem+json",
        )

    if isinstance(exc, HTTPException):
        content = {
            "type": f"https://errors.snackystudio.io/http-{exc.status_code}",
            "title": exc.detail if isinstance(exc.detail, str) else "HTTP Error",
            "status": exc.status_code,
            "detail": str(exc.detail),
            "instance": path,
        }
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers or {},
            media_type="application/problem+json",
        )

    if isinstance(exc, RequestValidationError):
        invalid_params = []
        for error in exc.errors():
            loc = ".".join(str(l) for l in error.get("loc", []))
            invalid_params.append({
                "name": loc,
                "reason": error.get("msg", ""),
                "type": error.get("type", ""),
            })
        content = {
            "type": "https://errors.snackystudio.io/validation-error",
            "title": "Unprocessable Entity",
            "status": 422,
            "detail": "Request body or query parameters failed schema validation.",
            "instance": path,
            "invalid_params": invalid_params,
        }
        return JSONResponse(
            status_code=422,
            content=content,
            media_type="application/problem+json",
        )

    # Generic unhandled exception
    content = {
        "type": "https://errors.snackystudio.io/internal-error",
        "title": "Internal Server Error",
        "status": HTTP_500_INTERNAL_SERVER_ERROR,
        "detail": "An unexpected server error occurred.",
        "instance": path,
    }
    return JSONResponse(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        content=content,
        media_type="application/problem+json",
    )

