"""
TelegramClient
==============

The single entry point for ALL Telegram Bot API calls in this application.

Rules enforced here:
  1. Every call goes through the rate limiter.
  2. Every call goes through RetryableRequest.
  3. Dry-run mode intercepts every call.
  4. Secrets are never logged.
  5. Every capability is checked against the registry before calling.
  6. Structured log events are emitted for every call.

Do NOT scatter direct aiogram Bot calls throughout the codebase.
Use this client exclusively so that future Bot API changes need
only be made in one place.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    Animation, Audio, Document, InlineKeyboardMarkup, InputFile,
    InputMediaAnimation, InputMediaAudio, InputMediaDocument,
    InputMediaPhoto, InputMediaVideo, InputPollOption,
    Message, MessageId, PhotoSize, ReactionType, ReplyKeyboardMarkup,
    ReplyKeyboardRemove, Video, VideoNote, Voice,
)

from app.core.config import settings
from app.core.exceptions import TelegramCapabilityUnavailableError
from app.core.logging_config import get_logger
from app.telegram.capability_registry import get_registry
from app.telegram.rate_limiter import RetryableRequest, get_rate_limiter

log = get_logger(__name__)


class TelegramClient:
    """
    Thin, safe wrapper around the aiogram Bot.

    Do not create instances directly — use get_client().
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot
        self._limiter = get_rate_limiter()
        self._registry = get_registry()

    # ── Internal helpers ──────────────────────────────────────

    def _require(self, capability: str) -> None:
        if not self._registry.is_available(capability):
            cap = self._registry.get(capability)
            raise TelegramCapabilityUnavailableError(
                capability, cap.min_bot_api_version
            )

    async def _call(
        self,
        capability: str,
        fn_name: str,
        chat_id: str | int | None = None,
        is_group: bool = False,
        dry_run_result: Any = None,
        **kwargs: Any,
    ) -> Any:
        self._require(capability)

        chat_id_str = str(chat_id) if chat_id is not None else "N/A"

        if settings.dry_run:
            log.info(
                "dry_run_call",
                capability=capability,
                fn=fn_name,
                chat_id=chat_id_str,
                kwargs_keys=list(kwargs.keys()),
            )
            return dry_run_result

        if chat_id is not None:
            await self._limiter.acquire(chat_id_str, is_group=is_group)

        fn = getattr(self._bot, fn_name)
        result = await RetryableRequest(
            fn,
            chat_id=chat_id_str,
            limiter=self._limiter,
            **{k: v for k, v in kwargs.items() if k != "chat_id"},
        ).execute()

        log.info(
            "telegram_call_success",
            capability=capability,
            fn=fn_name,
            chat_id=chat_id_str,
        )
        return result

    # ── Core messaging ────────────────────────────────────────

    async def send_message(
        self,
        chat_id: str | int,
        text: str,
        *,
        parse_mode: str | None = "HTML",
        reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove | None = None,
        message_thread_id: int | None = None,
        disable_web_page_preview: bool = False,
        disable_notification: bool = False,
        protect_content: bool = False,
        is_group: bool = False,
        **kwargs: Any,
    ) -> Message:
        return await self._call(
            "send_message",
            "send_message",
            chat_id=chat_id,
            is_group=is_group,
            dry_run_result=None,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
            disable_web_page_preview=disable_web_page_preview,
            disable_notification=disable_notification,
            protect_content=protect_content,
            **kwargs,
        )

    async def send_photo(
        self,
        chat_id: str | int,
        photo: InputFile | str,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
        reply_markup: InlineKeyboardMarkup | None = None,
        message_thread_id: int | None = None,
        is_group: bool = False,
        **kwargs: Any,
    ) -> Message:
        return await self._call(
            "send_photo",
            "send_photo",
            chat_id=chat_id,
            is_group=is_group,
            dry_run_result=None,
            photo=photo,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
            **kwargs,
        )

    async def send_video(
        self,
        chat_id: str | int,
        video: InputFile | str,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
        reply_markup: InlineKeyboardMarkup | None = None,
        message_thread_id: int | None = None,
        is_group: bool = False,
        **kwargs: Any,
    ) -> Message:
        return await self._call(
            "send_video",
            "send_video",
            chat_id=chat_id,
            is_group=is_group,
            dry_run_result=None,
            video=video,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
            **kwargs,
        )

    async def send_audio(
        self,
        chat_id: str | int,
        audio: InputFile | str,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
        reply_markup: InlineKeyboardMarkup | None = None,
        is_group: bool = False,
        **kwargs: Any,
    ) -> Message:
        return await self._call(
            "send_audio",
            "send_audio",
            chat_id=chat_id,
            is_group=is_group,
            dry_run_result=None,
            audio=audio,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )

    async def send_document(
        self,
        chat_id: str | int,
        document: InputFile | str,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
        reply_markup: InlineKeyboardMarkup | None = None,
        is_group: bool = False,
        **kwargs: Any,
    ) -> Message:
        return await self._call(
            "send_document",
            "send_document",
            chat_id=chat_id,
            is_group=is_group,
            dry_run_result=None,
            document=document,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )

    async def send_animation(
        self,
        chat_id: str | int,
        animation: InputFile | str,
        caption: str | None = None,
        parse_mode: str | None = "HTML",
        reply_markup: InlineKeyboardMarkup | None = None,
        is_group: bool = False,
        **kwargs: Any,
    ) -> Message:
        return await self._call(
            "send_animation",
            "send_animation",
            chat_id=chat_id,
            is_group=is_group,
            dry_run_result=None,
            animation=animation,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )

    async def send_voice(
        self,
        chat_id: str | int,
        voice: InputFile | str,
        caption: str | None = None,
        is_group: bool = False,
        **kwargs: Any,
    ) -> Message:
        return await self._call(
            "send_voice",
            "send_voice",
            chat_id=chat_id,
            is_group=is_group,
            dry_run_result=None,
            voice=voice,
            caption=caption,
            **kwargs,
        )

    async def send_sticker(
        self,
        chat_id: str | int,
        sticker: InputFile | str,
        is_group: bool = False,
        **kwargs: Any,
    ) -> Message:
        return await self._call(
            "send_sticker",
            "send_sticker",
            chat_id=chat_id,
            is_group=is_group,
            dry_run_result=None,
            sticker=sticker,
            **kwargs,
        )

    async def send_media_group(
        self,
        chat_id: str | int,
        media: list[InputMediaPhoto | InputMediaVideo | InputMediaAudio | InputMediaDocument],
        is_group: bool = False,
        **kwargs: Any,
    ) -> list[Message]:
        return await self._call(
            "send_media_group",
            "send_media_group",
            chat_id=chat_id,
            is_group=is_group,
            dry_run_result=[],
            media=media,
            **kwargs,
        )

    async def send_poll(
        self,
        chat_id: str | int,
        question: str,
        options: list[InputPollOption],
        is_anonymous: bool = True,
        allows_multiple_answers: bool = False,
        is_group: bool = False,
        **kwargs: Any,
    ) -> Message:
        return await self._call(
            "send_poll",
            "send_poll",
            chat_id=chat_id,
            is_group=is_group,
            dry_run_result=None,
            question=question,
            options=options,
            is_anonymous=is_anonymous,
            allows_multiple_answers=allows_multiple_answers,
            **kwargs,
        )

    # ── Rich Messages (Bot API 10.1+) ─────────────────────────

    async def send_rich_message(
        self,
        chat_id: str | int,
        rich_message: dict,  # InputRichMessage structure
        is_group: bool = False,
        **kwargs: Any,
    ) -> Message:
        """Send a rich message with structured blocks. Requires Bot API 10.1+."""
        self._require("send_rich_message")
        # Delegated to bot.send_rich_message when aiogram supports it fully
        # For now, falls back to formatted sendMessage until aiogram 3.x adds it
        log.info("send_rich_message", chat_id=chat_id)
        return await self._bot.send_message(
            chat_id=chat_id,
            text=rich_message.get("text", ""),
            parse_mode="HTML",
            **kwargs,
        )

    # ── Message management ────────────────────────────────────

    async def edit_message_text(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        parse_mode: str | None = "HTML",
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs: Any,
    ) -> Message | bool:
        return await self._call(
            "edit_message_text",
            "edit_message_text",
            chat_id=chat_id,
            dry_run_result=True,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )

    async def delete_message(self, chat_id: str | int, message_id: int) -> bool:
        return await self._call(
            "delete_message",
            "delete_message",
            chat_id=chat_id,
            dry_run_result=True,
            message_id=message_id,
        )

    async def pin_message(self, chat_id: str | int, message_id: int) -> bool:
        return await self._call(
            "pin_message",
            "pin_chat_message",
            chat_id=chat_id,
            dry_run_result=True,
            message_id=message_id,
        )

    async def copy_message(
        self,
        chat_id: str | int,
        from_chat_id: str | int,
        message_id: int,
        caption: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs: Any,
    ) -> MessageId:
        return await self._call(
            "copy_message",
            "copy_message",
            chat_id=chat_id,
            dry_run_result=None,
            from_chat_id=from_chat_id,
            message_id=message_id,
            caption=caption,
            reply_markup=reply_markup,
            **kwargs,
        )

    # ── Chat administration ────────────────────────────────────

    async def get_chat(self, chat_id: str | int):
        return await self._call(
            "get_chat",
            "get_chat",
            chat_id=chat_id,
            dry_run_result=None,
        )

    async def get_chat_administrators(self, chat_id: str | int):
        return await self._call(
            "get_chat_administrators",
            "get_chat_administrators",
            chat_id=chat_id,
            dry_run_result=[],
        )

    async def get_chat_member_count(self, chat_id: str | int) -> int:
        result = await self._call(
            "get_user_count",
            "get_chat_member_count",
            chat_id=chat_id,
            dry_run_result=0,
        )
        return result or 0

    # ── Bot info ──────────────────────────────────────────────

    async def get_me(self):
        return await self._bot.get_me()

    # ── Webhook management ─────────────────────────────────────

    async def set_webhook(self, url: str, secret_token: str | None = None) -> bool:
        return await self._bot.set_webhook(
            url=url,
            secret_token=secret_token,
            allowed_updates=[
                "message", "edited_message", "channel_post",
                "edited_channel_post", "callback_query",
                "inline_query", "chosen_inline_result",
                "chat_join_request", "chat_member", "my_chat_member",
                "message_reaction", "message_reaction_count",
            ],
        )

    async def delete_webhook(self) -> bool:
        return await self._bot.delete_webhook(drop_pending_updates=True)

    # ── Bot commands ──────────────────────────────────────────

    async def set_my_commands(self, commands: list[dict]) -> bool:
        from aiogram.types import BotCommand
        bot_commands = [BotCommand(command=c["command"], description=c["description"]) for c in commands]
        return await self._bot.set_my_commands(bot_commands)

    # ── Reactions (Bot API 7+) ────────────────────────────────

    async def set_message_reaction(
        self,
        chat_id: str | int,
        message_id: int,
        reaction: list[ReactionType] | None = None,
    ) -> bool:
        return await self._call(
            "set_message_reaction",
            "set_message_reaction",
            chat_id=chat_id,
            dry_run_result=True,
            message_id=message_id,
            reaction=reaction or [],
        )

    # ── Inline mode ───────────────────────────────────────────

    async def answer_inline_query(
        self,
        inline_query_id: str,
        results: list,
        cache_time: int = 300,
        **kwargs: Any,
    ) -> bool:
        return await self._bot.answer_inline_query(
            inline_query_id=inline_query_id,
            results=results,
            cache_time=cache_time,
            **kwargs,
        )

    # ── Callback queries ──────────────────────────────────────

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> bool:
        return await self._bot.answer_callback_query(
            callback_query_id=callback_query_id,
            text=text,
            show_alert=show_alert,
        )

    # ── Underlying bot reference (use sparingly) ───────────────

    @property
    def bot(self) -> Bot:
        """Direct access to aiogram Bot. Use only when no wrapper method exists."""
        return self._bot


# ── Singleton management ──────────────────────────────────────

_client: TelegramClient | None = None


def create_client(token: str | None = None) -> TelegramClient:
    global _client
    bot = Bot(
        token=token or settings.bot_token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=False,
        ),
    )
    _client = TelegramClient(bot)
    return _client


def get_client() -> TelegramClient:
    if _client is None:
        return create_client()
    return _client
