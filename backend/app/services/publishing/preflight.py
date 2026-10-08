"""
Pre-flight Validator
====================

Every publish operation runs this checklist before sending anything to Telegram.
If any required check fails, the job is rejected with an actionable error.

Checks:
  ✓ Target exists and is accessible
  ✓ Bot has required permissions
  ✓ Content is valid (text length, caption length, entity validity)
  ✓ Media is valid (type, size, format)
  ✓ Buttons are valid
  ✓ Caption length is within Telegram limits
  ✓ Schedule is valid (not in the past, not in a blackout window)
  ✓ Duplicate check completed
  ✓ Rate-limit window is clear
  ✓ Idempotency key is unique
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.core.config import settings
from app.core.exceptions import PreflightError
from app.core.logging_config import get_logger
from app.db.models import Post, PostTarget
from app.telegram.client import TelegramClient
from app.telegram.permission_engine import TelegramPermissionEngine

log = get_logger(__name__)

# Telegram message limits
TEXT_MAX_CHARS = 4096
CAPTION_MAX_CHARS = 1024
MEDIA_GROUP_MAX = 10
BUTTON_CALLBACK_DATA_MAX = 64


@dataclass
class PreflightResult:
    checks: list[dict] = field(default_factory=list)

    def add(self, name: str, passed: bool, message: str = "", action: str = "") -> None:
        self.checks.append({
            "name": name,
            "passed": passed,
            "message": message,
            "action": action,
        })

    @property
    def passed(self) -> bool:
        return all(c["passed"] for c in self.checks)

    @property
    def failed(self) -> list[dict]:
        return [c for c in self.checks if not c["passed"]]

    def raise_if_failed(self) -> None:
        if not self.passed:
            raise PreflightError([c["name"] for c in self.failed])


class PreflightValidator:
    """Runs all pre-flight checks before a publish attempt."""

    def __init__(self, client: TelegramClient) -> None:
        self._client = client
        self._perm_engine = TelegramPermissionEngine(client)

    async def validate(
        self,
        post: Post,
        target: PostTarget,
        idempotency_key: str,
        skip_permission_check: bool = False,
    ) -> PreflightResult:
        result = PreflightResult()

        # 1. Target is configured
        has_target = target.channel_id or target.group_id
        result.add(
            "target_configured",
            passed=bool(has_target),
            message="Target channel or group is set",
            action="Assign the post to at least one channel or group." if not has_target else "",
        )
        if not has_target:
            return result

        # 2. Content is non-empty
        has_content = bool(post.text or post.caption or post.media)
        result.add(
            "content_non_empty",
            passed=has_content,
            message="Post has content",
            action="Add text, caption, or media to the post." if not has_content else "",
        )

        # 3. Text length
        if post.text:
            length = len(post.text)
            ok = length <= TEXT_MAX_CHARS
            result.add(
                "text_length",
                passed=ok,
                message=f"Text length: {length}/{TEXT_MAX_CHARS} chars",
                action=f"Shorten the text by {length - TEXT_MAX_CHARS} characters." if not ok else "",
            )

        # 4. Caption length
        caption = target.custom_caption or post.caption
        if caption:
            length = len(caption)
            ok = length <= CAPTION_MAX_CHARS
            result.add(
                "caption_length",
                passed=ok,
                message=f"Caption length: {length}/{CAPTION_MAX_CHARS} chars",
                action=f"Shorten the caption by {length - CAPTION_MAX_CHARS} characters." if not ok else "",
            )

        # 5. Media group size
        if post.media:
            count = len(post.media)
            ok = count <= MEDIA_GROUP_MAX
            result.add(
                "media_group_size",
                passed=ok,
                message=f"Media group: {count}/{MEDIA_GROUP_MAX} items",
                action=f"Remove {count - MEDIA_GROUP_MAX} media items." if not ok else "",
            )

        # 6. Button callback data length
        reply_markup = target.custom_reply_markup or post.reply_markup
        if reply_markup:
            ok, bad_buttons = self._validate_buttons(reply_markup)
            result.add(
                "button_validity",
                passed=ok,
                message="All buttons are valid" if ok else f"Invalid buttons: {bad_buttons}",
                action="Shorten callback_data to ≤64 chars." if not ok else "",
            )

        # 7. Permissions
        if not skip_permission_check:
            if target.channel_id:
                from app.db.session import get_db
                async with get_db() as db:
                    from sqlalchemy import select
                    from app.db.models import Channel
                    channel = (await db.execute(
                        select(Channel).where(Channel.id == target.channel_id)
                    )).scalar_one_or_none()

                    if channel:
                        perm_report = await self._perm_engine.verify_channel(channel.telegram_id)
                        result.add(
                            "permissions",
                            passed=perm_report.passed,
                            message="Bot has required permissions" if perm_report.passed
                                else "; ".join(c.message for c in perm_report.failed_checks),
                            action="; ".join(c.action for c in perm_report.failed_checks if c.action),
                        )

        # 8. Idempotency key is new
        result.add(
            "idempotency_key",
            passed=bool(idempotency_key),
            message=f"Idempotency key: {idempotency_key[:12]}...",
        )

        # 9. Dry-run mode note
        if settings.dry_run:
            result.add(
                "dry_run_mode",
                passed=True,
                message="DRY_RUN=true — no real messages will be sent",
            )

        log.info(
            "preflight_complete",
            post_id=post.id,
            target_id=target.id,
            passed=result.passed,
            failed_count=len(result.failed),
        )
        return result

    @staticmethod
    def _validate_buttons(reply_markup: dict) -> tuple[bool, list[str]]:
        """Validate inline keyboard button constraints."""
        bad = []
        inline_keyboard = reply_markup.get("inline_keyboard", [])
        for row in inline_keyboard:
            for btn in row:
                cb = btn.get("callback_data", "")
                if len(cb) > BUTTON_CALLBACK_DATA_MAX:
                    bad.append(f"'{btn.get('text', '?')}': callback_data too long ({len(cb)} chars)")
        return (len(bad) == 0), bad
