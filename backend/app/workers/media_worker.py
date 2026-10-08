"""Media Worker — image processing, thumbnail generation, deduplication."""
from __future__ import annotations
import asyncio
from celery.utils.log import get_task_logger
from app.workers.celery_app import celery
log = get_task_logger(__name__)

@celery.task(name="app.workers.media_worker.process_media", queue="media")
def process_media(media_file_id: int) -> dict:
    return asyncio.new_event_loop().run_until_complete(_process(media_file_id))

async def _process(media_file_id: int) -> dict:
    from sqlalchemy import select
    from app.db.models import MediaFile, MediaType
    from app.db.session import get_db
    from app.services.content.deduplication import get_dedup_engine
    async with get_db() as db:
        mf = (await db.execute(select(MediaFile).where(MediaFile.id == media_file_id))).scalar_one_or_none()
        if not mf or not mf.storage_path:
            return {"error": "Media file not found"}
        if mf.media_type == MediaType.PHOTO and mf.storage_path:
            engine = get_dedup_engine()
            phash = await engine._compute_phash(mf.storage_path)
            if phash:
                mf.perceptual_hash = phash
                await db.commit()
                return {"media_id": media_file_id, "phash": phash}
    return {"media_id": media_file_id, "status": "processed"}
