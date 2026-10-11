"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import APP_ROOT, get_settings
from .db import dispose_engine, init_db, session_scope
from .middleware import AppMiddleware
from .migrations import run_migrations
from .web import render

log = logging.getLogger("office.main")

__version__ = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=os.environ.get("OFFICE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    settings = get_settings()
    settings.ensure_dirs()
    init_db()
    try:
        run_migrations()
    except Exception as exc:
        log.error("schema migration problem: %s", exc)
        raise

    from .bootstrap import ensure_initial_data

    with session_scope() as db:
        created = ensure_initial_data(db)
    if created.get("admin_password"):
        log.warning("first run: administrator password written to data/initial-admin.txt")

    scheduler = None
    if os.environ.get("OFFICE_SCHEDULER", "1") not in ("0", "false", "False"):
        try:
            from .scheduler import start_scheduler

            scheduler = start_scheduler()
        except Exception as exc:
            log.warning("scheduler did not start: %s", exc)

    yield

    if scheduler is not None:
        try:
            from .scheduler import stop_scheduler

            stop_scheduler()
        except Exception:
            pass
    dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_short_name,
        description="سامانه یکپارچه CRM و اتوماسیون اداری",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.add_middleware(AppMiddleware)
    app.mount("/static", StaticFiles(directory=str(APP_ROOT / "static")), name="static")

    # ---- routers -------------------------------------------------------
    from .routers import admin, auth, crm, dashboard, files, oa, reports

    # custom pages first so that e.g. /deals/board is not swallowed by /deals/{id}
    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(crm.router)
    app.include_router(oa.router)
    app.include_router(files.router)
    app.include_router(reports.router)
    app.include_router(admin.router)

    from . import entities  # noqa: F401  (registers the entities)
    from .crud import ENTITIES, build_router

    for entity in ENTITIES.values():
        app.include_router(build_router(entity))

    # ---- error pages ---------------------------------------------------
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            target = f"/login?next={request.url.path}"
            if request.headers.get("hx-request"):
                response = HTMLResponse("", status_code=401)
                response.headers["HX-Redirect"] = target
                return response
            return RedirectResponse(target, status_code=303)
        if request.url.path.startswith(("/api", "/static")):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        if request.headers.get("hx-request") and exc.status_code < 500:
            response = HTMLResponse(
                f'<div class="alert alert-error text-sm">{exc.detail}</div>',
                status_code=exc.status_code,
            )
            return response
        template = {403: "errors/403.html", 404: "errors/404.html"}.get(
            exc.status_code, "errors/generic.html"
        )
        return render(
            request, template,
            status_code=exc.status_code,
            detail=exc.detail,
            code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):  # pragma: no cover
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        if request.url.path.startswith(("/api", "/static")):
            return JSONResponse({"detail": "internal error"}, status_code=500)
        return render(
            request, "errors/generic.html",
            status_code=500, code=500,
            detail="خطای پیش‌بینی‌نشده در سامانه رخ داد. لطفاً به مدیر سامانه اطلاع دهید.",
        )

    # ---- health --------------------------------------------------------
    started_at = time.time()

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        from .migrations import check

        return {
            "status": "ok",
            "version": __version__,
            "uptime_seconds": int(time.time() - started_at),
            "database": check(),
        }

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return RedirectResponse("/static/favicon.svg", status_code=307)

    return app


app = create_app()


def run() -> None:                                        # pragma: no cover
    """``python -m app.main`` convenience entry point."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        workers=int(os.environ.get("OFFICE_WORKERS", "1")),
        log_level=os.environ.get("OFFICE_LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":                               # pragma: no cover
    run()
