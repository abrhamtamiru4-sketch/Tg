"""Campaigns API router."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Campaign, CampaignStatus
from app.db.session import get_db_session
router = APIRouter()

@router.get("/")
async def list_campaigns(db: AsyncSession = Depends(get_db_session)):
    rows = (await db.execute(select(Campaign))).scalars().all()
    return [{"id": c.id, "name": c.name, "status": c.status.value} for c in rows]

@router.post("/{campaign_id}/activate")
async def activate(campaign_id: int, db: AsyncSession = Depends(get_db_session)):
    c = (await db.execute(select(Campaign).where(Campaign.id == campaign_id))).scalar_one_or_none()
    if not c: raise HTTPException(404, "Campaign not found")
    c.status = CampaignStatus.ACTIVE
    await db.commit()
    return {"status": "active"}
