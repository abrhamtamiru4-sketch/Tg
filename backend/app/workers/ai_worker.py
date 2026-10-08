"""AI Worker — async content generation tasks."""
from __future__ import annotations
import asyncio
from celery.utils.log import get_task_logger
from app.workers.celery_app import celery
log = get_task_logger(__name__)

@celery.task(name="app.workers.ai_worker.generate_content", queue="ai")
def generate_content(post_id: int, operation: str = "rewrite", **kwargs) -> dict:
    return asyncio.new_event_loop().run_until_complete(_generate(post_id, operation, **kwargs))

async def _generate(post_id: int, operation: str, **kwargs) -> dict:
    from app.services.ai.assistant import get_ai_assistant
    from app.db.session import get_db
    from app.db.models import Post
    from sqlalchemy import select
    ai = get_ai_assistant()
    if not ai:
        return {"error": "AI not configured"}
    async with get_db() as db:
        post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
        if not post:
            return {"error": "Post not found"}
        if operation == "rewrite" and post.text:
            result = await ai.rewrite(post.text)
            return {"content": result.content, "provider": result.provider}
        elif operation == "translate":
            lang = kwargs.get("language", "en")
            result = await ai.translate(post.text or post.caption or "", lang)
            return {"content": result.content, "language": lang}
        return {"error": f"Unknown operation: {operation}"}
