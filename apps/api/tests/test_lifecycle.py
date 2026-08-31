"""Guards on deadlines you can trust.

Every failure pinned here is one where the product would mislead a student
about time: a deadline that moved without saying so, a date that vanished from
a posting and was rendered as "we never knew", an expired opportunity offered
as a recommendation, or — worst — a source outage marking a page of live
postings as gone.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.agents.base import AgentContext
from app.agents.deadline_agent import DeadlineAgent, DeadlineRequest, urgency_for
from app.agents.search_agent import OpportunitySearchAgent, SearchRequest
from app.api.routes import opportunities as opportunity_routes
from app.llm.deterministic import DeterministicProvider
from app.models.change import ChangeKind, OpportunityChange
from app.models.enums import (
    DeadlineState,
    DeadlineType,
    OpportunityStatus,
    OpportunityType,
    SearchKind,
    SourceKind,
    SourceStatus,
)
from app.models.opportunity import Opportunity, OpportunitySource
from app.schemas import common as S
from app.services.dedup import upsert_opportunity
from app.services.lifecycle import (
    deadline_state_for,
    reconcile_source,
    sweep_expired,
)
from app.services.runs import start_run
from app.sources.base import DiscoveredDocument, SourceAdapter
from app.sources.registry import SOURCE_ADAPTERS

TODAY = date(2026, 9, 1)
NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _source(db, slug: str = "test-source") -> OpportunitySource:
    row = OpportunitySource(
        slug=f"{slug}-{uuid.uuid4().hex[:8]}",
        name="Test source",
        kind=SourceKind.CAMPUS_JOBS,
        base_url="https://jobs.example.edu",
    )
    db.add(row)
    db.flush()
    return row


def _posting(url: str, deadline: date | None, **extra) -> dict:
    data = {
        "title": "Undergraduate Research Assistant",
        "type": OpportunityType.ON_CAMPUS.value,
        "source_url": url,
        "deadline": deadline,
        "deadline_type": DeadlineType.HARD.value if deadline else DeadlineType.UNKNOWN.value,
    }
    data.update(extra)
    return data


def _opportunity(db, source, url: str, deadline: date | None, **extra) -> Opportunity:
    opp = Opportunity(
        title=extra.pop("title", "Undergraduate Research Assistant"),
        type=OpportunityType.ON_CAMPUS,
        status=extra.pop("status", OpportunityStatus.NEW),
        source_id=source.id if source else None,
        source_url=url,
        deadline=deadline,
        deadline_type=DeadlineType.HARD if deadline else DeadlineType.UNKNOWN,
        deadline_state=DeadlineState.HARD if deadline else DeadlineState.UNKNOWN,
        first_seen_at=NOW,
        **extra,
    )
    db.add(opp)
    db.flush()
    return opp


def _changes(db, opp: Opportunity, kind: ChangeKind | None = None) -> list[OpportunityChange]:
    stmt = select(OpportunityChange).where(OpportunityChange.opportunity_id == opp.id)
    if kind is not None:
        stmt = stmt.where(OpportunityChange.kind == kind)
    return list(db.scalars(stmt.order_by(OpportunityChange.noticed_at)))


# --------------------------------------------------------------------------
# 1. the vocabulary
# --------------------------------------------------------------------------


def test_deadline_state_vocabulary():
    assert deadline_state_for(date(2026, 9, 15), DeadlineType.HARD, TODAY) == DeadlineState.HARD
    assert deadline_state_for(None, DeadlineType.ROLLING, TODAY) == DeadlineState.ROLLING
    assert deadline_state_for(None, DeadlineType.UNKNOWN, TODAY) == DeadlineState.UNKNOWN
    assert deadline_state_for(date(2026, 8, 28), DeadlineType.HARD, TODAY) == DeadlineState.EXPIRED
    # Today is still today: a deadline does not expire until it has passed.
    assert deadline_state_for(TODAY, DeadlineType.HARD, TODAY) == DeadlineState.HARD


def test_expired_never_reads_as_urgent_or_due_today():
    """The whole point: a lapsed date must never wear the colour of a live one."""
    urgency = urgency_for(date(2026, 8, 20), DeadlineType.HARD, TODAY)
    assert urgency == "overdue"
    assert urgency not in ("urgent", "soon", "later")


# --------------------------------------------------------------------------
# 2. deadline change detection
# --------------------------------------------------------------------------


def test_deadline_move_is_logged(db):
    """Sep 10 -> Sep 15 is logged, with both dates in the sentence."""
    source = _source(db)
    url = "https://jobs.example.edu/ra-1"
    opp, first = upsert_opportunity(db, _posting(url, date(2026, 9, 10)), source=source, now=NOW)
    assert first == "created"

    opp, outcome = upsert_opportunity(db, _posting(url, date(2026, 9, 15)), source=source, now=NOW)
    assert outcome == "updated"

    logged = _changes(db, opp, ChangeKind.DEADLINE)
    assert len(logged) == 1
    assert logged[0].summary == "Deadline moved from Sep 10, 2026 to Sep 15, 2026."
    assert logged[0].old_value == "2026-09-10"
    assert logged[0].new_value == "2026-09-15"
    assert opp.deadline == date(2026, 9, 15)


def test_deadline_disappearing_is_logged_honestly(db):
    """Sep 10 -> Unknown. The date VANISHING is a change, and the summary must
    say what it used to be rather than reading as "we never knew"."""
    source = _source(db)
    url = "https://jobs.example.edu/ra-2"
    upsert_opportunity(db, _posting(url, date(2026, 9, 10)), source=source, now=NOW)
    opp, outcome = upsert_opportunity(db, _posting(url, None), source=source, now=NOW)

    assert outcome == "updated"
    assert opp.deadline is None
    logged = _changes(db, opp, ChangeKind.DEADLINE)
    assert len(logged) == 1
    assert logged[0].summary == (
        "Deadline removed from the posting — it previously said Sep 10, 2026."
    )
    assert logged[0].old_value == "2026-09-10"
    assert logged[0].new_value is None


def test_deadline_agent_logs_a_date_it_can_no_longer_find(db):
    """The agent writes the deadline last, so it owns the removal when the page
    it re-read no longer states one."""
    source = _source(db)
    opp = _opportunity(db, source, "https://jobs.example.edu/ra-3", date(2026, 9, 10))

    ctx = AgentContext(db=db, today=TODAY)
    DeadlineAgent().run(
        ctx,
        DeadlineRequest(opportunity=opp, text="Applications are read as they arrive."),
    )
    db.flush()

    assert opp.deadline is None
    logged = _changes(db, opp, ChangeKind.DEADLINE)
    assert len(logged) == 1
    assert "previously said Sep 10, 2026" in logged[0].summary


def test_deadline_agent_does_not_double_log_a_first_date(db):
    """A first date on a row is already reported by the upsert or by
    "Discovered"; the agent must not print the same fact twice."""
    source = _source(db)
    opp = _opportunity(db, source, "https://jobs.example.edu/ra-4", None)

    ctx = AgentContext(db=db, today=TODAY)
    DeadlineAgent().run(
        ctx, DeadlineRequest(opportunity=opp, text="Apply by September 15, 2026.")
    )
    db.flush()

    assert opp.deadline == date(2026, 9, 15)
    assert _changes(db, opp, ChangeKind.DEADLINE) == []


# --------------------------------------------------------------------------
# 3. expiry is a recorded state
# --------------------------------------------------------------------------


def test_sweep_marks_expired_and_logs_it_once(db):
    source = _source(db)
    opp = _opportunity(db, source, "https://jobs.example.edu/ra-5", date(2026, 8, 20))
    assert opp.deadline_state == DeadlineState.HARD

    first = sweep_expired(db, TODAY, now=NOW)
    assert first.expired == 1
    assert opp.deadline_state == DeadlineState.EXPIRED

    # Idempotent: the state is stored, so a second sweep has nothing to say.
    second = sweep_expired(db, TODAY, now=NOW)
    assert second.expired == 0

    logged = _changes(db, opp, ChangeKind.EXPIRED)
    assert len(logged) == 1
    assert "Aug 20, 2026" in logged[0].summary
    assert logged[0].new_value == "expired"


def test_sweep_leaves_rolling_and_unknown_alone(db):
    source = _source(db)
    rolling = _opportunity(db, source, "https://jobs.example.edu/roll", None)
    rolling.deadline_type = DeadlineType.ROLLING
    rolling.deadline_state = DeadlineState.ROLLING
    unknown = _opportunity(db, source, "https://jobs.example.edu/unknown", None)
    db.flush()

    sweep_expired(db, TODAY, now=NOW)

    assert rolling.deadline_state == DeadlineState.ROLLING
    assert unknown.deadline_state == DeadlineState.UNKNOWN
    assert _changes(db, rolling) == []
    assert _changes(db, unknown) == []


def test_sweep_never_deletes(db):
    source = _source(db)
    opp = _opportunity(db, source, "https://jobs.example.edu/ra-6", date(2026, 1, 30))
    opp_id = opp.id
    sweep_expired(db, TODAY, now=NOW)
    db.flush()
    assert db.get(Opportunity, opp_id) is not None


def test_an_extended_deadline_is_live_again(db):
    """A posting that moves its date into the future stops being expired."""
    source = _source(db)
    url = "https://jobs.example.edu/ra-7"
    upsert_opportunity(db, _posting(url, date(2026, 8, 20)), source=source, now=NOW)
    sweep_expired(db, TODAY, now=NOW)

    opp, outcome = upsert_opportunity(db, _posting(url, date(2026, 10, 1)), source=source, now=NOW)
    assert outcome == "updated"
    assert opp.deadline_state == DeadlineState.HARD
    assert "moved from Aug 20, 2026 to Oct 1, 2026" in _changes(db, opp, ChangeKind.DEADLINE)[0].summary


def test_re_running_discovery_does_not_re_expire(db):
    """An unchanged expired row must not flip back to hard and be logged again
    every time discovery runs — that would fill the change log with noise."""
    source = _source(db)
    url = "https://jobs.example.edu/ra-8"
    data = _posting(url, date(2026, 8, 20))
    upsert_opportunity(db, data, source=source, now=NOW)
    sweep_expired(db, TODAY, now=NOW)

    opp, outcome = upsert_opportunity(db, data, source=source, now=NOW)
    assert outcome == "unchanged"
    assert opp.deadline_state == DeadlineState.EXPIRED
    sweep_expired(db, TODAY, now=NOW)
    assert len(_changes(db, opp, ChangeKind.EXPIRED)) == 1


def test_recommended_sort_sinks_expired(db):
    """An expired opportunity may never surface near the top of "recommended",
    however good the fit."""

    def item(title: str, **kw) -> S.OpportunityListItem:
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

    expired = item("Perfect but expired", urgency="overdue", deadline_state="expired", fit_score=99.0)
    live = item("Decent and live", fit_score=40.0)
    ordered = opportunity_routes._sort([expired, live], "recommended")
    assert [i.title for i in ordered] == ["Decent and live", "Perfect but expired"]

    ordered = opportunity_routes._sort([expired, live], "deadline")
    assert [i.title for i in ordered] == ["Decent and live", "Perfect but expired"]


def test_opportunities_router_exposes_no_delete():
    """History matters: there is no route that can remove an opportunity.

    A sub-resource of your own may be deleted — undoing a feedback signal is a
    DELETE on ``/opportunities/{id}/feedback`` — but no DELETE anywhere in this
    router addresses the opportunity row itself.
    """
    deletable = {
        route.path
        for route in opportunity_routes.router.routes
        if "DELETE" in getattr(route, "methods", set())
    }
    for path in deletable:
        assert not path.endswith("{opportunity_id}"), f"{path} would delete the opportunity"
    assert "/opportunities/{opportunity_id}" not in deletable


# --------------------------------------------------------------------------
# 4. postings that vanish from their source
# --------------------------------------------------------------------------


def test_absent_posting_is_flagged_not_deleted(db):
    source = _source(db)
    still_there = _opportunity(db, source, "https://jobs.example.edu/a", None)
    taken_down = _opportunity(db, source, "https://jobs.example.edu/b", None)

    report = reconcile_source(
        db,
        source,
        seen_urls={"https://jobs.example.edu/a"},
        seen_keys=set(),
        source_succeeded=True,
        now=NOW,
    )

    assert report.marked_gone == 1
    assert still_there.source_status == SourceStatus.LIVE
    assert taken_down.source_status == SourceStatus.GONE
    assert taken_down.source_status_at == NOW
    assert db.get(Opportunity, taken_down.id) is not None

    logged = _changes(db, taken_down, ChangeKind.DISAPPEARED)
    assert len(logged) == 1
    assert "Source no longer available" in logged[0].summary


def test_a_source_that_failed_wholesale_marks_nothing(db):
    """The dangerous case: one network error must not declare a whole source's
    postings dead."""
    source = _source(db)
    opp = _opportunity(db, source, "https://jobs.example.edu/c", None)

    report = reconcile_source(
        db, source, seen_urls=set(), seen_keys=set(), source_succeeded=False, now=NOW
    )
    assert report.marked_gone == 0
    assert opp.source_status == SourceStatus.LIVE

    # And an "empty success" is not evidence either: a source that answers with
    # nothing at all is indistinguishable from one that quietly broke.
    report = reconcile_source(
        db, source, seen_urls=set(), seen_keys=set(), source_succeeded=True, now=NOW
    )
    assert report.marked_gone == 0
    assert opp.source_status == SourceStatus.LIVE
    assert _changes(db, opp) == []


def test_reconciliation_only_touches_its_own_source(db):
    one = _source(db, "one")
    two = _source(db, "two")
    mine = _opportunity(db, one, "https://jobs.example.edu/mine", None)
    theirs = _opportunity(db, two, "https://jobs.example.edu/theirs", None)

    reconcile_source(
        db,
        one,
        seen_urls={"https://jobs.example.edu/mine"},
        seen_keys=set(),
        source_succeeded=True,
        now=NOW,
    )
    assert mine.source_status == SourceStatus.LIVE
    assert theirs.source_status == SourceStatus.LIVE


def test_a_posting_matched_by_external_key_is_not_marked_gone(db):
    """URLs change; the per-source key is the stronger identity and must count."""
    source = _source(db)
    opp = _opportunity(db, source, "https://jobs.example.edu/old-path", None)
    opp.external_key = "req-200888"
    db.flush()

    report = reconcile_source(
        db,
        source,
        seen_urls={"https://jobs.example.edu/new-path"},
        seen_keys={"req-200888"},
        source_succeeded=True,
        now=NOW,
    )
    assert report.marked_gone == 0
    assert opp.source_status == SourceStatus.LIVE


def test_a_returning_posting_is_marked_live_again(db):
    source = _source(db)
    opp = _opportunity(db, source, "https://jobs.example.edu/d", None)
    opp.source_status = SourceStatus.GONE
    db.flush()

    report = reconcile_source(
        db,
        source,
        seen_urls={"https://jobs.example.edu/d"},
        seen_keys=set(),
        source_succeeded=True,
        now=NOW,
    )
    assert report.marked_back == 1
    assert opp.source_status == SourceStatus.LIVE
    assert _changes(db, opp, ChangeKind.REAPPEARED)[0].summary.startswith("Back on")


# --------------------------------------------------------------------------
# 5. the discovery run itself
# --------------------------------------------------------------------------


#: Two genuinely different postings. Dedup resolves identity by title when the
#: URL is new, so reusing one title would collapse them into a single row and
#: quietly make these tests pass for the wrong reason.
POSTINGS = {
    "a": (
        "Undergraduate Research Assistant, Vision Lab",
        "The Vision Lab is hiring a Stanford undergraduate research assistant for autumn "
        "quarter. Pay is $22.50 per hour for 10 hours per week. Required qualifications: "
        "coursework in CS 106B. Application deadline: September 15, 2026. To apply, email "
        "visionlab@stanford.edu with a resume.",
    ),
    "b": (
        "Student Circulation Assistant, Green Library",
        "Green Library is hiring student circulation assistants for the academic year. Pay "
        "is $19.00 per hour for 8 hours per week. Required: work-study eligibility. "
        "Application deadline: October 2, 2026. To apply, email libjobs@stanford.edu.",
    ),
}


class _FakeAdapter(SourceAdapter):
    """A source we can make succeed, fail, or drop a posting on demand."""

    slug = "fake-jobs"
    name = "Fake job board"
    kind = SourceKind.CAMPUS_JOBS
    base_url = "https://jobs.example.edu"

    documents: list[DiscoveredDocument] = []
    explode = False

    def discover(self, ctx):
        if type(self).explode:
            raise RuntimeError("connection reset by peer")
        return list(type(self).documents)


def _document(path: str, *, status: int = 200, error: str | None = None) -> DiscoveredDocument:
    title, body = POSTINGS[path]
    return DiscoveredDocument(
        url=f"https://jobs.example.edu/{path}",
        title=title,
        text=f"{title}\n\n{body}",
        http_status=status,
        error=error,
    )


def _discover(db, monkeypatch, documents, *, explode: bool = False):
    """Run one discovery pass over the fake source and return the run."""
    monkeypatch.setitem(SOURCE_ADAPTERS, _FakeAdapter.slug, _FakeAdapter)
    monkeypatch.setattr(_FakeAdapter, "documents", documents, raising=False)
    monkeypatch.setattr(_FakeAdapter, "explode", explode, raising=False)

    source = db.scalars(
        select(OpportunitySource).where(OpportunitySource.slug == _FakeAdapter.slug)
    ).first()
    if source is None:
        source = OpportunitySource(
            slug=_FakeAdapter.slug, name=_FakeAdapter.name, kind=SourceKind.CAMPUS_JOBS
        )
        db.add(source)
        db.flush()

    run = start_run(db, kind=SearchKind.JOBS, trigger="test")
    ctx = AgentContext(db=db, llm=DeterministicProvider(), today=TODAY, search_run_id=run.id)
    OpportunitySearchAgent().run(
        ctx, SearchRequest(profile=None, run=run, source_slugs=[_FakeAdapter.slug])
    )
    db.flush()
    return source


def test_a_posting_that_leaves_the_source_is_flagged_by_the_run(db, monkeypatch):
    source = _discover(db, monkeypatch, [_document("a"), _document("b")])
    rows = {o.source_url: o for o in db.scalars(
        select(Opportunity).where(Opportunity.source_id == source.id)
    )}
    assert len(rows) == 2

    # Second run: the source answers, and "b" is simply not in the answer.
    _discover(db, monkeypatch, [_document("a")])

    kept = rows["https://jobs.example.edu/a"]
    gone = rows["https://jobs.example.edu/b"]
    db.refresh(kept)
    db.refresh(gone)
    assert kept.source_status == SourceStatus.LIVE
    assert gone.source_status == SourceStatus.GONE
    assert db.get(Opportunity, gone.id) is not None
    assert "Source no longer available" in _changes(db, gone, ChangeKind.DISAPPEARED)[0].summary


def test_a_source_outage_flags_nothing(db, monkeypatch):
    """The destructive case. A source that raises must leave every one of its
    postings exactly as it found them."""
    source = _discover(db, monkeypatch, [_document("a"), _document("b")])
    before = list(db.scalars(select(Opportunity).where(Opportunity.source_id == source.id)))

    _discover(db, monkeypatch, [], explode=True)

    for opp in before:
        db.refresh(opp)
        assert opp.source_status == SourceStatus.LIVE
        assert _changes(db, opp, ChangeKind.DISAPPEARED) == []


def test_a_page_we_could_not_read_is_not_a_posting_that_was_taken_down(db, monkeypatch):
    """A timeout on one page is our failure, not evidence of removal."""
    source = _discover(db, monkeypatch, [_document("a"), _document("b")])

    _discover(
        db,
        monkeypatch,
        [_document("a"), _document("b", status=500, error="read timed out")],
    )

    rows = {o.source_url: o for o in db.scalars(
        select(Opportunity).where(Opportunity.source_id == source.id)
    )}
    unreadable = rows["https://jobs.example.edu/b"]
    db.refresh(unreadable)
    assert unreadable.source_status == SourceStatus.LIVE


def test_a_404_is_evidence_of_removal(db, monkeypatch):
    """Unlike a timeout, a 404 is the source answering "it is not here"."""
    source = _discover(db, monkeypatch, [_document("a"), _document("b")])

    _discover(
        db,
        monkeypatch,
        [_document("a"), _document("b", status=404, error="404 Not Found")],
    )

    rows = {o.source_url: o for o in db.scalars(
        select(Opportunity).where(Opportunity.source_id == source.id)
    )}
    removed = rows["https://jobs.example.edu/b"]
    db.refresh(removed)
    assert removed.source_status == SourceStatus.GONE


def test_a_discovery_run_expires_lapsed_deadlines_without_being_asked(db, monkeypatch):
    """Expiry has to happen without a human remembering to trigger it."""
    source = _source(db, "stale")
    stale = _opportunity(db, source, "https://jobs.example.edu/stale", date(2026, 8, 20))
    assert stale.deadline_state == DeadlineState.HARD

    _discover(db, monkeypatch, [_document("a")])

    db.refresh(stale)
    assert stale.deadline_state == DeadlineState.EXPIRED
    assert len(_changes(db, stale, ChangeKind.EXPIRED)) == 1


def test_our_own_page_budget_never_looks_like_a_removal(db, monkeypatch):
    """Several sources enumerate a catalogue bigger than the run's budget. A
    posting we simply did not get to must never be reported as taken down."""
    source = _discover(db, monkeypatch, [_document("a"), _document("b")])

    monkeypatch.setitem(SOURCE_ADAPTERS, _FakeAdapter.slug, _FakeAdapter)
    monkeypatch.setattr(_FakeAdapter, "documents", [_document("a")], raising=False)
    run = start_run(db, kind=SearchKind.JOBS, trigger="test")
    ctx = AgentContext(db=db, llm=DeterministicProvider(), today=TODAY, search_run_id=run.id)
    OpportunitySearchAgent().run(
        ctx,
        SearchRequest(
            profile=None,
            run=run,
            source_slugs=[_FakeAdapter.slug],
            # The listing filled the budget exactly, so it was cut short by us.
            limit_per_source=1,
        ),
    )
    db.flush()

    for opp in db.scalars(select(Opportunity).where(Opportunity.source_id == source.id)):
        db.refresh(opp)
        assert opp.source_status == SourceStatus.LIVE
