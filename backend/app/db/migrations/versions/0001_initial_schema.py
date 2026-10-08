"""Initial schema — all tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-01
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users
    op.create_table("users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger, unique=True, nullable=False),
        sa.Column("username", sa.String(64)),
        sa.Column("first_name", sa.String(64), default=""),
        sa.Column("last_name", sa.String(64)),
        sa.Column("role", sa.String(32), default="viewer"),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("hashed_password", sa.String(128)),
        sa.Column("language_code", sa.String(8), default="en"),
        sa.Column("timezone", sa.String(64), default="UTC"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("settings", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])
    op.create_index("ix_users_role", "users", ["role"])

    # api_keys
    op.create_table("api_keys",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(64), default="Default"),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])

    # channels
    op.create_table("channels",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("telegram_id", sa.BigInteger, unique=True, nullable=False),
        sa.Column("username", sa.String(64)),
        sa.Column("title", sa.String(256), default=""),
        sa.Column("description", sa.Text),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("bot_is_admin", sa.Boolean, default=False),
        sa.Column("can_post_messages", sa.Boolean, default=False),
        sa.Column("can_pin_messages", sa.Boolean, default=False),
        sa.Column("member_count", sa.Integer, default=0),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("timezone", sa.String(64), default="UTC"),
        sa.Column("default_parse_mode", sa.String(16), default="HTML"),
        sa.Column("default_signature", sa.Text),
        sa.Column("default_disable_notification", sa.Boolean, default=False),
        sa.Column("default_protect_content", sa.Boolean, default=False),
        sa.Column("posting_limits", sa.JSON),
        sa.Column("config", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_channels_telegram_id", "channels", ["telegram_id"])

    # groups
    op.create_table("groups",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("telegram_id", sa.BigInteger, unique=True, nullable=False),
        sa.Column("username", sa.String(64)),
        sa.Column("title", sa.String(256), default=""),
        sa.Column("is_supergroup", sa.Boolean, default=False),
        sa.Column("is_forum", sa.Boolean, default=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("bot_is_admin", sa.Boolean, default=False),
        sa.Column("member_count", sa.Integer, default=0),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("moderation_config", sa.JSON),
        sa.Column("config", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_groups_telegram_id", "groups", ["telegram_id"])

    # topics
    op.create_table("topics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("group_id", sa.Integer, sa.ForeignKey("groups.id"), nullable=False),
        sa.Column("telegram_thread_id", sa.Integer, nullable=False),
        sa.Column("name", sa.String(128), default=""),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("is_closed", sa.Boolean, default=False),
        sa.Column("icon_emoji", sa.String(16)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id", "telegram_thread_id"),
    )

    # campaigns (before posts due to FK)
    op.create_table("campaigns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("status", sa.String(32), default="draft"),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("config", sa.JSON),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_campaigns_status", "campaigns", ["status"])

    # templates (before posts due to FK)
    op.create_table("templates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("folder", sa.String(64)),
        sa.Column("version", sa.Integer, default=1),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("text_template", sa.Text),
        sa.Column("caption_template", sa.Text),
        sa.Column("reply_markup_template", sa.JSON),
        sa.Column("default_hashtags", sa.String(512)),
        sa.Column("default_post_type", sa.String(32), default="text"),
        sa.Column("variables_schema", sa.JSON),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # posts
    op.create_table("posts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(256)),
        sa.Column("text", sa.Text),
        sa.Column("caption", sa.Text),
        sa.Column("post_type", sa.String(32), default="text"),
        sa.Column("status", sa.String(32), default="draft"),
        sa.Column("parse_mode", sa.String(16), default="HTML"),
        sa.Column("author_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("reply_markup", sa.JSON),
        sa.Column("rich_message", sa.JSON),
        sa.Column("poll_data", sa.JSON),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("media_hash", sa.String(64)),
        sa.Column("campaign_id", sa.Integer, sa.ForeignKey("campaigns.id")),
        sa.Column("template_id", sa.Integer, sa.ForeignKey("templates.id")),
        sa.Column("ab_variant", sa.String(8)),
        sa.Column("ab_group_id", sa.String(64)),
        sa.Column("tags", sa.JSON),
        sa.Column("language", sa.String(8)),
        sa.Column("notes", sa.Text),
        sa.Column("metadata", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_posts_status", "posts", ["status"])
    op.create_index("ix_posts_scheduled_at", "posts", ["scheduled_at"])
    op.create_index("ix_posts_content_hash", "posts", ["content_hash"])

    # post_versions
    op.create_table("post_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("post_id", sa.Integer, sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("snapshot", sa.JSON, nullable=False),
        sa.Column("changed_by_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("change_note", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_post_versions_post_id", "post_versions", ["post_id"])

    # post_targets
    op.create_table("post_targets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("post_id", sa.Integer, sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("channel_id", sa.Integer, sa.ForeignKey("channels.id")),
        sa.Column("group_id", sa.Integer, sa.ForeignKey("groups.id")),
        sa.Column("topic_id", sa.Integer, sa.ForeignKey("topics.id")),
        sa.Column("custom_caption", sa.Text),
        sa.Column("custom_reply_markup", sa.JSON),
        sa.Column("custom_hashtags", sa.String(512)),
        sa.Column("custom_signature", sa.String(256)),
        sa.Column("disable_notification", sa.Boolean, default=False),
        sa.Column("protect_content", sa.Boolean, default=False),
        sa.Column("pin_after_publish", sa.Boolean, default=False),
        sa.Column("status", sa.String(32), default="pending_review"),
        sa.Column("telegram_message_id", sa.BigInteger),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text),
        sa.Column("attempts", sa.Integer, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_post_targets_post_id", "post_targets", ["post_id"])

    # media_files
    op.create_table("media_files",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("filename", sa.String(256), default=""),
        sa.Column("original_filename", sa.String(256)),
        sa.Column("media_type", sa.String(32)),
        sa.Column("mime_type", sa.String(128)),
        sa.Column("size_bytes", sa.BigInteger, default=0),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("duration_seconds", sa.Float),
        sa.Column("storage_path", sa.String(512)),
        sa.Column("storage_provider", sa.String(32), default="local"),
        sa.Column("telegram_file_id", sa.String(256)),
        sa.Column("telegram_file_unique_id", sa.String(128)),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("perceptual_hash", sa.String(64)),
        sa.Column("tags", sa.JSON),
        sa.Column("folder", sa.String(128)),
        sa.Column("alt_text", sa.String(256)),
        sa.Column("uploaded_by_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_media_telegram_file_id", "media_files", ["telegram_file_id"])
    op.create_index("ix_media_content_hash", "media_files", ["content_hash"])

    # post_media
    op.create_table("post_media",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("post_id", sa.Integer, sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("media_file_id", sa.Integer, sa.ForeignKey("media_files.id"), nullable=False),
        sa.Column("position", sa.Integer, default=0),
        sa.Column("caption", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_post_media_post_id", "post_media", ["post_id"])

    # schedules
    op.create_table("schedules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), default=""),
        sa.Column("post_id", sa.Integer, sa.ForeignKey("posts.id")),
        sa.Column("campaign_id", sa.Integer, sa.ForeignKey("campaigns.id")),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("cron_expression", sa.String(128)),
        sa.Column("timezone", sa.String(64), default="UTC"),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("run_count", sa.Integer, default=0),
        sa.Column("max_runs", sa.Integer),
        sa.Column("blackout_config", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_schedules_next_run_at", "schedules", ["next_run_at"])

    # jobs
    op.create_table("jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.String(64), unique=True, nullable=False),
        sa.Column("idempotency_key", sa.String(64), unique=True, nullable=False),
        sa.Column("job_type", sa.String(64), default="publish"),
        sa.Column("post_id", sa.Integer, sa.ForeignKey("posts.id")),
        sa.Column("target_id", sa.Integer, sa.ForeignKey("post_targets.id")),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("priority", sa.Integer, default=5),
        sa.Column("status", sa.String(32), default="pending"),
        sa.Column("attempts", sa.Integer, default=0),
        sa.Column("max_attempts", sa.Integer, default=5),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_type", sa.String(64)),
        sa.Column("error_message", sa.Text),
        sa.Column("result", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_scheduled_at", "jobs", ["scheduled_at"])
    op.create_index("ix_jobs_idempotency_key", "jobs", ["idempotency_key"])

    # sources
    op.create_table("sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("source_type", sa.String(32), default="rss"),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("category", sa.String(64)),
        sa.Column("language", sa.String(8)),
        sa.Column("refresh_interval_seconds", sa.Integer, default=3600),
        sa.Column("is_enabled", sa.Boolean, default=True),
        sa.Column("priority", sa.Integer, default=5),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        sa.Column("fetch_count", sa.Integer, default=0),
        sa.Column("error_count", sa.Integer, default=0),
        sa.Column("config", sa.JSON),
        sa.Column("default_template_id", sa.Integer, sa.ForeignKey("templates.id")),
        sa.Column("default_target_channel_ids", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # workflows
    op.create_table("workflows",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("trigger", sa.JSON, nullable=False),
        sa.Column("conditions", sa.JSON),
        sa.Column("actions", sa.JSON, nullable=False),
        sa.Column("else_actions", sa.JSON),
        sa.Column("run_count", sa.Integer, default=0),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # workflow_runs
    op.create_table("workflow_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workflow_id", sa.Integer, sa.ForeignKey("workflows.id"), nullable=False),
        sa.Column("status", sa.String(32), default="running"),
        sa.Column("trigger_data", sa.JSON),
        sa.Column("result", sa.JSON),
        sa.Column("error", sa.Text),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])

    # analytics_events
    op.create_table("analytics_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("post_id", sa.Integer, sa.ForeignKey("posts.id")),
        sa.Column("target_id", sa.Integer, sa.ForeignKey("post_targets.id")),
        sa.Column("channel_id", sa.Integer, sa.ForeignKey("channels.id")),
        sa.Column("campaign_id", sa.Integer, sa.ForeignKey("campaigns.id")),
        sa.Column("telegram_message_id", sa.BigInteger),
        sa.Column("reaction_emoji", sa.String(64)),
        sa.Column("user_telegram_id", sa.BigInteger),
        sa.Column("value", sa.Float),
        sa.Column("metadata", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_analytics_event_type", "analytics_events", ["event_type"])
    op.create_index("ix_analytics_created_at", "analytics_events", ["created_at"])

    # audit_logs
    op.create_table("audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("role", sa.String(32)),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64)),
        sa.Column("resource_id", sa.Integer),
        sa.Column("old_value", sa.JSON),
        sa.Column("new_value", sa.JSON),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.String(256)),
        sa.Column("result", sa.String(16), default="success"),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_action", "audit_logs", ["action"])
    op.create_index("ix_audit_created_at", "audit_logs", ["created_at"])

    # settings
    op.create_table("settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(128), unique=True, nullable=False),
        sa.Column("value", sa.JSON),
        sa.Column("description", sa.String(512)),
        sa.Column("is_secret", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_settings_key", "settings", ["key"])

    # notifications
    op.create_table("notifications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("recipient_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("level", sa.String(16), default="info"),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("body", sa.Text),
        sa.Column("action_url", sa.String(512)),
        sa.Column("is_read", sa.Boolean, default=False),
        sa.Column("sent_via_telegram", sa.Boolean, default=False),
        sa.Column("metadata", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notifications_recipient_unread", "notifications", ["recipient_id", "is_read"])


def downgrade() -> None:
    tables = [
        "notifications", "settings", "audit_logs", "analytics_events",
        "workflow_runs", "workflows", "sources", "jobs", "schedules",
        "post_media", "media_files", "post_targets", "post_versions",
        "posts", "templates", "campaigns", "topics", "groups",
        "channels", "api_keys", "users",
    ]
    for t in tables:
        op.drop_table(t)
