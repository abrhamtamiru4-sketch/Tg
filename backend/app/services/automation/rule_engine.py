"""
Automation Rule Engine
======================

Evaluates WHEN/IF/THEN/ELSE workflow rules.

Rule structure (stored as JSON in Workflow.trigger / .conditions / .actions):

WHEN (trigger):
  {
    "type": "rss_update" | "schedule" | "publish_success" | "webhook" | "manual",
    "source_id": 5,            // for rss_update
    "cron": "0 8 * * 1-5",    // for schedule
  }

IF (conditions — all must match):
  [
    {"field": "category", "op": "eq", "value": "technology"},
    {"field": "duplicate_score", "op": "lt", "value": 0.8},
    {"field": "language", "op": "in", "value": ["en", "am"]},
  ]

THEN (actions — executed in order):
  [
    {"type": "translate", "params": {"language": "am"}},
    {"type": "apply_template", "params": {"template_id": 3}},
    {"type": "send_for_approval"},
    {"type": "schedule", "params": {"delay_minutes": 60}},
    {"type": "publish", "params": {"channel_ids": [1, 2]}},
    {"type": "notify_admin", "params": {"message": "New post ready"}},
    {"type": "add_tag", "params": {"tag": "auto-processed"}},
    {"type": "pause_workflow"},
  ]

ELSE (actions when IF fails):
  [{"type": "notify_admin", "params": {"message": "Skipped: conditions not met"}}]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.logging_config import get_logger

log = get_logger(__name__)


@dataclass
class RuleContext:
    """Context passed to every condition and action."""
    trigger_type: str
    trigger_data: dict = field(default_factory=dict)
    post_data: dict = field(default_factory=dict)
    variables: dict = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)


@dataclass
class RuleResult:
    workflow_id: int
    triggered: bool
    conditions_passed: bool
    actions_executed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.triggered and not self.errors


class RuleEngine:
    """
    Evaluates a single Workflow against a trigger event.

    Usage:
        engine = RuleEngine(db)
        result = await engine.evaluate(workflow, context)
    """

    def __init__(self, db) -> None:
        self._db = db

    async def evaluate(self, workflow, context: RuleContext) -> RuleResult:
        result = RuleResult(workflow_id=workflow.id, triggered=False, conditions_passed=False)

        # 1. Check trigger match
        if not self._trigger_matches(workflow.trigger, context):
            log.debug("workflow_trigger_mismatch", workflow_id=workflow.id)
            return result

        result.triggered = True

        # 2. Evaluate IF conditions
        conditions = workflow.conditions or []
        if not self._evaluate_conditions(conditions, context):
            log.debug("workflow_conditions_failed", workflow_id=workflow.id)
            # Execute ELSE actions
            else_actions = workflow.else_actions or []
            for action in else_actions:
                try:
                    await self._execute_action(action, context, result)
                except Exception as exc:
                    result.errors.append(f"else_action/{action.get('type')}: {exc}")
            return result

        result.conditions_passed = True

        # 3. Execute THEN actions
        for action in workflow.actions:
            try:
                await self._execute_action(action, context, result)
                result.actions_executed.append(action.get("type", "unknown"))
            except StopWorkflow:
                log.info("workflow_paused", workflow_id=workflow.id)
                break
            except Exception as exc:
                log.error("workflow_action_error",
                           workflow_id=workflow.id,
                           action=action.get("type"),
                           error=str(exc))
                result.errors.append(f"action/{action.get('type')}: {exc}")
                break  # Stop on first error

        return result

    # ── Trigger matching ──────────────────────────────────────

    @staticmethod
    def _trigger_matches(trigger: dict, context: RuleContext) -> bool:
        trigger_type = trigger.get("type")
        if trigger_type == "manual":
            return context.trigger_type == "manual"
        if trigger_type == "rss_update":
            source_id = trigger.get("source_id")
            return (
                context.trigger_type == "rss_update"
                and (source_id is None or context.trigger_data.get("source_id") == source_id)
            )
        if trigger_type == "publish_success":
            return context.trigger_type == "publish_success"
        if trigger_type == "publish_failure":
            return context.trigger_type == "publish_failure"
        if trigger_type in ("schedule", "webhook", "new_content"):
            return context.trigger_type == trigger_type
        return False

    # ── Condition evaluation ──────────────────────────────────

    @staticmethod
    def _evaluate_conditions(conditions: list[dict], context: RuleContext) -> bool:
        """All conditions must pass (AND logic)."""
        for cond in conditions:
            field_name = cond.get("field", "")
            op = cond.get("op", "eq")
            expected = cond.get("value")

            # Resolve field value from context
            value = (
                context.post_data.get(field_name)
                or context.trigger_data.get(field_name)
                or context.variables.get(field_name)
            )

            if not _compare(value, op, expected):
                log.debug("condition_failed", field=field_name, op=op, value=value, expected=expected)
                return False
        return True

    # ── Action execution ──────────────────────────────────────

    async def _execute_action(
        self,
        action: dict,
        context: RuleContext,
        result: RuleResult,
    ) -> None:
        action_type = action.get("type")
        params = action.get("params", {})

        log.debug("executing_action", action_type=action_type, workflow_id=result.workflow_id)

        if action_type == "translate":
            await self._action_translate(params, context)

        elif action_type == "apply_template":
            await self._action_apply_template(params, context)

        elif action_type == "send_for_approval":
            await self._action_send_for_approval(context)

        elif action_type == "schedule":
            await self._action_schedule(params, context)

        elif action_type == "publish":
            await self._action_publish(params, context)

        elif action_type == "notify_admin":
            await self._action_notify_admin(params)

        elif action_type == "add_tag":
            await self._action_add_tag(params, context)

        elif action_type == "pause_workflow":
            raise StopWorkflow()

        elif action_type == "start_campaign":
            await self._action_start_campaign(params)

        elif action_type == "generate_ai_content":
            await self._action_ai_content(params, context)

        else:
            log.warning("unknown_action_type", action_type=action_type)

    async def _action_translate(self, params: dict, context: RuleContext) -> None:
        from app.services.ai.assistant import get_ai_assistant
        ai = get_ai_assistant()
        if ai and context.post_data.get("text"):
            result = await ai.translate(
                context.post_data["text"],
                target_language=params.get("language", "en"),
            )
            context.variables["translated_text"] = result.content

    async def _action_apply_template(self, params: dict, context: RuleContext) -> None:
        template_id = params.get("template_id")
        if not template_id:
            return
        from sqlalchemy import select
        from app.db.models import Template
        from app.services.templates.engine import get_template_engine

        template = (await self._db.execute(
            select(Template).where(Template.id == template_id)
        )).scalar_one_or_none()

        if template and template.text_template:
            engine = get_template_engine()
            rendered = engine.render(template.text_template, context=context.post_data)
            context.variables["rendered_text"] = rendered

    async def _action_send_for_approval(self, context: RuleContext) -> None:
        post_id = context.post_data.get("post_id")
        if post_id:
            from app.db.models import Post, PostStatus
            from sqlalchemy import select
            post = (await self._db.execute(
                select(Post).where(Post.id == post_id)
            )).scalar_one_or_none()
            if post:
                post.status = PostStatus.PENDING_REVIEW
                await self._db.commit()

    async def _action_schedule(self, params: dict, context: RuleContext) -> None:
        from datetime import datetime, timedelta, timezone
        delay_minutes = params.get("delay_minutes", 0)
        scheduled_at = datetime.now(tz=timezone.utc) + timedelta(minutes=delay_minutes)
        context.variables["scheduled_at"] = scheduled_at.isoformat()

    async def _action_publish(self, params: dict, context: RuleContext) -> None:
        post_id = context.post_data.get("post_id")
        if not post_id:
            return
        from app.workers.publisher_worker import publish_post
        import shortuuid
        publish_post.apply_async(
            args=[post_id],
            kwargs={},
            queue="publisher",
        )

    async def _action_notify_admin(self, params: dict) -> None:
        from app.services.notifications.notifier import get_notifier
        notifier = get_notifier()
        await notifier.notify_all(
            "info",
            "🤖 Automation",
            params.get("message", "Workflow action executed"),
        )

    async def _action_add_tag(self, params: dict, context: RuleContext) -> None:
        post_id = context.post_data.get("post_id")
        tag = params.get("tag")
        if post_id and tag:
            from sqlalchemy import select
            from app.db.models import Post
            post = (await self._db.execute(
                select(Post).where(Post.id == post_id)
            )).scalar_one_or_none()
            if post:
                tags = list(post.tags or [])
                if tag not in tags:
                    tags.append(tag)
                    post.tags = tags
                    await self._db.commit()

    async def _action_start_campaign(self, params: dict) -> None:
        campaign_id = params.get("campaign_id")
        if campaign_id:
            from sqlalchemy import select
            from app.db.models import Campaign, CampaignStatus
            campaign = (await self._db.execute(
                select(Campaign).where(Campaign.id == campaign_id)
            )).scalar_one_or_none()
            if campaign:
                campaign.status = CampaignStatus.ACTIVE
                await self._db.commit()

    async def _action_ai_content(self, params: dict, context: RuleContext) -> None:
        from app.services.ai.assistant import get_ai_assistant
        ai = get_ai_assistant()
        if ai:
            operation = params.get("operation", "rewrite")
            text = context.post_data.get("text", "")
            if operation == "rewrite" and text:
                result = await ai.rewrite(text, params.get("instruction", "Improve engagement"))
                context.variables["ai_content"] = result.content


class StopWorkflow(Exception):
    """Raised by pause_workflow action to halt the current workflow run."""


def _compare(value: Any, op: str, expected: Any) -> bool:
    """Evaluate a single condition."""
    if op == "eq":
        return value == expected
    elif op == "ne":
        return value != expected
    elif op == "lt":
        return value is not None and float(value) < float(expected)
    elif op == "lte":
        return value is not None and float(value) <= float(expected)
    elif op == "gt":
        return value is not None and float(value) > float(expected)
    elif op == "gte":
        return value is not None and float(value) >= float(expected)
    elif op == "in":
        return value in (expected or [])
    elif op == "not_in":
        return value not in (expected or [])
    elif op == "contains":
        return expected in str(value or "")
    elif op == "starts_with":
        return str(value or "").startswith(str(expected))
    elif op == "is_null":
        return value is None
    elif op == "is_not_null":
        return value is not None
    return False
