"""
backend/app_factory.py

Application factory for WeatherGPT.

Creates and configures the FastAPI application instance, aggregates all
routers, installs global exception handlers, CORS, and structured logging.
"""

from __future__ import annotations

import logging
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _configure_logging(level: str = "INFO") -> None:
    """Configure root + application loggers with a structured format."""
    fmt = (
        "%(asctime)s | %(levelname)-8s | %(name)s | "
        "%(request_id)s | %(message)s"
    )

    class RequestIdFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if not hasattr(record, "request_id"):
                record.request_id = "-"
            return True

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%dT%H:%M:%S"))
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Quieten noisy third-party loggers
    for name in ("httpx", "httpcore", "uvicorn.access", "multipart"):
        logging.getLogger(name).setLevel(logging.WARNING)


logger = logging.getLogger("weathergpt")

# ---------------------------------------------------------------------------
# Request-ID middleware
# ---------------------------------------------------------------------------

class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request / log record / response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Make request_id available to log records in this context
        old_factory = logging.getLogRecordFactory()

        def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = old_factory(*args, **kwargs)
            record.request_id = request_id  # type: ignore[attr-defined]
            return record

        logging.setLogRecordFactory(record_factory)
        start = time.perf_counter()

        try:
            response = await call_next(request)
        finally:
            logging.setLogRecordFactory(old_factory)

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms:.1f}ms"
        logger.info(
            "%s %s → %s (%.1f ms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------

async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    logger.warning(
        "HTTP %s on %s %s – %s",
        exc.status_code,
        request.method,
        request.url.path,
        exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "detail": exc.detail,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    logger.warning("Validation error on %s: %s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": True,
            "status_code": 422,
            "detail": "Request validation failed",
            "errors": exc.errors(),
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    logger.error(
        "Unhandled exception on %s %s\n%s",
        request.method,
        request.url.path,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": True,
            "status_code": 500,
            "detail": "Internal server error",
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(
    *,
    title: str = "WeatherGPT API",
    version: str = "1.0.0",
    log_level: str = "INFO",
    enable_docs: bool = True,
) -> FastAPI:
    """
    Build and return a fully-configured FastAPI application.

    Routers aggregated from:
      - main.py          (weather, health, alerts, coastal …)
      - whatsapp_bot.py  (WhatsApp webhook)
      - webhooks.py      (broadcast weather-alert webhook)
    """
    _configure_logging(log_level)

    app = FastAPI(
        title=title,
        version=version,
        description=(
            "Production API for WeatherGPT – multilingual weather advisories, "
            "voice, WhatsApp, telephony and alert broadcasting for India."
        ),
        docs_url="/docs" if enable_docs else None,
        redoc_url="/redoc" if enable_docs else None,
        openapi_url="/openapi.json" if enable_docs else None,
    )

    # ---- Middleware -------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)

    # ---- Exception handlers -----------------------------------------------
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # ---- Routers ----------------------------------------------------------
    # Import inside the factory so that environment variables / side-effects
    # in those modules are evaluated only when the app is actually created.
    try:
        # main.py may expose `app` or individual routers; we prefer routers.
        # If main.py only defines an `app`, we re-mount its routes.
        import main as main_module

        if hasattr(main_module, "router"):
            app.include_router(main_module.router)
        elif hasattr(main_module, "app"):
            # Copy routes from the standalone app defined in main.py
            for route in main_module.app.routes:
                app.routes.append(route)
        else:
            logger.warning("main.py has no router or app – skipped")
    except ImportError as exc:
        logger.warning("Could not import main.py: %s", exc)

    try:
        from Whatsapp_bot import router as whatsapp_router
        app.include_router(whatsapp_router)
        # Optional static media mount for TTS audio replies
        if hasattr(__import__("Whatsapp_bot"), "mount_media_route"):
            from Whatsapp_bot import mount_media_route
            mount_media_route(app)
    except ImportError as exc:
        logger.warning("Could not import whatsapp_bot: %s", exc)

    try:
        from webhooks import router as webhooks_router
        app.include_router(webhooks_router)
    except ImportError as exc:
        logger.warning("Could not import webhooks: %s", exc)

    # ---- Startup / shutdown hooks ----------------------------------------
    @app.on_event("startup")
    async def _startup() -> None:
        logger.info("WeatherGPT application starting (v%s)", version)
        # Eagerly initialise shared services if they exist
        try:
            from weather_service import get_weather_service
            get_weather_service()
        except Exception:
            pass
        try:
            from voice_service import get_voice_service
            get_voice_service()
        except Exception:
            pass
        try:
            from webhooks import seed_demo_sessions
            seed_demo_sessions()
        except Exception:
            pass

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        logger.info("WeatherGPT application shutting down")
        try:
            from weather_service import get_weather_service
            await get_weather_service().aclose()
        except Exception:
            pass

    # ---- Health endpoint is expected from main.py; add a minimal one if absent
    if not any(getattr(r, "path", "") == "/health" for r in app.routes):
        @app.get("/health", tags=["System"])
        async def health() -> Dict[str, Any]:
            return {
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "service": "WeatherGPT",
                "version": version,
            }

    logger.info("FastAPI application created successfully")
    return app


# ---------------------------------------------------------------------------
# Convenience: allow `uvicorn backend.app_factory:app`
# ---------------------------------------------------------------------------
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app_factory:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )