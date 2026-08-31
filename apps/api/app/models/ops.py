from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import (
    ReminderProviderKind,
    ReminderStatus,
    RunStatus,
    SearchKind,
)
from app.models.user import enum_col

if TYPE_CHECKING:
    pass


class SavedSearch(UUIDPk, Timestamps, Base):
    """A standing instruction like "find research labs working on AI agents"."""

    __tablename__ = "saved_searches"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    kind: Mapped[SearchKind] = mapped_column(enum_col(SearchKind, "search_kind"), nullable=False)
    query: Mapped[str | None] = mapped_column(Text)
    source_slugs: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    filters: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    schedule: Mapped[str | None] = mapped_column(String(40))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    runs: Mapped[list[SearchRun]] = relationship(
        back_populates="saved_search", cascade="all, delete-orphan"
    )


class SearchRun(UUIDPk, Timestamps, Base):
    __tablename__ = "search_runs"

    saved_search_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("saved_searches.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[SearchKind] = mapped_column(enum_col(SearchKind, "search_kind"), nullable=False)
    trigger: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        enum_col(RunStatus, "run_status"), default=RunStatus.QUEUED, nullable=False, index=True
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sources_attempted: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, nullable=False
    )
    documents_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error: Mapped[str | None] = mapped_column(Text)
    steps: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    saved_search: Mapped[SavedSearch | None] = relationship(back_populates="runs")


class Reminder(UUIDPk, Timestamps, Base):
    """A deadline reminder the student can export.

    Offsets are stored per-reminder (defaulted from settings, not hard-coded)
    so they can become user-configurable without a migration.
    """

    __tablename__ = "reminders"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    due_on: Mapped[date | None] = mapped_column(Date, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offsets_days: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list, nullable=False)
    provider: Mapped[ReminderProviderKind] = mapped_column(
        enum_col(ReminderProviderKind, "reminder_provider"),
        default=ReminderProviderKind.ICS,
        nullable=False,
    )
    status: Mapped[ReminderStatus] = mapped_column(
        enum_col(ReminderStatus, "reminder_status"), default=ReminderStatus.PENDING, nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(1000))
    documents: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentRun(UUIDPk, Timestamps, Base):
    """Observability for every agent invocation that touched a decision."""

    __tablename__ = "agent_runs"

    agent: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    search_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("search_runs.id", ondelete="CASCADE"), index=True
    )
    subject_type: Mapped[str | None] = mapped_column(String(40))
    subject_id: Mapped[uuid.UUID | None] = mapped_column()

    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[RunStatus] = mapped_column(
        enum_col(RunStatus, "run_status"), default=RunStatus.SUCCEEDED, nullable=False
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    # Deliberately excludes application answers: sensitive form responses are
    # never written to agent logs (docs/privacy.md).
    summary: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class DataProvenance(UUIDPk, Timestamps, Base):
    """Where the shipped corpus came from, surfaced in Settings → Data sources."""

    __tablename__ = "data_provenance"

    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
