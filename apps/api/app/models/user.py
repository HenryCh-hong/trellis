from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import WorkAuthorization

if TYPE_CHECKING:
    from app.models.resume import Resume


def enum_col(enum_cls: type, name: str):
    return SAEnum(enum_cls, name=name, native_enum=False, values_callable=lambda e: [m.value for m in e])


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))

    profile: Mapped[StudentProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    resumes: Mapped[list[Resume]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class StudentProfile(UUIDPk, Timestamps, Base):
    __tablename__ = "student_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    university: Mapped[str] = mapped_column(String(200), nullable=False)
    campus: Mapped[str | None] = mapped_column(String(200))
    major: Mapped[str | None] = mapped_column(String(200))
    secondary_major: Mapped[str | None] = mapped_column(String(200))
    degree: Mapped[str | None] = mapped_column(String(80))
    graduation_year: Mapped[int | None] = mapped_column(Integer)
    gpa: Mapped[float | None] = mapped_column(Float)
    gpa_is_public: Mapped[bool] = mapped_column(default=False, nullable=False)

    work_authorization: Mapped[WorkAuthorization] = mapped_column(
        enum_col(WorkAuthorization, "work_authorization"),
        default=WorkAuthorization.NOT_SPECIFIED,
        nullable=False,
    )
    work_authorization_note: Mapped[str | None] = mapped_column(Text)

    hours_per_week_min: Mapped[int | None] = mapped_column(Integer)
    hours_per_week_max: Mapped[int | None] = mapped_column(Integer)
    preferred_job_types: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, nullable=False
    )
    preferred_locations: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, nullable=False
    )
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)

    availability_note: Mapped[str | None] = mapped_column(Text)

    # Durable UI choices that belong to the student, not the browser: which view
    # of the opportunity list they last used, which opportunities they hid.
    # localStorage would lose these on a new machine and cannot be reasoned
    # about server-side (e.g. when deciding what to put on the Overview).
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="profile")
    skills: Mapped[list[ProfileSkill]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    interests: Mapped[list[ProfileResearchInterest]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    coursework: Mapped[list[Coursework]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    experiences: Mapped[list[Experience]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("gpa IS NULL OR (gpa >= 0 AND gpa <= 5)", name="gpa_range"),
    )


class Skill(UUIDPk, Timestamps, Base):
    """Canonical skill vocabulary, shared by profiles, resumes and opportunities."""

    __tablename__ = "skills"

    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)


class ProfileSkill(UUIDPk, Timestamps, Base):
    __tablename__ = "profile_skills"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    # 'user' = typed during onboarding; 'resume' = observed in an uploaded resume.
    # We never mark a skill as the student's unless one of those two is true.
    origin: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    proficiency: Mapped[str | None] = mapped_column(String(20))
    evidence: Mapped[str | None] = mapped_column(Text)
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL")
    )

    profile: Mapped[StudentProfile] = relationship(back_populates="skills")
    skill: Mapped[Skill] = relationship(lazy="joined")

    __table_args__ = (UniqueConstraint("profile_id", "skill_id", name="uq_profile_skill"),)


class ResearchTopic(UUIDPk, Timestamps, Base):
    __tablename__ = "research_topics"

    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("research_topics.id", ondelete="SET NULL")
    )
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    parent: Mapped[ResearchTopic | None] = relationship(remote_side="ResearchTopic.id")


class ProfileResearchInterest(UUIDPk, Timestamps, Base):
    """Free-form research interests, optionally resolved to a canonical topic."""

    __tablename__ = "profile_research_interests"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("research_topics.id", ondelete="SET NULL")
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    profile: Mapped[StudentProfile] = relationship(back_populates="interests")
    topic: Mapped[ResearchTopic | None] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("profile_id", "label", name="uq_profile_interest_label"),
        CheckConstraint("weight >= 0 AND weight <= 3", name="weight_range"),
    )


class Coursework(UUIDPk, Timestamps, Base):
    __tablename__ = "coursework"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    term: Mapped[str | None] = mapped_column(String(40))
    grade: Mapped[str | None] = mapped_column(String(10))
    topics: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    origin: Mapped[str] = mapped_column(String(20), default="user", nullable=False)

    profile: Mapped[StudentProfile] = relationship(back_populates="coursework")


class Experience(UUIDPk, Timestamps, Base):
    __tablename__ = "experiences"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization: Mapped[str] = mapped_column(String(240), nullable=False)
    role: Mapped[str] = mapped_column(String(240), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(40))
    started_on: Mapped[date | None] = mapped_column(Date)
    ended_on: Mapped[date | None] = mapped_column(Date)
    summary: Mapped[str | None] = mapped_column(Text)
    highlights: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    skills: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    origin: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL")
    )
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    profile: Mapped[StudentProfile] = relationship(back_populates="experiences")
