"""Settings API router."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Setting
from app.db.session import get_db_session
from app.core.feature_flags import flags
from app.core.config import settings as cfg
router = APIRouter()

@router.get("/features")
async def get_feature_flags():
    return flags.all_flags()

@router.post("/features/{flag_name}/toggle")
async def toggle_flag(flag_name: str):
    try:
        new_state = flags.toggle(flag_name)
        return {"flag": flag_name, "enabled": new_state}
    except KeyError:
        from fastapi import HTTPException
        raise HTTPException(404, f"Unknown flag: {flag_name}")

@router.get("/")
async def get_settings(db: AsyncSession = Depends(get_db_session)):
    rows = (await db.execute(select(Setting).where(Setting.is_secret == False))).scalars().all()
    return {r.key: r.value for r in rows}
