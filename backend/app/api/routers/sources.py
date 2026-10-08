"""Sources API router."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Source, SourceType
from app.db.session import get_db_session
router = APIRouter()

class SourceCreate(BaseModel):
    name: str; url: str; source_type: str = "rss"; refresh_interval_seconds: int = 3600

@router.get("/")
async def list_sources(db: AsyncSession = Depends(get_db_session)):
    rows = (await db.execute(select(Source))).scalars().all()
    return [{"id": s.id, "name": s.name, "url": s.url, "type": s.source_type.value, "enabled": s.is_enabled} for s in rows]

@router.post("/")
async def add_source(data: SourceCreate, db: AsyncSession = Depends(get_db_session)):
    from app.workers.source_worker import _is_safe_url
    ok, reason = _is_safe_url(data.url)
    if not ok: raise HTTPException(400, f"URL blocked: {reason}")
    src = Source(name=data.name, url=data.url, source_type=SourceType(data.source_type), refresh_interval_seconds=data.refresh_interval_seconds)
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return {"id": src.id, "name": src.name}

@router.post("/{source_id}/fetch")
async def trigger_fetch(source_id: int):
    from app.workers.source_worker import fetch_all_sources
    fetch_all_sources.apply_async(queue="source")
    return {"status": "fetch_enqueued"}
