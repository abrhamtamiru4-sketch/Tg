"""
Telegram Bot Entry Point
========================

Starts the bot in either:
  - Webhook mode (production, when WEBHOOK_URL is set)
  - Long-polling mode (development, Termux, environments without public HTTPS)

Set WEBHOOK_URL= (empty) to use long-polling.
"""

from __future__ import annotations

import asyncio
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from app.core.config import settings
from app.core.logging_config import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)

# ── Bot & Dispatcher setup ────────────────────────────────────

bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

# Use Redis storage for FSM when available, fall back to memory
try:
    from redis.asyncio import Redis
    _redis = Redis.from_url(settings.redis_url)
    storage = RedisStorage(_redis, key_builder=None)
    log.info("fsm_storage", backend="redis")
except Exception:
    storage = MemoryStorage()
    log.info("fsm_storage", backend="memory")

dp = Dispatcher(storage=storage)

# ── Register routers ──────────────────────────────────────────

from app.bot.handlers.start import router as start_router
from app.bot.handlers.posts import router as posts_router
from app.bot.handlers.inline import router as inline_router

dp.include_routers(start_router, posts_router, inline_router)


# ── Bot commands ──────────────────────────────────────────────

async def set_commands() -> None:
    """Register commands in Telegram so they appear in the menu."""
    from aiogram.types import BotCommand, BotCommandScopeDefault

    commands = [
        BotCommand(command="start", description="⚡ Open control center"),
        BotCommand(command="help", description="📖 Help & documentation"),
        BotCommand(command="status", description="🔧 System status"),
        BotCommand(command="newpost", description="📝 Create new post"),
        BotCommand(command="posts", description="📮 List recent posts"),
        BotCommand(command="schedule", description="📅 View schedule"),
        BotCommand(command="queue", description="📋 Queue status"),
        BotCommand(command="channels", description="📡 Manage channels"),
        BotCommand(command="analytics", description="📊 Analytics"),
        BotCommand(command="settings", description="🔧 Bot settings"),
        BotCommand(command="pause", description="⏸ Pause publishing"),
        BotCommand(command="resume", description="▶️ Resume publishing"),
    ]

    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    log.info("bot_commands_registered", count=len(commands))


# ── Startup / Shutdown ────────────────────────────────────────

async def on_startup() -> None:
    from app.db.session import create_all_tables, get_engine

    get_engine()

    if settings.is_development or settings.is_sqlite:
        await create_all_tables()

    # Ensure initial admin user exists
    await _ensure_admin_users()

    me = await bot.get_me()
    log.info("bot_started", username=me.username, id=me.id, dry_run=settings.dry_run)

    if settings.dry_run:
        log.warning("DRY_RUN_MODE", message="No real Telegram messages will be sent")

    await set_commands()

    if settings.use_webhook:
        ok = await bot.set_webhook(
            url=settings.webhook_url + settings.webhook_path,
            secret_token=settings.webhook_secret or None,
            drop_pending_updates=True,
        )
        log.info("webhook_set", url=settings.webhook_url, success=ok)
    else:
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("polling_mode_active")


async def on_shutdown() -> None:
    log.info("bot_shutting_down")
    await bot.session.close()
    from app.db.session import close_engine
    await close_engine()


async def _ensure_admin_users() -> None:
    """Create User records for admin IDs if they don't exist."""
    from sqlalchemy import select
    from app.db.models import User, UserRole
    from app.db.session import get_db

    for admin_id in settings.admin_id_list:
        async with get_db() as db:
            existing = (await db.execute(
                select(User).where(User.telegram_id == admin_id)
            )).scalar_one_or_none()
            if not existing:
                db.add(User(
                    telegram_id=admin_id,
                    first_name="Admin",
                    role=UserRole.OWNER,
                ))
                await db.commit()
                log.info("admin_user_created", telegram_id=admin_id)


# ── Main ──────────────────────────────────────────────────────

async def main() -> None:
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    if settings.use_webhook:
        # In webhook mode the FastAPI server handles updates.
        # This process just keeps the dispatcher alive for FSM.
        log.info("bot_webhook_mode", url=settings.webhook_url)
        await on_startup()
        # Keep alive
        stop = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_event_loop().add_signal_handler(sig, stop.set)
        await stop.wait()
        await on_shutdown()
    else:
        # Long-polling mode — great for development and Termux
        log.info("bot_polling_mode")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("bot_stopped")
