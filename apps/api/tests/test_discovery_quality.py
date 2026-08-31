"""Guards on the confidence gate, the run ledger and rejected-result suppression.

Every failure pinned here is one where discovery would cost the student
something real: a verified opening buried behind a "low confidence" label, a
half-read page presented as a recommendation with a fit score on it, a run
reporting numbers that do not add up, or something they already dismissed
handed back as a new find.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.search_agent import OpportunitySearchAgent, SearchOutcome
from app.services.confidence import (
    HOLD_BELOW_CONFIDENCE,
    assess_extraction,
    assess_row,
)
from app.services.signals import NEGATIVE_KINDS, Suppressions


def _page(**kw) -> dict:
    """An extraction result, shaped the way WebExtractionAgent emits one."""
    base: dict = {
        "title": "Research Assistant",
        "extraction_confidence": 0.50,
        "requirements": [],
        "deadline": None,
        "pay_text": None,
        "pay_min": None,
        "hours_per_week": None,
        "application_method": None,
        "application_url": None,
        "contact_email": None,
        "description": "",
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------- gate


def test_thin_extraction_is_held_and_says_what_was_missing():
    """A title and nothing else is not something to put in front of a student."""
    verdict = assess_extraction(_page(description="Apply now. Positions available."))
    assert verdict.hold
    assert verdict.state == "held"
    # The reason is rendered verbatim next to the row, so it has to name the
    # absence rather than label the row.
    assert "deadline" in verdict.reason
    assert "way to apply" in verdict.reason
    assert "low quality" not in verdict.reason.lower()


def test_one_actionable_fact_is_enough_to_stay_in_the_list():
    """The gate asks whether we read anything, not whether we read everything."""
    for field, value in (
        ("deadline", "2026-10-01"),
        ("pay_text", "$18.00/hour"),
        ("hours_per_week", 10),
        ("application_url", "https://example.edu/apply"),
        ("contact_email", "pi@stanford.edu"),
    ):
        verdict = assess_extraction(_page(**{field: value}))
        assert not verdict.hold, f"{field} alone should keep the row"
        assert verdict.evidence


def test_verified_harvest_rows_are_never_held():
    """The Recreation & Wellness block: 13 real campus jobs at confidence 0.55.

    They sit below the threshold and are exactly the rows a naive confidence
    cut-off would delete. Pinned with their real shape — pay, a stated
    application route, a short description, and no parsed requirements.
    """
    lifeguard = _page(
        title="Lifeguard",
        extraction_confidence=0.55,
        pay_text="$19.50 - $21.00 per hour",
        application_method=(
            "Download and submit the Recreation & Wellness electronic application"
        ),
        application_url="https://rec.stanford.edu/employment",
        description="x" * 681,
    )
    verdict = assess_extraction(lifeguard)
    assert not verdict.hold
    assert "stated pay" in verdict.reason


def test_a_clean_read_with_nothing_actionable_is_not_held():
    """Confidence is a field count, not a quality score, so a page that came
    through cleanly is left alone even when it states nothing to act on."""
    verdict = assess_extraction(
        _page(extraction_confidence=HOLD_BELOW_CONFIDENCE, description="y" * 4000)
    )
    assert not verdict.hold


def test_confidence_alone_never_holds_a_row():
    """The lowest possible confidence cannot hold a row that states a fact."""
    verdict = assess_extraction(_page(extraction_confidence=0.0, deadline="2026-10-01"))
    assert not verdict.hold


@dataclass
class _Row:
    """The stored fields assess_row reads. Enough of an Opportunity to judge."""

    extraction_confidence: float = 0.50
    deadline: object = None
    pay_text: str | None = None
    pay_min: float | None = None
    hours_per_week: int | None = None
    application_method: str | None = None
    application_url: str | None = None
    contact_email: str | None = None
    description: str | None = None
    faculty_id: object = None
    requirements: tuple = ()


def test_faculty_leads_are_exempt_from_the_extraction_gate():
    """Seven faculty leads sit at confidence 0.00 with no posting behind them.

    There is nothing to extract from a PI record, so extraction_confidence is
    measuring the wrong thing; their honesty lives in lead_state instead.
    """
    lead = _Row(extraction_confidence=0.0, faculty_id="a-real-uuid")
    verdict = assess_row(lead)
    assert not verdict.hold
    assert "lead state" in verdict.reason


def test_a_held_row_that_reextracts_well_is_promoted():
    thin = _Row(extraction_confidence=0.50)
    assert assess_row(thin).hold

    @dataclass
    class _Req:
        text: str

    better = _Row(
        extraction_confidence=0.85,
        requirements=(_Req("Enrolled Stanford undergraduate"), _Req("Available 10 hrs/week")),
        application_url="https://example.edu/apply",
    )
    assert not assess_row(better).hold


# -------------------------------------------------------------- run ledger


def test_summary_reports_every_bucket_that_happened():
    """The step text is the whole report for most students, so it may not omit
    a bucket that is non-zero — especially the ones where we withheld a row."""
    summary = OpportunitySearchAgent()._summary(
        SearchOutcome(
            created=3, updated=2, unchanged=7, expired=1, held=4, skipped=9, suppressed=2
        )
    )
    assert "3 new" in summary
    assert "2 updated" in summary
    assert "7 unchanged" in summary
    assert "1 expired" in summary
    assert "4 held as low-confidence" in summary
    assert "9 skipped as not an opening" in summary
    assert "you rejected" in summary


def test_summary_stays_short_when_nothing_was_withheld():
    summary = OpportunitySearchAgent()._summary(SearchOutcome(created=1, unchanged=4))
    assert summary == "1 new, 0 updated, 4 unchanged."


# ------------------------------------------------------------- suppression


def test_suppression_blocks_by_url_and_by_external_key():
    s = Suppressions(
        urls={"https://jobs.stanford.edu/posting/1"},
        external_keys={"req-200761"},
        available=True,
    )
    assert s.blocks(url="https://jobs.stanford.edu/posting/1", external_key=None)
    assert s.blocks(url=None, external_key="req-200761")
    assert not s.blocks(url="https://jobs.stanford.edu/posting/2", external_key="other")


def test_an_empty_suppression_set_never_blocks_anything():
    """Written defensively because the feedback table may not exist yet: the
    absence of a place to record a rejection must not silently drop results."""
    s = Suppressions()
    assert not s
    assert not s.blocks(url="https://example.edu/x", external_key="k")


def test_negative_kinds_are_only_the_rejections():
    """A signals table also records saves and applications; suppressing on those
    would hide the things the student liked most."""
    assert "hidden" in NEGATIVE_KINDS
    assert "not_relevant" in NEGATIVE_KINDS
    for positive in ("saved", "interested", "applied", "starred"):
        assert positive not in NEGATIVE_KINDS


def test_load_suppressions_survives_a_missing_feedback_table():
    """The Signals phase may not have landed. Discovery must still run."""
    from app.db.session import session_scope
    from app.services.signals import load_suppressions

    with session_scope() as db:
        result = load_suppressions(db, None)
    assert isinstance(result, Suppressions)
    # available=False is a fact about the schema, not about the student.
    assert result.available in (True, False)


def test_a_rejection_is_found_once_the_signals_table_exists():
    """Pins the shape the Signals phase will land, without depending on it.

    The table is created inside a transaction and rolled back, so this proves
    the introspection actually works rather than only that it fails safely.
    Postgres DDL is transactional, so nothing survives the test.
    """
    from sqlalchemy import select, text

    from app.db.session import SessionLocal
    from app.models.opportunity import Opportunity
    from app.services.signals import load_suppressions

    db = SessionLocal()
    try:
        row = db.execute(
            select(Opportunity.id, Opportunity.source_url).limit(1)
        ).first()
        if row is None:
            return  # empty database; nothing to reject
        db.execute(
            text(
                "CREATE TABLE opportunity_signals ("
                "  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
                "  opportunity_id uuid, kind text, cleared_at timestamptz)"
            )
        )
        db.execute(
            text(
                "INSERT INTO opportunity_signals (opportunity_id, kind) "
                "VALUES (:oid, 'not_relevant')"
            ),
            {"oid": row.id},
        )
        found = load_suppressions(db, None)
        assert found.available
        assert row.id in found.opportunity_ids
        if row.source_url:
            assert found.urls

        # A withdrawn signal must stop suppressing: unhiding has to work.
        db.execute(text("UPDATE opportunity_signals SET cleared_at = now()"))
        assert not load_suppressions(db, None).opportunity_ids

        # And a positive signal must never suppress anything.
        db.execute(
            text("UPDATE opportunity_signals SET cleared_at = NULL, kind = 'saved'")
        )
        assert not load_suppressions(db, None).opportunity_ids
    finally:
        db.rollback()
        db.close()
