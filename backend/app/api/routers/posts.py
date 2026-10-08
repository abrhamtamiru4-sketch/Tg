"""Posts API router."""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Post, PostStatus, PostType, PostTarget
from app.db.session import get_db_session
import datetime

router = APIRouter()

class PostCreate(BaseModel):
    title: Optional[str] = None
    text: Optional[str] = None
    caption: Optional[str] = None
    post_type: str = "text"
    channel_ids: list[int] = []
    scheduled_at: Optional[datetime.datetime] = None
    template_id: Optional[int] = None
    tags: list[str] = []

class PostOut(BaseModel):
    id: int; title: Optional[str]; text: Optional[str]
    status: str; post_type: str; created_at: datetime.datetime
    scheduled_at: Optional[datetime.datetime]
    class Config: from_attributes = True

@router.get("/", response_model=list[PostOut])
async def list_posts(
    status: Optional[str] = None, q: Optional[str] = None,
    limit: int = Query(50, le=200), offset: int = 0,
    db: AsyncSession = Depends(get_db_session),
):
    stmt = select(Post).order_by(desc(Post.id)).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(Post.status == status)
    if q:
        stmt = stmt.where(or_(Post.title.ilike(f"%{q}%"), Post.text.ilike(f"%{q}%")))
    return (await db.execute(stmt)).scalars().all()

@router.post("/", response_model=PostOut)
async def create_post(data: PostCreate, db: AsyncSession = Depends(get_db_session)):
    post = Post(
        title=data.title, text=data.text, caption=data.caption,
        post_type=PostType(data.post_type), status=PostStatus.DRAFT,
        scheduled_at=data.scheduled_at, template_id=data.template_id, tags=data.tags,
    )
    db.add(post)
    await db.flush()
    for ch_id in data.channel_ids:
        db.add(PostTarget(post_id=post.id, channel_id=ch_id))
    await db.commit()
    await db.refresh(post)
    return post

@router.get("/{post_id}", response_model=PostOut)
async def get_post(post_id: int, db: AsyncSession = Depends(get_db_session)):
    post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
    if not post: raise HTTPException(404, "Post not found")
    return post

@router.patch("/{post_id}")
async def update_post(post_id: int, data: dict, db: AsyncSession = Depends(get_db_session)):
    post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
    if not post: raise HTTPException(404, "Post not found")
    for k, v in data.items():
        if hasattr(post, k): setattr(post, k, v)
    await db.commit()
    return {"status": "updated"}

@router.delete("/{post_id}")
async def delete_post(post_id: int, db: AsyncSession = Depends(get_db_session)):
    post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
    if not post: raise HTTPException(404, "Post not found")
    post.status = PostStatus.ARCHIVED
    await db.commit()
    return {"status": "archived"}

@router.post("/{post_id}/approve")
async def approve_post(post_id: int, db: AsyncSession = Depends(get_db_session)):
    post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
    if not post: raise HTTPException(404, "Post not found")
    post.status = PostStatus.APPROVED
    await db.commit()
    return {"status": "approved"}

@router.post("/{post_id}/publish")
async def publish_post_now(post_id: int, db: AsyncSession = Depends(get_db_session)):
    """Enqueue post for immediate publishing."""
    post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
    if not post: raise HTTPException(404, "Post not found")
    post.status = PostStatus.APPROVED
    await db.commit()
    targets = (await db.execute(select(PostTarget).where(PostTarget.post_id == post_id))).scalars().all()
    if not targets: raise HTTPException(400, "No targets configured")
    from app.workers.publisher_worker import publish_post as enqueue
    from app.core.security import make_idempotency_key
    from app.db.models import Job, JobStatus, JobPriority
    import shortuuid
    enqueued = 0
    for target in targets:
        job_id = str(shortuuid.uuid())
        idem = make_idempotency_key(post.id, target.id)
        db.add(Job(job_id=job_id, idempotency_key=idem, job_type="publish",
                   post_id=post.id, target_id=target.id, priority=JobPriority.HIGH, status=JobStatus.PENDING))
        await db.flush()
        enqueue.apply_async(args=[post.id, target.id, job_id], priority=JobPriority.HIGH, queue="publisher")
        enqueued += 1
    await db.commit()
    return {"status": "enqueued", "targets": enqueued}

@router.post("/{post_id}/duplicate")
async def duplicate_post(post_id: int, db: AsyncSession = Depends(get_db_session)):
    post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
    if not post: raise HTTPException(404, "Post not found")
    new_post = Post(title=(post.title or "") + " (copy)", text=post.text, caption=post.caption,
                    post_type=post.post_type, status=PostStatus.DRAFT, tags=post.tags)
    db.add(new_post)
    await db.commit()
    await db.refresh(new_post)
    return {"id": new_post.id, "status": "duplicated"}

@router.post("/{post_id}/preflight")
async def preflight_check(post_id: int, target_id: int, db: AsyncSession = Depends(get_db_session)):
    post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
    target = (await db.execute(select(PostTarget).where(PostTarget.id == target_id))).scalar_one_or_none()
    if not post or not target: raise HTTPException(404, "Not found")
    from app.services.publishing.preflight import PreflightValidator
    from app.telegram.client import get_client
    validator = PreflightValidator(get_client())
    result = await validator.validate(post, target, "preflight_check", skip_permission_check=True)
    return {"passed": result.passed, "checks": result.checks, "failed": result.failed}
