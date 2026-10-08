"""
pytest configuration and shared fixtures.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# Test environment — must be set BEFORE any app imports
os.environ.setdefault("BOT_TOKEN", "123456789:ABCdef_test_token_here_1234567890")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_publisher.db")
os.environ.setdefault("ADMIN_IDS", "12345")
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("SECRET_KEY", "test_secret_key_not_for_production_32chars_min")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")  # Separate test DB
os.environ.setdefault("LOG_LEVEL", "WARNING")  # Quiet during tests


@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the entire test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    """Create all tables once before any tests run."""
    from app.db.session import create_all_tables
    await create_all_tables()
    yield
    # Cleanup: remove test database
    if os.path.exists("./test_publisher.db"):
        os.remove("./test_publisher.db")


@pytest.fixture
def anyio_backend():
    return "asyncio"
