"""
FastAPI Application
===================

Starts the API server. The bot runs in a separate process (bot_main.py).
Workers run via Celery (worker_main.py).

Endpoints:
  /api/v1/*      — REST API
  /webhook       — Telegram webhook receiver
  /health        — Health check
  /ready         — Readiness probe
  /version       — Version info
  /docs          — Swagger UI (development only)
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging_config import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    log.info("api_starting", environment=settings.environment, dry_run=settings.dry_run)

    # Database
    from app.db.session import create_all_tables, get_engine
    get_engine()  # Initialize connection pool
    if settings.is_development or settings.is_sqlite:
        await create_all_tables()
        log.info("database_tables_ensured")

    # Telegram client
    from app.telegram.client import create_client
    client = create_client()
    try:
        me = await client.get_me()
        log.info("telegram_connected", bot_username=me.username)
    except Exception as exc:
        log.error("telegram_connect_failed", error=str(exc))

    yield

    # Shutdown
    log.info("api_shutting_down")
    from app.db.session import close_engine
    await close_engine()


# ── Application ────────────────────────────────────────────────

app = FastAPI(
    title="Telegram Publisher API",
    description="Production-grade Telegram Publishing Platform",
    version="1.0.0",
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    lifespan=lifespan,
)

# ── Middleware ─────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not settings.is_development:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Add X-Request-ID header and log all requests."""
    import uuid
    request_id = str(uuid.uuid4())[:8]
    start = time.monotonic()
    response = await call_next(request)
    duration = (time.monotonic() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    log.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=f"{duration:.1f}",
        request_id=request_id,
    )
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if not settings.is_development:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ── Global exception handler ──────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


# ── Health endpoints ───────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "dry_run": settings.dry_run}


@app.get("/ready", tags=["Health"])
async def readiness():
    checks = {}

    # Database
    try:
        from app.db.session import get_db
        from sqlalchemy import text
        async with get_db() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    # Redis
    try:
        import redis.asyncio as redis
        r = redis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"

    # Telegram
    try:
        from app.telegram.client import get_client
        await get_client().get_me()
        checks["telegram"] = "ok"
    except Exception as exc:
        checks["telegram"] = f"error: {exc}"

    all_ok = checks.get("database") == "ok" and checks.get("telegram") == "ok"
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ready" if all_ok else "not_ready", "checks": checks},
    )


@app.get("/version", tags=["Health"])
async def version():
    from app.telegram.capability_registry import get_registry
    registry = get_registry()
    return {
        "version": "1.0.0",
        "telegram_api_version": settings.telegram_api_version,
        "environment": settings.environment,
        "dry_run": settings.dry_run,
        "capabilities_total": len(registry.matrix()),
        "capabilities_available": sum(1 for c in registry.matrix() if c["available"]),
    }


# ── Webhook endpoint ───────────────────────────────────────────

@app.post(settings.webhook_path, tags=["Telegram"])
async def telegram_webhook(request: Request):
    """Receive and process Telegram updates via webhook."""
    from app.core.security import validate_webhook_secret

    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not validate_webhook_secret(secret):
        log.warning("webhook_invalid_secret", ip=request.client.host)
        return JSONResponse(status_code=403, content={"detail": "Invalid secret"})

    body = await request.json()

    # Process update through aiogram dispatcher
    try:
        from aiogram.types import Update
        from app.bot_main import dp, bot
        update = Update.model_validate(body)
        await dp.feed_update(bot, update)
    except Exception as exc:
        log.error("webhook_processing_error", error=str(exc))

    return JSONResponse(content={"ok": True})


# ── API Routers ────────────────────────────────────────────────

API_PREFIX = "/api/v1"

from app.api.routers import (
    auth, channels, posts, scheduler, media,
    templates, campaigns, analytics, automation,
    sources, settings as settings_router,
    capabilities,
)

app.include_router(auth.router, prefix=API_PREFIX + "/auth", tags=["Auth"])
app.include_router(channels.router, prefix=API_PREFIX + "/channels", tags=["Channels"])
app.include_router(posts.router, prefix=API_PREFIX + "/posts", tags=["Posts"])
app.include_router(scheduler.router, prefix=API_PREFIX + "/scheduler", tags=["Scheduler"])
app.include_router(media.router, prefix=API_PREFIX + "/media", tags=["Media"])
app.include_router(templates.router, prefix=API_PREFIX + "/templates", tags=["Templates"])
app.include_router(campaigns.router, prefix=API_PREFIX + "/campaigns", tags=["Campaigns"])
app.include_router(analytics.router, prefix=API_PREFIX + "/analytics", tags=["Analytics"])
app.include_router(automation.router, prefix=API_PREFIX + "/automation", tags=["Automation"])
app.include_router(sources.router, prefix=API_PREFIX + "/sources", tags=["Sources"])
app.include_router(settings_router.router, prefix=API_PREFIX + "/settings", tags=["Settings"])
app.include_router(capabilities.router, prefix=API_PREFIX + "/capabilities", tags=["Capabilities"])
