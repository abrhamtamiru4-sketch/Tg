"""
Centralised Telegram request rate-limiter.

Telegram limits (per official FAQ):
  • 1 msg / second per chat
  • 20 msgs / minute per group
  • ~30 msgs / second globally (free broadcast)

We stay conservatively below those limits and handle 429 responses
with exponential backoff + Retry-After header respect.

All limits are configurable via settings.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Awaitable, Callable, TypeVar

from app.core.config import settings
from app.core.exceptions import TelegramRateLimitError
from app.core.logging_config import get_logger

log = get_logger(__name__)

T = TypeVar("T")


class _TokenBucket:
    """Simple token bucket for per-entity rate limiting."""

    def __init__(self, rate: float, capacity: float) -> None:
        self.rate = rate        # tokens per second
        self.capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._last_refill = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self.rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


class _SlidingWindow:
    """Sliding window counter for per-group-per-minute limiting."""

    def __init__(self, max_count: int, window_seconds: float = 60.0) -> None:
        self.max_count = max_count
        self.window = window_seconds
        self._times: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            # Drop old entries
            while self._times and now - self._times[0] > self.window:
                self._times.popleft()
            if len(self._times) >= self.max_count:
                sleep_until = self._times[0] + self.window
                await asyncio.sleep(sleep_until - now)
            self._times.append(time.monotonic())


class TelegramRateLimiter:
    """
    Manages Telegram API rate limits at three scopes:
      1. Per-chat (1 msg/sec)
      2. Per-group (20 msg/min)
      3. Global (30 msg/sec)
    """

    def __init__(self) -> None:
        # Global bucket
        self._global = _TokenBucket(
            rate=settings.rate_limit_global_per_second,
            capacity=settings.rate_limit_burst_capacity,
        )
        # Per-chat buckets (created on demand)
        self._per_chat: dict[str, _TokenBucket] = {}
        # Per-group sliding windows
        self._per_group: dict[str, _SlidingWindow] = {}
        # Retry-After state (chat_id → resume_at)
        self._blocked_until: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _chat_bucket(self, chat_id: str) -> _TokenBucket:
        if chat_id not in self._per_chat:
            self._per_chat[chat_id] = _TokenBucket(
                rate=settings.rate_limit_per_chat_per_second,
                capacity=2.0,  # Allow short burst
            )
        return self._per_chat[chat_id]

    def _group_window(self, chat_id: str) -> _SlidingWindow:
        if chat_id not in self._per_group:
            self._per_group[chat_id] = _SlidingWindow(
                max_count=settings.rate_limit_per_group_per_minute
            )
        return self._per_group[chat_id]

    async def check_blocked(self, chat_id: str) -> None:
        blocked = self._blocked_until.get(chat_id, 0)
        if blocked > time.monotonic():
            wait = blocked - time.monotonic()
            log.warning("rate_limit_blocked", chat_id=chat_id, wait_seconds=wait)
            await asyncio.sleep(wait)

    async def acquire(self, chat_id: str, is_group: bool = False) -> None:
        """Wait until it's safe to send a message to chat_id."""
        await self.check_blocked(chat_id)
        await self._global.acquire()
        await self._chat_bucket(chat_id).acquire()
        if is_group:
            await self._group_window(chat_id).acquire()

    def handle_retry_after(self, chat_id: str, retry_after: int) -> None:
        """Call this when Telegram returns a 429 with Retry-After."""
        self._blocked_until[chat_id] = time.monotonic() + retry_after + 1
        log.warning(
            "telegram_rate_limited",
            chat_id=chat_id,
            retry_after=retry_after,
        )


class RetryableRequest:
    """
    Wraps a Telegram API call with exponential backoff retry.

    Retryable errors:
      - 429 Too Many Requests  (with Retry-After)
      - 500/502/503 server errors
      - Network timeouts

    Non-retryable (fail immediately):
      - 400 Bad Request (malformed content)
      - 403 Forbidden (permission denied)
      - 404 Not Found
    """

    RETRYABLE_CODES = {429, 500, 502, 503, 504}
    NON_RETRYABLE_CODES = {400, 401, 403, 404, 409}

    def __init__(
        self,
        fn: Callable[..., Awaitable[T]],
        *args,
        max_attempts: int | None = None,
        base_delay: float | None = None,
        chat_id: str | None = None,
        limiter: TelegramRateLimiter | None = None,
        **kwargs,
    ) -> None:
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._max_attempts = max_attempts or settings.max_retry_attempts
        self._base_delay = base_delay or settings.retry_base_delay
        self._chat_id = chat_id
        self._limiter = limiter

    async def execute(self) -> T:
        from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter, TelegramServerError

        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._fn(*self._args, **self._kwargs)

            except TelegramRetryAfter as exc:
                retry_after = int(exc.retry_after)
                if self._limiter and self._chat_id:
                    self._limiter.handle_retry_after(self._chat_id, retry_after)
                log.warning(
                    "telegram_retry_after",
                    attempt=attempt,
                    retry_after=retry_after,
                    chat_id=self._chat_id,
                )
                await asyncio.sleep(retry_after + 1)

            except TelegramServerError as exc:
                delay = self._base_delay * (2 ** (attempt - 1))
                log.warning(
                    "telegram_server_error",
                    attempt=attempt,
                    delay=delay,
                    error=str(exc),
                )
                if attempt == self._max_attempts:
                    raise
                await asyncio.sleep(delay)

            except TelegramBadRequest as exc:
                # Non-retryable — fail immediately
                log.error("telegram_bad_request", error=str(exc), chat_id=self._chat_id)
                raise

        # Should not reach here
        raise TelegramRateLimitError()


# Module-level singleton
_limiter: TelegramRateLimiter | None = None


def get_rate_limiter() -> TelegramRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = TelegramRateLimiter()
    return _limiter
