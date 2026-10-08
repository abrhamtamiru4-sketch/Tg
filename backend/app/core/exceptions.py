"""
Application-wide exception hierarchy.

All domain errors are subclasses of PublisherError so callers
can catch a single type and still get structured metadata.
"""

from __future__ import annotations

from typing import Any


class PublisherError(Exception):
    """Base class for all application errors."""

    def __init__(self, message: str = "", **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def __str__(self) -> str:
        if self.context:
            ctx = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
            return f"{self.message} [{ctx}]"
        return self.message


# ── Feature flags ─────────────────────────────────────────────
class FeatureDisabledError(PublisherError):
    """Raised when a disabled feature is accessed."""

    def __init__(self, feature: str) -> None:
        super().__init__(f"Feature '{feature}' is disabled", feature=feature)


# ── Authentication & Authorization ────────────────────────────
class AuthenticationError(PublisherError):
    """Invalid credentials or expired token."""


class AuthorizationError(PublisherError):
    """Insufficient permissions for the requested action."""


class AdminNotAllowedError(AuthorizationError):
    """Telegram user is not in the admin allowlist."""

    def __init__(self, user_id: int) -> None:
        super().__init__(f"User {user_id} is not an administrator", user_id=user_id)


# ── Telegram API errors ───────────────────────────────────────
class TelegramError(PublisherError):
    """Base for all Telegram API related errors."""

    def __init__(self, message: str, error_code: int | None = None, **ctx: Any) -> None:
        super().__init__(message, error_code=error_code, **ctx)
        self.error_code = error_code


class TelegramPermissionError(TelegramError):
    """Bot lacks a required Telegram permission."""

    def __init__(self, chat_id: str | int, permission: str) -> None:
        super().__init__(
            f"Bot lacks '{permission}' in chat {chat_id}",
            chat_id=chat_id,
            permission=permission,
        )


class TelegramRateLimitError(TelegramError):
    """Telegram rate-limit (429) was hit."""

    def __init__(self, retry_after: int = 1) -> None:
        super().__init__(
            f"Telegram rate limit — retry after {retry_after}s",
            retry_after=retry_after,
        )
        self.retry_after = retry_after


class TelegramMediaError(TelegramError):
    """Invalid or unsupported media."""


class TelegramEntityError(TelegramError):
    """Malformed message entities."""


class TelegramChatNotFoundError(TelegramError):
    """Chat or channel could not be found."""

    def __init__(self, chat_id: str | int) -> None:
        super().__init__(f"Chat '{chat_id}' not found", chat_id=chat_id)


class TelegramBotNotAdminError(TelegramError):
    """Bot is not an administrator in the target chat."""

    def __init__(self, chat_id: str | int) -> None:
        super().__init__(f"Bot is not an admin in '{chat_id}'", chat_id=chat_id)


class TelegramCapabilityUnavailableError(TelegramError):
    """Requested capability is not available in current API version."""

    def __init__(self, capability: str, available_from: str | None = None) -> None:
        msg = f"Capability '{capability}' is not available"
        if available_from:
            msg += f" (requires Bot API {available_from})"
        super().__init__(msg, capability=capability, available_from=available_from)


# ── Publishing ────────────────────────────────────────────────
class PublishingError(PublisherError):
    """Something went wrong during publishing."""

    retryable: bool = False


class DuplicatePostError(PublishingError):
    """Duplicate content detected."""

    def __init__(self, similarity: float, original_id: int | None = None) -> None:
        super().__init__(
            f"Duplicate post (similarity={similarity:.0%})",
            similarity=similarity,
            original_id=original_id,
        )
        self.similarity = similarity


class PreflightError(PublishingError):
    """Pre-flight validation failed — do not attempt to publish."""

    def __init__(self, checks: list[str]) -> None:
        super().__init__(f"Pre-flight failed: {', '.join(checks)}", failed_checks=checks)
        self.failed_checks = checks


class IdempotencyViolationError(PublishingError):
    """Same idempotency key was already successfully published."""

    def __init__(self, key: str) -> None:
        super().__init__(f"Idempotency key already used: {key}", key=key)


# ── Queue / Jobs ──────────────────────────────────────────────
class JobNotFoundError(PublisherError):
    def __init__(self, job_id: str) -> None:
        super().__init__(f"Job '{job_id}' not found", job_id=job_id)


class QueueError(PublisherError):
    """Generic queue / worker error."""


# ── Content / Sources ─────────────────────────────────────────
class ContentValidationError(PublisherError):
    """Content failed validation checks."""


class SourceFetchError(PublisherError):
    """External source could not be fetched."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"Source fetch failed for '{url}': {reason}", url=url, reason=reason)


class SSRFError(PublisherError):
    """Blocked SSRF attempt in source URL."""

    def __init__(self, url: str) -> None:
        super().__init__(f"SSRF protection blocked: {url}", url=url)


# ── AI ────────────────────────────────────────────────────────
class AIError(PublisherError):
    """AI provider returned an error."""


class AIProviderNotConfiguredError(AIError):
    def __init__(self) -> None:
        super().__init__("AI provider is not configured. Set AI_PROVIDER and API key in .env")


# ── Media ─────────────────────────────────────────────────────
class MediaError(PublisherError):
    """Media processing or validation error."""


class MediaTooLargeError(MediaError):
    def __init__(self, size_bytes: int, max_bytes: int) -> None:
        super().__init__(
            f"Media too large: {size_bytes:,} bytes (max {max_bytes:,})",
            size_bytes=size_bytes,
            max_bytes=max_bytes,
        )


class UnsupportedMediaTypeError(MediaError):
    def __init__(self, media_type: str) -> None:
        super().__init__(f"Unsupported media type: {media_type}", media_type=media_type)


# ── Database ──────────────────────────────────────────────────
class NotFoundError(PublisherError):
    """Resource not found in the database."""

    def __init__(self, resource: str, id: Any) -> None:
        super().__init__(f"{resource} '{id}' not found", resource=resource, id=id)


class ConflictError(PublisherError):
    """Unique constraint violation."""
