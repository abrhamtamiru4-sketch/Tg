"""
Scheduler Worker
================

Runs every 60 seconds to evaluate all active schedules.

For each due schedule:
  1. Create a Job record with idempotency key.
  2. Enqueue the publish task.
  3. Update next_run_at for recurring schedules.

Blackout window logic prevents publishing during quiet hours.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from celery.utils.log import get_task_logger

from app.workers.celery_app import celery

log = get_task_logger(__name__)


@celery.task(
    name="app.workers.scheduler_worker.evaluate_schedules",
    queue="scheduler",
)
def evaluate_schedules() -> dict:
    loop = asyncio.new_event_loop()
    return loop.run_until_complete(_evaluate_async())


async def _evaluate_async() -> dict:
    from sqlalchemy import select, and_

    from app.core.security import make_idempotency_key
    from app.db.models import (
        Job, JobStatus, JobPriority, Post, PostStatus,
        PostTarget, Schedule,
    )
    from app.db.session import get_db
    from app.workers.publisher_worker import publish_post
    import shortuuid

    now = datetime.now(tz=timezone.utc)
    enqueued = 0
    errors = 0

    async with get_db() as db:
        due_schedules = (await db.execute(
            select(Schedule).where(
                and_(
                    Schedule.is_active == True,
                    Schedule.next_run_at <= now,
                )
            )
        )).scalars().all()

        for sched in due_schedules:
            try:
                # Check blackout window
                if sched.blackout_config and _is_blacked_out(sched.blackout_config, now):
                    log.info("schedule_blacked_out", schedule_id=sched.id)
                    await _advance_next_run(db, sched, now)
                    continue

                # Check max_runs
                if sched.max_runs and sched.run_count >= sched.max_runs:
                    sched.is_active = False
                    await db.commit()
                    continue

                # Find posts to publish for this schedule
                posts_to_publish: list[Post] = []
                if sched.post_id:
                    post = (await db.execute(
                        select(Post).where(Post.id == sched.post_id)
                    )).scalar_one_or_none()
                    if post and post.status == PostStatus.APPROVED:
                        posts_to_publish.append(post)

                for post in posts_to_publish:
                    targets = (await db.execute(
                        select(PostTarget).where(PostTarget.post_id == post.id)
                    )).scalars().all()

                    for target in targets:
                        job_id = str(shortuuid.uuid())
                        idem_key = make_idempotency_key(
                            post.id, target.id, now.timestamp()
                        )

                        # Skip if already queued/published
                        existing = (await db.execute(
                            select(Job).where(Job.idempotency_key == idem_key)
                        )).scalar_one_or_none()
                        if existing:
                            continue

                        job = Job(
                            job_id=job_id,
                            idempotency_key=idem_key,
                            job_type="publish",
                            post_id=post.id,
                            target_id=target.id,
                            scheduled_at=now,
                            priority=JobPriority.NORMAL,
                            status=JobStatus.PENDING,
                        )
                        db.add(job)
                        await db.flush()

                        # Enqueue
                        publish_post.apply_async(
                            args=[post.id, target.id, job_id],
                            priority=JobPriority.NORMAL,
                            queue="publisher",
                        )
                        enqueued += 1
                        log.info(
                            "job_enqueued",
                            job_id=job_id,
                            post_id=post.id,
                            target_id=target.id,
                        )

                # Update schedule state
                sched.run_count = (sched.run_count or 0) + 1
                sched.last_run_at = now
                await _advance_next_run(db, sched, now)
                await db.commit()

            except Exception as exc:
                errors += 1
                log.error("schedule_evaluation_error", schedule_id=sched.id, error=str(exc))

    log.info("scheduler_cycle_done", enqueued=enqueued, errors=errors)
    return {"enqueued": enqueued, "errors": errors, "evaluated": len(due_schedules)}


async def _advance_next_run(db, sched, now: datetime) -> None:
    """Calculate and persist the next_run_at for a recurring schedule."""
    if not sched.cron_expression:
        # One-time schedule — deactivate
        sched.is_active = False
        sched.next_run_at = None
        await db.commit()
        return

    try:
        from croniter import croniter
        import pytz
        tz = pytz.timezone(sched.timezone or "UTC")
        cron = croniter(sched.cron_expression, now.astimezone(tz))
        next_dt = cron.get_next(datetime)
        sched.next_run_at = next_dt.astimezone(timezone.utc)
        await db.commit()
    except Exception as exc:
        log.error("cron_advance_failed", schedule_id=sched.id, error=str(exc))


def _is_blacked_out(config: dict, now: datetime) -> bool:
    """
    Check if now falls in a blackout window.

    Config format:
      {
        "windows": [
          {"weekday": [0, 6], "hour_start": 22, "hour_end": 8}
        ]
      }
    """
    windows = config.get("windows", [])
    for w in windows:
        weekdays = w.get("weekday", [])
        if weekdays and now.weekday() not in weekdays:
            continue
        h_start = w.get("hour_start", 0)
        h_end = w.get("hour_end", 0)
        if h_start <= h_end:
            if h_start <= now.hour < h_end:
                return True
        else:
            # Overnight window (e.g. 22→8)
            if now.hour >= h_start or now.hour < h_end:
                return True
    return False


@celery.task(
    name="app.workers.scheduler_worker.cleanup_dead_jobs",
    queue="scheduler",
)
def cleanup_dead_jobs() -> dict:
    """Archive dead jobs older than 7 days."""
    loop = asyncio.new_event_loop()
    return loop.run_until_complete(_cleanup_async())


async def _cleanup_async() -> dict:
    from datetime import timedelta
    from sqlalchemy import delete, and_

    from app.db.models import Job, JobStatus
    from app.db.session import get_db

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=7)

    async with get_db() as db:
        result = await db.execute(
            delete(Job).where(
                and_(
                    Job.status.in_([JobStatus.DEAD, JobStatus.SUCCESS]),
                    Job.created_at < cutoff,
                )
            )
        )
        await db.commit()
        deleted = result.rowcount

    log.info("dead_jobs_cleaned", deleted=deleted)
    return {"deleted": deleted}
