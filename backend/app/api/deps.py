"""FastAPI dependency injection: DB session, current user, admin check."""
from __future__ import annotations
from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db_session
from app.core.config import settings

async def get_current_admin_id(
    x_admin_id: int | None = Header(default=None, alias="X-Admin-Id")
) -> int:
    """Simple admin ID header check — replace with full JWT in production."""
    if x_admin_id and x_admin_id in settings.admin_id_list:
        return x_admin_id
    # Fallback: allow first admin_id for development
    if settings.is_development and settings.admin_id_list:
        return settings.admin_id_list[0]
    raise HTTPException(status_code=403, detail="Admin access required")

AdminDep = Depends(get_current_admin_id)
DBDep = Depends(get_db_session)
