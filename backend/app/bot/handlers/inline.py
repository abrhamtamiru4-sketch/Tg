"""
Inline mode handler.

Allows admins to search published posts and templates and insert them
into any chat by typing @botname <query>.

Requires inline mode enabled via @BotFather.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import (
    ChosenInlineResult,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from app.core.config import settings
from app.core.feature_flags import is_enabled
from app.core.logging_config import get_logger

log = get_logger(__name__)
router = Router(name="inline")


@router.inline_query()
async def handle_inline_query(inline_query: InlineQuery) -> None:
    if not is_enabled("INLINE"):
        await inline_query.answer([], cache_time=5)
        return

    # Only admins can use inline mode for this bot
    if inline_query.from_user.id not in settings.admin_id_list:
        await inline_query.answer(
            [],
            cache_time=60,
            switch_pm_text="Admin access required",
            switch_pm_parameter="start",
        )
        return

    query = inline_query.query.strip()
    results = []

    try:
        posts = await _search_posts(query)
        for post in posts[:30]:  # Max 50, but keep under 30 for performance
            preview = (post.get("text") or post.get("caption") or "")[:100]
            results.append(
                InlineQueryResultArticle(
                    id=f"post_{post['id']}",
                    title=post.get("title") or f"Post #{post['id']}",
                    description=preview or post.get("status", ""),
                    input_message_content=InputTextMessageContent(
                        message_text=post.get("text") or post.get("caption") or "",
                        parse_mode="HTML",
                    ),
                    thumbnail_url=post.get("thumb_url"),
                )
            )

        # Also search templates
        templates = await _search_templates(query)
        for tpl in templates[:10]:
            results.append(
                InlineQueryResultArticle(
                    id=f"tpl_{tpl['id']}",
                    title=f"📋 {tpl['name']}",
                    description=tpl.get("description") or "Template",
                    input_message_content=InputTextMessageContent(
                        message_text=tpl.get("text_template") or f"[Template: {tpl['name']}]",
                        parse_mode="HTML",
                    ),
                )
            )

    except Exception as exc:
        log.error("inline_query_error", error=str(exc))

    await inline_query.answer(results, cache_time=30)


@router.chosen_inline_result()
async def handle_chosen_inline(chosen: ChosenInlineResult) -> None:
    """Track which inline results were actually used."""
    from app.db.models import AnalyticsEvent
    from app.db.session import get_db

    log.info(
        "inline_result_chosen",
        result_id=chosen.result_id,
        user_id=chosen.from_user.id,
        query=chosen.query,
    )

    try:
        async with get_db() as db:
            db.add(AnalyticsEvent(
                event_type="inline_used",
                metadata={"result_id": chosen.result_id, "query": chosen.query},
            ))
            await db.commit()
    except Exception:
        pass


async def _search_posts(query: str) -> list[dict]:
    from sqlalchemy import select, or_
    from app.db.models import Post, PostStatus
    from app.db.session import get_db

    async with get_db() as db:
        stmt = (
            select(Post)
            .where(Post.status.in_([PostStatus.PUBLISHED, PostStatus.APPROVED, PostStatus.DRAFT]))
            .order_by(Post.id.desc())
            .limit(20)
        )
        if query:
            stmt = stmt.where(
                or_(
                    Post.title.ilike(f"%{query}%"),
                    Post.text.ilike(f"%{query}%"),
                )
            )
        posts = (await db.execute(stmt)).scalars().all()
        return [
            {
                "id": p.id,
                "title": p.title,
                "text": p.text,
                "caption": p.caption,
                "status": p.status.value,
            }
            for p in posts
        ]


async def _search_templates(query: str) -> list[dict]:
    from sqlalchemy import select
    from app.db.models import Template
    from app.db.session import get_db

    async with get_db() as db:
        stmt = (
            select(Template)
            .where(Template.is_active == True)
            .order_by(Template.id.desc())
            .limit(10)
        )
        if query:
            stmt = stmt.where(Template.name.ilike(f"%{query}%"))
        templates = (await db.execute(stmt)).scalars().all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "text_template": t.text_template,
            }
            for t in templates
        ]
