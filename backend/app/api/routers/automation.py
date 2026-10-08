"""Automation API router."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Workflow
from app.db.session import get_db_session
from app.core.feature_flags import is_enabled
router = APIRouter()

@router.get("/")
async def list_workflows(db: AsyncSession = Depends(get_db_session)):
    if not is_enabled("AUTOMATION"): return {"enabled": False}
    rows = (await db.execute(select(Workflow))).scalars().all()
    return [{"id": w.id, "name": w.name, "is_active": w.is_active, "run_count": w.run_count} for w in rows]

@router.post("/{wf_id}/toggle")
async def toggle(wf_id: int, db: AsyncSession = Depends(get_db_session)):
    wf = (await db.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one_or_none()
    if not wf: raise HTTPException(404, "Not found")
    wf.is_active = not wf.is_active
    await db.commit()
    return {"is_active": wf.is_active}
