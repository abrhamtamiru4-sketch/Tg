"""Analytics engine — aggregates publishing metrics."""
from __future__ import annotations
from sqlalchemy import select, func
from app.db.models import AnalyticsEvent, Post, PostStatus, Channel

async def get_summary(db) -> dict:
    total = (await db.execute(select(func.count()).select_from(Post))).scalar_one()
    published = (await db.execute(select(func.count()).where(Post.status == PostStatus.PUBLISHED))).scalar_one()
    failed = (await db.execute(select(func.count()).where(Post.status == PostStatus.FAILED))).scalar_one()
    events = (await db.execute(select(func.count()).select_from(AnalyticsEvent))).scalar_one()
    channels = (await db.execute(select(func.count()).select_from(Channel))).scalar_one()
    return {
        "total_posts": total,
        "published": published,
        "failed": failed,
        "events": events,
        "channels": channels,
        "success_rate": round(published / total * 100, 1) if total else 0,
    }

async def record_event(db, event_type: str, post_id: int | None = None, **kwargs) -> None:
    db.add(AnalyticsEvent(event_type=event_type, post_id=post_id, metadata=kwargs))
    await db.commit()
