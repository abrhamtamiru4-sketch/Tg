"""Admin filter for bot handlers."""
from __future__ import annotations
from aiogram.filters import BaseFilter
from aiogram.types import Message
from app.core.config import settings

class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in settings.admin_id_list)
