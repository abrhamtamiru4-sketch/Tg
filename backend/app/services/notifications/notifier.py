"""
Notification Service
====================

Sends alerts to administrators via:
  1. Telegram DM (primary — instant)
  2. Database (secondary — shown in dashboard)

Events that trigger notifications:
  - publish success / failure
  - permission problems
  - rate limits exceeded
  - source fetch failures
  - AI failures
  - queue failures / dead jobs
  - suspicious activity
  - campaign completion
  - system health issues
"""

from __future__ import annotations

from typing import Literal

from app.core.config import settings
from app.core.logging_config import get_logger

log = get_logger(__name__)

NotificationLevel = Literal["info", "warning", "error", "critical"]

LEVEL_EMOJI: dict[str, str] = {
    "info": "ℹ️",
    "warning": "⚠️",
    "error": "❌",
    "critical": "🚨",
}


class Notifier:
    """Sends structured notifications to all configured admin recipients."""

    def __init__(self) -> None:
        self._admin_ids = settings.admin_id_list

    async def notify_all(
        self,
        level: NotificationLevel,
        title: str,
        body: str = "",
        action_url: str | None = None,
    ) -> None:
        """Send to all admins."""
        for admin_id in self._admin_ids:
            await self.notify_user(admin_id, level, title, body, action_url)

    async def notify_user(
        self,
        telegram_id: int,
        level: NotificationLevel,
        title: str,
        body: str = "",
        action_url: str | None = None,
    ) -> None:
        """Send notification to a specific Telegram user and persist to DB."""
        # 1. Persist to database
        await self._persist(telegram_id, level, title, body, action_url)

        # 2. Send Telegram DM
        await self._send_telegram(telegram_id, level, title, body, action_url)

    async def _send_telegram(
        self,
        telegram_id: int,
        level: NotificationLevel,
        title: str,
        body: str,
        action_url: str | None,
    ) -> None:
        try:
            from app.telegram.client import get_client
            client = get_client()

            emoji = LEVEL_EMOJI.get(level, "📌")
            text = f"{emoji} <b>{title}</b>"
            if body:
                text += f"\n\n{body}"

            markup = None
            if action_url:
                from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
                markup = InlineKeyboardMarkup(
                    inline_keyboard=[[
                        InlineKeyboardButton(text="Open Dashboard", url=action_url)
                    ]]
                )

            await client.send_message(
                chat_id=telegram_id,
                text=text,
                reply_markup=markup,
                disable_notification=(level == "info"),
            )
        except Exception as exc:
            log.warning("notification_send_failed", telegram_id=telegram_id, error=str(exc))

    async def _persist(
        self,
        telegram_id: int,
        level: NotificationLevel,
        title: str,
        body: str,
        action_url: str | None,
    ) -> None:
        """Store notification in the database for dashboard display."""
        try:
            from sqlalchemy import select
            from app.db.models import Notification, User
            from app.db.session import get_db

            async with get_db() as db:
                user = (await db.execute(
                    select(User).where(User.telegram_id == telegram_id)
                )).scalar_one_or_none()

                if user:
                    db.add(Notification(
                        recipient_id=user.id,
                        level=level,
                        title=title,
                        body=body,
                        action_url=action_url,
                        sent_via_telegram=True,
                    ))
                    await db.commit()
        except Exception as exc:
            log.warning("notification_persist_failed", error=str(exc))

    # ── Pre-built notification templates ──────────────────────

    async def publish_success(self, post_id: int, channel_name: str, msg_id: int) -> None:
        await self.notify_all(
            "info",
            "✅ Post Published",
            f"Post #{post_id} → {channel_name}\nMessage ID: {msg_id}",
        )

    async def publish_failed(self, post_id: int, target: str, error: str) -> None:
        await self.notify_all(
            "error",
            "❌ Publishing Failed",
            f"Post #{post_id} → {target}\n\nReason: {error}\n\nRecommended action: Check channel permissions.",
        )

    async def permission_error(self, channel: str, permission: str) -> None:
        await self.notify_all(
            "error",
            "🚫 Permission Error",
            f"Channel: {channel}\nMissing permission: {permission}\n\n"
            f"Action: Grant the bot '{permission}' in channel admin settings.",
        )

    async def rate_limit_hit(self, chat_id: str, retry_after: int) -> None:
        await self.notify_all(
            "warning",
            "⏱ Rate Limit Hit",
            f"Chat: {chat_id}\nRetrying in {retry_after}s",
        )

    async def source_fetch_failed(self, source_name: str, error: str) -> None:
        await self.notify_all(
            "warning",
            "📡 Source Fetch Failed",
            f"Source: {source_name}\nError: {error}",
        )

    async def dead_job(self, job_id: str, post_id: int, error: str) -> None:
        await self.notify_all(
            "critical",
            "💀 Job Failed (Dead Letter)",
            f"Job: {job_id}\nPost: #{post_id}\nError: {error}\n\n"
            f"Action: Review the failed job in the dashboard.",
        )

    async def campaign_completed(self, campaign_name: str, published: int, failed: int) -> None:
        await self.notify_all(
            "info",
            "🏁 Campaign Completed",
            f"Campaign: {campaign_name}\n"
            f"Published: {published} posts\nFailed: {failed} posts",
        )

    async def system_health_issue(self, component: str, issue: str) -> None:
        await self.notify_all(
            "critical",
            f"🔥 System Issue: {component}",
            issue,
        )


_notifier: Notifier | None = None


def get_notifier() -> Notifier:
    global _notifier
    if _notifier is None:
        _notifier = Notifier()
    return _notifier
