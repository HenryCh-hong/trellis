from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import (
    AnswerCategory,
    AnswerSource,
    DocumentKind,
    DocumentStatus,
    OpportunityStatus,
)
from app.models.user import enum_col

if TYPE_CHECKING:
    from app.models.opportunity import Opportunity


class Application(UUIDPk, Timestamps, Base):
    """The "Application Kit" for one opportunity.

    Nothing here is ever submitted without an explicit approval event — see
    ``approved_at`` and ``ApplicationEvent``.
    """

    __tablename__ = "applications"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[OpportunityStatus] = mapped_column(
        enum_col(OpportunityStatus, "opportunity_status"),
        default=OpportunityStatus.PREPARING,
        nullable=False,
        index=True,
    )

    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL")
    )
    resume_locked_by_user: Mapped[bool] = mapped_column(default=False, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text)
    external_reference: Mapped[str | None] = mapped_column(String(200))

    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set only by an explicit user action in the review step. Assisted apply
    # refuses to run without it.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_payload_hash: Mapped[str | None] = mapped_column(String(64))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    opportunity: Mapped[Opportunity] = relationship(back_populates="applications")
    documents: Mapped[list[ApplicationDocument]] = relationship(
        back_populates="application", cascade="all, delete-orphan", lazy="selectin"
    )
    answers: Mapped[list[ApplicationAnswer]] = relationship(
        back_populates="application", cascade="all, delete-orphan", lazy="selectin"
    )
    events: Mapped[list[ApplicationEvent]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ApplicationEvent.created_at",
    )


class ApplicationDocument(UUIDPk, Timestamps, Base):
    __tablename__ = "application_documents"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[DocumentKind] = mapped_column(enum_col(DocumentKind, "document_kind"), nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        enum_col(DocumentStatus, "document_status"), default=DocumentStatus.MISSING, nullable=False
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL")
    )
    filename: Mapped[str | None] = mapped_column(String(400))
    storage_path: Mapped[str | None] = mapped_column(String(500))
    required: Mapped[bool] = mapped_column(default=True, nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)

    application: Mapped[Application] = relationship(back_populates="documents")


class ApplicationAnswer(UUIDPk, Timestamps, Base):
    """A question the application form asks.

    ``category`` is the four-way classification from
    :func:`app.services.applications.classify_question` and is what decides
    whether software may touch the answer at all.  ``is_sensitive`` is the
    single bit the submission gate reads; it is written from ``category`` and
    the two can never disagree.

    A ``SENSITIVE`` question — work authorisation, visa status, demographics,
    disability, veteran status, criminal history, age, self-identification or
    a legal attestation — is never auto-filled or drafted: ``source`` must be
    ``user`` and ``reuse_approved`` must be explicitly set.  See docs/privacy.md.
    """

    __tablename__ = "application_answers"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    field_key: Mapped[str | None] = mapped_column(String(120))
    answer: Mapped[str | None] = mapped_column(Text)
    source: Mapped[AnswerSource] = mapped_column(
        enum_col(AnswerSource, "answer_source"), default=AnswerSource.USER, nullable=False
    )
    profile_field: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[AnswerCategory] = mapped_column(
        enum_col(AnswerCategory, "answer_category"),
        default=AnswerCategory.UNKNOWN,
        nullable=False,
    )
    is_sensitive: Mapped[bool] = mapped_column(default=False, nullable=False)
    sensitive_category: Mapped[str | None] = mapped_column(String(60))
    reuse_approved: Mapped[bool] = mapped_column(default=False, nullable=False)
    needs_user_input: Mapped[bool] = mapped_column(default=True, nullable=False)
    max_length: Mapped[int | None] = mapped_column(Integer)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    application: Mapped[Application] = relationship(back_populates="answers")


class ApplicationEvent(UUIDPk, Timestamps, Base):
    """Append-only history: status moves, approvals, assisted-apply handoffs."""

    __tablename__ = "application_events"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(40))
    to_status: Mapped[str | None] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    application: Mapped[Application] = relationship(back_populates="events")


class ResumeRecommendation(UUIDPk, Timestamps, Base):
    """Per-opportunity ranking of the student's uploaded resumes.

    Kept separate from ``OpportunityMatch`` so we can show the runner-up
    resumes and why each scored where it did, without bloating the match row.
    """

    __tablename__ = "resume_recommendations"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched_strengths: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, nullable=False
    )
    weak_or_missing: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    emphasize: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
