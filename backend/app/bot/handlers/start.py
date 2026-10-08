"""
Bot handlers: /start, /help, /status, /dashboard

The bot control center is launched from Telegram and mirrors the web dashboard.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.core.config import settings
from app.core.logging_config import get_logger
from app.telegram.capability_registry import get_registry

log = get_logger(__name__)
router = Router(name="start")


def _control_center_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Main navigation keyboard for the bot control center."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📮 Posts", callback_data="menu:posts"),
                InlineKeyboardButton(text="📅 Scheduler", callback_data="menu:scheduler"),
            ],
            [
                InlineKeyboardButton(text="📡 Channels", callback_data="menu:channels"),
                InlineKeyboardButton(text="👥 Groups", callback_data="menu:groups"),
            ],
            [
                InlineKeyboardButton(text="🖼 Media", callback_data="menu:media"),
                InlineKeyboardButton(text="🧩 Templates", callback_data="menu:templates"),
            ],
            [
                InlineKeyboardButton(text="🤖 AI", callback_data="menu:ai"),
                InlineKeyboardButton(text="⚙️ Automation", callback_data="menu:automation"),
            ],
            [
                InlineKeyboardButton(text="📊 Analytics", callback_data="menu:analytics"),
                InlineKeyboardButton(text="🛡 Security", callback_data="menu:security"),
            ],
            [
                InlineKeyboardButton(text="🔧 Settings", callback_data="menu:settings"),
                InlineKeyboardButton(text="❓ Help", callback_data="menu:help"),
            ],
        ]
    )


def _status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh", callback_data="status:refresh")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="menu:main")],
        ]
    )


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if not message.from_user:
        return

    from app.db.models import User, UserRole
    from app.db.session import get_db
    from sqlalchemy import select

    user_id = message.from_user.id
    is_admin = user_id in settings.admin_id_list

    # Upsert user in the database
    async with get_db() as db:
        user = (await db.execute(
            select(User).where(User.telegram_id == user_id)
        )).scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=user_id,
                username=message.from_user.username,
                first_name=message.from_user.first_name or "",
                last_name=message.from_user.last_name,
                language_code=message.from_user.language_code or "en",
                role=UserRole.OWNER if user_id in settings.admin_id_list else UserRole.VIEWER,
            )
            db.add(user)
            await db.commit()
            log.info("new_user", telegram_id=user_id, username=message.from_user.username)
        else:
            from datetime import datetime, timezone
            user.last_seen_at = datetime.now(tz=timezone.utc)
            await db.commit()

    if not is_admin:
        await message.answer(
            "👋 Welcome to <b>Telegram Publisher</b>.\n\n"
            "This bot is managed by the channel owner. "
            "Contact the administrator if you need access.",
        )
        return

    name = message.from_user.first_name or "Admin"
    await message.answer(
        f"⚡ <b>CONTROL CENTER</b>\n\n"
        f"Welcome back, <b>{name}</b>!\n\n"
        f"{'🔴 DRY RUN MODE ACTIVE' if settings.dry_run else '🟢 Live Mode'}\n"
        f"Bot API: {settings.telegram_api_version}",
        reply_markup=_control_center_keyboard(user_id),
    )
    log.info("control_center_opened", user_id=user_id)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    if message.from_user and message.from_user.id not in settings.admin_id_list:
        return

    registry = get_registry()
    available_count = sum(1 for cap in registry.matrix() if cap["available"])
    total_count = len(registry.matrix())

    from app.core.feature_flags import flags
    enabled_flags = [name for name, info in flags.all_flags().items() if info["enabled"]]

    text = (
        "<b>📖 TELEGRAM PUBLISHER HELP</b>\n\n"
        "<b>Commands:</b>\n"
        "/start — Open control center\n"
        "/help — This help message\n"
        "/status — System health status\n"
        "/newpost — Create a new post\n"
        "/posts — List recent posts\n"
        "/schedule — View schedule\n"
        "/queue — Queue status\n"
        "/channels — Manage channels\n"
        "/analytics — View analytics\n"
        "/settings — Bot settings\n"
        "/pause — Pause all publishing\n"
        "/resume — Resume publishing\n\n"
        f"<b>API Capabilities:</b> {available_count}/{total_count} available\n"
        f"<b>Active Features:</b> {', '.join(enabled_flags) or 'none'}\n\n"
        f"<b>Mode:</b> {'🔴 DRY RUN' if settings.dry_run else '🟢 Live'}"
    )
    await message.answer(text)


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if message.from_user and message.from_user.id not in settings.admin_id_list:
        return

    status_text = await _build_status()
    await message.answer(status_text, reply_markup=_status_keyboard())


@router.callback_query(F.data == "status:refresh")
async def cb_status_refresh(callback: CallbackQuery) -> None:
    status_text = await _build_status()
    await callback.message.edit_text(status_text, reply_markup=_status_keyboard())
    await callback.answer("Refreshed ✓")


@router.callback_query(F.data == "menu:main")
async def cb_menu_main(callback: CallbackQuery) -> None:
    if not callback.from_user:
        return
    await callback.message.edit_text(
        "⚡ <b>CONTROL CENTER</b>",
        reply_markup=_control_center_keyboard(callback.from_user.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("menu:"))
async def cb_menu_section(callback: CallbackQuery) -> None:
    """Route to section info — full handlers in dedicated files."""
    section = callback.data.split(":", 1)[1]
    text = _section_text(section)
    back_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Back", callback_data="menu:main")]]
    )
    await callback.message.edit_text(text, reply_markup=back_keyboard)
    await callback.answer()


@router.message(Command("pause"))
async def cmd_pause(message: Message) -> None:
    if message.from_user and message.from_user.id not in settings.admin_id_list:
        return
    # Persist pause state to settings
    from app.db.session import get_db
    from app.db.models import Setting
    async with get_db() as db:
        setting = Setting(key="publishing_paused", value={"paused": True})
        db.add(setting)
        await db.commit()
    await message.answer("⏸ <b>Publishing paused.</b>\n\nAll scheduled posts will wait. Send /resume to continue.")


@router.message(Command("resume"))
async def cmd_resume(message: Message) -> None:
    if message.from_user and message.from_user.id not in settings.admin_id_list:
        return
    from app.db.session import get_db
    from app.db.models import Setting
    from sqlalchemy import select, delete
    async with get_db() as db:
        await db.execute(delete(Setting).where(Setting.key == "publishing_paused"))
        await db.commit()
    await message.answer("▶️ <b>Publishing resumed.</b>")


@router.message(Command("queue"))
async def cmd_queue(message: Message) -> None:
    if message.from_user and message.from_user.id not in settings.admin_id_list:
        return

    from sqlalchemy import select, func
    from app.db.models import Job, JobStatus
    from app.db.session import get_db

    async with get_db() as db:
        counts = {}
        for status in JobStatus:
            count = (await db.execute(
                select(func.count()).where(Job.status == status)
            )).scalar_one()
            counts[status.value] = count

    lines = ["<b>📋 QUEUE STATUS</b>\n"]
    emoji = {
        "pending": "⏳", "running": "🔄", "success": "✅",
        "failed": "❌", "retrying": "🔁", "dead": "💀", "cancelled": "🚫"
    }
    for status, count in counts.items():
        if count > 0:
            lines.append(f"{emoji.get(status, '•')} {status.title()}: <b>{count}</b>")

    await message.answer("\n".join(lines) or "Queue is empty.")


async def _build_status() -> str:
    """Collect system health status."""
    components = []

    # Database
    try:
        from app.db.session import get_db
        async with get_db() as db:
            await db.execute(__import__("sqlalchemy").text("SELECT 1"))
        components.append("🟢 Database")
    except Exception:
        components.append("🔴 Database")

    # Redis
    try:
        import redis.asyncio as redis
        r = redis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        components.append("🟢 Redis")
    except Exception:
        components.append("🟡 Redis (unavailable)")

    # Telegram API
    try:
        from app.telegram.client import get_client
        client = get_client()
        me = await client.get_me()
        components.append(f"🟢 Telegram (@{me.username})")
    except Exception:
        components.append("🔴 Telegram")

    # AI
    from app.core.feature_flags import is_enabled
    if is_enabled("AI"):
        components.append(f"🟢 AI ({settings.ai_provider})")
    else:
        components.append("⚪ AI (disabled)")

    mode = "🔴 DRY RUN" if settings.dry_run else "🟢 Live"

    return (
        "<b>🔧 SYSTEM STATUS</b>\n\n"
        + "\n".join(components)
        + f"\n\nMode: {mode}\n"
        f"API: v{settings.telegram_api_version}"
    )


def _section_text(section: str) -> str:
    texts = {
        "posts": (
            "<b>📮 POSTS</b>\n\n"
            "Commands:\n"
            "/newpost — Create new post\n"
            "/posts — List recent posts\n\n"
            "Use /newpost to start the composer."
        ),
        "scheduler": (
            "<b>📅 SCHEDULER</b>\n\n"
            "/schedule — View upcoming schedule\n\n"
            "The scheduler runs every 60 seconds and evaluates all active schedules."
        ),
        "channels": (
            "<b>📡 CHANNELS</b>\n\n"
            "/channels — List configured channels\n\n"
            "Use the dashboard to add and verify channels."
        ),
        "analytics": (
            "<b>📊 ANALYTICS</b>\n\n"
            "/analytics — View analytics summary\n\n"
            "Analytics are tracked from bot interactions and publishing events."
        ),
        "ai": (
            f"<b>🤖 AI ASSISTANT</b>\n\n"
            f"Status: {'✅ Enabled' if settings.feature_ai else '❌ Disabled'}\n"
            f"Provider: {settings.ai_provider}\n\n"
            "Enable via FEATURE_AI=true in .env"
        ),
        "settings": (
            "<b>🔧 SETTINGS</b>\n\n"
            f"Timezone: {settings.default_timezone}\n"
            f"Mode: {'DRY RUN' if settings.dry_run else 'Live'}\n"
            f"Log level: {settings.log_level}"
        ),
    }
    return texts.get(section, f"<b>{section.upper()}</b>\n\nUse the dashboard for full control.")
