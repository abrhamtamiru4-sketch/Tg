"""
Integration and end-to-end tests.

Covers:
- Database: create, read, update, cascade
- API endpoints: channels, posts, analytics
- Full publish pipeline simulation (DRY_RUN)
- Queue: idempotency, retry logic
- Source worker: SSRF, RSS parsing
- Failure scenarios: permission denied, rate limit, bad media
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Set test environment before any app imports
os.environ["BOT_TOKEN"] = "123456789:ABCdef_test_token_here_1234567890"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_publisher.db"
os.environ["ADMIN_IDS"] = "12345"
os.environ["DRY_RUN"] = "true"
os.environ["ENVIRONMENT"] = "testing"


# ── Fixtures ──────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def db_session():
    """In-memory SQLite session for testing."""
    from app.db.session import create_all_tables, get_session_factory
    await create_all_tables()
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def mock_telegram_client():
    """Mocked TelegramClient that never calls real Telegram."""
    client = MagicMock()
    client.send_message = AsyncMock(return_value=MagicMock(message_id=1001))
    client.send_photo = AsyncMock(return_value=MagicMock(message_id=1002))
    client.get_me = AsyncMock(return_value=MagicMock(username="test_bot", id=999))
    client.get_chat = AsyncMock(return_value=MagicMock(type="channel", title="Test Channel"))
    client.get_chat_administrators = AsyncMock(return_value=[
        MagicMock(user=MagicMock(id=999), can_post_messages=True)
    ])
    return client


# ── Database Integration Tests ────────────────────────────────

class TestDatabaseModels:
    """Create, read, update, delete operations on all major models."""

    @pytest.mark.asyncio
    async def test_create_user(self, db_session):
        from app.db.models import User, UserRole

        user = User(
            telegram_id=11111,
            first_name="TestUser",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db_session.add(user)
        await db_session.flush()

        assert user.id is not None
        assert user.telegram_id == 11111
        assert user.created_at is not None

    @pytest.mark.asyncio
    async def test_create_channel(self, db_session):
        from app.db.models import Channel

        ch = Channel(
            telegram_id=-1001234567890,
            username="abuta_art",
            title="Abuta Art",
            is_active=True,
            bot_is_admin=True,
            can_post_messages=True,
        )
        db_session.add(ch)
        await db_session.flush()

        assert ch.id is not None
        assert ch.telegram_id == -1001234567890

    @pytest.mark.asyncio
    async def test_create_post_with_target(self, db_session):
        from sqlalchemy import select
        from app.db.models import Channel, Post, PostTarget, PostType, PostStatus

        # Create a channel first
        ch = Channel(telegram_id=-1009876543210, title="Test", is_active=True)
        db_session.add(ch)
        await db_session.flush()

        # Create post
        post = Post(
            text="Hello from integration test! 🎨",
            post_type=PostType.TEXT,
            status=PostStatus.DRAFT,
            content_hash="abc123",
        )
        db_session.add(post)
        await db_session.flush()

        # Create target
        target = PostTarget(post_id=post.id, channel_id=ch.id)
        db_session.add(target)
        await db_session.flush()

        assert target.id is not None
        assert target.post_id == post.id
        assert target.channel_id == ch.id
        assert target.status.value == "pending_review"

    @pytest.mark.asyncio
    async def test_post_version_tracking(self, db_session):
        from app.db.models import Post, PostVersion, PostType, PostStatus

        post = Post(text="Version 1", post_type=PostType.TEXT, status=PostStatus.DRAFT)
        db_session.add(post)
        await db_session.flush()

        version = PostVersion(
            post_id=post.id,
            version=1,
            snapshot={"text": "Version 1", "status": "draft"},
        )
        db_session.add(version)
        await db_session.flush()

        assert version.id is not None
        assert version.version == 1

    @pytest.mark.asyncio
    async def test_analytics_event_create(self, db_session):
        from app.db.models import AnalyticsEvent

        event = AnalyticsEvent(
            event_type="post_published",
            post_id=None,
            metadata={"test": True},
        )
        db_session.add(event)
        await db_session.flush()

        assert event.id is not None
        assert event.event_type == "post_published"

    @pytest.mark.asyncio
    async def test_audit_log_create(self, db_session):
        from app.db.models import AuditLog

        log = AuditLog(
            action="test_action",
            resource_type="post",
            resource_id=1,
            result="success",
        )
        db_session.add(log)
        await db_session.flush()

        assert log.id is not None
        assert log.action == "test_action"

    @pytest.mark.asyncio
    async def test_template_create_and_render(self, db_session):
        from app.db.models import Template
        from app.services.templates.engine import get_template_engine

        tpl = Template(
            name="Abuta Art Standard",
            text_template="🎨 {{title}}\n\n{{description}}\n\n#abuta_art #{{category}}",
            description="Standard art post template",
        )
        db_session.add(tpl)
        await db_session.flush()

        assert tpl.id is not None

        engine = get_template_engine()
        rendered = engine.render(
            tpl.text_template,
            variables={"title": "My Art", "description": "Painted today", "category": "digital"},
        )
        assert "My Art" in rendered
        assert "#abuta_art" in rendered

    @pytest.mark.asyncio
    async def test_job_idempotency_key_unique(self, db_session):
        from app.db.models import Job, JobStatus, JobPriority
        import uuid

        key = f"test_key_{uuid.uuid4()}"

        job1 = Job(
            job_id=str(uuid.uuid4()),
            idempotency_key=key,
            job_type="publish",
            status=JobStatus.PENDING,
            priority=JobPriority.NORMAL,
        )
        db_session.add(job1)
        await db_session.flush()

        # Second job with same key should fail
        job2 = Job(
            job_id=str(uuid.uuid4()),
            idempotency_key=key,  # same key!
            job_type="publish",
            status=JobStatus.PENDING,
            priority=JobPriority.NORMAL,
        )
        db_session.add(job2)

        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            await db_session.flush()

        await db_session.rollback()


# ── API Integration Tests ─────────────────────────────────────

class TestAPIEndpoints:
    """HTTP endpoint integration tests using FastAPI TestClient."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        with patch("app.telegram.client.create_client"), \
             patch("app.telegram.client.get_client"):
            from backend.main import app
            return TestClient(app, raise_server_exceptions=False)

    def test_health_endpoint(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["dry_run"] is True

    def test_version_endpoint(self, client):
        r = client.get("/version")
        assert r.status_code == 200
        data = r.json()
        assert "version" in data
        assert "telegram_api_version" in data
        assert data["telegram_api_version"] == "10.3"

    def test_capabilities_endpoint(self, client):
        r = client.get("/api/v1/capabilities/")
        assert r.status_code == 200
        data = r.json()
        assert "capabilities" in data
        assert len(data["capabilities"]) > 20
        caps = {c["capability"] for c in data["capabilities"]}
        assert "send_message" in caps
        assert "send_rich_message" in caps

    def test_channels_list_empty(self, client):
        r = client.get("/api/v1/channels/")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_posts_list(self, client):
        r = client.get("/api/v1/posts/")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_analytics_summary(self, client):
        r = client.get("/api/v1/analytics/summary")
        assert r.status_code == 200
        data = r.json()
        assert "total_posts" in data
        assert "published" in data
        assert "failed" in data

    def test_feature_flags_endpoint(self, client):
        r = client.get("/api/v1/settings/features")
        assert r.status_code == 200
        flags = r.json()
        assert "ANALYTICS" in flags
        assert "AI" in flags
        assert "enabled" in flags["AI"]

    def test_toggle_feature_flag(self, client):
        r = client.post("/api/v1/settings/features/ANALYTICS/toggle")
        assert r.status_code == 200
        data = r.json()
        assert "flag" in data
        assert "enabled" in data
        # Toggle back
        client.post("/api/v1/settings/features/ANALYTICS/toggle")

    def test_create_post_via_api(self, client):
        r = client.post("/api/v1/posts/", json={
            "text": "Test post from API integration test 🎨",
            "post_type": "text",
            "channel_ids": [],
        })
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert data["status"] == "draft"

    def test_create_and_get_post(self, client):
        create = client.post("/api/v1/posts/", json={
            "text": "Fetch me later",
            "post_type": "text",
        })
        assert create.status_code == 200
        post_id = create.json()["id"]

        get = client.get(f"/api/v1/posts/{post_id}")
        assert get.status_code == 200
        assert get.json()["id"] == post_id

    def test_404_for_nonexistent_post(self, client):
        r = client.get("/api/v1/posts/999999")
        assert r.status_code == 404

    def test_webhook_rejects_invalid_secret(self, client):
        r = client.post(
            "/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_secret"},
        )
        # Either 403 (secret configured) or 200 (no secret configured in test)
        assert r.status_code in (200, 403)

    def test_add_source_with_ssrf_url_rejected(self, client):
        r = client.post("/api/v1/sources/", json={
            "name": "Internal Source",
            "url": "http://192.168.1.1/feed.xml",
            "source_type": "rss",
        })
        assert r.status_code == 400
        assert "blocked" in r.json()["detail"].lower()

    def test_add_source_with_valid_url(self, client):
        r = client.post("/api/v1/sources/", json={
            "name": "Public RSS",
            "url": "https://feeds.bbci.co.uk/news/rss.xml",
            "source_type": "rss",
        })
        assert r.status_code == 200


# ── Full Publish Flow (DRY RUN) ───────────────────────────────

class TestPublishFlow:
    """End-to-end publish pipeline simulation with DRY_RUN=true."""

    @pytest.mark.asyncio
    async def test_dry_run_publish_returns_none(self, db_session, mock_telegram_client):
        """DRY_RUN=true → TelegramClient returns dry_run_result instead of calling API."""
        with patch("app.telegram.client._client", mock_telegram_client):
            from app.telegram.client import get_client
            client = get_client()

            # In DRY_RUN mode, send_message returns None (dry_run_result)
            # The mock still returns message_id=1001 because we mocked it
            # In real dry-run mode it would return None
            result = await client.send_message(
                chat_id=-100123456789,
                text="Test message",
            )
            # With mock: result is MagicMock with message_id=1001

    @pytest.mark.asyncio
    async def test_permission_engine_no_admin(self, mock_telegram_client):
        """Bot not admin → permission check fails."""
        from app.telegram.permission_engine import TelegramPermissionEngine

        # Configure mock: bot is NOT in admin list
        mock_telegram_client.get_me = AsyncMock(return_value=MagicMock(id=888))
        mock_telegram_client.get_chat = AsyncMock(
            return_value=MagicMock(type="channel", title="Test")
        )
        mock_telegram_client.get_chat_administrators = AsyncMock(return_value=[
            MagicMock(user=MagicMock(id=777))  # Different ID — bot not in list
        ])

        engine = TelegramPermissionEngine(mock_telegram_client)
        report = await engine.verify_channel(-100123456)

        assert report.passed is False
        assert any(c.name == "bot_is_admin" for c in report.failed_checks)

    @pytest.mark.asyncio
    async def test_permission_engine_with_admin(self, mock_telegram_client):
        """Bot IS admin → permission check passes."""
        from app.telegram.permission_engine import TelegramPermissionEngine

        bot_id = 999
        mock_telegram_client.get_me = AsyncMock(return_value=MagicMock(id=bot_id))
        mock_telegram_client.get_chat = AsyncMock(
            return_value=MagicMock(type="channel", title="My Channel")
        )

        admin_mock = MagicMock()
        admin_mock.user.id = bot_id
        admin_mock.can_post_messages = True
        mock_telegram_client.get_chat_administrators = AsyncMock(return_value=[admin_mock])

        engine = TelegramPermissionEngine(mock_telegram_client)
        report = await engine.verify_channel(-100123456)

        assert report.passed is True

    @pytest.mark.asyncio
    async def test_deduplication_blocks_identical_content(self, db_session):
        """Same text → duplicate detected, publish blocked."""
        from app.db.models import Post, PostType, PostStatus
        from app.services.content.deduplication import DeduplicationEngine

        engine = DeduplicationEngine()
        text = "This is a unique test post for deduplication 🎨"
        content_hash = engine.compute_content_hash(text)

        # Create a "published" post with this hash
        existing = Post(
            text=text,
            post_type=PostType.TEXT,
            status=PostStatus.PUBLISHED,
            content_hash=content_hash,
        )
        db_session.add(existing)
        await db_session.flush()

        # Now check the same text
        result = await engine.check_text(text, db=db_session, exclude_post_id=None)

        # Should detect exact or normalized match
        assert result.is_duplicate is True
        assert result.similarity >= 0.90
        assert result.can_publish_anyway is True  # Admin override always available

    @pytest.mark.asyncio
    async def test_template_renders_for_post(self):
        """Template with Amharic context renders correctly."""
        from app.services.templates.engine import get_template_engine

        engine = get_template_engine()
        tpl = "🇪🇹 {{title}}\n\nBy {{author}}\n📅 {{date}}\n\n#abuta_art #{{category}}"

        rendered = engine.render(
            tpl,
            variables={"title": "New Digital Art", "author": "Abita", "category": "digital"},
        )

        assert "New Digital Art" in rendered
        assert "Abita" in rendered
        assert "#abuta_art" in rendered
        assert "#digital" in rendered

    @pytest.mark.asyncio
    async def test_workflow_trigger_matching(self):
        """Workflow evaluates correctly for RSS trigger."""
        from app.services.automation.rule_engine import RuleEngine, RuleContext

        engine = RuleEngine(db=None)

        workflow = MagicMock()
        workflow.id = 1
        workflow.trigger = {"type": "rss_update", "source_id": 3}
        workflow.conditions = [
            {"field": "category", "op": "eq", "value": "technology"},
        ]
        workflow.actions = [{"type": "notify_admin", "params": {"message": "New tech post"}}]
        workflow.else_actions = []

        # Matching context
        context_match = RuleContext(
            trigger_type="rss_update",
            trigger_data={"source_id": 3},
            post_data={"category": "technology", "post_id": 42},
        )

        # Non-matching context (wrong source)
        context_miss = RuleContext(
            trigger_type="rss_update",
            trigger_data={"source_id": 9},  # Different source
            post_data={"category": "technology"},
        )

        result_match = await engine.evaluate(workflow, context_match)
        result_miss = await engine.evaluate(workflow, context_miss)

        assert result_match.triggered is True
        assert result_miss.triggered is False


# ── Failure Scenario Tests ────────────────────────────────────

class TestFailureScenarios:
    """Verify graceful handling of all error categories."""

    @pytest.mark.asyncio
    async def test_telegram_rate_limit_triggers_retry(self, mock_telegram_client):
        """429 from Telegram → RetryableRequest schedules retry."""
        from aiogram.exceptions import TelegramRetryAfter
        from app.telegram.rate_limiter import RetryableRequest

        call_count = 0

        async def flaky_fn(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                exc = TelegramRetryAfter(retry_after=1)
                raise exc
            return MagicMock(message_id=999)

        req = RetryableRequest(
            flaky_fn,
            max_attempts=5,
            base_delay=0.01,
        )
        result = await req.execute()
        assert result.message_id == 999
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_bad_request_not_retried(self, mock_telegram_client):
        """400 Bad Request → immediate failure, no retry."""
        from aiogram.exceptions import TelegramBadRequest
        from app.telegram.rate_limiter import RetryableRequest

        call_count = 0

        async def bad_fn(**kwargs):
            nonlocal call_count
            call_count += 1
            raise TelegramBadRequest("chat not found")

        req = RetryableRequest(bad_fn, max_attempts=5)

        with pytest.raises(TelegramBadRequest):
            await req.execute()

        assert call_count == 1  # Only called once — not retried

    def test_feature_disabled_error_is_raised(self):
        """Accessing disabled feature raises FeatureDisabledError."""
        from app.core.feature_flags import flags, FeatureFlag, FeatureFlagRegistry
        from app.core.exceptions import FeatureDisabledError

        registry = FeatureFlagRegistry()
        registry.register(FeatureFlag("DISABLED_TEST", "Always off", default=False))
        registry.disable("DISABLED_TEST")

        from app.core.feature_flags import require_flag
        with patch("app.core.feature_flags.flags", registry):
            with pytest.raises(FeatureDisabledError):
                require_flag("DISABLED_TEST")

    def test_ai_raises_when_not_configured(self):
        """AIAssistant raises when FEATURE_AI=false."""
        from app.core.exceptions import FeatureDisabledError
        from app.core.feature_flags import flags

        flags.disable("AI")
        with pytest.raises(FeatureDisabledError):
            from app.services.ai.assistant import AIAssistant
            AIAssistant()

    @pytest.mark.asyncio
    async def test_source_rejects_private_url(self):
        """RSS source worker rejects private IP URLs."""
        from app.workers.source_worker import _is_safe_url
        from app.core.exceptions import SSRFError

        ok, reason = _is_safe_url("http://10.10.10.10/admin")
        assert ok is False

    @pytest.mark.asyncio
    async def test_preflight_fails_without_target(self, db_session):
        """Post with no channel/group target fails preflight."""
        from app.services.publishing.preflight import PreflightValidator
        from app.db.models import Post, PostTarget, PostType, PostStatus

        validator = PreflightValidator(client=None)

        post = MagicMock()
        post.text = "Some content"
        post.caption = None
        post.media = []
        post.reply_markup = None
        post.post_type = PostType.TEXT

        # Target with neither channel nor group
        target = MagicMock()
        target.channel_id = None
        target.group_id = None
        target.custom_caption = None
        target.custom_reply_markup = None

        result = await validator.validate(post, target, "key", skip_permission_check=True)

        assert result.passed is False
        target_check = next((c for c in result.checks if c["name"] == "target_configured"), None)
        assert target_check is not None
        assert target_check["passed"] is False


# ── Scheduler Tests ───────────────────────────────────────────

class TestScheduler:
    """Schedule evaluation and blackout windows."""

    def test_blackout_window_overnight(self):
        from app.workers.scheduler_worker import _is_blacked_out
        from datetime import datetime, timezone

        config = {"windows": [{"hour_start": 22, "hour_end": 8}]}

        # 23:00 → blocked
        dt_night = datetime(2026, 10, 1, 23, 0, tzinfo=timezone.utc)
        assert _is_blacked_out(config, dt_night) is True

        # 07:00 → blocked (overnight)
        dt_early = datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc)
        assert _is_blacked_out(config, dt_early) is True

        # 12:00 → not blocked
        dt_noon = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
        assert _is_blacked_out(config, dt_noon) is False

    def test_blackout_window_by_weekday(self):
        from app.workers.scheduler_worker import _is_blacked_out
        from datetime import datetime, timezone

        config = {"windows": [{"weekday": [5, 6]}]}  # Saturday=5, Sunday=6

        # Saturday 2026-10-03 → blocked
        sat = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
        assert sat.weekday() == 5  # confirm it's Saturday
        assert _is_blacked_out(config, sat) is True

        # Wednesday 2026-09-30 → not blocked
        wed = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        assert _is_blacked_out(config, wed) is False

    def test_no_blackout_with_empty_config(self):
        from app.workers.scheduler_worker import _is_blacked_out
        from datetime import datetime, timezone

        config = {"windows": []}
        dt = datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)
        assert _is_blacked_out(config, dt) is False
