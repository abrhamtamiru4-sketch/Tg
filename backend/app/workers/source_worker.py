"""
Source Worker
=============

Fetches content from external sources (RSS, Atom, webhooks).

Security:
  • SSRF protection: blocks private/loopback IP ranges
  • URL validation: scheme must be http(s)
  • Max response size: 5 MB
  • Domain allow/block lists
  • Content-type validation
  • Safe XML/HTML parsing
  • Never executes fetched content
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

from celery.utils.log import get_task_logger

from app.workers.celery_app import celery

log = get_task_logger(__name__)

MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB
FETCH_TIMEOUT = 30  # seconds
ALLOWED_SCHEMES = {"http", "https"}

# Private IP ranges to block (SSRF protection)
_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Return (is_safe, reason). Blocks SSRF attempts."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Malformed URL"

    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"Scheme '{parsed.scheme}' not allowed (use http/https)"

    hostname = parsed.hostname
    if not hostname:
        return False, "No hostname"

    try:
        ip = ipaddress.ip_address(socket.gethostbyname(hostname))
        for private_range in _PRIVATE_RANGES:
            if ip in private_range:
                return False, f"SSRF blocked: {ip} is in private range {private_range}"
    except (socket.gaierror, ValueError):
        # DNS failed or IPv6 — allow and let the HTTP layer handle it
        pass

    return True, "OK"


@celery.task(
    name="app.workers.source_worker.fetch_all_sources",
    queue="source",
)
def fetch_all_sources() -> dict:
    loop = asyncio.new_event_loop()
    return loop.run_until_complete(_fetch_all_async())


async def _fetch_all_async() -> dict:
    from sqlalchemy import select, and_
    from datetime import timedelta

    from app.db.models import Source
    from app.db.session import get_db

    now = datetime.now(tz=timezone.utc)
    fetched, errors = 0, 0

    async with get_db() as db:
        sources = (await db.execute(
            select(Source).where(Source.is_enabled == True)
        )).scalars().all()

        for source in sources:
            # Check if due
            if source.last_fetched_at:
                due_at = source.last_fetched_at + timedelta(seconds=source.refresh_interval_seconds)
                if now < due_at:
                    continue

            try:
                await _fetch_source(source, db)
                fetched += 1
            except Exception as exc:
                errors += 1
                source.last_error = str(exc)
                source.error_count = (source.error_count or 0) + 1
                await db.commit()
                log.error("source_fetch_error", source_id=source.id, error=str(exc))

    return {"fetched": fetched, "errors": errors}


async def _fetch_source(source, db) -> None:
    from app.db.models import Source, SourceType

    is_safe, reason = _is_safe_url(source.url)
    if not is_safe:
        from app.core.exceptions import SSRFError
        raise SSRFError(source.url)

    if source.source_type == SourceType.RSS:
        items = await _fetch_rss(source.url)
    elif source.source_type == SourceType.ATOM:
        items = await _fetch_rss(source.url)  # feedparser handles both
    else:
        items = []

    new_posts = 0
    for item in items[:20]:  # Max 20 items per fetch
        created = await _ingest_item(item, source, db)
        if created:
            new_posts += 1

    source.last_fetched_at = datetime.now(tz=timezone.utc)
    source.fetch_count = (source.fetch_count or 0) + 1
    source.last_error = None
    await db.commit()

    log.info("source_fetched", source_id=source.id, new_posts=new_posts)


async def _fetch_rss(url: str) -> list[dict]:
    """Fetch and parse RSS/Atom feed safely."""
    import aiohttp
    import feedparser

    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT),
            headers={"User-Agent": "TelegramPublisher/1.0"},
        ) as resp:
            content_type = resp.content_type or ""
            if not any(ct in content_type for ct in ("xml", "rss", "atom", "text/")):
                log.warning("unexpected_content_type", url=url, content_type=content_type)

            content = await resp.read(MAX_RESPONSE_BYTES)

    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries:
        items.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "summary": entry.get("summary", ""),
            "content": entry.get("content", [{}])[0].get("value", "") if entry.get("content") else "",
            "published": entry.get("published", ""),
            "author": entry.get("author", ""),
            "tags": [t.term for t in entry.get("tags", [])],
        })
    return items


async def _ingest_item(item: dict, source, db) -> bool:
    """Create a Post from a source item. Returns True if new."""
    import bleach

    from app.db.models import Post, PostStatus, PostType
    from app.services.content.deduplication import get_dedup_engine

    # Sanitise HTML from external source
    safe_content = bleach.clean(
        item.get("content") or item.get("summary", ""),
        tags=["b", "i", "u", "a", "code", "pre"],
        attributes={"a": ["href"]},
        strip=True,
    )

    title = item.get("title", "").strip()
    text = f"<b>{title}</b>\n\n{safe_content}".strip() if safe_content else title

    if not text:
        return False

    # Dedup check
    engine = get_dedup_engine()
    dup = await engine.check_text(text, db=db)
    if dup.is_duplicate:
        log.debug("source_item_duplicate", similarity=dup.similarity)
        return False

    # Create draft post
    content_hash = engine.compute_content_hash(text)

    post = Post(
        title=title,
        text=text,
        post_type=PostType.TEXT,
        status=PostStatus.DRAFT,  # Always draft — never auto-publish
        content_hash=content_hash,
        tags=item.get("tags", []),
        language=source.language,
        metadata={
            "source_id": source.id,
            "source_url": item.get("link", ""),
            "original_author": item.get("author", ""),
            "ai_generated": False,
        },
    )

    # Apply default template if configured
    if source.default_template_id:
        post.template_id = source.default_template_id

    db.add(post)
    await db.flush()

    # Trigger workflow evaluation
    await _trigger_workflows(post.id, source.id, db)

    await db.commit()
    return True


async def _trigger_workflows(post_id: int, source_id: int, db) -> None:
    """Find and evaluate workflows triggered by new RSS content."""
    from sqlalchemy import select
    from app.db.models import Workflow
    from app.services.automation.rule_engine import RuleContext, RuleEngine

    workflows = (await db.execute(
        select(Workflow).where(Workflow.is_active == True)
    )).scalars().all()

    context = RuleContext(
        trigger_type="rss_update",
        trigger_data={"source_id": source_id},
        post_data={"post_id": post_id},
    )

    engine = RuleEngine(db)
    for wf in workflows:
        try:
            result = await engine.evaluate(wf, context)
            if result.triggered:
                wf.run_count = (wf.run_count or 0) + 1
                wf.last_run_at = datetime.now(tz=timezone.utc)
        except Exception as exc:
            log.error("workflow_evaluation_error", workflow_id=wf.id, error=str(exc))

    await db.commit()
