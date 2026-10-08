"""
Post composer bot handler.

Conversation flow:
  /newpost
    → Ask for post type
    → Ask for content
    → Ask for target channels
    → Show preview
    → Ask: Schedule / Publish now / Save draft
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.core.config import settings
from app.core.logging_config import get_logger

log = get_logger(__name__)
router = Router(name="posts")


class PostState(StatesGroup):
    waiting_for_type = State()
    waiting_for_text = State()
    waiting_for_caption = State()
    waiting_for_media = State()
    waiting_for_channels = State()
    waiting_for_schedule = State()
    preview = State()


def _type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Text", callback_data="type:text"),
                InlineKeyboardButton(text="🖼 Photo", callback_data="type:photo"),
            ],
            [
                InlineKeyboardButton(text="🎬 Video", callback_data="type:video"),
                InlineKeyboardButton(text="🎵 Audio", callback_data="type:audio"),
            ],
            [
                InlineKeyboardButton(text="📄 Document", callback_data="type:document"),
                InlineKeyboardButton(text="🎞 Animation", callback_data="type:animation"),
            ],
            [
                InlineKeyboardButton(text="🗳 Poll", callback_data="type:poll"),
                InlineKeyboardButton(text="🖼🖼 Album", callback_data="type:media_group"),
            ],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="post:cancel")],
        ]
    )


def _action_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Publish Now", callback_data=f"post:publish:{post_id}"),
                InlineKeyboardButton(text="📅 Schedule", callback_data=f"post:schedule:{post_id}"),
            ],
            [
                InlineKeyboardButton(text="✏️ Edit", callback_data=f"post:edit:{post_id}"),
                InlineKeyboardButton(text="💾 Draft", callback_data=f"post:draft:{post_id}"),
            ],
            [
                InlineKeyboardButton(text="📋 Duplicate", callback_data=f"post:duplicate:{post_id}"),
                InlineKeyboardButton(text="🗑 Delete", callback_data=f"post:delete:{post_id}"),
            ],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="menu:posts")],
        ]
    )


@router.message(Command("newpost"))
async def cmd_new_post(message: Message, state: FSMContext) -> None:
    if message.from_user and message.from_user.id not in settings.admin_id_list:
        return

    await state.set_state(PostState.waiting_for_type)
    await message.answer(
        "<b>📝 NEW POST</b>\n\nSelect the post type:",
        reply_markup=_type_keyboard(),
    )


@router.callback_query(F.data.startswith("type:"))
async def cb_post_type(callback: CallbackQuery, state: FSMContext) -> None:
    post_type = callback.data.split(":", 1)[1]
    await state.update_data(post_type=post_type)

    if post_type == "text":
        await state.set_state(PostState.waiting_for_text)
        await callback.message.edit_text(
            "<b>📝 TEXT POST</b>\n\n"
            "Send your post text. Supports HTML formatting:\n"
            "<code>&lt;b&gt;bold&lt;/b&gt;, &lt;i&gt;italic&lt;/i&gt;, &lt;a href='url'&gt;link&lt;/a&gt;</code>\n\n"
            "Max 4096 characters.",
        )
    elif post_type in ("photo", "video", "audio", "document", "animation"):
        await state.set_state(PostState.waiting_for_media)
        type_names = {
            "photo": "photo (JPG/PNG)", "video": "video (MP4)",
            "audio": "audio (MP3/OGG)", "document": "any file",
            "animation": "GIF/animation"
        }
        await callback.message.edit_text(
            f"<b>📎 SEND MEDIA</b>\n\nSend your {type_names.get(post_type, 'file')}.",
        )
    elif post_type == "poll":
        await state.set_state(PostState.waiting_for_text)
        await callback.message.edit_text(
            "<b>🗳 POLL</b>\n\n"
            "Send poll data in this format:\n\n"
            "<code>Question text\n"
            "Option 1\n"
            "Option 2\n"
            "Option 3</code>"
        )
    elif post_type == "media_group":
        await state.set_state(PostState.waiting_for_media)
        await callback.message.edit_text(
            "<b>🖼🖼 MEDIA GROUP (Album)</b>\n\n"
            "Send up to 10 photos or videos. Send them together as an album.",
        )
    await callback.answer()


@router.message(PostState.waiting_for_text, F.text)
async def receive_text(message: Message, state: FSMContext) -> None:
    if len(message.text) > 4096:
        await message.answer(f"❌ Text too long: {len(message.text)}/4096 chars. Please shorten it.")
        return

    await state.update_data(text=message.text)
    data = await state.get_data()

    # Ask for target channels
    await _ask_for_channels(message, state, data)


@router.message(PostState.waiting_for_media)
async def receive_media(message: Message, state: FSMContext) -> None:
    media_data = {}

    if message.photo:
        photo = message.photo[-1]
        media_data = {"type": "photo", "file_id": photo.file_id, "file_unique_id": photo.file_unique_id}
    elif message.video:
        media_data = {"type": "video", "file_id": message.video.file_id, "file_unique_id": message.video.file_unique_id}
    elif message.audio:
        media_data = {"type": "audio", "file_id": message.audio.file_id, "file_unique_id": message.audio.file_unique_id}
    elif message.document:
        media_data = {"type": "document", "file_id": message.document.file_id, "file_unique_id": message.document.file_unique_id}
    elif message.animation:
        media_data = {"type": "animation", "file_id": message.animation.file_id}
    else:
        await message.answer("Please send a valid media file.")
        return

    await state.update_data(media=media_data, caption=message.caption or "")
    data = await state.get_data()
    await _ask_for_channels(message, state, data)


async def _ask_for_channels(message: Message, state: FSMContext, data: dict) -> None:
    from sqlalchemy import select
    from app.db.models import Channel
    from app.db.session import get_db

    async with get_db() as db:
        channels = (await db.execute(
            select(Channel).where(Channel.is_active == True).limit(20)
        )).scalars().all()

    if not channels:
        await message.answer(
            "⚠️ No channels configured.\n\n"
            "Add a channel first: send /channels to manage channels.",
        )
        await state.clear()
        return

    buttons = []
    for ch in channels:
        name = ch.title or ch.username or str(ch.telegram_id)
        buttons.append([InlineKeyboardButton(
            text=f"📡 {name}",
            callback_data=f"target:ch:{ch.id}",
        )])
    buttons.append([
        InlineKeyboardButton(text="✅ Done", callback_data="target:done"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="post:cancel"),
    ])

    await state.update_data(selected_channels=[])
    await state.set_state(PostState.waiting_for_channels)
    await message.answer(
        "<b>📡 SELECT CHANNELS</b>\n\nTap channels to select, then press Done:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(PostState.waiting_for_channels, F.data.startswith("target:ch:"))
async def cb_select_channel(callback: CallbackQuery, state: FSMContext) -> None:
    channel_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    selected = data.get("selected_channels", [])

    if channel_id in selected:
        selected.remove(channel_id)
        await callback.answer("Deselected")
    else:
        selected.append(channel_id)
        await callback.answer("✓ Selected")

    await state.update_data(selected_channels=selected)


@router.callback_query(PostState.waiting_for_channels, F.data == "target:done")
async def cb_channels_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = data.get("selected_channels", [])

    if not selected:
        await callback.answer("Select at least one channel!", show_alert=True)
        return

    # Create the post in the database
    post_id = await _create_post(data, callback.from_user.id)
    if not post_id:
        await callback.message.edit_text("❌ Failed to create post. Try again.")
        await state.clear()
        return

    # Show preview
    preview = _build_preview(data)
    await callback.message.edit_text(
        f"<b>👁 PREVIEW</b>\n\n{preview}\n\n"
        f"<b>Targets:</b> {len(selected)} channel(s)\n"
        f"<b>Post ID:</b> #{post_id}",
        reply_markup=_action_keyboard(post_id),
    )
    await state.set_state(PostState.preview)
    await state.update_data(post_id=post_id)
    await callback.answer()


async def _create_post(data: dict, user_telegram_id: int) -> int | None:
    """Persist the composed post to the database."""
    try:
        from sqlalchemy import select
        from app.db.models import Post, PostTarget, PostType, PostStatus, User
        from app.db.session import get_db

        post_type_map = {
            "text": PostType.TEXT, "photo": PostType.PHOTO,
            "video": PostType.VIDEO, "audio": PostType.AUDIO,
            "document": PostType.DOCUMENT, "animation": PostType.ANIMATION,
            "poll": PostType.POLL, "media_group": PostType.MEDIA_GROUP,
        }

        async with get_db() as db:
            user = (await db.execute(
                select(User).where(User.telegram_id == user_telegram_id)
            )).scalar_one_or_none()

            post = Post(
                text=data.get("text"),
                caption=data.get("caption"),
                post_type=post_type_map.get(data.get("post_type", "text"), PostType.TEXT),
                status=PostStatus.DRAFT,
                author_id=user.id if user else None,
            )
            db.add(post)
            await db.flush()

            # Create targets
            for ch_id in data.get("selected_channels", []):
                target = PostTarget(post_id=post.id, channel_id=ch_id)
                db.add(target)

            await db.commit()
            return post.id
    except Exception as exc:
        log.error("create_post_failed", error=str(exc))
        return None


def _build_preview(data: dict) -> str:
    """Build a preview of the post content."""
    post_type = data.get("post_type", "text")
    text = data.get("text", "")
    caption = data.get("caption", "")

    if post_type == "text":
        return text[:500] + ("..." if len(text) > 500 else "")
    else:
        media_labels = {
            "photo": "🖼 Photo", "video": "🎬 Video", "audio": "🎵 Audio",
            "document": "📄 Document", "animation": "🎞 Animation",
            "media_group": "🖼🖼 Album",
        }
        preview = media_labels.get(post_type, "📎 Media")
        if caption:
            preview += f"\n{caption[:200]}"
        return preview


@router.callback_query(F.data.startswith("post:publish:"))
async def cb_publish_now(callback: CallbackQuery, state: FSMContext) -> None:
    post_id = int(callback.data.split(":")[-1])
    await _enqueue_publish(post_id, callback)
    await state.clear()


async def _enqueue_publish(post_id: int, callback: CallbackQuery) -> None:
    """Approve and enqueue a post for immediate publishing."""
    from sqlalchemy import select
    from app.db.models import Post, PostStatus, PostTarget
    from app.db.session import get_db
    from app.workers.publisher_worker import publish_post
    from app.core.security import make_idempotency_key
    from app.db.models import Job, JobStatus, JobPriority
    import shortuuid
    import time

    async with get_db() as db:
        post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
        if not post:
            await callback.answer("Post not found!", show_alert=True)
            return

        post.status = PostStatus.APPROVED
        await db.flush()

        targets = (await db.execute(
            select(PostTarget).where(PostTarget.post_id == post_id)
        )).scalars().all()

        enqueued = 0
        for target in targets:
            job_id = str(shortuuid.uuid())
            idem_key = make_idempotency_key(post.id, target.id)
            job = Job(
                job_id=job_id,
                idempotency_key=idem_key,
                job_type="publish",
                post_id=post.id,
                target_id=target.id,
                priority=JobPriority.HIGH,
                status=JobStatus.PENDING,
            )
            db.add(job)
            await db.flush()

            publish_post.apply_async(
                args=[post.id, target.id, job_id],
                priority=JobPriority.HIGH,
                queue="publisher",
            )
            enqueued += 1

        await db.commit()

    await callback.message.edit_text(
        f"<b>🚀 Publishing!</b>\n\n"
        f"Post #{post_id} → {enqueued} target(s) enqueued.\n\n"
        f"{'⚠️ DRY RUN — no real messages sent' if settings.dry_run else 'Check your channels shortly.'}",
    )
    await callback.answer("Enqueued ✓")


@router.callback_query(F.data == "post:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ Cancelled.")
    await callback.answer()


@router.message(Command("posts"))
async def cmd_list_posts(message: Message) -> None:
    if message.from_user and message.from_user.id not in settings.admin_id_list:
        return

    from sqlalchemy import select
    from app.db.models import Post
    from app.db.session import get_db

    async with get_db() as db:
        posts = (await db.execute(
            select(Post).order_by(Post.id.desc()).limit(10)
        )).scalars().all()

    if not posts:
        await message.answer("No posts yet. Use /newpost to create one.")
        return

    status_emoji = {
        "draft": "📝", "approved": "✅", "scheduled": "📅",
        "publishing": "🔄", "published": "✅", "failed": "❌",
        "pending_review": "⏳", "rejected": "🚫", "archived": "📦",
    }

    lines = ["<b>📮 RECENT POSTS</b>\n"]
    for post in posts:
        emoji = status_emoji.get(post.status.value, "•")
        title = post.title or (post.text[:40] if post.text else "Untitled") + "..."
        lines.append(f"{emoji} <b>#{post.id}</b> {title} [{post.status.value}]")

    await message.answer("\n".join(lines))
