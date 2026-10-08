"""In-process scheduler using APScheduler (for lightweight/Termux mode)."""
from __future__ import annotations
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core.logging_config import get_logger
log = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None

def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler

async def start_scheduler() -> None:
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        log.info("apscheduler_started")

async def stop_scheduler() -> None:
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        log.info("apscheduler_stopped")
