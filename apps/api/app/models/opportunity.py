from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import (
    Certainty,
    ConfidenceState,
    DeadlineState,
    DeadlineType,
    EligibilityState,
    ExtractionMethod,
    LeadState,
    OpportunityStatus,
    OpportunityType,
    RequirementKind,
    RequirementMatch,
    SourceKind,
    SourceStatus,
)
from app.models.user import enum_col

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.research import Faculty, Lab


class OpportunitySource(UUIDPk, Timestamps, Base):
    """A place opportunities come from.

    Adding a source is a row plus an adapter class (``app/sources/``); nothing
    else in the system needs to change.
    """

    __tablename__ = "opportunity_sources"

    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    kind: Mapped[SourceKind] = mapped_column(enum_col(SourceKind, "source_kind"), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(1000))
    adapter: Mapped[str | None] = mapped_column(String(160))
    requires_auth: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_public: Mapped[bool] = mapped_column(default=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    opportunities: Mapped[list[Opportunity]] = relationship(back_populates="source")


class SourceDocument(UUIDPk, Timestamps, Base):
    """A fetched page, kept so every extracted claim can be traced and re-checked."""

    __tablename__ = "source_documents"

    url: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    canonical_url: Mapped[str | None] = mapped_column(String(1000))
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunity_sources.id", ondelete="SET NULL")
    )
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(160))
    title: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetch_error: Mapped[str | None] = mapped_column(Text)
    # 'server' = our backend fetched it; 'extension' = the student's own browser
    # handed it to us (Handshake).  We never fetch behind someone's login.
    retrieved_by: Mapped[str] = mapped_column(String(20), default="server", nullable=False)


class Opportunity(UUIDPk, Timestamps, Base):
    """The unified record for every kind of opportunity.

    Research leads live here too (``research_opening`` / ``research_outreach``)
    so that deadlines, saving, the application pipeline and reminders work
    identically for a lab lead and a dining-hall job.  The extra research
    intelligence hangs off ``faculty_id`` / ``lab_id``.
    """

    __tablename__ = "opportunities"

    title: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[OpportunityType] = mapped_column(
        enum_col(OpportunityType, "opportunity_type"), nullable=False, index=True
    )
    status: Mapped[OpportunityStatus] = mapped_column(
        enum_col(OpportunityStatus, "opportunity_status"),
        default=OpportunityStatus.NEW,
        nullable=False,
        index=True,
    )

    organization: Mapped[str | None] = mapped_column(String(300))
    university: Mapped[str | None] = mapped_column(String(200), index=True)
    department: Mapped[str | None] = mapped_column(String(200), index=True)

    faculty_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("faculty.id", ondelete="SET NULL"), index=True
    )
    lab_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("labs.id", ondelete="SET NULL"))

    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunity_sources.id", ondelete="SET NULL"), index=True
    )
    source_url: Mapped[str | None] = mapped_column(String(1000))
    # Stable per-source identity used for dedup on re-runs (spec §21).
    external_key: Mapped[str | None] = mapped_column(String(400), index=True)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64))

    location: Mapped[str | None] = mapped_column(String(300))
    is_remote: Mapped[bool | None] = mapped_column()
    pay_text: Mapped[str | None] = mapped_column(String(300))
    pay_min: Mapped[float | None] = mapped_column(Float)
    pay_max: Mapped[float | None] = mapped_column(Float)
    pay_period: Mapped[str | None] = mapped_column(String(20))
    hours_per_week: Mapped[int | None] = mapped_column(Integer)
    hours_note: Mapped[str | None] = mapped_column(String(300))

    deadline: Mapped[date | None] = mapped_column(Date, index=True)
    deadline_type: Mapped[DeadlineType] = mapped_column(
        enum_col(DeadlineType, "deadline_type"), default=DeadlineType.UNKNOWN, nullable=False
    )
    #: The lifecycle state. ``deadline_type`` is what the posting said;
    #: this is where the posting has got to, including EXPIRED once a stated
    #: date has passed. Written by app/services/lifecycle.py, never on read.
    deadline_state: Mapped[DeadlineState] = mapped_column(
        enum_col(DeadlineState, "deadline_state"),
        default=DeadlineState.UNKNOWN,
        nullable=False,
        index=True,
    )
    deadline_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    deadline_certainty: Mapped[Certainty] = mapped_column(
        enum_col(Certainty, "certainty"), default=Certainty.UNKNOWN, nullable=False
    )
    deadline_source_text: Mapped[str | None] = mapped_column(Text)

    description: Mapped[str | None] = mapped_column(Text)
    skills: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    documents_required: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, nullable=False
    )

    application_method: Mapped[str | None] = mapped_column(String(120))
    application_url: Mapped[str | None] = mapped_column(String(1000))
    contact_name: Mapped[str | None] = mapped_column(String(240))
    contact_email: Mapped[str | None] = mapped_column(String(320))

    eligibility: Mapped[EligibilityState] = mapped_column(
        enum_col(EligibilityState, "eligibility_state"),
        default=EligibilityState.UNCLEAR,
        nullable=False,
    )
    eligibility_reasons: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, nullable=False
    )

    posted_at: Mapped[date | None] = mapped_column(Date)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_stale: Mapped[bool] = mapped_column(default=False, nullable=False)

    #: Whether the posting is still on the source that produced it. Rows are
    #: never deleted when a posting disappears — history is the product.
    source_status: Mapped[SourceStatus] = mapped_column(
        enum_col(SourceStatus, "source_status"),
        default=SourceStatus.LIVE,
        nullable=False,
        index=True,
    )
    #: When ``source_status`` last changed, so the badge can say when we looked.
    source_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    #: Set by app/services/confidence.py at upsert time.  ``HELD`` rows are kept
    #: in full but stay out of the default list, the Overview and match scoring
    #: until a later run reads their page well enough to promote them.
    confidence_state: Mapped[ConfidenceState] = mapped_column(
        enum_col(ConfidenceState, "confidence_state"),
        default=ConfidenceState.OK,
        nullable=False,
        index=True,
    )
    #: One short, specific sentence naming what was missing.  Rendered verbatim,
    #: so it may never be a category label like "low quality".
    confidence_reason: Mapped[str | None] = mapped_column(Text)
    confidence_state_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Research leads only.  NULL means "never classified" -- distinct from
    # LeadState.UNKNOWN, which is a *conclusion* ("we read the pages and still
    # cannot say").  Programme-level openings (CURIS, VPUE grants) carry no
    # faculty and are never run through the classifier, so they stay NULL and
    # fall back to the type-derived state.
    lead_state: Mapped[LeadState | None] = mapped_column(
        enum_col(LeadState, "lead_state"), index=True
    )
    # The specific, sourced signals that produced ``lead_state``.  Persisted
    # rather than recomputed so the reason survives a reload even if the lab
    # page changes underneath us.
    lead_state_signals: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    lead_state_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source: Mapped[OpportunitySource | None] = relationship(back_populates="opportunities")
    faculty: Mapped[Faculty | None] = relationship(lazy="selectin")
    lab: Mapped[Lab | None] = relationship(lazy="selectin")
    requirements: Mapped[list[Requirement]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan", lazy="selectin"
    )
    topics: Mapped[list[OpportunityTopic]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan", lazy="selectin"
    )
    fields: Mapped[list[ExtractedField]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan"
    )
    matches: Mapped[list[OpportunityMatch]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan", lazy="selectin"
    )
    applications: Mapped[list[Application]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source_id", "external_key", name="uq_opportunity_source_key"),
        Index("ix_opportunity_deadline_type", "deadline", "type"),
    )


class Requirement(UUIDPk, Timestamps, Base):
    """One stated qualification.

    ``kind`` is load-bearing: a 'preferred' line may never be rendered as
    'required', and 'inferred' marks something the model deduced rather than
    read.  See docs/uncertainty.md.
    """

    __tablename__ = "requirements"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[RequirementKind] = mapped_column(
        enum_col(RequirementKind, "requirement_kind"), nullable=False
    )
    category: Mapped[str | None] = mapped_column(String(60))
    skill_slugs: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    opportunity: Mapped[Opportunity] = relationship(back_populates="requirements")


class OpportunityTopic(UUIDPk, Timestamps, Base):
    __tablename__ = "opportunity_topics"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    opportunity: Mapped[Opportunity] = relationship(back_populates="topics")
    topic = relationship("ResearchTopic", lazy="joined")

    __table_args__ = (UniqueConstraint("opportunity_id", "topic_id", name="uq_opportunity_topic"),)


class ExtractedField(UUIDPk, Timestamps, Base):
    """The {value, confidence, source} triple from spec §20.

    Any field whose correctness could change what a student does — deadline,
    pay, eligibility, requirements — gets a row here so the UI can show where
    it came from and how sure we are.
    """

    __tablename__ = "extracted_fields"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    certainty: Mapped[Certainty] = mapped_column(
        enum_col(Certainty, "certainty"), default=Certainty.UNKNOWN, nullable=False
    )
    method: Mapped[ExtractionMethod] = mapped_column(
        enum_col(ExtractionMethod, "extraction_method"), nullable=False
    )
    source_text: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL")
    )
    extractor_version: Mapped[str | None] = mapped_column(String(60))

    opportunity: Mapped[Opportunity] = relationship(back_populates="fields")

    __table_args__ = (UniqueConstraint("opportunity_id", "field", name="uq_extracted_field"),)


class OpportunityMatch(UUIDPk, Timestamps, Base):
    """An explainable score. No mystery numbers: ``breakdown`` holds each
    component's raw score, weight and the human-readable reason."""

    __tablename__ = "opportunity_matches"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    fit_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    model: Mapped[str] = mapped_column(String(60), default="jobs-v1", nullable=False)
    scorer_version: Mapped[str] = mapped_column(String(20), default="1", nullable=False)

    breakdown: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    strengths: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    gaps: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    why_interesting: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(String(40))

    requirement_matches: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)

    recommended_resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL")
    )
    resume_rationale: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    opportunity: Mapped[Opportunity] = relationship(back_populates="matches")

    __table_args__ = (
        UniqueConstraint("opportunity_id", "profile_id", name="uq_match_opportunity_profile"),
    )


# Late import to satisfy the RequirementMatch reference used by services.
__all__ = [
    "ExtractedField",
    "Opportunity",
    "OpportunityMatch",
    "OpportunitySource",
    "OpportunityTopic",
    "Requirement",
    "RequirementMatch",
    "SourceDocument",
]
