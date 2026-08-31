from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.models.user import enum_col


class ChangeKind(StrEnum):
    DISCOVERED = "discovered"
    DEADLINE = "deadline"
    REQUIREMENT_ADDED = "requirement_added"
    REQUIREMENT_REMOVED = "requirement_removed"
    PAY = "pay"
    HOURS = "hours"
    APPLICATION_URL = "application_url"
    RECRUITING_STATUS = "recruiting_status"
    LEAD_STATE = "lead_state"
    DISAPPEARED = "disappeared"
    REAPPEARED = "reappeared"


class OpportunityChange(UUIDPk, Timestamps, Base):
    """One noticed change to an opportunity.

    This is the thing a student cannot get from a job board: a deadline moved,
    a document was added to the requirements, a lab's recruiting status firmed
    up. Silently overwriting those is the failure mode — the point of re-running
    discovery is to learn what moved.

    Deliberately append-only and flat. It is a changelog, not version control:
    there is no diff view, no revert, and no branching.
    """

    __tablename__ = "opportunity_changes"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[ChangeKind] = mapped_column(enum_col(ChangeKind, "change_kind"), nullable=False)
    field: Mapped[str | None] = mapped_column(String(60))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    search_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("search_runs.id", ondelete="SET NULL")
    )
    noticed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Cleared when the student has seen it, so "what changed" stays useful.
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_change_noticed", "noticed_at", "opportunity_id"),)
