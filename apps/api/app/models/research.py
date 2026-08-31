from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import Certainty, EvidenceKind, SignalKind
from app.models.user import ResearchTopic, enum_col

if TYPE_CHECKING:
    pass


class Faculty(UUIDPk, Timestamps, Base):
    __tablename__ = "faculty"

    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    university: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str | None] = mapped_column(String(200), index=True)

    faculty_url: Mapped[str | None] = mapped_column(String(1000))
    personal_url: Mapped[str | None] = mapped_column(String(1000))
    scholar_id: Mapped[str | None] = mapped_column(String(120))
    openalex_id: Mapped[str | None] = mapped_column(String(120), index=True)

    email: Mapped[str | None] = mapped_column(String(320))
    email_source_url: Mapped[str | None] = mapped_column(String(1000))
    email_certainty: Mapped[Certainty] = mapped_column(
        enum_col(Certainty, "certainty"), default=Certainty.UNKNOWN, nullable=False
    )

    research_areas: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    # Inferred from RECENT evidence only (see ResearchEvidence); never copied
    # from an old biography.
    current_direction: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, nullable=False
    )
    current_direction_basis: Mapped[str | None] = mapped_column(Text)
    current_direction_certainty: Mapped[Certainty] = mapped_column(
        enum_col(Certainty, "certainty"), default=Certainty.UNKNOWN, nullable=False
    )
    bio: Mapped[str | None] = mapped_column(Text)

    last_evidence_year: Mapped[int | None] = mapped_column(Integer)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=False, nullable=False)

    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_urls: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    fetch_notes: Mapped[str | None] = mapped_column(Text)

    labs: Mapped[list[Lab]] = relationship(
        back_populates="pi", cascade="all, delete-orphan"
    )
    evidence: Mapped[list[ResearchEvidence]] = relationship(
        back_populates="faculty",
        cascade="all, delete-orphan",
        order_by="ResearchEvidence.year.desc().nullslast()",
    )
    signals: Mapped[list[LabSignal]] = relationship(
        back_populates="faculty", cascade="all, delete-orphan"
    )
    topics: Mapped[list[FacultyTopic]] = relationship(
        back_populates="faculty", cascade="all, delete-orphan"
    )


class Lab(UUIDPk, Timestamps, Base):
    __tablename__ = "labs"

    pi_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("faculty.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    url: Mapped[str | None] = mapped_column(String(1000))
    university: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    news_url: Mapped[str | None] = mapped_column(String(1000))
    people_url: Mapped[str | None] = mapped_column(String(1000))
    join_url: Mapped[str | None] = mapped_column(String(1000))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pi: Mapped[Faculty | None] = relationship(back_populates="labs")


class ResearchEvidence(UUIDPk, Timestamps, Base):
    """One dated artefact proving what a lab is working on NOW.

    Deviation from the spec's entity list, explained: the spec names a
    ``publications`` table, but §22 asks for a single "2-5 pieces of recent
    evidence" timeline mixing papers, projects, news and grants.  Splitting
    those across tables would make that timeline a UNION on every read, so
    publications live here with publication-specific columns
    (``venue``/``doi``/``authors``) and ``kind='publication'``.
    """

    __tablename__ = "research_evidence"

    faculty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("faculty.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lab_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("labs.id", ondelete="SET NULL"))

    kind: Mapped[EvidenceKind] = mapped_column(enum_col(EvidenceKind, "evidence_kind"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    published_on: Mapped[date | None] = mapped_column(Date)
    url: Mapped[str | None] = mapped_column(String(1000))
    venue: Mapped[str | None] = mapped_column(String(300))
    doi: Mapped[str | None] = mapped_column(String(200))
    external_id: Mapped[str | None] = mapped_column(String(200), index=True)
    authors: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    topics: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)

    source: Mapped[str | None] = mapped_column(String(80))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    faculty: Mapped[Faculty] = relationship(back_populates="evidence")

    __table_args__ = (
        UniqueConstraint("faculty_id", "title", "year", name="uq_evidence_faculty_title_year"),
    )


class LabSignal(UUIDPk, Timestamps, Base):
    """An honesty-scoped claim about a lab.

    Every signal carries the certainty the UI is allowed to display and the URL
    that backs it.  A signal with no ``source_url`` may never render as
    'verified'.
    """

    __tablename__ = "lab_signals"

    faculty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("faculty.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lab_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("labs.id", ondelete="SET NULL"))
    kind: Mapped[SignalKind] = mapped_column(enum_col(SignalKind, "signal_kind"), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    certainty: Mapped[Certainty] = mapped_column(
        enum_col(Certainty, "certainty"), default=Certainty.UNKNOWN, nullable=False
    )
    statement: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    faculty: Mapped[Faculty] = relationship(back_populates="signals")


class FacultyTopic(UUIDPk, Timestamps, Base):
    __tablename__ = "faculty_topics"

    faculty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("faculty.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    # 'directory' = listed on the department page; 'evidence' = derived from
    # recent papers/news. Ranking weights 'evidence' higher (spec §22).
    origin: Mapped[str] = mapped_column(String(20), default="directory", nullable=False)
    evidence_years: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list, nullable=False)

    faculty: Mapped[Faculty] = relationship(back_populates="topics")
    topic: Mapped[ResearchTopic] = relationship(lazy="joined")

    __table_args__ = (UniqueConstraint("faculty_id", "topic_id", "origin", name="uq_faculty_topic"),)
