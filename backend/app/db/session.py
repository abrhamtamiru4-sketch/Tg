"""
Async database session management.

Pattern:
    async with get_db() as db:
        result = await db.execute(select(User).where(User.id == 1))

Or via FastAPI dependency:
    @router.get("/")
    async def handler(db: AsyncSession = Depends(get_db_session)):
        ...
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.logging_config import get_logger

log = get_logger(__name__)

# Engine is created once and reused across the application lifetime
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        connect_args: dict = {}
        if settings.is_sqlite:
            connect_args["check_same_thread"] = False

        _engine = create_async_engine(
            settings.database_url,
            echo=settings.is_development,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args=connect_args,
        )
        log.info("database_engine_created", url=settings.database_url.split("@")[-1])
    return _engine


def get_session_factory() -> async_sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Context manager that yields a database session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    async with get_db() as session:
        yield session


async def create_all_tables() -> None:
    """Create all tables. For use in tests and initial dev setup."""
    from app.db.base import Base
    # Import all models to ensure they're registered
    import app.db.models  # noqa: F401
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("database_tables_created")


async def close_engine() -> None:
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
        log.info("database_engine_closed")
