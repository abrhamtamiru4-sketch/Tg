"""
Database models — SQLAlchemy 2.0 style with typed columns.

Entities:
    User              — Admins and operators
    Role              — RBAC roles
    Permission        — Fine-grained permissions
    Channel           — Telegram channels
    Group             — Telegram groups/supergroups
    Topic             — Forum topics inside groups
    Post              — Content to be published
    PostVersion       — Immutable version history of posts
    PostTarget        — Post × Channel/Group/Topic publish target
    PublishRecord     — Outcome of each publish attempt
    MediaFile         — Media library item
    PostMedia         — Post × MediaFile relation
    Template          — Reusable post templates
    Schedule          — Scheduling rules (recurring or one-time)
    Job               — Queue job records
    Campaign          — Grouped publishing campaigns
    CampaignPost      — Campaign × Post relation
    Source            — External content sources (RSS, webhooks)
    Workflow          — Automation workflows
    WorkflowRun       — Workflow execution log
    AnalyticsEvent    — Measurable events (reactions, forwards, etc.)
    AuditLog          — Immutable audit trail
    Setting           — Persistent key-value configuration
    APIKey            — API access keys
    Notification      — Queued admin notifications
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, Float, ForeignKey,
    Index, Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ── Enums ─────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    OWNER = "owner"
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    EDITOR = "editor"
    PUBLISHER = "publisher"
    MODERATOR = "moderator"
    ANALYST = "analyst"
    VIEWER = "viewer"


class PostStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class PostType(str, enum.Enum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    ANIMATION = "animation"
    VOICE = "voice"
    STICKER = "sticker"
    MEDIA_GROUP = "media_group"
    POLL = "poll"
    RICH = "rich"


class MediaType(str, enum.Enum):
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    ANIMATION = "animation"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    STICKER = "sticker"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD = "dead"
    CANCELLED = "cancelled"


class JobPriority(int, enum.Enum):
    CRITICAL = 10
    HIGH = 7
    NORMAL = 5
    LOW = 3


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class SourceType(str, enum.Enum):
    RSS = "rss"
    ATOM = "atom"
    WEBHOOK = "webhook"
    API = "api"
    MANUAL = "manual"


class WorkflowTrigger(str, enum.Enum):
    SCHEDULE = "schedule"
    RSS_UPDATE = "rss_update"
    WEBHOOK = "webhook"
    NEW_CONTENT = "new_content"
    PUBLISH_SUCCESS = "publish_success"
    PUBLISH_FAILURE = "publish_failure"
    CAMPAIGN_EVENT = "campaign_event"
    MANUAL = "manual"


# ── User & Auth ───────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(64), default="")
    last_name: Mapped[Optional[str]] = mapped_column(String(64))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False), default=UserRole.VIEWER
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(128))  # For web login
    language_code: Mapped[str] = mapped_column(String(8), default="en")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    settings: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # Relationships
    audit_logs: Mapped[list["AuditLog"]] = relationship("AuditLog", back_populates="user", lazy="dynamic")
    api_keys: Mapped[list["APIKey"]] = relationship("APIKey", back_populates="user")

    __table_args__ = (
        Index("ix_users_role", "role"),
    )


class APIKey(Base):
    __tablename__ = "api_keys"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), default="Default")
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship("User", back_populates="api_keys")


# ── Channels & Groups ─────────────────────────────────────────

class Channel(Base):
    __tablename__ = "channels"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256), default="")
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    bot_is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    can_post_messages: Mapped[bool] = mapped_column(Boolean, default=False)
    can_pin_messages: Mapped[bool] = mapped_column(Boolean, default=False)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    default_parse_mode: Mapped[str] = mapped_column(String(16), default="HTML")
    default_signature: Mapped[Optional[str]] = mapped_column(Text)
    default_disable_notification: Mapped[bool] = mapped_column(Boolean, default=False)
    default_protect_content: Mapped[bool] = mapped_column(Boolean, default=False)
    posting_limits: Mapped[Optional[dict]] = mapped_column(JSON)  # blackout windows, etc.
    config: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # Relationships
    post_targets: Mapped[list["PostTarget"]] = relationship("PostTarget", back_populates="channel")


class Group(Base):
    __tablename__ = "groups"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256), default="")
    is_supergroup: Mapped[bool] = mapped_column(Boolean, default=False)
    is_forum: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    bot_is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    moderation_config: Mapped[Optional[dict]] = mapped_column(JSON)
    config: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    topics: Mapped[list["Topic"]] = relationship("Topic", back_populates="group")
    post_targets: Mapped[list["PostTarget"]] = relationship("PostTarget", back_populates="group")


class Topic(Base):
    __tablename__ = "topics"

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), nullable=False, index=True)
    telegram_thread_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(128), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    icon_emoji: Mapped[Optional[str]] = mapped_column(String(16))

    group: Mapped["Group"] = relationship("Group", back_populates="topics")
    post_targets: Mapped[list["PostTarget"]] = relationship("PostTarget", back_populates="topic")

    __table_args__ = (
        UniqueConstraint("group_id", "telegram_thread_id"),
    )


# ── Posts ─────────────────────────────────────────────────────

class Post(Base):
    __tablename__ = "posts"

    title: Mapped[Optional[str]] = mapped_column(String(256))
    text: Mapped[Optional[str]] = mapped_column(Text)
    caption: Mapped[Optional[str]] = mapped_column(Text)
    post_type: Mapped[PostType] = mapped_column(
        Enum(PostType, native_enum=False), default=PostType.TEXT
    )
    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus, native_enum=False), default=PostStatus.DRAFT
    )
    parse_mode: Mapped[str] = mapped_column(String(16), default="HTML")

    # Author
    author_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    # Scheduling
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Inline keyboard (stored as JSON)
    reply_markup: Mapped[Optional[dict]] = mapped_column(JSON)

    # Rich message data (Bot API 10.1+)
    rich_message: Mapped[Optional[dict]] = mapped_column(JSON)

    # Poll data
    poll_data: Mapped[Optional[dict]] = mapped_column(JSON)

    # Content fingerprints for deduplication
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    media_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    # Campaign
    campaign_id: Mapped[Optional[int]] = mapped_column(ForeignKey("campaigns.id"))

    # Template origin
    template_id: Mapped[Optional[int]] = mapped_column(ForeignKey("templates.id"))

    # A/B test variant
    ab_variant: Mapped[Optional[str]] = mapped_column(String(8))  # "A", "B", "C"
    ab_group_id: Mapped[Optional[str]] = mapped_column(String(64))

    # Metadata
    tags: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    language: Mapped[Optional[str]] = mapped_column(String(8))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    metadata: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # Relationships
    author: Mapped[Optional["User"]] = relationship("User")
    media: Mapped[list["PostMedia"]] = relationship("PostMedia", back_populates="post")
    targets: Mapped[list["PostTarget"]] = relationship("PostTarget", back_populates="post")
    versions: Mapped[list["PostVersion"]] = relationship("PostVersion", back_populates="post",
                                                          order_by="PostVersion.version")
    campaign: Mapped[Optional["Campaign"]] = relationship("Campaign", back_populates="posts")
    template: Mapped[Optional["Template"]] = relationship("Template")

    __table_args__ = (
        Index("ix_posts_status", "status"),
        Index("ix_posts_scheduled_at", "scheduled_at"),
        Index("ix_posts_author", "author_id"),
    )


class PostVersion(Base):
    __tablename__ = "post_versions"

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)  # Full post state at this version
    changed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    change_note: Mapped[Optional[str]] = mapped_column(String(512))

    post: Mapped["Post"] = relationship("Post", back_populates="versions")
    changed_by: Mapped[Optional["User"]] = relationship("User")


class PostTarget(Base):
    """Maps a post to a specific channel/group/topic for publishing."""
    __tablename__ = "post_targets"

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False, index=True)
    channel_id: Mapped[Optional[int]] = mapped_column(ForeignKey("channels.id"))
    group_id: Mapped[Optional[int]] = mapped_column(ForeignKey("groups.id"))
    topic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("topics.id"))

    # Per-target customisation
    custom_caption: Mapped[Optional[str]] = mapped_column(Text)
    custom_reply_markup: Mapped[Optional[dict]] = mapped_column(JSON)
    custom_hashtags: Mapped[Optional[str]] = mapped_column(String(512))
    custom_signature: Mapped[Optional[str]] = mapped_column(String(256))
    disable_notification: Mapped[bool] = mapped_column(Boolean, default=False)
    protect_content: Mapped[bool] = mapped_column(Boolean, default=False)
    pin_after_publish: Mapped[bool] = mapped_column(Boolean, default=False)

    # Result tracking
    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus, native_enum=False), default=PostStatus.PENDING_REVIEW
    )
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    post: Mapped["Post"] = relationship("Post", back_populates="targets")
    channel: Mapped[Optional["Channel"]] = relationship("Channel", back_populates="post_targets")
    group: Mapped[Optional["Group"]] = relationship("Group", back_populates="post_targets")
    topic: Mapped[Optional["Topic"]] = relationship("Topic", back_populates="post_targets")


# ── Media ─────────────────────────────────────────────────────

class MediaFile(Base):
    __tablename__ = "media_files"

    filename: Mapped[str] = mapped_column(String(256), default="")
    original_filename: Mapped[Optional[str]] = mapped_column(String(256))
    media_type: Mapped[MediaType] = mapped_column(Enum(MediaType, native_enum=False))
    mime_type: Mapped[Optional[str]] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)

    # Storage
    storage_path: Mapped[Optional[str]] = mapped_column(String(512))
    storage_provider: Mapped[str] = mapped_column(String(32), default="local")

    # Telegram file IDs (reuse to avoid re-uploading)
    telegram_file_id: Mapped[Optional[str]] = mapped_column(String(256), index=True)
    telegram_file_unique_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)

    # Deduplication
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    perceptual_hash: Mapped[Optional[str]] = mapped_column(String(64))  # For images

    # Metadata
    tags: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    folder: Mapped[Optional[str]] = mapped_column(String(128))
    alt_text: Mapped[Optional[str]] = mapped_column(String(256))
    uploaded_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    post_media: Mapped[list["PostMedia"]] = relationship("PostMedia", back_populates="media_file")

    __table_args__ = (
        Index("ix_media_content_hash", "content_hash"),
        Index("ix_media_type", "media_type"),
    )


class PostMedia(Base):
    __tablename__ = "post_media"

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False, index=True)
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_files.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0)
    caption: Mapped[Optional[str]] = mapped_column(Text)

    post: Mapped["Post"] = relationship("Post", back_populates="media")
    media_file: Mapped["MediaFile"] = relationship("MediaFile", back_populates="post_media")


# ── Templates ─────────────────────────────────────────────────

class Template(Base):
    __tablename__ = "templates"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    folder: Mapped[Optional[str]] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Template body — supports {{variables}}
    text_template: Mapped[Optional[str]] = mapped_column(Text)
    caption_template: Mapped[Optional[str]] = mapped_column(Text)
    reply_markup_template: Mapped[Optional[dict]] = mapped_column(JSON)
    default_hashtags: Mapped[Optional[str]] = mapped_column(String(512))
    default_post_type: Mapped[PostType] = mapped_column(
        Enum(PostType, native_enum=False), default=PostType.TEXT
    )

    # Custom variable schema
    variables_schema: Mapped[Optional[dict]] = mapped_column(JSON)

    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[Optional["User"]] = relationship("User")


# ── Scheduler ─────────────────────────────────────────────────

class Schedule(Base):
    __tablename__ = "schedules"

    name: Mapped[str] = mapped_column(String(128), default="")
    post_id: Mapped[Optional[int]] = mapped_column(ForeignKey("posts.id"))
    campaign_id: Mapped[Optional[int]] = mapped_column(ForeignKey("campaigns.id"))

    # Trigger: one-time or recurring
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cron_expression: Mapped[Optional[str]] = mapped_column(String(128))
    # e.g. "0 8,12,18 * * 1-5" = MWF at 08, 12, 18
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")

    # State
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    max_runs: Mapped[Optional[int]] = mapped_column(Integer)

    # Blackout windows (e.g. no posts on weekends)
    blackout_config: Mapped[Optional[dict]] = mapped_column(JSON)

    post: Mapped[Optional["Post"]] = relationship("Post")
    campaign: Mapped[Optional["Campaign"]] = relationship("Campaign")

    __table_args__ = (
        Index("ix_schedules_next_run", "next_run_at"),
    )


# ── Jobs ──────────────────────────────────────────────────────

class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    # What to do
    job_type: Mapped[str] = mapped_column(String(64), default="publish")
    post_id: Mapped[Optional[int]] = mapped_column(ForeignKey("posts.id"))
    target_id: Mapped[Optional[int]] = mapped_column(ForeignKey("post_targets.id"))

    # Scheduling
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=JobPriority.NORMAL)

    # State
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False), default=JobStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Results
    error_type: Mapped[Optional[str]] = mapped_column(String(64))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    result: Mapped[Optional[dict]] = mapped_column(JSON)

    post: Mapped[Optional["Post"]] = relationship("Post")
    target: Mapped[Optional["PostTarget"]] = relationship("PostTarget")

    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_scheduled_at", "scheduled_at"),
        Index("ix_jobs_priority", "priority"),
    )


# ── Campaigns ─────────────────────────────────────────────────

class Campaign(Base):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, native_enum=False), default=CampaignStatus.DRAFT
    )
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    config: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    posts: Mapped[list["Post"]] = relationship("Post", back_populates="campaign")
    created_by: Mapped[Optional["User"]] = relationship("User")

    __table_args__ = (
        Index("ix_campaigns_status", "status"),
    )


# ── Sources ───────────────────────────────────────────────────

class Source(Base):
    __tablename__ = "sources"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False), default=SourceType.RSS
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(64))
    language: Mapped[Optional[str]] = mapped_column(String(8))
    refresh_interval_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)

    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    fetch_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # Mapping: source → template + channels
    default_template_id: Mapped[Optional[int]] = mapped_column(ForeignKey("templates.id"))
    default_target_channel_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    default_template: Mapped[Optional["Template"]] = relationship("Template")


# ── Workflows (Automation) ────────────────────────────────────

class Workflow(Base):
    __tablename__ = "workflows"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # WHEN / IF / THEN / ELSE stored as JSON rule trees
    trigger: Mapped[dict] = mapped_column(JSON, nullable=False)  # WHEN
    conditions: Mapped[Optional[list]] = mapped_column(JSON)     # IF
    actions: Mapped[list] = mapped_column(JSON, nullable=False)  # THEN
    else_actions: Mapped[Optional[list]] = mapped_column(JSON)   # ELSE

    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    runs: Mapped[list["WorkflowRun"]] = relationship("WorkflowRun", back_populates="workflow")
    created_by: Mapped[Optional["User"]] = relationship("User")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    trigger_data: Mapped[Optional[dict]] = mapped_column(JSON)
    result: Mapped[Optional[dict]] = mapped_column(JSON)
    error: Mapped[Optional[str]] = mapped_column(Text)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="runs")


# ── Analytics ─────────────────────────────────────────────────

class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Types: reaction, forward, post_published, post_failed, bot_command, inline_used, etc.

    post_id: Mapped[Optional[int]] = mapped_column(ForeignKey("posts.id"), index=True)
    target_id: Mapped[Optional[int]] = mapped_column(ForeignKey("post_targets.id"))
    channel_id: Mapped[Optional[int]] = mapped_column(ForeignKey("channels.id"), index=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(ForeignKey("campaigns.id"))

    # Telegram data where available
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    reaction_emoji: Mapped[Optional[str]] = mapped_column(String(64))
    user_telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    value: Mapped[Optional[float]] = mapped_column(Float)
    metadata: Mapped[Optional[dict]] = mapped_column(JSON)

    __table_args__ = (
        Index("ix_analytics_event_type", "event_type"),
        Index("ix_analytics_post_id", "post_id"),
        Index("ix_analytics_channel_id", "channel_id"),
        Index("ix_analytics_created_at", "created_at"),
    )


# ── Audit Log ─────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    role: Mapped[Optional[str]] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64))
    resource_id: Mapped[Optional[int]] = mapped_column(Integer)
    old_value: Mapped[Optional[dict]] = mapped_column(JSON)
    new_value: Mapped[Optional[dict]] = mapped_column(JSON)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(String(256))
    result: Mapped[str] = mapped_column(String(16), default="success")
    notes: Mapped[Optional[str]] = mapped_column(Text)

    user: Mapped[Optional["User"]] = relationship("User", back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_action", "action"),
        Index("ix_audit_user_id", "user_id"),
        Index("ix_audit_created_at", "created_at"),
    )


# ── Settings ──────────────────────────────────────────────────

class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    value: Mapped[Optional[dict]] = mapped_column(JSON)
    description: Mapped[Optional[str]] = mapped_column(String(512))
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_settings_key", "key"),
    )


# ── Notifications ─────────────────────────────────────────────

class Notification(Base):
    __tablename__ = "notifications"

    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(16), default="info")  # info, warning, error, critical
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text)
    action_url: Mapped[Optional[str]] = mapped_column(String(512))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_via_telegram: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata: Mapped[Optional[dict]] = mapped_column(JSON)

    recipient: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index("ix_notifications_recipient_unread", "recipient_id", "is_read"),
    )
