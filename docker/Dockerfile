# ══════════════════════════════════════════════════════════════
# Telegram Publisher — Production Dockerfile
# Multi-stage: builder → runtime
# Final image: ~180 MB (Alpine + Python)
# ══════════════════════════════════════════════════════════════

# ── Stage 1: Builder ─────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency spec first (layer cache)
COPY pyproject.toml .

# Install all dependencies into a prefix
RUN pip install --upgrade pip && \
    pip install --prefix=/install \
        aiogram==3.13.1 \
        fastapi uvicorn[standard] python-multipart \
        pydantic pydantic-settings \
        sqlalchemy[asyncio] alembic asyncpg aiosqlite \
        "celery[redis]" redis kombu \
        passlib[bcrypt] python-jose[cryptography] \
        APScheduler \
        httpx aiofiles \
        feedparser bleach Pillow imagehash \
        jinja2 langdetect \
        python-dotenv structlog tenacity \
        pytz shortuuid humanize xxhash croniter

# ── Stage 2: Runtime ─────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY backend/ ./backend/
COPY alembic.ini .

# Create non-root user
RUN useradd -m -u 1000 publisher && \
    mkdir -p /app/media /app/logs && \
    chown -R publisher:publisher /app

USER publisher

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

ENV PYTHONPATH=/app/backend \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
