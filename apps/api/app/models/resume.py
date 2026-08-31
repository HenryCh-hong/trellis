from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk

if TYPE_CHECKING:
    from app.models.user import User


class Resume(UUIDPk, Timestamps, Base):
    """A resume the STUDENT uploaded.

    The original bytes are always preserved untouched on disk; ``text`` is a
    parsed copy used for matching.  The product never rewrites a resume — see
    docs/architecture.md, "Resume handling".
    """

    __tablename__ = "resumes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(400), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Path relative to settings.resume_dir — never a public/static URL.
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)
    kind_hint: Mapped[str | None] = mapped_column(String(40))

    parse_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    parse_error: Mapped[str | None] = mapped_column(Text)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    page_count: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text)

    detected_skills: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    detected_topics: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    user: Mapped[User] = relationship(back_populates="resumes")
    highlights: Mapped[list[ResumeHighlight]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )


class ResumeHighlight(UUIDPk, Timestamps, Base):
    """A verbatim line lifted from the uploaded resume.

    Stored verbatim on purpose: everything the UI shows as "your experience"
    must be quotable back to the student's own document.
    """

    __tablename__ = "resume_highlights"

    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section: Mapped[str | None] = mapped_column(String(80))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    line_index: Mapped[int | None] = mapped_column(Integer)
    skills: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    topics: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)

    resume: Mapped[Resume] = relationship(back_populates="highlights")
