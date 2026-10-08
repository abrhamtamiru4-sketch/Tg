"""
Feature flag system.

Every experimental or optional capability is gated behind a flag.
Flags can be read from settings (env vars) and toggled at runtime
via the admin API without restarting the application.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from app.core.config import settings


@dataclass
class FeatureFlag:
    name: str
    description: str
    default: bool
    min_api_version: str | None = None  # e.g. "10.1" for Rich Messages
    _runtime_override: bool | None = field(default=None, init=False, repr=False)

    @property
    def enabled(self) -> bool:
        if self._runtime_override is not None:
            return self._runtime_override
        return self.default

    def enable(self) -> None:
        self._runtime_override = True

    def disable(self) -> None:
        self._runtime_override = False

    def reset(self) -> None:
        """Restore to settings/env default."""
        self._runtime_override = None


class FeatureFlagRegistry:
    """Central registry for all feature flags."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flags: dict[str, FeatureFlag] = {}
        self._callbacks: dict[str, list[Callable[[bool], None]]] = {}

    def register(self, flag: FeatureFlag) -> FeatureFlag:
        with self._lock:
            self._flags[flag.name] = flag
        return flag

    def get(self, name: str) -> FeatureFlag:
        flag = self._flags.get(name)
        if flag is None:
            raise KeyError(f"Unknown feature flag: '{name}'")
        return flag

    def is_enabled(self, name: str) -> bool:
        return self.get(name).enabled

    def enable(self, name: str) -> None:
        flag = self.get(name)
        with self._lock:
            flag.enable()
        self._fire(name, True)

    def disable(self, name: str) -> None:
        flag = self.get(name)
        with self._lock:
            flag.disable()
        self._fire(name, False)

    def toggle(self, name: str) -> bool:
        flag = self.get(name)
        with self._lock:
            new_state = not flag.enabled
            flag._runtime_override = new_state
        self._fire(name, new_state)
        return new_state

    def on_change(self, name: str, callback: Callable[[bool], None]) -> None:
        self._callbacks.setdefault(name, []).append(callback)

    def _fire(self, name: str, state: bool) -> None:
        for cb in self._callbacks.get(name, []):
            try:
                cb(state)
            except Exception:  # pragma: no cover
                pass

    def all_flags(self) -> dict[str, dict]:
        return {
            name: {
                "enabled": flag.enabled,
                "default": flag.default,
                "description": flag.description,
                "min_api_version": flag.min_api_version,
                "runtime_override": flag._runtime_override,
            }
            for name, flag in self._flags.items()
        }


# ── Global registry ───────────────────────────────────────────────────────────
flags = FeatureFlagRegistry()

# Core capabilities (always available with correct bot permissions)
flags.register(FeatureFlag("ANALYTICS", "Post analytics and engagement tracking", default=settings.feature_analytics))
flags.register(FeatureFlag("AUTOMATION", "Automation rule engine (WHEN/IF/THEN)", default=settings.feature_automation))
flags.register(FeatureFlag("INLINE", "Inline mode for content insertion", default=settings.feature_inline))
flags.register(FeatureFlag("CAMPAIGNS", "Campaign management system", default=settings.feature_campaigns))

# Requires AI provider configuration
flags.register(FeatureFlag("AI", "AI content assistant (generate/rewrite/translate)", default=settings.feature_ai))
flags.register(FeatureFlag("AB_TESTING", "A/B content variant testing", default=settings.feature_ab_testing))

# Bot API 10.0 (May 2026)
flags.register(FeatureFlag(
    "GUEST_MODE",
    "Guest mode — bot responds in chats it's not a member of",
    default=settings.feature_guest_mode,
    min_api_version="10.0",
))

# Bot API 10.1 (June 2026)
flags.register(FeatureFlag(
    "RICH_MESSAGES",
    "Rich Messages with structured blocks (paragraphs, tables, collages, etc.)",
    default=settings.feature_rich_messages,
    min_api_version="10.1",
))

# Bot API 10.2 (July 2026)
flags.register(FeatureFlag(
    "EPHEMERAL",
    "Ephemeral messages visible only to a specific user",
    default=settings.feature_ephemeral,
    min_api_version="10.2",
))
flags.register(FeatureFlag(
    "COMMUNITIES",
    "Community management (supergroups + channels linked together)",
    default=settings.feature_communities,
    min_api_version="10.2",
))

# Bot API 10.3 (August 2026)
flags.register(FeatureFlag(
    "DISABLED_BUTTONS",
    "Disabled (greyed-out) inline keyboard buttons",
    default=True,
    min_api_version="10.3",
))
flags.register(FeatureFlag(
    "RICH_MESSAGE_BUTTONS",
    "Buttons attached to Rich Messages",
    default=True,
    min_api_version="10.3",
))
flags.register(FeatureFlag(
    "EXPANDABLE_QUOTE_BLOCKS",
    "Expandable/collapsible block quotations in rich messages",
    default=True,
    min_api_version="10.3",
))

# Infrastructure
flags.register(FeatureFlag("MINI_APP", "Telegram Mini App / Web App interface", default=settings.feature_mini_app))
flags.register(FeatureFlag("MONITORING", "Prometheus metrics and Sentry error tracking", default=settings.feature_monitoring))


# Convenience helpers
def is_enabled(name: str) -> bool:
    return flags.is_enabled(name)


def require_flag(name: str) -> None:
    """Raise if a feature is disabled — use in handlers."""
    if not flags.is_enabled(name):
        from app.core.exceptions import FeatureDisabledError
        raise FeatureDisabledError(name)
