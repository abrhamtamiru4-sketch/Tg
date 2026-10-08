"""Templates API router."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Template
from app.db.session import get_db_session
from app.services.templates.engine import get_template_engine
router = APIRouter()

class TemplateCreate(BaseModel):
    name: str; text_template: Optional[str] = None; description: Optional[str] = None

@router.get("/")
async def list_templates(db: AsyncSession = Depends(get_db_session)):
    rows = (await db.execute(select(Template).where(Template.is_active == True))).scalars().all()
    return [{"id": t.id, "name": t.name, "description": t.description} for t in rows]

@router.post("/")
async def create_template(data: TemplateCreate, db: AsyncSession = Depends(get_db_session)):
    engine = get_template_engine()
    errors = engine.validate(data.text_template or "")
    if errors:
        raise HTTPException(400, {"detail": "Template syntax errors", "errors": errors})
    tpl = Template(**data.model_dump())
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return {"id": tpl.id, "name": tpl.name}

@router.post("/{template_id}/render")
async def render_template(template_id: int, variables: dict = {}, db: AsyncSession = Depends(get_db_session)):
    tpl = (await db.execute(select(Template).where(Template.id == template_id))).scalar_one_or_none()
    if not tpl: raise HTTPException(404, "Template not found")
    engine = get_template_engine()
    rendered = engine.render(tpl.text_template or "", variables=variables)
    return {"rendered": rendered}
