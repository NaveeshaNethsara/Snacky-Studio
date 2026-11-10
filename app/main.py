"""Application composition for local processing or independent cloud workers."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import router
from app.api_v1 import authenticate_v1, router as v1_router
from app.auth import CloudAccessMiddleware, router as auth_router
from app.config import Settings
from app.downloader import download_media, ensure_ffmpeg
from app.errors import ProblemDetail, problem_detail_handler
from app.events import TaskEventHub
from app.files import build_content_disposition  # Existing import remains available.
from app.health import router as health_router
from app.jobs import DownloadManager, JobStore
from app.logging_conf import CorrelationIdMiddleware, setup_logging
from app.metrics import PrometheusMetricsMiddleware, get_metrics_exposition
from app.middleware import LocalAccessMiddleware
from app.observability import init_sentry
from app.seo import SEO_ROUTES, generate_robots_txt, generate_sitemap, inject_seo_meta
from app.storage import LocalMediaStorage, S3MediaStorage


def create_app(settings: Settings | None = None, worker=download_media, *, recover_jobs=True) -> FastAPI:
    settings = settings or Settings()
    is_cloud = settings.mode == "cloud"
    setup_logging(json_output=is_cloud)
    init_sentry(settings)

    @asynccontextmanager
    async def lifespan(app):
        settings.prepare()
        if settings.mode == "local":
            await asyncio.to_thread(ensure_ffmpeg)
            store = JobStore(settings.data_dir / "jobs.sqlite3")
            app.state.jobs = DownloadManager(store, settings.downloads_dir, worker, settings.max_workers, settings.max_queued,
                                             recover=recover_jobs)
            app.state.storage = LocalMediaStorage(settings)
        else:
            from app.cloud import CloudDownloadManager
            app.state.jobs = await asyncio.to_thread(CloudDownloadManager, settings)
            app.state.storage = S3MediaStorage(settings, app.state.jobs.store)
        app.state.analysis_slots = asyncio.Semaphore(2)
        app.state.events = TaskEventHub(app.state.jobs, settings)
        await app.state.events.start()
        try:
            yield
        finally:
            await app.state.events.close()
            await asyncio.to_thread(app.state.jobs.shutdown)

    is_cloud = settings.mode == "cloud"
    app = FastAPI(
        title="Snacky Studio API",
        version="3.0.0",
        lifespan=lifespan,
        docs_url=None if is_cloud else "/docs",
        redoc_url=None,
        openapi_url=None if is_cloud else "/openapi.json",
    )
    app.state.settings = settings

    # RFC 9457 Problem Details Exception Handlers
    app.add_exception_handler(ProblemDetail, problem_detail_handler)
    app.add_exception_handler(RequestValidationError, problem_detail_handler)

    # SRE Observability: Correlation IDs & Prometheus Latency/Throughput Middlewares
    app.add_middleware(PrometheusMetricsMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    if is_cloud:
        from urllib.parse import urlsplit
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(settings.public_origin).hostname or "localhost", "127.0.0.1", "localhost", "testserver"])
        app.add_middleware(CloudAccessMiddleware, settings=settings)

        # Auth-gated OpenAPI in cloud mode
        @app.get("/docs", include_in_schema=False)
        async def get_docs(auth: dict = Depends(authenticate_v1)):
            return get_swagger_ui_html(openapi_url="/openapi.json", title="Snacky Studio API Docs")

        @app.get("/openapi.json", include_in_schema=False)
        async def get_open_api(auth: dict = Depends(authenticate_v1)):
            return JSONResponse(get_openapi(title=app.title, version=app.version, routes=app.routes))
    else:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])
        app.add_middleware(LocalAccessMiddleware)

    # --- SEO endpoints -------------------------------------------------------

    @app.get("/sitemap.xml", include_in_schema=False)
    async def sitemap():
        return Response(
            content=generate_sitemap(settings.public_origin),
            media_type="application/xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/robots.txt", include_in_schema=False)
    async def robots():
        return Response(
            content=generate_robots_txt(settings.public_origin),
            media_type="text/plain",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # --- Existing utility endpoints -------------------------------------------

    @app.get("/legacy", include_in_schema=False)
    async def legacy():
        return FileResponse(settings.static_dir / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint():
        content, content_type = get_metrics_exposition()
        return Response(content=content, media_type=content_type)

    # --- Static file mounts ---------------------------------------------------

    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
    if (settings.web_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=settings.web_dir / "assets"), name="assets")

    # --- API routers ----------------------------------------------------------

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(router)
    app.include_router(v1_router)

    # --- SPA catch-all (MUST be registered last) ------------------------------

    @app.get("/", include_in_schema=False)
    @app.get("/{path:path}", include_in_schema=False)
    async def spa_catch_all(request: Request, path: str = ""):
        request_path = "/" + path.lstrip("/") if path else "/"

        # Don't intercept API, static, assets, or other mounted paths
        if request_path.startswith(("/api/", "/static/", "/assets/", "/docs", "/openapi.json", "/metrics", "/health", "/legacy", "/events/")):
            raise HTTPException(404)

        entry = settings.web_dir / "index.html"
        html_path = entry if entry.is_file() else settings.static_dir / "index.html"
        html = html_path.read_text(encoding="utf-8")

        html = inject_seo_meta(html, request_path, settings.public_origin)

        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    return app


app = create_app()
