"""
Worker entry point.
Starts Celery workers for the specified queues.
"""
from app.workers.celery_app import celery  # noqa: F401 — imports all tasks

if __name__ == "__main__":
    import sys
    # Usage: python worker_main.py [--queues publisher,media,analytics]
    queues = "publisher,media,analytics,scheduler,source,ai"
    for arg in sys.argv[1:]:
        if arg.startswith("--queues="):
            queues = arg.split("=", 1)[1]
    celery.worker_main([
        "worker",
        "--loglevel=info",
        f"--queues={queues}",
        "--concurrency=2",
    ])
