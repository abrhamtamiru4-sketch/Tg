"""Media API router."""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import MediaFile, MediaType
from app.db.session import get_db_session
import os, hashlib, aiofiles
from app.core.config import settings
router = APIRouter()

@router.get("/")
async def list_media(db: AsyncSession = Depends(get_db_session)):
    rows = (await db.execute(select(MediaFile).limit(100))).scalars().all()
    return [{"id": m.id, "filename": m.filename, "media_type": m.media_type.value, "size_bytes": m.size_bytes} for m in rows]

@router.post("/upload")
async def upload_media(file: UploadFile = File(...), db: AsyncSession = Depends(get_db_session)):
    content = await file.read()
    content_hash = hashlib.sha256(content).hexdigest()
    existing = (await db.execute(select(MediaFile).where(MediaFile.content_hash == content_hash))).scalar_one_or_none()
    if existing:
        return {"id": existing.id, "duplicate": True, "filename": existing.filename}
    os.makedirs(settings.local_media_path, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1]
    save_path = os.path.join(settings.local_media_path, f"{content_hash}{ext}")
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(content)
    ct = file.content_type or ""
    if "image" in ct: mt = MediaType.PHOTO
    elif "video" in ct: mt = MediaType.VIDEO
    elif "audio" in ct: mt = MediaType.AUDIO
    else: mt = MediaType.DOCUMENT
    media = MediaFile(filename=os.path.basename(save_path), original_filename=file.filename,
                      media_type=mt, mime_type=ct, size_bytes=len(content),
                      storage_path=save_path, content_hash=content_hash)
    db.add(media)
    await db.commit()
    await db.refresh(media)
    return {"id": media.id, "filename": media.filename, "size": len(content)}
