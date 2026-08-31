"""What a drafted cold email is allowed to claim.

Every test here is a sentence Trellis must never write. The draft is composed,
not generated, precisely so these can be enforced as rules rather than hoped
for as tendencies — the student is the one who has to answer for what the email
says, so nothing may appear in it that we cannot point at.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.models.enums import EvidenceKind
from app.services import outreach
from app.services.fit import BackgroundPoint, FitBreakdown, OverlapPoint

THIS_YEAR = 2026


@dataclass
class FakeEvidence:
    title: str
    year: int | None
    kind: str = EvidenceKind.PUBLICATION
    url: str | None = "https://example.org/paper"


@dataclass
class FakeFaculty:
    name: str = "Jane Q. Roe"
    evidence: list = field(default_factory=list)


@dataclass
class FakeUser:
    display_name: str | None = "Sam Lee"


@dataclass
class FakeProfile:
    major: str | None = "Computer Science"
    graduation_year: int | None = 2028
    user: FakeUser = field(default_factory=FakeUser)


def _paper(title="Learning to See", year=2025, kind=EvidenceKind.PUBLICATION):
    return FakeEvidence(title=title, year=year, kind=kind)


def _breakdown(*, overlap_title="Learning to See", background=True):
    return FitBreakdown(
        strong_overlap=[
            OverlapPoint(
                label="computer vision",
                kind="interest",
                evidence=f"Their 2025 paper “{overlap_title}” touches Computer Vision.",
                source_url="https://lab.example.edu",
            )
        ],
        relevant_background=(
            [
                BackgroundPoint(
                    label="Python",
                    kind="skill",
                    detail="Wrote a segmentation pipeline in PyTorch",
                    resume="research.txt",
                    verbatim=True,
                )
            ]
            if background
            else []
        ),
    )


def _compose(faculty=None, profile=None, breakdown=None):
    return outreach.compose_draft(
        faculty or FakeFaculty(evidence=[_paper()]),
        profile or FakeProfile(),
        breakdown if breakdown is not None else _breakdown(),
        this_year=THIS_YEAR,
    )


def test_a_draft_is_within_the_length_a_professor_will_read():
    draft = _compose()
    assert draft.refusal is None
    assert outreach.MIN_WORDS <= draft.word_count <= outreach.MAX_WORDS, draft.body


def test_it_never_claims_the_student_read_or_enjoyed_the_paper():
    """The one lie that is easiest to write and worst to send."""
    body = _compose().body.lower()
    for phrase in (
        "i read",
        "i have read",
        "i enjoyed",
        "i was fascinated",
        "i was excited",
        "i loved",
        "i found your",
        "i admire",
        "i have been following",
    ):
        assert phrase not in body, f"the draft claims familiarity: {phrase!r}"


def test_it_names_no_skill_the_student_does_not_have():
    draft = _compose()
    body = draft.body.lower()
    # The only concrete claims are the ones the breakdown supplied.
    assert "pytorch" in body  # came from their own resume line
    for invented in ("c++", "matlab", "ros", "kubernetes", "tensorflow"):
        assert invented not in body


def test_every_claim_about_the_student_is_cited():
    draft = _compose()
    assert draft.student_citations, "the draft says things about the student with no source"
    for citation in draft.student_citations:
        assert citation.side == "student"
        assert citation.detail


def test_the_paper_it_opens_on_is_cited_with_its_link():
    draft = _compose()
    first = draft.research_citations[0]
    assert "Learning to See" in first.label
    assert first.source_url == "https://example.org/paper"


def test_it_refuses_rather_than_writing_a_generic_email():
    """No recent work that connects means no draft, not a template."""
    breakdown = _breakdown(overlap_title="Something Else Entirely")
    draft = _compose(breakdown=breakdown)
    assert draft.body is None
    assert draft.refusal and "generic" in draft.refusal


def test_it_refuses_when_it_knows_nothing_real_about_the_student():
    draft = _compose(breakdown=_breakdown(background=False))
    assert draft.body is None
    assert draft.refusal and "resume" in draft.refusal.lower()


def test_a_teaching_listing_is_never_called_a_paper():
    """The evidence table holds course and news rows; only a publication is a paper."""
    faculty = FakeFaculty(
        evidence=[
            FakeEvidence(
                title="2025-26 teaching, including Supervised Undergraduate Research",
                year=2026,
                kind=EvidenceKind.COURSE,
            )
        ]
    )
    breakdown = _breakdown(overlap_title="2025-26 teaching, including Supervised Undergraduate Research")
    draft = _compose(faculty=faculty, breakdown=breakdown)
    assert draft.body is None, "a course listing was offered as a paper to open on"


def test_stale_work_is_not_called_recent():
    faculty = FakeFaculty(evidence=[_paper(year=THIS_YEAR - 6)])
    draft = _compose(faculty=faculty)
    assert draft.body is None
    assert draft.refusal


def test_the_topic_named_is_the_one_the_chosen_paper_evidences():
    """Not merely the student's first interest, which may be unrelated."""
    faculty = FakeFaculty(evidence=[_paper(title="Robot Grasping", year=2025)])
    breakdown = FitBreakdown(
        strong_overlap=[
            OverlapPoint(label="NLP", kind="interest", evidence="Their 2026 project “Thrusts” touches NLP."),
            OverlapPoint(
                label="robotics",
                kind="interest",
                evidence="Their 2025 paper “Robot Grasping” touches Robotics.",
            ),
        ],
        relevant_background=_breakdown().relevant_background,
    )
    draft = _compose(faculty=faculty, breakdown=breakdown)
    assert "robotics" in draft.subject.lower()
    assert "nlp" not in draft.subject.lower()


def test_a_blank_name_is_flagged_rather_than_invented():
    profile = FakeProfile(user=FakeUser(display_name=None))
    draft = _compose(profile=profile)
    assert any("name" in todo.lower() for todo in draft.todos)
    assert "None" not in draft.body


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("J Kenneth Salisbury, Jr.", "Salisbury"),
        ("Marco Pavone", "Pavone"),
        ("C. Karen Liu", "Liu"),
        ("Serena Yeung-Levy", "Yeung-Levy"),
    ],
)
def test_the_greeting_uses_a_usable_surname(raw, expected):
    assert outreach._surname(raw) == expected


def test_the_student_is_always_told_what_to_fix_before_sending():
    draft = _compose()
    assert draft.todos
    assert any("read the paper" in t.lower() for t in draft.todos)
    assert any("your own voice" in t.lower() for t in draft.todos)
