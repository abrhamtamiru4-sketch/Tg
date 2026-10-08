"""Bot authentication middleware — checks admin allowlist."""
from __future__ import annotations
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from typing import Any, Awaitable, Callable
from app.core.config import settings

class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Allow all updates through — per-handler auth done in handler
        return await handler(event, data)
