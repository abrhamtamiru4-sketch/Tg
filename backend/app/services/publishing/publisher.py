"""
Publisher
=========

Orchestrates the end-to-end publish flow:

  1. Pre-flight validation
  2. Idempotency check (prevent duplicate publishing)
  3. Telegram API call (via TelegramClient)
  4. Post-publish verification
  5. Status update + analytics recording
  6. Error classification + retry scheduling

This module is called by the publisher Celery worker.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    IdempotencyViolationError,
    PreflightError,
    PublishingError,
    TelegramPermissionError,
)
from app.core.logging_config import get_logger
from app.core.security import make_idempotency_key
from app.db.models import (
    AnalyticsEvent,
    AuditLog,
    Job,
    JobStatus,
    MediaFile,
    MediaType,
    Post,
    PostStatus,
    PostTarget,
)
from app.services.publishing.preflight import PreflightValidator
from app.telegram.client import TelegramClient
from aiogram.types import (
    InputFile,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaAudio,
    InputMediaDocument,
)

log = get_logger(__name__)


class Publisher:
    """
    Executes a single publish attempt for one (Post × PostTarget).

    Instances are short-lived: one per publish job.
    """

    def __init__(self, client: TelegramClient, db: AsyncSession) -> None:
        self._client = client
        self._db = db
        self._preflight = PreflightValidator(client)

    async def publish(self, post: Post, target: PostTarget, job: Job) -> dict:
        """
        Full publish flow. Returns a result dict.
        Raises PublishingError on unrecoverable failure.
        """
        chat_id = await self._resolve_chat_id(target)
        is_group = target.group_id is not None
        message_thread_id = await self._resolve_thread_id(target)

        idempotency_key = make_idempotency_key(
            post.id, target.id, target.post.scheduled_at.timestamp()
            if target.post and target.post.scheduled_at else None
        )

        # ── 1. Idempotency check ─────────────────────────────
        existing = (await self._db.execute(
            select(Job).where(
                Job.idempotency_key == idempotency_key,
                Job.status == JobStatus.SUCCESS,
                Job.id != job.id,
            )
        )).scalar_one_or_none()

        if existing:
            raise IdempotencyViolationError(idempotency_key)

        # ── 2. Pre-flight ─────────────────────────────────────
        preflight = await self._preflight.validate(post, target, idempotency_key)
        if not preflight.passed:
            raise PreflightError([c["name"] for c in preflight.failed])

        # ── 3. Mark as publishing ─────────────────────────────
        await self._set_target_status(target, PostStatus.PUBLISHING)
        job.started_at = datetime.now(tz=timezone.utc)
        job.status = JobStatus.RUNNING
        await self._db.commit()

        # ── 4. Send message ───────────────────────────────────
        try:
            message = await self._send(post, target, chat_id, is_group, message_thread_id)
        except Exception as exc:
            log.error(
                "publish_failed",
                post_id=post.id,
                target_id=target.id,
                error=str(exc),
            )
            error_type = type(exc).__name__
            is_retryable = isinstance(exc, (TelegramPermissionError,)) is False
            await self._set_target_status(target, PostStatus.FAILED, str(exc))
            await self._record_event("post_failed", post, target, metadata={"error": str(exc)})
            raise

        # ── 5. Post-publish verification ──────────────────────
        msg_id = message.message_id if message else None

        # Pin if requested
        if target.pin_after_publish and msg_id and not settings.dry_run:
            try:
                await self._client.pin_message(chat_id, msg_id)
            except Exception as exc:
                log.warning("pin_failed", chat_id=chat_id, msg_id=msg_id, error=str(exc))

        # ── 6. Update status ──────────────────────────────────
        now = datetime.now(tz=timezone.utc)
        target.status = PostStatus.PUBLISHED
        target.telegram_message_id = msg_id
        target.published_at = now
        target.error_message = None

        # Update post if all targets are published
        all_targets = (await self._db.execute(
            select(PostTarget).where(PostTarget.post_id == post.id)
        )).scalars().all()

        if all(t.status == PostStatus.PUBLISHED for t in all_targets):
            post.status = PostStatus.PUBLISHED
            post.published_at = now

        job.status = JobStatus.SUCCESS
        job.completed_at = now
        job.result = {"telegram_message_id": msg_id, "chat_id": str(chat_id)}

        await self._db.commit()

        # ── 7. Analytics ──────────────────────────────────────
        await self._record_event("post_published", post, target, metadata={
            "telegram_message_id": msg_id,
            "chat_id": str(chat_id),
        })

        # ── 8. Audit log ──────────────────────────────────────
        self._db.add(AuditLog(
            action="post_published",
            resource_type="post",
            resource_id=post.id,
            new_value={"target_id": target.id, "chat_id": str(chat_id), "message_id": msg_id},
            result="success",
        ))
        await self._db.commit()

        log.info(
            "publish_success",
            post_id=post.id,
            target_id=target.id,
            chat_id=str(chat_id),
            telegram_message_id=msg_id,
        )

        return {
            "post_id": post.id,
            "target_id": target.id,
            "chat_id": str(chat_id),
            "telegram_message_id": msg_id,
            "published_at": now.isoformat(),
        }

    async def _send(
        self,
        post: Post,
        target: PostTarget,
        chat_id: str | int,
        is_group: bool,
        message_thread_id: int | None,
    ):
        """Route to the correct Telegram send method based on post type."""
        from app.db.models import PostType

        caption = target.custom_caption or post.caption
        reply_markup_data = target.custom_reply_markup or post.reply_markup
        reply_markup = self._build_keyboard(reply_markup_data) if reply_markup_data else None

        common = dict(
            chat_id=chat_id,
            is_group=is_group,
            message_thread_id=message_thread_id,
            reply_markup=reply_markup,
        )

        if post.post_type == PostType.MEDIA_GROUP and post.media:
            return await self._send_media_group(post, target, **common)

        media_item = post.media[0].media_file if post.media else None

        if post.post_type == PostType.TEXT or not media_item:
            text = post.text or caption or ""
            return await self._client.send_message(
                text=text,
                parse_mode=post.parse_mode,
                **common,
            )

        file_id_or_path = media_item.telegram_file_id or media_item.storage_path
        if not file_id_or_path:
            raise PublishingError("Media has no file_id and no storage_path")

        if post.post_type == PostType.PHOTO:
            return await self._client.send_photo(
                photo=file_id_or_path,
                caption=caption,
                parse_mode=post.parse_mode,
                **common,
            )
        elif post.post_type == PostType.VIDEO:
            return await self._client.send_video(
                video=file_id_or_path,
                caption=caption,
                parse_mode=post.parse_mode,
                **common,
            )
        elif post.post_type == PostType.AUDIO:
            return await self._client.send_audio(
                audio=file_id_or_path,
                caption=caption,
                parse_mode=post.parse_mode,
                **common,
            )
        elif post.post_type == PostType.DOCUMENT:
            return await self._client.send_document(
                document=file_id_or_path,
                caption=caption,
                parse_mode=post.parse_mode,
                **common,
            )
        elif post.post_type == PostType.ANIMATION:
            return await self._client.send_animation(
                animation=file_id_or_path,
                caption=caption,
                parse_mode=post.parse_mode,
                **common,
            )
        elif post.post_type == PostType.VOICE:
            return await self._client.send_voice(
                voice=file_id_or_path,
                caption=caption,
                **common,
            )
        elif post.post_type == PostType.STICKER:
            return await self._client.send_sticker(
                sticker=file_id_or_path,
                **common,
            )
        elif post.post_type == PostType.POLL and post.poll_data:
            from aiogram.types import InputPollOption
            options = [InputPollOption(text=o) for o in post.poll_data.get("options", [])]
            return await self._client.send_poll(
                chat_id=chat_id,
                question=post.poll_data["question"],
                options=options,
                is_anonymous=post.poll_data.get("is_anonymous", True),
                allows_multiple_answers=post.poll_data.get("allows_multiple_answers", False),
                is_group=is_group,
                message_thread_id=message_thread_id,
            )
        elif post.post_type == PostType.RICH and post.rich_message:
            return await self._client.send_rich_message(
                chat_id=chat_id,
                rich_message=post.rich_message,
                is_group=is_group,
            )
        else:
            # Fallback: send as text
            return await self._client.send_message(
                text=post.text or caption or "📌",
                parse_mode=post.parse_mode,
                **common,
            )

    async def _send_media_group(self, post: Post, target, **common):
        from aiogram.types import InputMediaPhoto, InputMediaVideo

        items = sorted(post.media, key=lambda m: m.position)
        media_list = []
        for i, pm in enumerate(items[:10]):
            mf = pm.media_file
            file_ref = mf.telegram_file_id or mf.storage_path
            caption = (pm.caption or target.custom_caption or post.caption) if i == 0 else None

            if mf.media_type == MediaType.PHOTO:
                media_list.append(InputMediaPhoto(media=file_ref, caption=caption))
            elif mf.media_type == MediaType.VIDEO:
                media_list.append(InputMediaVideo(media=file_ref, caption=caption))
            elif mf.media_type == MediaType.AUDIO:
                media_list.append(InputMediaAudio(media=file_ref, caption=caption))
            elif mf.media_type == MediaType.DOCUMENT:
                media_list.append(InputMediaDocument(media=file_ref, caption=caption))

        messages = await self._client.send_media_group(
            chat_id=common["chat_id"],
            media=media_list,
            is_group=common.get("is_group", False),
            message_thread_id=common.get("message_thread_id"),
        )
        return messages[0] if messages else None

    @staticmethod
    def _build_keyboard(data: dict):
        """Build an InlineKeyboardMarkup from stored JSON."""
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        rows = []
        for row_data in data.get("inline_keyboard", []):
            row = []
            for btn_data in row_data:
                kwargs = {k: v for k, v in btn_data.items() if v is not None}
                row.append(InlineKeyboardButton(**kwargs))
            rows.append(row)
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _resolve_chat_id(self, target: PostTarget) -> str | int:
        if target.channel_id:
            from app.db.models import Channel
            ch = (await self._db.execute(
                select(Channel).where(Channel.id == target.channel_id)
            )).scalar_one_or_none()
            if ch:
                return ch.telegram_id
        if target.group_id:
            from app.db.models import Group
            grp = (await self._db.execute(
                select(Group).where(Group.id == target.group_id)
            )).scalar_one_or_none()
            if grp:
                return grp.telegram_id
        raise PublishingError("Cannot resolve chat_id: no channel or group configured")

    async def _resolve_thread_id(self, target: PostTarget) -> int | None:
        if target.topic_id:
            from app.db.models import Topic
            topic = (await self._db.execute(
                select(Topic).where(Topic.id == target.topic_id)
            )).scalar_one_or_none()
            return topic.telegram_thread_id if topic else None
        return None

    async def _set_target_status(
        self,
        target: PostTarget,
        status: PostStatus,
        error: str | None = None,
    ) -> None:
        target.status = status
        if error:
            target.error_message = error
        await self._db.commit()

    async def _record_event(
        self,
        event_type: str,
        post: Post,
        target: PostTarget,
        metadata: dict | None = None,
    ) -> None:
        self._db.add(AnalyticsEvent(
            event_type=event_type,
            post_id=post.id,
            target_id=target.id,
            channel_id=target.channel_id,
            campaign_id=post.campaign_id,
            metadata=metadata,
        ))
        await self._db.commit()
