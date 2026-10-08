"""Auth API router."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import create_access_token, create_refresh_token, verify_password, hash_password
from app.core.exceptions import AuthenticationError
from app.db.models import User, UserRole
from app.db.session import get_db_session

router = APIRouter()


class LoginRequest(BaseModel):
    telegram_id: int
    password: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db_session)):
    user = (await db.execute(
        select(User).where(User.telegram_id == req.telegram_id, User.is_active == True)
    )).scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    from app.core.config import settings
    if req.telegram_id not in settings.admin_id_list:
        raise HTTPException(status_code=403, detail="Access denied")

    access = create_access_token(user.id, extra={"role": user.role.value})
    refresh = create_refresh_token(user.id)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.get("/me")
async def get_me(db: AsyncSession = Depends(get_db_session)):
    """Placeholder — full JWT auth middleware wired in api/deps.py."""
    return {"status": "authenticated"}
