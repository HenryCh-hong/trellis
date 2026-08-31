"""Guards on "Can I apply right now?".

Three ways this screen could mislead a student, each pinned here:

* offering a button that implies Trellis will submit for them;
* claiming an application link is "Verified" when nobody read it off a page;
* calling a kit ready while something is still outstanding.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from app.agents.application_agent import ApplicationPrepAgent, PrepRequest
from app.agents.base import AgentContext
from app.llm.deterministic import DeterministicProvider
from app.models.enums import (
    AnswerCategory,
    Certainty,
    DeadlineState,
    DeadlineType,
    DocumentStatus,
    ExtractionMethod,
    LinkVerification,
    OpportunityType,
    ReadinessState,
    SourceKind,
)
from app.models.opportunity import ExtractedField, Opportunity, OpportunitySource
from app.models.resume import Resume
from app.models.user import StudentProfile, User
from app.services.applications import create_kit
from app.services.readiness import (
    CTA_CONTINUE,
    CTA_REVIEW,
    application_link_state,
    readiness_for,
)

TODAY = date(2026, 9, 1)


# --------------------------------------------------------------------------- #
# The application link — pure, no database.


def _field(url: str | None, certainty: Certainty) -> ExtractedField:
    return ExtractedField(
        field="application_url",
        value={"value": url},
        confidence=1.0,
        certainty=certainty,
        method=ExtractionMethod.SOURCE,
        source_url="https://jobs.example.edu/posting",
    )


def test_link_is_verified_only_with_matching_source_provenance():
    state = application_link_state(
        [_field("https://apply.example.edu/form", Certainty.VERIFIED)],
        "https://apply.example.edu/form",
    )
    assert state.verification is LinkVerification.VERIFIED
    assert state.detail == "Verified"


def test_link_with_no_provenance_is_unverified_not_verified():
    """We hold a URL. Nobody watched a page say it is where you apply."""
    state = application_link_state([], "https://apply.example.edu/form")
    assert state.verification is LinkVerification.UNVERIFIED
    assert state.detail == "Unverified"


def test_link_provenance_for_a_different_url_does_not_verify_this_one():
    """A posting whose apply link moved must not inherit the old row's tick."""
    state = application_link_state(
        [_field("https://apply.example.edu/old", Certainty.VERIFIED)],
        "https://apply.example.edu/new",
    )
    assert state.verification is LinkVerification.UNVERIFIED


@pytest.mark.parametrize("certainty", [Certainty.LIKELY, Certainty.INFERRED, Certainty.UNKNOWN])
def test_link_below_verified_certainty_is_unverified(certainty):
    state = application_link_state(
        [_field("https://apply.example.edu/form", certainty)],
        "https://apply.example.edu/form",
    )
    assert state.verification is LinkVerification.UNVERIFIED


def test_no_link_reads_as_not_found():
    state = application_link_state([_field(None, Certainty.UNKNOWN)], None)
    assert state.verification is LinkVerification.NOT_FOUND
    assert state.detail == "Not found"
    assert state.url is None


def test_the_call_to_action_is_never_apply():
    """Trellis does not submit, so it never offers a button that says it will."""
    for label in (CTA_CONTINUE, CTA_REVIEW):
        assert "apply" not in label.lower()


# --------------------------------------------------------------------------- #
# Assembled readiness. These need the models' JSONB/ARRAY columns, so they run
# against the test Postgres and skip with it.


def _profile(db) -> StudentProfile:
    user = User(email=f"student-{uuid.uuid4().hex[:8]}@stanford.edu", display_name="A Student")
    db.add(user)
    db.flush()
    profile = StudentProfile(
        user_id=user.id,
        university="Stanford University",
        major="Computer Science",
        degree="BS",
        graduation_year=2028,
        hours_per_week_min=10,
        hours_per_week_max=15,
    )
    db.add(profile)
    db.flush()
    return profile


def _opportunity(db, **extra) -> Opportunity:
    source = OpportunitySource(
        slug=f"readiness-{uuid.uuid4().hex[:8]}",
        name="Test source",
        kind=SourceKind.CAMPUS_JOBS,
    )
    db.add(source)
    db.flush()
    fields = {
        "title": "Undergraduate Research Assistant",
        "type": OpportunityType.ON_CAMPUS,
        "source_id": source.id,
        "source_url": "https://jobs.example.edu/posting",
        "application_url": "https://apply.example.edu/form",
        "application_method": "form",
        "deadline": date(2026, 9, 12),
        "deadline_type": DeadlineType.HARD,
        "deadline_state": DeadlineState.HARD,
        "documents_required": ["Resume", "Transcript"],
    }
    fields.update(extra)
    opp = Opportunity(**fields)
    db.add(opp)
    db.flush()
    return opp


def _resume(db, profile: StudentProfile) -> Resume:
    resume = Resume(
        user_id=profile.user_id,
        label="Research resume",
        original_filename="research_resume.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        storage_path=f"{uuid.uuid4().hex}/research_resume.pdf",
        checksum=uuid.uuid4().hex,
        is_default=True,
    )
    db.add(resume)
    db.flush()
    return resume


def _rows(readiness) -> dict[str, tuple[str, str]]:
    return {row.label: (row.state.value, row.detail) for row in readiness.rows}


def test_readiness_answers_the_question_line_by_line(db):
    profile = _profile(db)
    resume = _resume(db, profile)
    opp = _opportunity(db)
    db.add(
        ExtractedField(
            opportunity_id=opp.id,
            field="application_url",
            value={"value": opp.application_url},
            confidence=1.0,
            certainty=Certainty.VERIFIED,
            method=ExtractionMethod.SOURCE,
            source_url=opp.source_url,
        )
    )
    app = create_kit(db, profile, opp)
    ApplicationPrepAgent().run(
        AgentContext(db=db, llm=DeterministicProvider(), today=TODAY),
        PrepRequest(application=app, profile=profile),
    )
    db.flush()
    db.refresh(app)

    readiness = readiness_for(db, opportunity=opp, application=app, today=TODAY)
    rows = _rows(readiness)

    assert rows["Resume"] == ("ready", resume.original_filename)
    assert rows["Transcript"] == ("attention", "Missing")
    assert rows["Deadline"] == ("ready", "Sep 12")
    assert rows["Application link"] == ("ready", "Verified")
    # Three research questions, none of them answerable from a profile.
    assert rows["Questions"][0] == "attention"
    assert rows["Questions"][1].endswith("unanswered")
    assert rows["Sensitive"] == ("ready", "None asked")

    assert readiness.ready is False
    assert readiness.cta == CTA_CONTINUE


def test_a_kit_with_nothing_outstanding_offers_review_not_apply(db):
    profile = _profile(db)
    _resume(db, profile)
    opp = _opportunity(db, documents_required=["Resume"])
    app = create_kit(db, profile, opp)
    ApplicationPrepAgent().run(
        AgentContext(db=db, llm=DeterministicProvider(), today=TODAY),
        PrepRequest(application=app, profile=profile),
    )
    db.flush()
    db.refresh(app)
    for answer in app.answers:
        if not answer.answer:
            answer.answer = "Answered by the student."
            answer.needs_user_input = False
    db.flush()

    readiness = readiness_for(db, opportunity=opp, application=app, today=TODAY)
    assert readiness.blocking == []
    assert readiness.ready is True
    assert readiness.cta == CTA_REVIEW


def test_a_sensitive_question_holds_the_kit_and_is_counted_separately(db):
    profile = _profile(db)
    _resume(db, profile)
    opp = _opportunity(db, documents_required=["Resume"])
    app = create_kit(db, profile, opp)
    ApplicationPrepAgent().run(
        AgentContext(db=db, llm=DeterministicProvider(), today=TODAY),
        PrepRequest(application=app, profile=profile),
    )
    db.flush()
    db.refresh(app)

    from app.models.application import ApplicationAnswer

    db.add(
        ApplicationAnswer(
            application_id=app.id,
            question="Are you legally authorized to work in the United States?",
            order_index=20,
            category=AnswerCategory.SENSITIVE,
            is_sensitive=True,
            sensitive_category="work_authorization",
        )
    )
    for answer in app.answers:
        answer.answer = answer.answer or "Answered by the student."
        answer.needs_user_input = False
    db.flush()
    db.refresh(app)

    readiness = readiness_for(db, opportunity=opp, application=app, today=TODAY)
    rows = _rows(readiness)
    assert rows["Sensitive"] == ("attention", "1 requires your input")
    assert readiness.ready is False
    assert readiness.cta == CTA_CONTINUE


def test_an_opportunity_with_no_kit_is_never_ready(db):
    """There is nothing to review until a kit exists, so the CTA stays
    "Continue preparation" however tidy everything else looks."""
    profile = _profile(db)
    _resume(db, profile)
    opp = _opportunity(db, documents_required=[])

    readiness = readiness_for(db, opportunity=opp, application=None, today=TODAY)
    rows = _rows(readiness)
    assert readiness.has_application is False
    assert readiness.ready is False
    assert readiness.cta == CTA_CONTINUE
    assert "The application kit has not been prepared yet." in readiness.blocking
    # It still previews the real question set rather than a placeholder.
    assert rows["Questions"][0] == "attention"
    assert rows["Deadline"] == ("ready", "Sep 12")


def test_a_passed_deadline_blocks_and_says_so(db):
    profile = _profile(db)
    _resume(db, profile)
    opp = _opportunity(
        db,
        deadline=date(2026, 8, 20),
        deadline_state=DeadlineState.EXPIRED,
        documents_required=["Resume"],
    )
    app = create_kit(db, profile, opp)
    db.flush()

    readiness = readiness_for(db, opportunity=opp, application=app, today=TODAY)
    deadline_row = next(r for r in readiness.rows if r.key == "deadline")
    assert deadline_row.state is ReadinessState.BLOCKED
    assert deadline_row.detail == "Passed Aug 20"
    assert readiness.ready is False


def test_an_unstated_deadline_reads_unknown_not_ready(db):
    profile = _profile(db)
    _resume(db, profile)
    opp = _opportunity(
        db,
        deadline=None,
        deadline_type=DeadlineType.UNKNOWN,
        deadline_state=DeadlineState.UNKNOWN,
    )
    readiness = readiness_for(db, opportunity=opp, application=None, today=TODAY)
    deadline_row = next(r for r in readiness.rows if r.key == "deadline")
    assert deadline_row.state is ReadinessState.UNKNOWN
    assert deadline_row.detail == "Not stated"


def test_the_resume_never_appears_twice(db):
    """"No resume selected" and "Missing document: Resume" are one problem."""
    profile = _profile(db)
    opp = _opportunity(db, documents_required=["Resume", "Transcript"])
    app = create_kit(db, profile, opp)
    db.flush()

    readiness = readiness_for(db, opportunity=opp, application=app, today=TODAY)
    labels = [row.label for row in readiness.rows]
    assert labels.count("Resume") == 1


def test_a_ready_document_reports_its_filename(db):
    profile = _profile(db)
    _resume(db, profile)
    opp = _opportunity(db, documents_required=["Resume", "Transcript"])
    app = create_kit(db, profile, opp)
    transcript = next(d for d in app.documents if d.label == "Transcript")
    transcript.status = DocumentStatus.READY
    transcript.filename = "unofficial_transcript.pdf"
    db.flush()

    readiness = readiness_for(db, opportunity=opp, application=app, today=TODAY)
    assert _rows(readiness)["Transcript"] == ("ready", "unofficial_transcript.pdf")


def test_prep_never_prefills_or_drafts_a_sensitive_question(db):
    """The profile holds a work-authorisation value; the form question about it
    still comes back empty and owned by the student."""
    profile = _profile(db)
    opp = _opportunity(db)
    app = create_kit(db, profile, opp)
    from app.models.enums import RequirementKind
    from app.models.opportunity import Requirement

    db.add(
        Requirement(
            opportunity_id=opp.id,
            text="Are you authorized to work in the United States?",
            kind=RequirementKind.REQUIRED,
            category="question",
        )
    )
    db.flush()
    db.refresh(opp)

    ApplicationPrepAgent().run(
        AgentContext(db=db, llm=DeterministicProvider(), today=TODAY),
        PrepRequest(application=app, profile=profile),
    )
    db.flush()
    db.refresh(app)

    sensitive = [a for a in app.answers if a.category is AnswerCategory.SENSITIVE]
    assert sensitive, "the posting's work-authorisation question must reach the kit"
    for answer in sensitive:
        assert answer.answer is None
        assert answer.needs_user_input is True
        assert answer.reuse_approved is False


def test_prep_leaves_an_unrecognised_question_for_the_student(db):
    profile = _profile(db)
    opp = _opportunity(db, type=OpportunityType.RESEARCH_OPENING)
    app = create_kit(db, profile, opp)
    ApplicationPrepAgent().run(
        AgentContext(db=db, llm=DeterministicProvider(), today=TODAY),
        PrepRequest(application=app, profile=profile),
    )
    db.flush()
    db.refresh(app)

    unknown = [a for a in app.answers if a.category is AnswerCategory.UNKNOWN]
    assert unknown, "the research question set contains one Trellis cannot classify"
    for answer in unknown:
        assert answer.answer is None, "an unrecognised question is never auto-answered"
        assert answer.needs_user_input is True


def test_readiness_and_the_kit_blocking_list_agree(db):
    """The panel and the kit page render the same object, so a divergence here
    is the two screens disagreeing in front of the student."""
    profile = _profile(db)
    opp = _opportunity(db)
    app = create_kit(db, profile, opp)
    ApplicationPrepAgent().run(
        AgentContext(db=db, llm=DeterministicProvider(), today=TODAY),
        PrepRequest(application=app, profile=profile),
    )
    db.flush()
    db.refresh(app)

    from app.services.applications import blocking_reasons

    readiness = readiness_for(db, opportunity=opp, application=app, today=TODAY)
    assert readiness.blocking == blocking_reasons(app, TODAY)
    assert readiness.ready == (not readiness.blocking)


def test_readiness_dates_stay_readable_across_years(db):
    profile = _profile(db)
    _resume(db, profile)
    opp = _opportunity(db, deadline=date(2027, 1, 15), deadline_state=DeadlineState.HARD)
    readiness = readiness_for(db, opportunity=opp, application=None, today=TODAY)
    assert next(r for r in readiness.rows if r.key == "deadline").detail == "Jan 15, 2027"


def test_readiness_is_computed_as_of_the_day_it_is_asked(db):
    profile = _profile(db)
    _resume(db, profile)
    opp = _opportunity(db, deadline=date(2026, 9, 12))
    later = datetime(2026, 9, 30, tzinfo=UTC).date()
    readiness = readiness_for(db, opportunity=opp, application=None, today=later)
    assert next(r for r in readiness.rows if r.key == "deadline").state is ReadinessState.BLOCKED
