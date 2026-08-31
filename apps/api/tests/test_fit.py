"""Guards on the "why is this relevant to me?" breakdown.

The panel this builds is the one a student reads just before spending half an
hour writing to a professor, so the failure modes are expensive in both
directions: an invented credential embarrasses them in front of a lab, and a
gap phrased as a verdict talks them out of an application they should send.
Each test below pins one of those.
"""

from __future__ import annotations

import uuid

from app.models.enums import Certainty, EvidenceKind, RequirementKind, RequirementMatch
from app.models.opportunity import Opportunity, OpportunityMatch, Requirement
from app.models.research import Faculty, FacultyTopic, ResearchEvidence
from app.models.resume import Resume, ResumeHighlight
from app.models.user import (
    Coursework,
    ProfileResearchInterest,
    ProfileSkill,
    ResearchTopic,
    Skill,
    StudentProfile,
)
from app.services.fit import compose_fit

RESUME_TEXT = """HENRY CHEN

EDUCATION
Stanford University — B.S. Computer Science, expected 2028
Relevant Coursework: CS 224N Natural Language Processing

RESEARCH EXPERIENCE
Undergraduate Research Assistant (2025-2026)
- Built a PyTorch evaluation harness for multimodal LLM agents across 4 benchmark suites
"""

LINE = "Built a PyTorch evaluation harness for multimodal LLM agents across 4 benchmark suites"


def _faculty(**kw) -> Faculty:
    base = dict(
        slug="test-pi",
        name="Test PI",
        university="Stanford University",
        department="Computer Science",
        faculty_url="https://example.edu/pi",
        evidence=[],
        topics=[],
        labs=[],
        signals=[],
        current_direction=[],
        source_urls=[],
        research_areas=[],
    )
    base.update(kw)
    return Faculty(**base)


def _evidence(title: str, *, year: int = 2026, kind: EvidenceKind = EvidenceKind.PUBLICATION,
              summary: str | None = None, url: str | None = "https://example.edu/paper",
              topics: list[str] | None = None) -> ResearchEvidence:
    return ResearchEvidence(
        kind=kind, title=title, summary=summary, year=year, url=url, topics=topics or [],
        authors=[],
    )


def _topic(slug: str, label: str, origin: str = "directory") -> FacultyTopic:
    return FacultyTopic(topic=ResearchTopic(slug=slug, label=label, aliases=[]), origin=origin,
                        weight=1.0, evidence_years=[])


def _profile(*, interests: list[str] | None = None, skills: list[tuple[str, str, str]] | None = None,
             coursework: list[tuple[str, str]] | None = None, keywords: list[str] | None = None,
             university: str = "Stanford University") -> StudentProfile:
    profile = StudentProfile(
        user_id=uuid.uuid4(),
        university=university,
        major="Computer Science",
        keywords=keywords or [],
        preferred_job_types=[],
        preferred_locations=[],
        preferences={},
        interests=[
            ProfileResearchInterest(label=label, weight=1.5) for label in (interests or [])
        ],
        coursework=[
            Coursework(code=code, title=title, topics=[]) for code, title in (coursework or [])
        ],
        experiences=[],
        skills=[
            ProfileSkill(
                skill=Skill(slug=slug, label=label, category=category, aliases=[]),
                origin="user",
            )
            for slug, label, category in (skills or [])
        ],
    )
    profile.id = uuid.uuid4()
    return profile


def _resume(*, filename: str = "research_resume.pdf", text: str | None = RESUME_TEXT,
            parse_status: str = "parsed", highlights: list[ResumeHighlight] | None = None) -> Resume:
    return Resume(
        user_id=uuid.uuid4(),
        label="Research resume",
        original_filename=filename,
        content_type="application/pdf",
        size_bytes=1024,
        storage_path="x",
        checksum="y",
        parse_status=parse_status,
        text=text,
        detected_skills=[],
        detected_topics=[],
        stats={},
        highlights=highlights
        if highlights is not None
        else [ResumeHighlight(section="research", text=LINE, line_index=0, skills=["pytorch"],
                              topics=["llm-agents"])],
    )


def _hci_lab() -> Faculty:
    return _faculty(
        evidence=[_evidence("Human-computer interaction for creative writing", topics=["hci"])],
        topics=[_topic("hci", "Human-Computer Interaction", origin="evidence")],
    )


def _nlp_lab() -> Faculty:
    return _faculty(
        evidence=[
            _evidence("Evaluating LLM agents on execution outcomes", topics=["llm-agents"]),
            _evidence("A benchmark for open audio foundation models", year=2026,
                      url="https://example.edu/audio"),
        ],
        topics=[_topic("nlp", "Natural Language Processing", origin="evidence")],
    )


# ------------------------------------------------------------ no fabrication


def test_background_only_ever_quotes_what_the_student_uploaded():
    """Every background line must be findable in the profile or a resume."""
    profile = _profile(interests=["LLM agents"])
    fit = compose_fit(_nlp_lab(), profile, [_resume()])

    assert fit.relevant_background
    for point in fit.relevant_background:
        if point.verbatim:
            assert point.detail is not None
            assert point.detail in RESUME_TEXT


def test_a_quoted_resume_line_is_verbatim_and_names_its_file():
    fit = compose_fit(_nlp_lab(), _profile(interests=["LLM agents"]), [_resume()])
    quoted = [p for p in fit.relevant_background if p.kind == "resume_line"]

    assert quoted, "the matching resume line should be surfaced"
    assert quoted[0].detail == LINE
    assert quoted[0].resume == "research_resume.pdf"
    assert quoted[0].verbatim is True


def test_a_skill_quote_names_the_resume_it_came_from():
    profile = _profile(interests=["LLM agents"], skills=[("hci", "Human-Computer Interaction",
                                                          "domain")])
    profile.skills[0].origin = "resume"
    profile.skills[0].evidence = "…Undergraduate Research Assistant (2025-2026) - Built a…"

    fit = compose_fit(_hci_lab(), profile, [_resume()])
    skills = [p for p in fit.relevant_background if p.kind == "skill"]

    assert [p.label for p in skills] == ["Human-Computer Interaction"]
    assert skills[0].resume == "research_resume.pdf"
    assert skills[0].verbatim is True


def test_a_quote_we_cannot_attribute_is_not_shown_as_a_quote():
    """A skill row can outlive the resume its snippet came from. The snippet is
    real but unattributable, and an unattributed quote is exactly what the
    'name which resume' rule exists to stop."""
    profile = _profile(interests=["LLM agents"], skills=[("hci", "Human-Computer Interaction",
                                                          "domain")])
    profile.skills[0].origin = "resume"
    profile.skills[0].evidence = "…a line from a resume that has since been deleted…"

    fit = compose_fit(_hci_lab(), profile, [_resume()])
    skills = [p for p in fit.relevant_background if p.kind == "skill"]

    assert [p.label for p in skills] == ["Human-Computer Interaction"]
    assert skills[0].detail is None
    assert skills[0].resume is None
    assert skills[0].verbatim is False


def test_no_resume_is_said_out_loud_rather_than_silently_shortening_the_list():
    fit = compose_fit(_nlp_lab(), _profile(interests=["LLM agents"]), [])

    assert fit.resumes_read == []
    assert fit.background_note is not None
    assert "No resume" in fit.background_note


def test_an_unreadable_resume_is_also_said_out_loud():
    fit = compose_fit(
        _nlp_lab(),
        _profile(interests=["LLM agents"]),
        [_resume(text=None, parse_status="failed", highlights=[])],
    )

    assert fit.resumes_read == []
    assert fit.background_note is not None
    assert "could be read" in fit.background_note


def test_coursework_keeps_the_code_as_the_document_prints_it():
    fit = compose_fit(_nlp_lab(), _profile(interests=["NLP"]), [_resume()])
    courses = [p for p in fit.relevant_background if p.kind == "coursework"]

    assert [p.label for p in courses] == ["CS 224N"]
    assert courses[0].detail == "Natural Language Processing"
    assert courses[0].resume == "research_resume.pdf"


# ------------------------------------------------------------------ overlap


def test_overlap_names_the_interest_and_cites_a_dated_artefact():
    fit = compose_fit(_nlp_lab(), _profile(interests=["LLM agents"]), [_resume()])

    assert [p.label for p in fit.strong_overlap] == ["LLM agents"]
    point = fit.strong_overlap[0]
    assert "2026" in point.evidence
    assert "Evaluating LLM agents on execution outcomes" in point.evidence
    assert point.source_url == "https://example.edu/paper"


def test_a_generic_department_area_is_not_reported_as_an_overlap():
    """Every lab in the school carries "Artificial Intelligence". Reporting it
    is true and tells the student nothing, so it is never the answer unless
    they named it themselves."""
    lab = _faculty(
        evidence=[_evidence("Physically based simulation of cloth")],
        topics=[_topic("artificial-intelligence", "Artificial Intelligence")],
    )
    fit = compose_fit(lab, _profile(interests=["LLM agents"]), [_resume()])

    assert fit.strong_overlap == []


def test_a_keyword_does_not_restate_an_interest_it_duplicates():
    profile = _profile(interests=["LLM agents"], keywords=["llm agents", "LLM agents"])
    fit = compose_fit(_nlp_lab(), profile, [_resume()])

    assert [p.label for p in fit.strong_overlap] == ["LLM agents"]


# --------------------------------------------------------------------- gaps


def test_a_gap_is_never_blocking_on_its_own():
    lab = _faculty(
        evidence=[
            _evidence("A study of speech and audio models", year=2026),
            _evidence("More speech and audio models", year=2025),
        ],
    )
    fit = compose_fit(lab, _profile(interests=["LLM agents"]), [_resume()])

    assert fit.potential_gaps
    assert all(gap.blocking is False for gap in fit.potential_gaps)


def test_a_gap_describes_the_missing_evidence_not_the_student():
    lab = _faculty(evidence=[_evidence("Human-computer interaction for creative writing")])
    fit = compose_fit(lab, _profile(interests=["LLM agents"]), [_resume()])

    for gap in fit.potential_gaps:
        assert "nothing in your profile" in gap.note
        for verdict in ("you lack", "you have no", "unqualified", "not qualified", "too junior"):
            assert verdict not in gap.note.lower()
            assert verdict not in gap.label.lower()


def test_a_missing_preferred_qualification_is_never_blocking():
    """The required/preferred split is load-bearing: a preferred line may not
    be rendered as a gate, however it is worded."""
    requirement = Requirement(
        text="Preferred: prior publication at a top venue",
        kind=RequirementKind.PREFERRED,
        category="experience",
        skill_slugs=[],
        order_index=0,
    )
    requirement.id = uuid.uuid4()
    opportunity = Opportunity(title="RA", requirements=[requirement])
    match = OpportunityMatch(
        fit_score=50.0,
        confidence=0.5,
        model="deterministic",
        requirement_matches=[
            {
                "requirement_id": str(requirement.id),
                "text": requirement.text,
                "kind": RequirementKind.PREFERRED.value,
                "category": "experience",
                "state": RequirementMatch.MISSING.value,
                "reason": "Nothing in the profile shows a publication.",
                "evidence": None,
            }
        ],
    )
    fit = compose_fit(
        _nlp_lab(), _profile(interests=["LLM agents"]), [_resume()],
        opportunity=opportunity, match=match,
    )

    preferred = [g for g in fit.potential_gaps if "publication" in g.label]
    assert preferred and preferred[0].blocking is False
    assert "preferred" in preferred[0].note.lower()


def test_only_a_stated_hard_requirement_can_block():
    requirement = Requirement(
        text="Must be a current Stanford undergraduate",
        kind=RequirementKind.REQUIRED,
        category="class_standing",
        skill_slugs=[],
        order_index=0,
    )
    requirement.id = uuid.uuid4()
    opportunity = Opportunity(title="RA", requirements=[requirement])
    match = OpportunityMatch(
        fit_score=10.0,
        confidence=0.9,
        model="deterministic",
        requirement_matches=[
            {
                "requirement_id": str(requirement.id),
                "text": requirement.text,
                "kind": RequirementKind.REQUIRED.value,
                "category": "class_standing",
                "state": RequirementMatch.MISSING.value,
                "reason": "Your profile records a different institution.",
                "evidence": None,
            }
        ],
    )
    fit = compose_fit(
        _nlp_lab(), _profile(interests=["LLM agents"], university="Elsewhere"), [_resume()],
        opportunity=opportunity, match=match,
    )

    blocking = [g for g in fit.potential_gaps if g.blocking]
    assert [g.label for g in blocking] == ["Must be a current Stanford undergraduate"]
    assert fit.potential_gaps[0].blocking is True


def test_nothing_reported_as_an_overlap_is_also_reported_as_a_gap():
    """A panel that claims an overlap on computer vision in one group and calls
    computer vision missing in the next is arguing with itself."""
    lab = _faculty(
        evidence=[
            _evidence("Evaluating LLM agents on execution outcomes", topics=["llm-agents"]),
            _evidence("Robot learning from human demonstrations", year=2025,
                      topics=["robot-learning"]),
        ],
        topics=[_topic("llm-agents", "LLM Agents", origin="evidence")],
    )
    fit = compose_fit(lab, _profile(interests=["LLM agents"]), [_resume()])

    assert [p.label for p in fit.strong_overlap] == ["LLM agents"]
    assert [g.label for g in fit.potential_gaps] == [
        "No Robot Learning in your profile or resumes"
    ]


# ------------------------------------------------------------- determinism


def test_the_same_inputs_always_produce_the_same_breakdown():
    profile = _profile(interests=["LLM agents", "NLP", "human-AI interaction"])
    lab = _nlp_lab()
    first = compose_fit(lab, profile, [_resume()])
    second = compose_fit(_nlp_lab(), profile, [_resume()])

    assert [p.evidence for p in first.strong_overlap] == [p.evidence for p in second.strong_overlap]
    assert [p.detail for p in first.relevant_background] == [
        p.detail for p in second.relevant_background
    ]
    assert [g.note for g in first.potential_gaps] == [g.note for g in second.potential_gaps]


def test_certainty_vocabulary_is_untouched_by_this_module():
    """The breakdown states facts about documents, so it never invents a new
    confidence word alongside the four in docs/uncertainty.md."""
    fit = compose_fit(_nlp_lab(), _profile(interests=["LLM agents"]), [_resume()])
    words = {c.value for c in Certainty}

    blob = " ".join(
        [p.evidence for p in fit.strong_overlap]
        + [g.note for g in fit.potential_gaps]
    ).lower()
    assert not (words - {"unknown"}) & set(blob.split())


def test_an_inferred_requirement_raises_no_gap_at_all():
    """Nobody stated it. Failing a student against a bar we invented ourselves
    is worse than staying quiet."""
    requirement = Requirement(
        text="Likely expects two prior research quarters",
        kind=RequirementKind.INFERRED,
        category="experience",
        skill_slugs=[],
        order_index=0,
    )
    requirement.id = uuid.uuid4()
    opportunity = Opportunity(title="RA", requirements=[requirement])
    match = OpportunityMatch(
        fit_score=40.0,
        confidence=0.4,
        model="deterministic",
        requirement_matches=[
            {
                "requirement_id": str(requirement.id),
                "text": requirement.text,
                "kind": RequirementKind.INFERRED.value,
                "category": "experience",
                "state": RequirementMatch.MISSING.value,
                "reason": "No prior research quarters recorded.",
                "evidence": None,
            }
        ],
    )
    fit = compose_fit(
        _nlp_lab(), _profile(interests=["LLM agents"]), [_resume()],
        opportunity=opportunity, match=match,
    )

    assert all("research quarters" not in g.label for g in fit.potential_gaps)
