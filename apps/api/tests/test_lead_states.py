"""Guards on the four lead states, the direction claims and the timing signal.

Every failure pinned here is one where the product would be lying to a student
about a lab: an opening that is really a postdoc posting, a direction the lab
stopped working on, or urgency assembled out of nothing.
"""

from __future__ import annotations

from datetime import date

from app.agents.base import AgentContext
from app.agents.research_agent import ResearchDiscoveryAgent
from app.core.config import get_settings
from app.models.enums import Certainty, EvidenceKind, LeadState, SignalKind
from app.models.research import Faculty, Lab, LabSignal, ResearchEvidence
from app.services.directions import direction_claims, why_now

TODAY = date(2026, 9, 1)


def _ctx() -> AgentContext:
    # The classifier only reads ``ctx.today``; nothing here touches the session.
    return AgentContext(db=None, today=TODAY)  # type: ignore[arg-type]


def _faculty(**kw) -> Faculty:
    base = dict(
        slug="test-pi",
        name="Test PI",
        university="Stanford University",
        department="Computer Science",
        faculty_url="https://example.edu/pi",
        email=None,
        email_certainty=Certainty.UNKNOWN,
        current_direction=[],
        current_direction_certainty=Certainty.UNKNOWN,
        evidence=[],
        signals=[],
        labs=[],
        topics=[],
    )
    base.update(kw)
    return Faculty(**base)


def _evidence(title: str, year: int, *, summary: str = "", kind=EvidenceKind.PUBLICATION):
    return ResearchEvidence(
        kind=kind, title=title, summary=summary, year=year, url=f"https://example.edu/{year}"
    )


def _recruiting(statement: str, *, certainty=Certainty.VERIFIED, status="open", url="https://lab.edu/join"):
    return LabSignal(
        kind=SignalKind.RECRUITING,
        label="Says it is recruiting students",
        certainty=certainty,
        statement=statement,
        source_url=url,
        note=f"harvest recruiting.status = {status}",
    )


def _undergrad(label: str, *, certainty=Certainty.VERIFIED, url="https://lab.edu/people"):
    return LabSignal(
        kind=SignalKind.UNDERGRAD_PRESENCE, label=label, certainty=certainty, source_url=url
    )


def classify(faculty: Faculty):
    evidence = sorted(faculty.evidence, key=lambda e: (e.year or 0), reverse=True)
    return ResearchDiscoveryAgent()._classify(faculty, evidence, _ctx(), get_settings())


# --------------------------------------------------------------- lead state


def test_quoted_undergraduate_invitation_is_an_opening():
    faculty = _faculty(
        evidence=[_evidence("A recent paper on robot manipulation", 2026)],
        signals=[
            _recruiting(
                "Stanford Undergraduate and Masters: We are happy to work with "
                "masters or undergraduate students. Please apply via the form."
            )
        ],
        email="pi@example.edu",
        email_certainty=Certainty.VERIFIED,
    )
    state, signals = classify(faculty)
    assert state is LeadState.OPENING
    opening = next(s for s in signals if s.key == "verified_opening")
    assert opening.source_url == "https://lab.edu/join"
    assert "undergraduate students" in (opening.detail or "")


def test_postdoc_only_posting_is_never_an_opening():
    """The exact shape that promoted three labs wrongly: a verified, open,
    sourced statement whose only mention of undergraduates rules them out."""
    faculty = _faculty(
        evidence=[_evidence("Robot learning at scale", 2026)],
        signals=[
            _recruiting("POSTDOC ONLY - not an undergraduate opening. Ph.D. required."),
            # Undergraduates really are in this lab; that still does not make
            # the postdoc posting an undergraduate opening.
            _undergrad("Lab page lists two named undergraduate members"),
        ],
        email="pi@example.edu",
        email_certainty=Certainty.VERIFIED,
    )
    state, _ = classify(faculty)
    assert state is LeadState.OUTREACH


def test_verification_note_about_absent_language_is_not_an_opening():
    faculty = _faculty(
        evidence=[_evidence("Humanoid control", 2026)],
        signals=[
            _recruiting(
                "We are looking for researchers and engineers. LIMIT ON DEGREE LEVEL: "
                "neither posting contains the word 'undergraduate' or any degree level."
            ),
            _undergrad("Lab People page lists nine current members with the role 'Undergrad'"),
        ],
        email="pi@example.edu",
        email_certainty=Certainty.VERIFIED,
    )
    state, _ = classify(faculty)
    assert state is LeadState.OUTREACH


def test_outreach_needs_a_contact_route():
    """Recent work and undergraduates in the lab, but nowhere to send an email."""
    faculty = _faculty(
        evidence=[_evidence("Recent paper", 2026), _evidence("Another paper", 2025)],
        signals=[_undergrad("Lab roster lists three current undergraduate members")],
    )
    state, signals = classify(faculty)
    assert state is LeadState.WATCH
    assert "public_contact" not in {s.key for s in signals}


def test_stale_lab_with_no_contact_is_unknown_not_outreach():
    """The rule this whole state exists for: never invent something to click."""
    faculty = _faculty(evidence=[_evidence("An old paper", 2018), _evidence("Older", 2016)])
    state, signals = classify(faculty)
    assert state is LeadState.UNKNOWN
    assert signals == []


def test_retired_faculty_is_not_an_outreach_lead():
    faculty = _faculty(
        evidence=[_evidence("A note", 2026), _evidence("A project", 2025)],
        email="pi@example.edu",
        email_certainty=Certainty.VERIFIED,
        signals=[
            _undergrad(
                "He retired from teaching at Stanford in 2017, so there is no current "
                "course through which an undergraduate could work with him",
                url="https://example.edu/bio",
            ),
        ],
    )
    state, signals = classify(faculty)
    assert state is LeadState.WATCH
    assert "no_longer_reachable" in {s.key for s in signals}


def test_negated_undergraduate_claims_do_not_count_as_presence():
    faculty = _faculty(
        evidence=[_evidence("Recent paper", 2026), _evidence("Recent paper 2", 2026)],
        email="pi@example.edu",
        email_certainty=Certainty.VERIFIED,
        signals=[
            _undergrad("No undergraduate members listed on the lab People page"),
            _undergrad("Lab people page has an 'Undergraduates' category, but it is empty"),
        ],
    )
    state, signals = classify(faculty)
    keys = {s.key for s in signals}
    assert not (keys & {"undergrads_in_lab", "undergrad_invited", "undergrad_track_record"})
    assert state is LeadState.WATCH


def test_close_scoped_to_phd_students_still_allows_outreach():
    faculty = _faculty(
        evidence=[_evidence("Recent paper", 2026)],
        email="pi@example.edu",
        email_certainty=Certainty.VERIFIED,
        signals=[
            LabSignal(
                kind=SignalKind.RECRUITING,
                label="Says it is not currently recruiting",
                certainty=Certainty.VERIFIED,
                statement=(
                    "Dr. Fan is not currently recruiting PhD students for Fall 2027. "
                    "Current Stanford students are welcome to get involved in the lab."
                ),
                source_url="https://lab.edu/prospective",
                note="harvest recruiting.status = closed",
            ),
            _undergrad("Lab people page lists two current undergraduates"),
        ],
    )
    state, signals = classify(faculty)
    assert state is LeadState.OUTREACH
    # The caveat is still shown; it just does not block the lead.
    assert "recruiting_narrowed" in {s.key for s in signals}


def test_blanket_close_blocks_outreach():
    faculty = _faculty(
        evidence=[_evidence("Recent paper", 2026), _evidence("Recent paper 2", 2026)],
        email="pi@example.edu",
        email_certainty=Certainty.VERIFIED,
        signals=[
            LabSignal(
                kind=SignalKind.RECRUITING,
                label="Says it is not currently recruiting",
                certainty=Certainty.VERIFIED,
                statement="We are not taking new students of any kind this year.",
                source_url="https://lab.edu/prospective",
                note="harvest recruiting.status = closed",
            ),
            _undergrad("Lab people page lists two current undergraduates"),
        ],
    )
    state, signals = classify(faculty)
    assert state is LeadState.WATCH
    assert "recruiting_closed" in {s.key for s in signals}


def test_every_signal_carries_a_source_url():
    faculty = _faculty(
        evidence=[_evidence("Recent paper", 2026)],
        email="pi@example.edu",
        email_certainty=Certainty.VERIFIED,
        email_source_url="https://example.edu/pi",
        signals=[
            _undergrad("Lab roster lists two current undergraduate members"),
            # Unsourced claims must not reach the student at all.
            LabSignal(
                kind=SignalKind.UNDERGRAD_PRESENCE,
                label="CURIS participation",
                certainty=Certainty.UNKNOWN,
                source_url=None,
            ),
        ],
    )
    _, signals = classify(faculty)
    assert signals
    assert all(s.source_url for s in signals)
    assert all("CURIS participation" not in s.label for s in signals)


def test_lab_join_url_counts_as_a_contact_route():
    faculty = _faculty(
        evidence=[_evidence("Recent paper", 2026)],
        signals=[_undergrad("Lab roster lists two current undergraduate members")],
    )
    faculty.labs = [
        Lab(
            name="Test Lab",
            slug="test-lab",
            university="Stanford University",
            url="https://lab.edu/",
            join_url="https://lab.edu/join",
        )
    ]
    state, signals = classify(faculty)
    assert state is LeadState.OUTREACH
    assert "public_contact" in {s.key for s in signals}


# -------------------------------------------------------------- directions


def test_direction_keeps_only_evidence_inside_the_recency_window():
    faculty = _faculty(
        current_direction=["Tactile manipulation with rolling graspers"],
        current_direction_certainty=Certainty.LIKELY,
        evidence=[
            _evidence("Tactile-Reactive Roller Grasper", 2026),
            # 2018 is history, not current direction.
            _evidence("Tactile manipulation with rolling graspers", 2018),
        ],
    )
    claims = direction_claims(faculty, today=TODAY)
    assert len(claims) == 1
    assert [e.evidence.year for e in claims[0].evidence] == [2026]


def test_direction_with_no_supporting_evidence_is_dropped():
    faculty = _faculty(
        current_direction=[
            "Generative interfaces that adapt the UI to the person",
            "Tactile manipulation with rolling graspers",
        ],
        current_direction_certainty=Certainty.LIKELY,
        evidence=[_evidence("Tactile-Reactive Roller Grasper", 2026)],
    )
    claims = direction_claims(faculty, today=TODAY)
    assert [c.direction for c in claims] == ["Tactile manipulation with rolling graspers"]


def test_why_is_derived_from_words_that_are_really_shared():
    faculty = _faculty(
        current_direction=["Auditing what AI agents do to human work"],
        current_direction_certainty=Certainty.LIKELY,
        evidence=[
            _evidence("Future of Work with AI Agents: Auditing Automation Potential", 2026)
        ],
    )
    claim = direction_claims(faculty, today=TODAY)[0]
    why = claim.evidence[0].why.lower()
    assert "auditing" in why and "agents" in why
    # Every word quoted in the reason appears in BOTH texts, character for
    # character. That is what makes this derived rather than written.
    clause = why.split(";")[0]
    quoted = [w for w in clause.split("names ", 1)[1].replace(" and ", ", ").split(", ") if w]
    direction = claim.direction.lower()
    title = claim.evidence[0].evidence.title.lower()
    assert all(word in direction and word in title for word in quoted)


def test_field_level_overlap_alone_is_not_support():
    """"Both mention AI and models" links nothing to anything."""
    faculty = _faculty(
        current_direction=["Machine learning models for AI systems"],
        current_direction_certainty=Certainty.LIKELY,
        evidence=[_evidence("AI models for protein folding", 2026)],
    )
    assert direction_claims(faculty, today=TODAY) == []


def test_no_recent_evidence_means_no_direction_claims():
    faculty = _faculty(
        current_direction=["Something the lab used to do"],
        current_direction_certainty=Certainty.LIKELY,
        evidence=[_evidence("Something the lab used to do", 2017)],
    )
    assert direction_claims(faculty, today=TODAY) == []


# ----------------------------------------------------------------- why now


def test_no_timing_signal_returns_none():
    faculty = _faculty(evidence=[_evidence("A single recent paper on graphs", 2026)])
    assert why_now(faculty, today=TODAY, claims=[]) is None


def test_recent_lab_news_is_a_timing_signal():
    faculty = _faculty(
        evidence=[
            _evidence("Four papers accepted to ICML 2026", 2026, kind=EvidenceKind.NEWS),
            _evidence("A paper", 2026),
        ]
    )
    signal = why_now(faculty, today=TODAY, claims=[])
    assert signal is not None
    assert "2026" in signal.statement
    assert signal.evidence


def test_stale_news_is_not_a_timing_signal():
    faculty = _faculty(
        evidence=[_evidence("An old announcement", 2019, kind=EvidenceKind.NEWS)]
    )
    assert why_now(faculty, today=TODAY, claims=[]) is None


def test_fetch_dates_in_recruiting_prose_never_become_urgency():
    """"re-fetched 2026-08-31" is when we looked, not when they wrote."""
    from app.services.directions import _recent_recruiting_year

    assert _recent_recruiting_year("re-fetched 2026-08-31", posted_floor=2025, cycle=2026) is None
    assert (
        _recent_recruiting_year("Date posted: Oct 30th 2026", posted_floor=2025, cycle=2026)
        == 2026
    )
    # An academic year that has already ended is not the current cycle.
    assert _recent_recruiting_year("applications for 2025-26", posted_floor=2025, cycle=2026) is None
