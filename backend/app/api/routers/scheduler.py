"""Scheduler API router."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Schedule, Job, JobStatus
from app.db.session import get_db_session
router = APIRouter()

@router.get("/")
async def list_schedules(db: AsyncSession = Depends(get_db_session)):
    rows = (await db.execute(select(Schedule))).scalars().all()
    return [{"id": s.id, "name": s.name, "is_active": s.is_active, "next_run_at": str(s.next_run_at)} for s in rows]

@router.get("/queue")
async def queue_status(db: AsyncSession = Depends(get_db_session)):
    from sqlalchemy import func
    counts = {}
    for status in JobStatus:
        c = (await db.execute(select(func.count()).where(Job.status == status))).scalar_one()
        counts[status.value] = c
    return counts
