"""Guards on the feedback loop.

The signals are cheap to record and easy to over-use, so the tests here pin the
restraint rather than the feature:

* one hide changes exactly one row, and nothing about its topic, department or
  source;
* the penalty is bounded — a demoted row is still ranked above a much worse one;
* the fit score itself is never edited, so the breakdown on screen keeps
  explaining the number on screen;
* "already applied" invents no Application, moves no pipeline status;
* undo leaves nothing behind.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.api import serializers as ser
from app.api.routes import opportunities as opportunity_routes
from app.models.application import Application
from app.models.enums import (
    FeedbackReason,
    FeedbackSignal,
    OpportunityStatus,
    OpportunityType,
    SourceKind,
)
from app.models.feedback import OpportunityFeedback
from app.models.opportunity import Opportunity, OpportunitySource
from app.models.user import ResearchTopic, StudentProfile, User
from app.schemas import common as S
from app.services import feedback as fb

TODAY = date(2026, 9, 1)
NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# pure: validation and the sort adjustment
# --------------------------------------------------------------------------


def test_reason_is_only_accepted_for_not_relevant():
    signal, reason = fb.parse("not_relevant", "wrong_topic")
    assert signal is FeedbackSignal.NOT_RELEVANT
    assert reason is FeedbackReason.WRONG_TOPIC

    for other in ("interested", "already_applied", "hidden"):
        with pytest.raises(fb.FeedbackError):
            fb.parse(other, "wrong_topic")


def test_unknown_values_are_refused_not_coerced():
    with pytest.raises(fb.FeedbackError):
        fb.parse("maybe_later", None)
    with pytest.raises(fb.FeedbackError):
        fb.parse("not_relevant", "vibes")


def test_the_sort_adjustment_is_bounded_and_scoped():
    """Only the two ranking signals move anything, and only by a few points."""
    assert fb.sort_adjustment("not_relevant") == -fb.NOT_RELEVANT_PENALTY
    assert fb.sort_adjustment("interested") == fb.INTERESTED_BOOST
    assert fb.sort_adjustment("already_applied") == 0.0
    assert fb.sort_adjustment(None) == 0.0
    # Bounded: a demotion may never be worth more than a whole score.
    assert 0 < fb.NOT_RELEVANT_PENALTY < 50
    assert 0 < fb.INTERESTED_BOOST < fb.NOT_RELEVANT_PENALTY


def _item(title: str, **kw) -> S.OpportunityListItem:
    base = dict(
        id=uuid.uuid4(),
        title=title,
        type="on_campus",
        status="new",
        eligibility="eligible",
        urgency="later",
        deadline_state="hard",
        fit_score=50.0,
    )
    base.update(kw)
    return S.OpportunityListItem(**base)


def _signal(signal: str, reason: str | None = None) -> S.FeedbackOut:
    return S.FeedbackOut(signal=signal, reason=reason, created_at=NOW)


def test_not_relevant_demotes_without_removing():
    """Demoted, not deleted — and the row keeps its own score."""
    marked = _item("Marked not relevant", fit_score=60.0, feedback=_signal("not_relevant"))
    neutral = _item("Said nothing", fit_score=55.0)

    ordered = opportunity_routes._sort([marked, neutral], "recommended")
    assert [i.title for i in ordered] == ["Said nothing", "Marked not relevant"]
    # Still present, and its score is untouched: the number the UI explains is
    # the number the UI shows.
    assert marked.fit_score == 60.0


def test_the_penalty_is_bounded_not_a_tier():
    """A strong match you marked not relevant still beats a weak one you did not.

    This is the difference between a nudge and a filter wearing a ranking's
    clothes, and it is what stops one dismissal from burying a whole area.
    """
    strong = _item("Strong but dismissed", fit_score=90.0, feedback=_signal("not_relevant"))
    weak = _item("Weak and untouched", fit_score=40.0)
    ordered = opportunity_routes._sort([strong, weak], "recommended")
    assert [i.title for i in ordered] == ["Strong but dismissed", "Weak and untouched"]


def test_one_dismissal_never_moves_a_second_row():
    """The whole constraint, stated as a test: same topic, same source, same
    department — only the row that was marked moves."""
    topic = [S.TopicRef(slug="robotics", label="Robotics")]
    marked = _item("Robotics lab A", fit_score=70.0, topics=topic, department="CS",
                   feedback=_signal("not_relevant", "wrong_topic"))
    sibling = _item("Robotics lab B", fit_score=69.0, topics=topic, department="CS")
    other = _item("Robotics lab C", fit_score=68.0, topics=topic, department="CS")

    before = [i.title for i in opportunity_routes._sort([sibling, other], "recommended")]
    after = [
        i.title
        for i in opportunity_routes._sort([marked, sibling, other], "recommended")
        if i.title != "Robotics lab A"
    ]
    assert before == after == ["Robotics lab B", "Robotics lab C"]


def test_interested_boosts_only_within_the_recommended_sort():
    liked = _item("Liked", fit_score=55.0, feedback=_signal("interested"))
    higher = _item("Higher fit", fit_score=60.0)

    assert [i.title for i in opportunity_routes._sort([higher, liked], "recommended")] == [
        "Liked",
        "Higher fit",
    ]
    # "Sort by fit" means sort by fit. A hidden adjustment there would print
    # 60 above 55 in the wrong order and look like a bug.
    assert [i.title for i in opportunity_routes._sort([liked, higher], "fit")] == [
        "Higher fit",
        "Liked",
    ]


def test_already_applied_sinks_out_of_the_actionable_top():
    done = _item("Applied elsewhere", fit_score=95.0, feedback=_signal("already_applied"))
    todo = _item("Still to do", fit_score=30.0)
    ordered = opportunity_routes._sort([done, todo], "recommended")
    assert [i.title for i in ordered] == ["Still to do", "Applied elsewhere"]


# --------------------------------------------------------------------------
# stored: these need the real columns, so they run against the test Postgres
# --------------------------------------------------------------------------


def _profile(db) -> StudentProfile:
    user = User(email=f"student-{uuid.uuid4().hex[:8]}@stanford.edu", display_name="A Student")
    db.add(user)
    db.flush()
    profile = StudentProfile(user_id=user.id, university="Stanford University", major="CS")
    db.add(profile)
    db.flush()
    return profile


def _opportunity(db, title: str = "Undergraduate RA") -> Opportunity:
    source = OpportunitySource(
        slug=f"feedback-src-{uuid.uuid4().hex[:8]}",
        name="Test source",
        kind=SourceKind.CAMPUS_JOBS,
    )
    db.add(source)
    db.flush()
    opp = Opportunity(
        title=title,
        type=OpportunityType.ON_CAMPUS,
        status=OpportunityStatus.NEW,
        source_id=source.id,
        first_seen_at=NOW,
    )
    db.add(opp)
    db.flush()
    return opp


def test_a_signal_is_replaced_not_accumulated(db):
    profile = _profile(db)
    opp = _opportunity(db)

    fb.set_feedback(
        db, opportunity_id=opp.id, profile=profile, signal="not_relevant", reason="too_far"
    )
    fb.set_feedback(db, opportunity_id=opp.id, profile=profile, signal="interested")

    rows = db.scalars(
        select(OpportunityFeedback).where(OpportunityFeedback.opportunity_id == opp.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].signal is FeedbackSignal.INTERESTED
    # The old reason goes with the old signal: "too far" said nothing about
    # being interested, and leaving it would be a claim nobody made.
    assert rows[0].reason is None


def test_undo_leaves_nothing_behind(db):
    profile = _profile(db)
    opp = _opportunity(db)

    fb.set_feedback(db, opportunity_id=opp.id, profile=profile, signal="hidden")
    assert fb.hidden_ids(db, profile) == {opp.id}

    assert fb.clear_feedback(db, opportunity_id=opp.id, profile=profile) is True
    assert fb.hidden_ids(db, profile) == set()
    assert fb.feedback_for_profile(db, profile) == {}
    # Undoing something that is already undone is not an error.
    assert fb.clear_feedback(db, opportunity_id=opp.id, profile=profile) is False


def test_hiding_never_deletes_the_opportunity(db):
    profile = _profile(db)
    opp = _opportunity(db)
    fb.set_feedback(db, opportunity_id=opp.id, profile=profile, signal="hidden")
    assert db.get(Opportunity, opp.id) is not None


def test_a_hidden_row_is_never_new_again(db):
    """Discovery re-reads the page; it may not walk the row back on screen
    wearing the badge that means "you have not seen this"."""
    profile = _profile(db)
    opp = _opportunity(db)

    fresh = ser.opportunity_item(opp, today=TODAY, profile_id=profile.id)
    assert fresh.is_new is True

    row = fb.set_feedback(db, opportunity_id=opp.id, profile=profile, signal="hidden")
    hidden = ser.opportunity_item(opp, today=TODAY, profile_id=profile.id, feedback=row)
    assert hidden.is_new is False
    assert hidden.feedback is not None
    assert hidden.feedback.signal == "hidden"


def test_already_applied_fabricates_no_application(db):
    """It is the student's word for what happened elsewhere, not a pipeline
    state. Nothing may be invented on the strength of it."""
    profile = _profile(db)
    opp = _opportunity(db)

    fb.set_feedback(db, opportunity_id=opp.id, profile=profile, signal="already_applied")

    assert db.scalars(select(Application).where(Application.opportunity_id == opp.id)).all() == []
    assert opp.status is OpportunityStatus.NEW


def test_the_reason_is_recorded_but_never_read_as_a_filter(db):
    """A reason may be stored for later analysis. Nothing in the service layer
    offers a way to turn it into a topic-level rule."""
    profile = _profile(db)
    topic = ResearchTopic(slug=f"robotics-{uuid.uuid4().hex[:6]}", label="Robotics")
    db.add(topic)
    db.flush()
    opp = _opportunity(db)

    row = fb.set_feedback(
        db,
        opportunity_id=opp.id,
        profile=profile,
        signal="not_relevant",
        reason="wrong_topic",
        note="  I meant surgical robotics.  ",
    )
    assert row.reason is FeedbackReason.WRONG_TOPIC
    assert row.note == "I meant surgical robotics."

    # Every public entry point is keyed by opportunity id. If a function here
    # ever takes a topic, a department or a source, this feature has grown into
    # the recommender it was explicitly not allowed to become.
    public = [
        value
        for name, value in vars(fb).items()
        if not name.startswith("_")
        and inspect.isfunction(value)
        and value.__module__ == fb.__name__
    ]
    assert public, "the service exposes no functions; this guard would pass vacuously"
    for func in public:
        params = set(inspect.signature(func).parameters)
        assert not params & {"topic", "topics", "department", "source", "slug"}


def test_note_is_optional_and_blank_is_stored_as_nothing(db):
    profile = _profile(db)
    opp = _opportunity(db)
    row = fb.set_feedback(
        db, opportunity_id=opp.id, profile=profile, signal="interested", note="   "
    )
    assert row.note is None
