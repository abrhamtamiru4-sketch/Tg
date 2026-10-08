"""Queue manager — creates and tracks publish jobs."""
from __future__ import annotations
from datetime import datetime, timezone
from app.db.models import Job, JobStatus, JobPriority
from app.core.security import make_idempotency_key
import shortuuid

async def create_publish_job(
    db,
    post_id: int,
    target_id: int,
    priority: int = JobPriority.NORMAL,
    scheduled_at: datetime | None = None,
) -> Job:
    """Create a Job record and return it (caller enqueues the Celery task)."""
    job_id = str(shortuuid.uuid())
    idem_key = make_idempotency_key(post_id, target_id, scheduled_at.timestamp() if scheduled_at else None)
    job = Job(
        job_id=job_id,
        idempotency_key=idem_key,
        job_type="publish",
        post_id=post_id,
        target_id=target_id,
        priority=priority,
        scheduled_at=scheduled_at or datetime.now(tz=timezone.utc),
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.flush()
    return job
