"""What the student said about one opportunity.

One row per (opportunity, profile): a signal is a current opinion, not a log,
and re-stating it overwrites rather than accumulates.  ``DELETE`` removes the
row entirely, so undo restores the exact state that existed before — there is
no tombstone and no residue in the ranking.

The reason column is *only* ever written for ``not_relevant``, and nothing in
the product may read it in aggregate.  See ``app/services/feedback.py``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import FeedbackReason, FeedbackSignal
from app.models.user import enum_col

#: Written into a CHECK so the invariant survives a route that forgets it.
_REASON_ONLY_FOR_NOT_RELEVANT = "reason IS NULL OR signal = 'not_relevant'"


class OpportunityFeedback(UUIDPk, Timestamps, Base):
    __tablename__ = "opportunity_feedback"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal: Mapped[FeedbackSignal] = mapped_column(
        enum_col(FeedbackSignal, "feedback_signal"), nullable=False, index=True
    )
    #: Never set for anything but ``not_relevant``; enforced by the CHECK below.
    reason: Mapped[FeedbackReason | None] = mapped_column(
        enum_col(FeedbackReason, "feedback_reason")
    )
    #: The student's own words. Rendered verbatim or not at all.
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("opportunity_id", "profile_id", name="uq_feedback_opportunity_profile"),
        CheckConstraint(_REASON_ONLY_FOR_NOT_RELEVANT, name="reason_only_for_not_relevant"),
    )


__all__ = ["OpportunityFeedback"]
