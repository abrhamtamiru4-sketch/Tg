"""Channels API router."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Channel
from app.db.session import get_db_session

router = APIRouter()


class ChannelCreate(BaseModel):
    telegram_id: int
    username: str | None = None
    title: str = ""


class ChannelOut(BaseModel):
    id: int
    telegram_id: int
    username: str | None
    title: str
    is_active: bool
    bot_is_admin: bool
    can_post_messages: bool
    member_count: int

    class Config:
        from_attributes = True


@router.get("/", response_model=list[ChannelOut])
async def list_channels(db: AsyncSession = Depends(get_db_session)):
    rows = (await db.execute(select(Channel).where(Channel.is_active == True))).scalars().all()
    return rows


@router.post("/", response_model=ChannelOut)
async def add_channel(data: ChannelCreate, db: AsyncSession = Depends(get_db_session)):
    ch = Channel(**data.model_dump())
    db.add(ch)
    await db.commit()
    await db.refresh(ch)
    return ch


@router.get("/{channel_id}", response_model=ChannelOut)
async def get_channel(channel_id: int, db: AsyncSession = Depends(get_db_session)):
    ch = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
    if not ch:
        raise HTTPException(404, "Channel not found")
    return ch


@router.post("/{channel_id}/verify")
async def verify_channel(channel_id: int, db: AsyncSession = Depends(get_db_session)):
    """Run live permission check against the Telegram API."""
    ch = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
    if not ch:
        raise HTTPException(404, "Channel not found")

    from app.telegram.client import get_client
    from app.telegram.permission_engine import TelegramPermissionEngine
    client = get_client()
    engine = TelegramPermissionEngine(client)
    report = await engine.verify_channel(ch.telegram_id)

    ch.bot_is_admin = report.passed
    ch.last_verified_at = __import__("datetime").datetime.now(tz=__import__("datetime").timezone.utc)
    await db.commit()

    return {"passed": report.passed, "checks": report.checks, "summary": report.summary()}


@router.delete("/{channel_id}")
async def remove_channel(channel_id: int, db: AsyncSession = Depends(get_db_session)):
    ch = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
    if not ch:
        raise HTTPException(404, "Channel not found")
    ch.is_active = False
    await db.commit()
    return {"status": "removed"}
