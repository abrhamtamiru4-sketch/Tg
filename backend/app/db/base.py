"""
SQLAlchemy 2.0 async setup.

All models import Base from here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    # Convenience columns available on every model:
    # id, created_at, updated_at

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id}>"
