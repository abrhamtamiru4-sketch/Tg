"""
Core system tests.

Covers:
- Configuration loading and validation
- Feature flags: enable, disable, toggle, callbacks
- Security: JWT encode/decode, password hashing, callback signing, idempotency
- Exceptions: hierarchy and metadata
- Capability registry: registration, availability, version checking
- Rate limiter: token bucket, sliding window
- Template engine: render, validate, extract variables
- Deduplication engine: exact hash, normalized, Jaccard, perceptual
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Test Config ───────────────────────────────────────────────

class TestSettings:
    """Config loads correctly from environment."""

    def test_default_timezone(self, monkeypatch):
        monkeypatch.setenv("BOT_TOKEN", "123456789:ABCdef_test_token_here_1234567890")
        monkeypatch.setenv("DEFAULT_TIMEZONE", "Africa/Addis_Ababa")
        from importlib import reload
        import app.core.config as cfg_module
        cfg_module.get_settings.cache_clear()
        settings = cfg_module.Settings()
        assert settings.default_timezone == "Africa/Addis_Ababa"

    def test_admin_id_list_parsing(self, monkeypatch):
        monkeypatch.setenv("BOT_TOKEN", "123456789:ABCdef_test_token_here_1234567890")
        monkeypatch.setenv("ADMIN_IDS", "111,222, 333 ,444")
        from app.core.config import Settings
        s = Settings()
        assert s.admin_id_list == [111, 222, 333, 444]

    def test_admin_id_list_empty(self, monkeypatch):
        monkeypatch.setenv("BOT_TOKEN", "123456789:ABCdef_test_token_here_1234567890")
        monkeypatch.setenv("ADMIN_IDS", "")
        from app.core.config import Settings
        s = Settings()
        assert s.admin_id_list == []

    def test_invalid_bot_token_raises(self):
        from app.core.config import Settings
        import pytest
        with pytest.raises(Exception):
            Settings(bot_token="invalid_no_colon")

    def test_dry_run_default_false(self, monkeypatch):
        monkeypatch.setenv("BOT_TOKEN", "123456789:ABCdef_test_token_here_1234567890")
        from app.core.config import Settings
        s = Settings()
        assert s.dry_run is False

    def test_sqlite_detection(self, monkeypatch):
        monkeypatch.setenv("BOT_TOKEN", "123456789:ABCdef_test_token_here_1234567890")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
        from app.core.config import Settings
        s = Settings()
        assert s.is_sqlite is True


# ── Test Feature Flags ────────────────────────────────────────

class TestFeatureFlags:
    """Feature flag system: toggle, callbacks, persistence."""

    def setup_method(self):
        from app.core.feature_flags import FeatureFlag, FeatureFlagRegistry
        self.registry = FeatureFlagRegistry()
        self.flag = FeatureFlag(
            name="TEST_FLAG",
            description="Test flag",
            default=False,
        )
        self.registry.register(self.flag)

    def test_initial_state_is_default(self):
        assert self.registry.is_enabled("TEST_FLAG") is False

    def test_enable(self):
        self.registry.enable("TEST_FLAG")
        assert self.registry.is_enabled("TEST_FLAG") is True

    def test_disable(self):
        self.registry.enable("TEST_FLAG")
        self.registry.disable("TEST_FLAG")
        assert self.registry.is_enabled("TEST_FLAG") is False

    def test_toggle(self):
        result = self.registry.toggle("TEST_FLAG")
        assert result is True
        result2 = self.registry.toggle("TEST_FLAG")
        assert result2 is False

    def test_reset_to_default(self):
        self.registry.enable("TEST_FLAG")
        self.flag.reset()
        assert self.registry.is_enabled("TEST_FLAG") is False  # back to default=False

    def test_callback_fires_on_change(self):
        fired = []
        self.registry.on_change("TEST_FLAG", lambda state: fired.append(state))
        self.registry.enable("TEST_FLAG")
        assert fired == [True]
        self.registry.disable("TEST_FLAG")
        assert fired == [True, False]

    def test_unknown_flag_raises(self):
        with pytest.raises(KeyError):
            self.registry.is_enabled("NONEXISTENT")

    def test_all_flags_returns_dict(self):
        all_flags = self.registry.all_flags()
        assert "TEST_FLAG" in all_flags
        assert "enabled" in all_flags["TEST_FLAG"]
        assert "description" in all_flags["TEST_FLAG"]

    def test_versioned_flag_with_api_version(self):
        from app.core.feature_flags import FeatureFlag
        flag = FeatureFlag(
            name="V_FLAG",
            description="Versioned",
            default=True,
            min_api_version="10.1",
        )
        self.registry.register(flag)
        assert flag.min_api_version == "10.1"


# ── Test Security ─────────────────────────────────────────────

class TestSecurity:
    """JWT, passwords, callback signing, idempotency."""

    def setup_method(self):
        import os
        os.environ.setdefault("BOT_TOKEN", "123456789:ABCdef_test_token_here_1234567890")

    def test_password_hash_and_verify(self):
        from app.core.security import hash_password, verify_password
        hashed = hash_password("supersecret123")
        assert hashed != "supersecret123"
        assert verify_password("supersecret123", hashed) is True
        assert verify_password("wrongpassword", hashed) is False

    def test_jwt_access_token_roundtrip(self):
        from app.core.security import create_access_token, decode_token
        token = create_access_token(subject=42, extra={"role": "admin"})
        payload = decode_token(token, expected_type="access")
        assert payload["sub"] == "42"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"

    def test_jwt_refresh_token_roundtrip(self):
        from app.core.security import create_refresh_token, decode_token
        token = create_refresh_token(subject=99)
        payload = decode_token(token, expected_type="refresh")
        assert payload["sub"] == "99"
        assert payload["type"] == "refresh"
        assert "jti" in payload

    def test_wrong_token_type_raises(self):
        from app.core.security import create_access_token, decode_token
        from app.core.exceptions import AuthenticationError
        token = create_access_token(subject=1)
        with pytest.raises(AuthenticationError):
            decode_token(token, expected_type="refresh")

    def test_tampered_token_raises(self):
        from app.core.security import create_access_token, decode_token
        from app.core.exceptions import AuthenticationError
        token = create_access_token(subject=1)
        bad_token = token[:-5] + "XXXXX"
        with pytest.raises(AuthenticationError):
            decode_token(bad_token)

    def test_callback_data_sign_and_verify(self):
        from app.core.security import sign_callback_data, verify_callback_data
        signed = sign_callback_data("action:publish:42")
        result = verify_callback_data(signed)
        assert result == "action:publish:42"

    def test_tampered_callback_data_raises(self):
        from app.core.security import sign_callback_data, verify_callback_data
        from app.core.exceptions import AuthenticationError
        signed = sign_callback_data("action:delete:1")
        # Tamper with the data part
        tampered = "action:delete:999|" + signed.split("|")[1]
        with pytest.raises(AuthenticationError):
            verify_callback_data(tampered)

    def test_unsigned_callback_data_raises(self):
        from app.core.security import verify_callback_data
        from app.core.exceptions import AuthenticationError
        with pytest.raises(AuthenticationError):
            verify_callback_data("no_pipe_separator_here")

    def test_idempotency_key_deterministic(self):
        from app.core.security import make_idempotency_key
        key1 = make_idempotency_key(post_id=1, channel_id=10, scheduled_at=1000000.0)
        key2 = make_idempotency_key(post_id=1, channel_id=10, scheduled_at=1000000.0)
        assert key1 == key2

    def test_idempotency_key_changes_with_different_ids(self):
        from app.core.security import make_idempotency_key
        key1 = make_idempotency_key(post_id=1, channel_id=10)
        key2 = make_idempotency_key(post_id=2, channel_id=10)
        assert key1 != key2

    def test_api_key_generate_and_verify(self):
        from app.core.security import generate_api_key, verify_api_key
        raw, hashed = generate_api_key()
        assert raw.startswith("tp_")
        assert verify_api_key(raw, hashed) is True
        assert verify_api_key("tp_wrong", hashed) is False

    def test_csrf_token_verify(self):
        from app.core.security import generate_csrf_token, verify_csrf_token
        token = generate_csrf_token()
        assert len(token) > 20
        assert verify_csrf_token(token, token) is True
        assert verify_csrf_token("different", token) is False


# ── Test Exceptions ───────────────────────────────────────────

class TestExceptions:
    """Exception hierarchy and metadata preservation."""

    def test_publisher_error_message(self):
        from app.core.exceptions import PublisherError
        exc = PublisherError("Something broke", code=42)
        assert "Something broke" in str(exc)
        assert exc.context["code"] == 42

    def test_telegram_rate_limit_error(self):
        from app.core.exceptions import TelegramRateLimitError
        exc = TelegramRateLimitError(retry_after=15)
        assert exc.retry_after == 15
        assert "15" in str(exc)

    def test_preflight_error_lists_checks(self):
        from app.core.exceptions import PreflightError
        exc = PreflightError(checks=["content_non_empty", "permissions"])
        assert "content_non_empty" in str(exc)
        assert exc.failed_checks == ["content_non_empty", "permissions"]

    def test_duplicate_post_error(self):
        from app.core.exceptions import DuplicatePostError
        exc = DuplicatePostError(similarity=0.95, original_id=123)
        assert exc.similarity == 0.95
        assert "95%" in str(exc)

    def test_feature_disabled_error(self):
        from app.core.exceptions import FeatureDisabledError
        exc = FeatureDisabledError("AI")
        assert "AI" in str(exc)

    def test_ssrf_error(self):
        from app.core.exceptions import SSRFError
        exc = SSRFError("http://192.168.1.1/secret")
        assert "192.168.1.1" in str(exc)


# ── Test Capability Registry ──────────────────────────────────

class TestCapabilityRegistry:
    """Bot API capability registration and availability checking."""

    def setup_method(self):
        from app.telegram.capability_registry import TelegramCapabilityRegistry
        self.registry = TelegramCapabilityRegistry(current_api_version="10.3")

    def test_send_message_is_available(self):
        assert self.registry.is_available("send_message") is True

    def test_rich_message_available_in_10_3(self):
        # Registered as min_bot_api_version="10.1", current is 10.3 → available
        assert self.registry.is_available("send_rich_message") is True

    def test_rich_message_unavailable_in_10_0(self):
        from app.telegram.capability_registry import TelegramCapabilityRegistry
        old_registry = TelegramCapabilityRegistry(current_api_version="10.0")
        assert old_registry.is_available("send_rich_message") is False

    def test_ephemeral_available_in_10_2(self):
        assert self.registry.is_available("send_ephemeral_message") is True

    def test_ephemeral_unavailable_in_10_1(self):
        from app.telegram.capability_registry import TelegramCapabilityRegistry
        old = TelegramCapabilityRegistry(current_api_version="10.1")
        assert old.is_available("send_ephemeral_message") is False

    def test_disabled_buttons_available_in_10_3(self):
        assert self.registry.is_available("disabled_buttons") is True

    def test_message_views_is_unsupported(self):
        assert self.registry.is_available("message_views") is False
        cap = self.registry.get("message_views")
        assert cap.fallback is not None  # should have a fallback suggestion

    def test_read_messages_is_unsupported(self):
        assert self.registry.is_available("read_messages") is False

    def test_matrix_returns_all(self):
        matrix = self.registry.matrix()
        assert len(matrix) > 20
        names = [r["capability"] for r in matrix]
        assert "send_message" in names
        assert "send_rich_message" in names
        assert "message_views" in names

    def test_unknown_capability_raises(self):
        with pytest.raises(KeyError):
            self.registry.get("totally_fake_method_xyz")

    def test_get_fallback(self):
        fallback = self.registry.get_fallback("message_views")
        assert fallback is not None
        assert len(fallback) > 5

    def test_version_comparison(self):
        assert self.registry._version_gte("10.3", "10.1") is True
        assert self.registry._version_gte("10.0", "10.1") is False
        assert self.registry._version_gte("10.3", "10.3") is True
        assert self.registry._version_gte("11.0", "10.3") is True


# ── Test Template Engine ──────────────────────────────────────

class TestTemplateEngine:
    """Jinja2 template rendering and validation."""

    def setup_method(self):
        from app.services.templates.engine import TemplateEngine
        self.engine = TemplateEngine()

    def test_simple_variable_substitution(self):
        rendered = self.engine.render("Hello {{title}}!", variables={"title": "World"})
        assert rendered == "Hello World!"

    def test_builtin_date_variable(self):
        rendered = self.engine.render("Year: {{year}}")
        import datetime
        assert str(datetime.datetime.now().year) in rendered

    def test_tracking_id_is_generated(self):
        rendered = self.engine.render("ID: {{tracking_id}}")
        assert "ID: " in rendered
        assert len(rendered) > 8

    def test_random_emoji_from_category(self):
        rendered = self.engine.render("{{random_emoji}}", context={"emoji_category": "ethiopia"})
        ethiopia_emojis = ["🇪🇹", "☕", "🌺", "🌍", "🦁", "🐘", "🌄", "🏔️"]
        assert any(e in rendered for e in ethiopia_emojis)

    def test_missing_variable_raises_validation_error(self):
        from app.core.exceptions import ContentValidationError
        with pytest.raises(ContentValidationError):
            self.engine.render("Hello {{undefined_var}}!")

    def test_syntax_error_raises_validation_error(self):
        from app.core.exceptions import ContentValidationError
        with pytest.raises(ContentValidationError):
            self.engine.render("{{unclosed")

    def test_validate_returns_errors_for_bad_syntax(self):
        errors = self.engine.validate("{{broken syntax here )")
        assert len(errors) > 0

    def test_validate_returns_empty_for_valid_template(self):
        errors = self.engine.validate("Hello {{title}}! Date: {{date}}")
        assert errors == []

    def test_extract_variables(self):
        variables = self.engine.extract_variables("{{title}} on {{date}} by {{author}}")
        assert "title" in variables
        assert "date" in variables
        assert "author" in variables

    def test_channel_name_in_context(self):
        rendered = self.engine.render(
            "Posting to {{channel_name}}",
            context={"channel_name": "@abuta_art"}
        )
        assert "@abuta_art" in rendered

    def test_multiple_variables(self):
        rendered = self.engine.render(
            "{{title}} — {{category}} {{random_emoji}}",
            variables={"title": "My Post", "category": "Art"},
        )
        assert "My Post" in rendered
        assert "Art" in rendered


# ── Test Deduplication Engine ─────────────────────────────────

class TestDeduplicationEngine:
    """Duplicate detection: exact, normalized, Jaccard, perceptual."""

    def setup_method(self):
        from app.services.content.deduplication import DeduplicationEngine
        self.engine = DeduplicationEngine()

    def test_content_hash_is_deterministic(self):
        h1 = self.engine.compute_content_hash("Hello World")
        h2 = self.engine.compute_content_hash("Hello World")
        assert h1 == h2

    def test_normalized_hash_ignores_case_and_spaces(self):
        h1 = self.engine.compute_content_hash("Hello World!!!")
        h2 = self.engine.compute_content_hash("  hello   world  ")
        # Same after normalization (punctuation removed, lowercased)
        assert h1 == h2

    def test_different_content_has_different_hash(self):
        h1 = self.engine.compute_content_hash("Digital art from Ethiopia")
        h2 = self.engine.compute_content_hash("Something completely different")
        assert h1 != h2

    @pytest.mark.asyncio
    async def test_no_duplicate_without_db(self):
        result = await self.engine.check_text("Brand new unique content xyz", db=None)
        assert result.is_duplicate is False
        assert result.method in ("none", "skip_empty")

    @pytest.mark.asyncio
    async def test_empty_text_skipped(self):
        result = await self.engine.check_text("", db=None)
        assert result.is_duplicate is False

    @pytest.mark.asyncio
    async def test_whitespace_only_skipped(self):
        result = await self.engine.check_text("   \n\t  ", db=None)
        assert result.is_duplicate is False

    def test_hamming_distance_identical(self):
        from app.services.content.deduplication import _hamming_distance
        assert _hamming_distance("deadbeef", "deadbeef") == 0

    def test_hamming_distance_different(self):
        from app.services.content.deduplication import _hamming_distance
        # deadbeef vs deadbee0 — differ in last nibble
        dist = _hamming_distance("deadbeef", "deadbee0")
        assert dist > 0

    def test_can_publish_anyway_is_always_true(self):
        from app.services.content.deduplication import DuplicateResult
        result = DuplicateResult(is_duplicate=True, similarity=1.0)
        assert result.can_publish_anyway is True  # Admin always has override


# ── Test Rate Limiter ─────────────────────────────────────────

class TestRateLimiter:
    """Token bucket and sliding window rate limiters."""

    def test_token_bucket_allows_first_request(self):
        from app.telegram.rate_limiter import _TokenBucket
        bucket = _TokenBucket(rate=1.0, capacity=5.0)

        async def run():
            await bucket.acquire()

        asyncio.run(run())  # Should not raise

    def test_rate_limiter_singleton(self):
        from app.telegram.rate_limiter import get_rate_limiter
        r1 = get_rate_limiter()
        r2 = get_rate_limiter()
        assert r1 is r2

    def test_handle_retry_after_blocks(self):
        from app.telegram.rate_limiter import TelegramRateLimiter
        limiter = TelegramRateLimiter()
        limiter.handle_retry_after("chat123", retry_after=10)
        assert "chat123" in limiter._blocked_until
        assert limiter._blocked_until["chat123"] > time.monotonic()

    def test_sliding_window_tracks_count(self):
        from app.telegram.rate_limiter import _SlidingWindow
        window = _SlidingWindow(max_count=5, window_seconds=60)

        async def run():
            for _ in range(3):
                await window.acquire()
            return len(window._times)

        count = asyncio.run(run())
        assert count == 3


# ── Test Source Worker SSRF Protection ───────────────────────

class TestSSRFProtection:
    """URL validation blocks private IP ranges."""

    def test_public_url_allowed(self):
        from app.workers.source_worker import _is_safe_url
        ok, reason = _is_safe_url("https://feeds.example.com/rss.xml")
        assert ok is True

    def test_localhost_blocked(self):
        from app.workers.source_worker import _is_safe_url
        ok, reason = _is_safe_url("http://localhost/admin")
        assert ok is False
        assert "private" in reason.lower() or "SSRF" in reason

    def test_private_ip_blocked(self):
        from app.workers.source_worker import _is_safe_url
        ok, reason = _is_safe_url("http://192.168.1.1/secret")
        assert ok is False

    def test_internal_10_network_blocked(self):
        from app.workers.source_worker import _is_safe_url
        ok, reason = _is_safe_url("http://10.0.0.1/data")
        assert ok is False

    def test_file_scheme_blocked(self):
        from app.workers.source_worker import _is_safe_url
        ok, reason = _is_safe_url("file:///etc/passwd")
        assert ok is False
        assert "Scheme" in reason

    def test_ftp_scheme_blocked(self):
        from app.workers.source_worker import _is_safe_url
        ok, reason = _is_safe_url("ftp://files.example.com/feed.xml")
        assert ok is False

    def test_malformed_url_blocked(self):
        from app.workers.source_worker import _is_safe_url
        ok, reason = _is_safe_url("not_a_url")
        assert ok is False


# ── Test Automation Rule Engine ───────────────────────────────

class TestRuleEngine:
    """WHEN/IF/THEN condition evaluation."""

    def test_trigger_matches_correct_type(self):
        from app.services.automation.rule_engine import RuleEngine, RuleContext
        engine = RuleEngine(db=None)
        trigger = {"type": "rss_update", "source_id": 5}
        context = RuleContext(
            trigger_type="rss_update",
            trigger_data={"source_id": 5},
        )
        assert engine._trigger_matches(trigger, context) is True

    def test_trigger_mismatches_different_type(self):
        from app.services.automation.rule_engine import RuleEngine, RuleContext
        engine = RuleEngine(db=None)
        trigger = {"type": "publish_success"}
        context = RuleContext(trigger_type="rss_update", trigger_data={})
        assert engine._trigger_matches(trigger, context) is False

    def test_condition_eq(self):
        from app.services.automation.rule_engine import RuleEngine, RuleContext, _compare
        assert _compare("technology", "eq", "technology") is True
        assert _compare("art", "eq", "technology") is False

    def test_condition_lt(self):
        from app.services.automation.rule_engine import _compare
        assert _compare(0.7, "lt", 0.8) is True
        assert _compare(0.9, "lt", 0.8) is False

    def test_condition_in(self):
        from app.services.automation.rule_engine import _compare
        assert _compare("en", "in", ["en", "am", "ar"]) is True
        assert _compare("zh", "in", ["en", "am", "ar"]) is False

    def test_condition_contains(self):
        from app.services.automation.rule_engine import _compare
        assert _compare("Hello World", "contains", "World") is True
        assert _compare("Hello", "contains", "World") is False

    def test_all_conditions_must_pass(self):
        from app.services.automation.rule_engine import RuleEngine, RuleContext
        engine = RuleEngine(db=None)
        conditions = [
            {"field": "category", "op": "eq", "value": "art"},
            {"field": "score", "op": "lt", "value": 0.8},
        ]
        context_pass = RuleContext(
            trigger_type="manual",
            post_data={"category": "art", "score": 0.5},
        )
        context_fail = RuleContext(
            trigger_type="manual",
            post_data={"category": "art", "score": 0.9},  # fails score check
        )
        assert engine._evaluate_conditions(conditions, context_pass) is True
        assert engine._evaluate_conditions(conditions, context_fail) is False

    def test_empty_conditions_pass(self):
        from app.services.automation.rule_engine import RuleEngine, RuleContext
        engine = RuleEngine(db=None)
        context = RuleContext(trigger_type="manual")
        assert engine._evaluate_conditions([], context) is True


# ── Test Preflight Validator ──────────────────────────────────

class TestPreflightValidator:
    """Pre-publish validation checks."""

    def test_validates_text_length(self):
        from app.services.publishing.preflight import PreflightValidator, TEXT_MAX_CHARS
        from app.db.models import Post, PostTarget, PostType, PostStatus

        validator = PreflightValidator(client=None)

        post = MagicMock(spec=Post)
        post.text = "A" * (TEXT_MAX_CHARS + 100)
        post.caption = None
        post.media = []
        post.reply_markup = None
        post.rich_message = None
        post.poll_data = None
        post.post_type = PostType.TEXT

        target = MagicMock(spec=PostTarget)
        target.channel_id = 1
        target.group_id = None
        target.custom_caption = None
        target.custom_reply_markup = None

        result = asyncio.run(validator.validate(
            post, target, "test_idem_key",
            skip_permission_check=True
        ))

        text_check = next((c for c in result.checks if c["name"] == "text_length"), None)
        assert text_check is not None
        assert text_check["passed"] is False

    def test_validates_caption_length(self):
        from app.services.publishing.preflight import PreflightValidator, CAPTION_MAX_CHARS
        from app.db.models import Post, PostTarget, PostType

        validator = PreflightValidator(client=None)

        post = MagicMock(spec=Post)
        post.text = None
        post.caption = "B" * (CAPTION_MAX_CHARS + 50)
        post.media = [MagicMock()]
        post.reply_markup = None
        post.rich_message = None
        post.poll_data = None
        post.post_type = PostType.PHOTO

        target = MagicMock(spec=PostTarget)
        target.channel_id = 1
        target.group_id = None
        target.custom_caption = None
        target.custom_reply_markup = None

        result = asyncio.run(validator.validate(
            post, target, "test_key",
            skip_permission_check=True
        ))

        caption_check = next((c for c in result.checks if c["name"] == "caption_length"), None)
        assert caption_check is not None
        assert caption_check["passed"] is False

    def test_empty_content_fails(self):
        from app.services.publishing.preflight import PreflightValidator
        from app.db.models import Post, PostTarget, PostType

        validator = PreflightValidator(client=None)
        post = MagicMock(spec=Post)
        post.text = None
        post.caption = None
        post.media = []
        post.reply_markup = None
        post.post_type = PostType.TEXT

        target = MagicMock(spec=PostTarget)
        target.channel_id = 1
        target.group_id = None
        target.custom_caption = None
        target.custom_reply_markup = None

        result = asyncio.run(validator.validate(post, target, "k", skip_permission_check=True))

        content_check = next((c for c in result.checks if c["name"] == "content_non_empty"), None)
        assert content_check is not None
        assert content_check["passed"] is False

    def test_valid_button_passes(self):
        result = PreflightValidator._validate_buttons({
            "inline_keyboard": [[
                {"text": "Click", "callback_data": "action:click:1"},
                {"text": "Link", "url": "https://example.com"},
            ]]
        })
        assert result[0] is True

    def test_oversized_callback_data_fails(self):
        result = PreflightValidator._validate_buttons({
            "inline_keyboard": [[
                {"text": "Bad", "callback_data": "x" * 70}  # > 64 chars
            ]]
        })
        assert result[0] is False
        assert len(result[1]) == 1
