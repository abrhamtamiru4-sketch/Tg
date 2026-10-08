"""Analytics Worker — processes and aggregates analytics events."""
from __future__ import annotations
import asyncio
from celery.utils.log import get_task_logger
from app.workers.celery_app import celery
log = get_task_logger(__name__)

@celery.task(name="app.workers.analytics_worker.process_event", queue="analytics")
def process_event(event_type: str, post_id: int | None = None, **metadata) -> dict:
    return asyncio.new_event_loop().run_until_complete(_process(event_type, post_id, metadata))

async def _process(event_type: str, post_id: int | None, metadata: dict) -> dict:
    from app.db.models import AnalyticsEvent
    from app.db.session import get_db
    async with get_db() as db:
        db.add(AnalyticsEvent(event_type=event_type, post_id=post_id, metadata=metadata))
        await db.commit()
    return {"status": "recorded", "event_type": event_type}
