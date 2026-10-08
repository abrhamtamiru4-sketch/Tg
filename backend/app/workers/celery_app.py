"""
Celery Application
==================

Task queues:
  publisher   — Telegram publish jobs (high priority)
  scheduler   — Schedule evaluation (runs every minute)
  ai          — AI content generation (low priority)
  source      — RSS/webhook content fetching
  analytics   — Analytics event processing
  media       — Media processing (compress, thumbnail, etc.)

All tasks are idempotent and handle their own error recovery.
Dead-letter queue: celery_dead_letter
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

# ── Application ────────────────────────────────────────────────

celery = Celery(
    "telegram_publisher",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.publisher_worker",
        "app.workers.scheduler_worker",
        "app.workers.source_worker",
        "app.workers.ai_worker",
        "app.workers.analytics_worker",
        "app.workers.media_worker",
    ],
)

celery.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.default_timezone,
    enable_utc=True,

    # Task routing — each queue processed by dedicated workers
    task_routes={
        "app.workers.publisher_worker.*": {"queue": "publisher"},
        "app.workers.scheduler_worker.*": {"queue": "scheduler"},
        "app.workers.ai_worker.*": {"queue": "ai"},
        "app.workers.source_worker.*": {"queue": "source"},
        "app.workers.analytics_worker.*": {"queue": "analytics"},
        "app.workers.media_worker.*": {"queue": "media"},
    },

    # Retry policy defaults
    task_acks_late=True,                 # Ack only after success
    task_reject_on_worker_lost=True,     # Re-queue if worker dies
    worker_prefetch_multiplier=1,        # Don't hog jobs

    # Results
    result_expires=86400,                # Keep results 24h

    # Dead letter
    task_queues_max_priority=10,
    task_default_priority=5,

    # Beat schedule — periodic tasks
    beat_schedule={
        "evaluate-schedules": {
            "task": "app.workers.scheduler_worker.evaluate_schedules",
            "schedule": 60.0,           # Every 60 seconds
            "options": {"queue": "scheduler"},
        },
        "fetch-sources": {
            "task": "app.workers.source_worker.fetch_all_sources",
            "schedule": crontab(minute="*/15"),   # Every 15 minutes
            "options": {"queue": "source"},
        },
        "cleanup-dead-jobs": {
            "task": "app.workers.scheduler_worker.cleanup_dead_jobs",
            "schedule": crontab(hour=3, minute=0),  # Daily at 03:00
            "options": {"queue": "scheduler"},
        },
    },
)
