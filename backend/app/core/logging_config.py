"""
Structured logging using structlog.

All log events are JSON objects, making them easy to ingest into
Grafana Loki, Datadog, ELK, or any log aggregator.
Secrets are never logged — see add_secret_filter().
"""

from __future__ import annotations

import logging
import re
import sys

import structlog

from app.core.config import settings

# Patterns that must never appear in logs
_REDACT_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{35}\b"),   # Bot tokens
    re.compile(r"(?i)(password|secret|token|api_key)\s*[=:]\s*\S+"),
    re.compile(r"\b[A-Z0-9]{20,}\b"),                  # Long uppercase keys
]
_REDACTED = "[REDACTED]"


def _redact_secrets(logger, method_name, event_dict: dict) -> dict:
    """Processor: replace sensitive strings in all string values."""
    for key, value in event_dict.items():
        if isinstance(value, str):
            for pattern in _REDACT_PATTERNS:
                value = pattern.sub(_REDACTED, value)
            event_dict[key] = value
    return event_dict


def configure_logging() -> None:
    """Call once at application startup."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _redact_secrets,
    ]

    if settings.is_development:
        # Pretty dev output
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        # Production: JSON
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Quieten noisy libraries
    for noisy in ("aiohttp", "aiogram", "celery", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    return structlog.get_logger(name)
