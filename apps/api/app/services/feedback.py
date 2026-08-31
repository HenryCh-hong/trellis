"""What a feedback signal is allowed to do.

This is deliberately not a recommender.  Nothing here learns, generalises or
aggregates: every effect is scoped to the single opportunity the student acted
on, and every one of them is undone completely by deleting that one row.

Three rules hold the whole module together:

* **One hide never poisons a topic.**  A reason is recorded for later analysis
  and is never read back into ranking.  There is no function here that takes a
  topic, a department or a source — only an opportunity id.
* **The fit score is never touched.**  It is an explained number with a visible
  breakdown, so quietly editing it would make that breakdown a lie.  The
  penalty and the boost move a row in the *recommended sort* only.
* **The penalty is bounded.**  ``not_relevant`` costs a fixed number of sort
  points, not a tier: a 90-point posting you marked not relevant still ranks
  above a 60-point one you said nothing about.  Demoted, not removed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import FeedbackReason, FeedbackSignal
from app.models.feedback import OpportunityFeedback
from app.models.user import StudentProfile

#: Sort-only adjustments, in fit points. Small on purpose: this is a nudge the
#: student can see the effect of, not a filter wearing a ranking's clothes.
NOT_RELEVANT_PENALTY = 20.0
INTERESTED_BOOST = 10.0

#: Signals that take a row out of the "what should I do next?" surfaces. Hidden
#: leaves the default list entirely; already-applied stays listed but stops
#: being offered as work to do.
TODO_EXCLUDED = (FeedbackSignal.HIDDEN, FeedbackSignal.ALREADY_APPLIED)


class FeedbackError(ValueError):
    """A signal/reason combination the product does not accept."""


def sort_adjustment(signal: str | None) -> float:
    """Fit points added to a row's *sort* key only. Never stored, never shown
    as a score, and never applied to anything but the row it came from."""
    if signal == FeedbackSignal.NOT_RELEVANT.value:
        return -NOT_RELEVANT_PENALTY
    if signal == FeedbackSignal.INTERESTED.value:
        return INTERESTED_BOOST
    return 0.0


def feedback_for_profile(
    db: Session, profile: StudentProfile | None
) -> dict[uuid.UUID, OpportunityFeedback]:
    """Every signal this student has left, keyed by opportunity id."""
    if profile is None:
        return {}
    rows = db.scalars(
        select(OpportunityFeedback).where(OpportunityFeedback.profile_id == profile.id)
    ).all()
    return {row.opportunity_id: row for row in rows}


def hidden_ids(db: Session, profile: StudentProfile | None) -> set[uuid.UUID]:
    if profile is None:
        return set()
    rows = db.scalars(
        select(OpportunityFeedback.opportunity_id).where(
            OpportunityFeedback.profile_id == profile.id,
            OpportunityFeedback.signal == FeedbackSignal.HIDDEN,
        )
    ).all()
    return set(rows)


def excluded_from_todo(
    feedback: dict[uuid.UUID, OpportunityFeedback], ids: Iterable[uuid.UUID] | None = None
) -> set[uuid.UUID]:
    """Ids that must not be offered as work to do."""
    wanted = set(ids) if ids is not None else None
    return {
        oid
        for oid, row in feedback.items()
        if row.signal in TODO_EXCLUDED and (wanted is None or oid in wanted)
    }


def parse(signal: str, reason: str | None) -> tuple[FeedbackSignal, FeedbackReason | None]:
    """Validate a request body. Raises :class:`FeedbackError` with a sentence
    that can be shown to the student as-is."""
    try:
        parsed_signal = FeedbackSignal(signal)
    except ValueError as exc:
        allowed = ", ".join(s.value for s in FeedbackSignal)
        raise FeedbackError(f"Unknown signal {signal!r}. Expected one of: {allowed}.") from exc

    if reason is None:
        return parsed_signal, None

    if parsed_signal is not FeedbackSignal.NOT_RELEVANT:
        raise FeedbackError(
            "A reason only belongs on 'not_relevant' — the other signals do not ask why."
        )
    try:
        parsed_reason = FeedbackReason(reason)
    except ValueError as exc:
        allowed = ", ".join(r.value for r in FeedbackReason)
        raise FeedbackError(f"Unknown reason {reason!r}. Expected one of: {allowed}.") from exc
    return parsed_signal, parsed_reason


def set_feedback(
    db: Session,
    *,
    opportunity_id: uuid.UUID,
    profile: StudentProfile,
    signal: str,
    reason: str | None = None,
    note: str | None = None,
) -> OpportunityFeedback:
    """Record (or replace) this student's signal for one opportunity."""
    parsed_signal, parsed_reason = parse(signal, reason)
    cleaned = (note or "").strip() or None

    row = db.scalars(
        select(OpportunityFeedback).where(
            OpportunityFeedback.opportunity_id == opportunity_id,
            OpportunityFeedback.profile_id == profile.id,
        )
    ).first()

    if row is None:
        row = OpportunityFeedback(
            opportunity_id=opportunity_id,
            profile_id=profile.id,
            signal=parsed_signal,
            reason=parsed_reason,
            note=cleaned,
        )
        db.add(row)
    else:
        row.signal = parsed_signal
        # Changing the signal drops the old reason with it: a reason recorded
        # against "not relevant" says nothing about "interested".
        row.reason = parsed_reason
        row.note = cleaned
    db.flush()
    return row


def clear_feedback(db: Session, *, opportunity_id: uuid.UUID, profile: StudentProfile) -> bool:
    """Undo. Returns whether there was anything to undo."""
    row = db.scalars(
        select(OpportunityFeedback).where(
            OpportunityFeedback.opportunity_id == opportunity_id,
            OpportunityFeedback.profile_id == profile.id,
        )
    ).first()
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
