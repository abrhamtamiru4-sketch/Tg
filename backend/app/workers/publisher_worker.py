"""
Publisher Worker
================

Celery tasks that execute publish jobs from the queue.

Flow:
  1. Job picked from priority queue
  2. Post + target loaded from DB
  3. Publisher.publish() called
  4. On success → job marked SUCCESS
  5. On retryable error → exponential backoff retry
  6. On non-retryable error → job marked DEAD, admin notified
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from celery import Task
from celery.utils.log import get_task_logger

from app.workers.celery_app import celery

log = get_task_logger(__name__)


class PublishTask(Task):
    """Base class for publish tasks — holds async event loop."""
    abstract = True
    _loop: asyncio.AbstractEventLoop | None = None

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    def run_async(self, coro):
        return self.loop.run_until_complete(coro)


@celery.task(
    bind=True,
    base=PublishTask,
    name="app.workers.publisher_worker.publish_post",
    max_retries=5,
    default_retry_delay=30,
    queue="publisher",
    priority=7,
    acks_late=True,
)
def publish_post(self, post_id: int, target_id: int, job_id: str) -> dict:
    """
    Execute a single publish job.

    Args:
        post_id: Database ID of the post to publish
        target_id: Database ID of the PostTarget
        job_id: Database ID of the Job record

    Returns:
        Result dict with telegram_message_id, chat_id, etc.
    """
    return self.run_async(_publish_async(self, post_id, target_id, job_id))


async def _publish_async(task: PublishTask, post_id: int, target_id: int, job_id: str) -> dict:
    from sqlalchemy import select

    from app.core.exceptions import (
        IdempotencyViolationError,
        PreflightError,
        TelegramPermissionError,
        TelegramRateLimitError,
    )
    from app.db.models import Job, JobStatus, Post, PostTarget
    from app.db.session import get_db
    from app.services.notifications.notifier import get_notifier
    from app.services.publishing.publisher import Publisher
    from app.telegram.client import get_client

    client = get_client()

    async with get_db() as db:
        post = (await db.execute(select(Post).where(Post.id == post_id))).scalar_one_or_none()
        target = (await db.execute(select(PostTarget).where(PostTarget.id == target_id))).scalar_one_or_none()
        job = (await db.execute(select(Job).where(Job.job_id == job_id))).scalar_one_or_none()

        if not post or not target or not job:
            log.error("publish_job_entity_missing", post_id=post_id, target_id=target_id, job_id=job_id)
            return {"error": "Entity not found"}

        publisher = Publisher(client, db)

        try:
            result = await publisher.publish(post, target, job)
            log.info("publish_task_success", job_id=job_id, result=result)
            return result

        except IdempotencyViolationError:
            # Already published — not an error
            log.warning("idempotency_violation", job_id=job_id)
            job.status = JobStatus.SUCCESS
            await db.commit()
            return {"status": "already_published"}

        except PreflightError as exc:
            # Non-retryable — content or permission issue
            log.error("preflight_failed", job_id=job_id, error=str(exc))
            job.status = JobStatus.DEAD
            job.error_type = "preflight"
            job.error_message = str(exc)
            await db.commit()

            notifier = get_notifier()
            await notifier.notify_all(
                level="error",
                title="❌ Publishing Failed (Pre-flight)",
                body=f"Post #{post_id}\n{exc}",
            )
            return {"error": str(exc)}

        except TelegramPermissionError as exc:
            # Non-retryable — admin action required
            log.error("permission_error", job_id=job_id, error=str(exc))
            job.status = JobStatus.DEAD
            job.error_type = "permission"
            job.error_message = str(exc)
            await db.commit()

            notifier = get_notifier()
            await notifier.notify_all(
                level="error",
                title="🚫 Bot Permission Error",
                body=str(exc),
            )
            return {"error": str(exc)}

        except TelegramRateLimitError as exc:
            # Retryable — back off
            job.status = JobStatus.RETRYING
            job.attempts += 1
            job.error_message = str(exc)
            await db.commit()

            countdown = exc.retry_after + 5
            raise task.retry(countdown=countdown, exc=exc, max_retries=10)

        except Exception as exc:
            # Generic retryable error
            job.status = JobStatus.RETRYING
            job.attempts += 1
            job.error_type = type(exc).__name__
            job.error_message = str(exc)
            await db.commit()

            delay = 30 * (2 ** min(task.request.retries, 4))
            log.warning(
                "publish_task_retry",
                job_id=job_id,
                attempt=task.request.retries + 1,
                retry_in=delay,
                error=str(exc),
            )

            if task.request.retries >= task.max_retries - 1:
                job.status = JobStatus.DEAD
                await db.commit()

                notifier = get_notifier()
                await notifier.notify_all(
                    level="critical",
                    title="💀 Job Dead (Max Retries Exceeded)",
                    body=f"Post #{post_id} → Target #{target_id}\nError: {exc}",
                )
                return {"error": str(exc)}

            raise task.retry(countdown=delay, exc=exc)


@celery.task(
    bind=True,
    base=PublishTask,
    name="app.workers.publisher_worker.bulk_publish",
    queue="publisher",
    priority=5,
)
def bulk_publish(self, post_ids: list[int]) -> dict:
    """Enqueue publish jobs for a list of post IDs."""
    results = []
    for post_id in post_ids:
        results.append(
            publish_post.apply_async(
                args=[post_id],
                priority=7,
            )
        )
    return {"enqueued": len(results)}
