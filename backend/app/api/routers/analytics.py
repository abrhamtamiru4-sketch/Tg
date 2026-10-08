"""Analytics API router."""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import AnalyticsEvent, Post, PostStatus
from app.db.session import get_db_session
router = APIRouter()

@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db_session)):
    total_posts = (await db.execute(select(func.count()).select_from(Post))).scalar_one()
    published = (await db.execute(select(func.count()).where(Post.status == PostStatus.PUBLISHED))).scalar_one()
    failed = (await db.execute(select(func.count()).where(Post.status == PostStatus.FAILED))).scalar_one()
    events = (await db.execute(select(func.count()).select_from(AnalyticsEvent))).scalar_one()
    return {"total_posts": total_posts, "published": published, "failed": failed, "events": events}

@router.get("/events")
async def list_events(db: AsyncSession = Depends(get_db_session)):
    rows = (await db.execute(select(AnalyticsEvent).order_by(AnalyticsEvent.id.desc()).limit(100))).scalars().all()
    return [{"id": e.id, "type": e.event_type, "post_id": e.post_id, "created_at": str(e.created_at)} for e in rows]
