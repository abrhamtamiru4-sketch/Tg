"""
Template Engine
===============

Renders Jinja2-powered Telegram post templates.

Built-in variables:
  {{title}}          Post title
  {{description}}    Post description
  {{date}}           Current date (locale-aware)
  {{time}}           Current time
  {{channel_name}}   Target channel name
  {{username}}       Target channel @username
  {{author}}         Post author name
  {{category}}       Content category
  {{hashtags}}       Auto-generated hashtags
  {{source}}         Source name (for RSS posts)
  {{random_quote}}   Random quote from configured list
  {{random_emoji}}   Random emoji from category
  {{short_link}}     Shortened URL (if configured)
  {{tracking_id}}    Unique tracking ID

Custom variables are passed in the variables dict.
"""

from __future__ import annotations

import random
import string
from datetime import datetime, timezone
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, UndefinedError

from app.core.config import settings
from app.core.exceptions import ContentValidationError
from app.core.logging_config import get_logger

log = get_logger(__name__)

# Art/creative emoji categories for @abuta_art style content
EMOJI_CATEGORIES: dict[str, list[str]] = {
    "art": ["🎨", "🖌️", "🖼️", "✏️", "🎭", "🌈", "✨", "💫", "🌟"],
    "ethiopia": ["🇪🇹", "☕", "🌺", "🌍", "🦁", "🐘", "🌄", "🏔️"],
    "digital": ["💻", "📱", "🖥️", "🎮", "🔮", "💡", "⚡", "🚀"],
    "general": ["🔥", "💥", "⭐", "🎯", "💎", "🏆", "🌠", "🎊"],
}


def _generate_tracking_id(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


class TemplateEngine:
    """Render post templates with variable substitution."""

    def __init__(self) -> None:
        self._env = Environment(
            variable_start_string="{{",
            variable_end_string="}}",
            undefined=StrictUndefined,
            autoescape=False,  # Telegram uses HTML, not HTML-escaped
        )

    def render(
        self,
        template_text: str,
        variables: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """
        Render a template string with built-in + custom variables.

        Args:
            template_text: Template with {{variable}} placeholders
            variables: Custom user-defined variables
            context: System context (channel, post, etc.)
        """
        built_ins = self._build_context(context or {})
        all_vars = {**built_ins, **(variables or {})}

        try:
            tpl = self._env.from_string(template_text)
            return tpl.render(**all_vars)
        except UndefinedError as exc:
            raise ContentValidationError(
                f"Template uses undefined variable: {exc}"
            ) from exc
        except TemplateSyntaxError as exc:
            raise ContentValidationError(
                f"Template syntax error at line {exc.lineno}: {exc.message}"
            ) from exc

    def render_post(
        self,
        post_data: dict,
        template_text: str,
        variables: dict | None = None,
        context: dict | None = None,
    ) -> str:
        """Render a template with a full post context dict."""
        merged_context = {**(context or {}), **post_data}
        return self.render(template_text, variables, merged_context)

    def validate(self, template_text: str) -> list[str]:
        """
        Parse a template and return any syntax errors.
        Returns empty list if valid.
        """
        errors = []
        try:
            self._env.parse(template_text)
        except TemplateSyntaxError as exc:
            errors.append(f"Line {exc.lineno}: {exc.message}")
        return errors

    def extract_variables(self, template_text: str) -> list[str]:
        """Return all {{variable}} names referenced in the template."""
        source = self._env.parse(template_text)
        from jinja2 import meta
        return list(meta.find_undeclared_variables(source))

    def _build_context(self, context: dict) -> dict:
        now = datetime.now(tz=timezone.utc)
        tz_name = context.get("timezone", settings.default_timezone)

        # Format dates in local timezone if pytz available
        try:
            import pytz
            tz = pytz.timezone(tz_name)
            now_local = now.astimezone(tz)
        except Exception:
            now_local = now

        return {
            # Date/time
            "date": now_local.strftime("%B %d, %Y"),
            "date_short": now_local.strftime("%d/%m/%Y"),
            "time": now_local.strftime("%H:%M"),
            "datetime": now_local.strftime("%B %d, %Y at %H:%M"),
            "year": str(now_local.year),
            "month": now_local.strftime("%B"),
            "day": now_local.strftime("%A"),

            # Post context
            "title": context.get("title", ""),
            "description": context.get("description", ""),
            "author": context.get("author", ""),
            "category": context.get("category", ""),
            "source": context.get("source", ""),
            "hashtags": context.get("hashtags", ""),
            "short_link": context.get("short_link", ""),

            # Channel context
            "channel_name": context.get("channel_name", ""),
            "username": context.get("username", ""),

            # Utility
            "tracking_id": _generate_tracking_id(),
            "random_emoji": self._random_emoji(context.get("emoji_category", "general")),
            "random_quote": self._random_quote(context.get("quotes", [])),

            # Amharic-friendly date parts
            "am_date": now_local.strftime("%d/%m/%Y"),  # Can be extended
        }

    @staticmethod
    def _random_emoji(category: str) -> str:
        pool = EMOJI_CATEGORIES.get(category, EMOJI_CATEGORIES["general"])
        return random.choice(pool)

    @staticmethod
    def _random_quote(quotes: list[str]) -> str:
        if not quotes:
            return ""
        return random.choice(quotes)


# Module-level singleton
_engine: TemplateEngine | None = None


def get_template_engine() -> TemplateEngine:
    global _engine
    if _engine is None:
        _engine = TemplateEngine()
    return _engine
