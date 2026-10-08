"""
TelegramPermissionEngine
========================

Before publishing to any chat, verify that:
  1. The bot exists in the chat.
  2. The bot has the required administrator rights.
  3. The content is valid for the target chat type.

Returns structured verification results with actionable error messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.core.logging_config import get_logger
from app.telegram.client import TelegramClient

log = get_logger(__name__)


@dataclass
class PermissionCheck:
    name: str
    passed: bool
    message: str = ""
    action: str = ""


@dataclass
class PermissionReport:
    chat_id: str
    checks: list[PermissionCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> list[PermissionCheck]:
        return [c for c in self.checks if not c.passed]

    def summary(self) -> str:
        if self.passed:
            return f"✅ All permission checks passed for {self.chat_id}"
        lines = [f"❌ Permission checks failed for {self.chat_id}:"]
        for c in self.failed_checks:
            lines.append(f"  • {c.name}: {c.message}")
            if c.action:
                lines.append(f"    → {c.action}")
        return "\n".join(lines)


class TelegramPermissionEngine:
    """
    Verifies bot permissions before attempting to publish.

    Checks are performed against the live Telegram API.
    Results are NOT cached because permissions can change at any time.
    """

    # Permissions required to post in a channel
    CHANNEL_POST_PERMISSIONS = ["can_post_messages"]

    # Permissions required to post in a group/supergroup
    GROUP_POST_PERMISSIONS: list[str] = []  # Only admin status needed

    # Permissions required for pinning
    PIN_PERMISSIONS = ["can_pin_messages"]

    # Permissions required for member management
    ADMIN_PERMISSIONS = ["can_restrict_members", "can_promote_members"]

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    async def verify_channel(self, chat_id: str | int) -> PermissionReport:
        """Full permission check for posting to a channel."""
        report = PermissionReport(chat_id=str(chat_id))
        bot_id = (await self._client.get_me()).id

        # 1. Chat is accessible
        try:
            chat = await self._client.get_chat(chat_id)
            report.checks.append(PermissionCheck(
                "chat_accessible",
                passed=True,
                message=f"Chat '{chat.title or chat_id}' is accessible",
            ))
        except TelegramBadRequest as exc:
            report.checks.append(PermissionCheck(
                "chat_accessible",
                passed=False,
                message=f"Chat not found: {exc}",
                action="Verify the channel @username or ID is correct.",
            ))
            return report  # No point checking further
        except TelegramForbiddenError:
            report.checks.append(PermissionCheck(
                "chat_accessible",
                passed=False,
                message="Bot is not a member of this chat",
                action="Add the bot to the channel as an administrator.",
            ))
            return report

        # 2. Chat is a channel (for channel-specific checks)
        is_channel = chat.type == "channel"
        is_group = chat.type in ("group", "supergroup")

        report.checks.append(PermissionCheck(
            "chat_type",
            passed=is_channel or is_group,
            message=f"Chat type: {chat.type}",
        ))

        # 3. Bot is an administrator
        try:
            admins = await self._client.get_chat_administrators(chat_id)
            admin_ids = [a.user.id for a in admins]
            is_admin = bot_id in admin_ids

            report.checks.append(PermissionCheck(
                "bot_is_admin",
                passed=is_admin,
                message="Bot is an administrator" if is_admin else "Bot is NOT an administrator",
                action="" if is_admin else (
                    "Promote the bot to administrator with 'Post Messages' permission."
                    if is_channel else
                    "Add the bot as an administrator."
                ),
            ))

            if is_admin:
                # 4. Check specific permissions
                bot_member = next((a for a in admins if a.user.id == bot_id), None)
                if bot_member and is_channel:
                    can_post = getattr(bot_member, "can_post_messages", False)
                    report.checks.append(PermissionCheck(
                        "can_post_messages",
                        passed=bool(can_post),
                        message="Has 'Post Messages' permission" if can_post else "Missing 'Post Messages'",
                        action="" if can_post else
                            "In channel settings → Administrators, enable 'Post Messages' for the bot.",
                    ))

        except Exception as exc:
            report.checks.append(PermissionCheck(
                "bot_is_admin",
                passed=False,
                message=f"Could not retrieve admin list: {exc}",
                action="Ensure the bot has the 'Read Admin List' permission.",
            ))

        return report

    async def verify_group(self, chat_id: str | int) -> PermissionReport:
        """Permission check for posting to a group/supergroup."""
        return await self.verify_channel(chat_id)  # Same checks apply

    async def can_pin(self, chat_id: str | int) -> bool:
        report = await self.verify_channel(chat_id)
        if not report.passed:
            return False
        try:
            bot_id = (await self._client.get_me()).id
            admins = await self._client.get_chat_administrators(chat_id)
            bot_member = next((a for a in admins if a.user.id == bot_id), None)
            return bool(bot_member and getattr(bot_member, "can_pin_messages", False))
        except Exception:
            return False

    async def verify_all(self, chat_ids: list[str | int]) -> dict[str, PermissionReport]:
        """Batch verification for multiple channels."""
        import asyncio
        results = await asyncio.gather(
            *(self.verify_channel(cid) for cid in chat_ids),
            return_exceptions=False,
        )
        return {str(cid): report for cid, report in zip(chat_ids, results)}
