from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.agents.base import AgentContext
from app.agents.deadline_agent import DeadlineAgent, DeadlineRequest, urgency_for
from app.agents.extraction_agent import (
    ExtractionRequest,
    WebExtractionAgent,
    persist_provenance,
)
from app.agents.matching_agent import MatchingAgent, MatchRequest
from app.api import serializers as ser
from app.api.deps import current_profile, current_profile_optional, get_session
from app.models.application import Application
from app.models.enums import (
    ConfidenceState,
    FeedbackReason,
    FeedbackSignal,
    OpportunityStatus,
    OpportunityType,
    SourceKind,
)
from app.models.opportunity import (
    Opportunity,
    OpportunitySource,
    OpportunityTopic,
)
from app.models.ops import Reminder
from app.models.research import Faculty
from app.models.user import ResearchTopic, StudentProfile
from app.schemas import common as S
from app.schemas import entities as E
from app.services import feedback as fb
from app.services import search
from app.services.dedup import upsert_opportunity
from app.services.lifecycle import sweep_expired
from app.sources.base import DiscoveredDocument
from app.sources.http import get_fetcher

router = APIRouter(tags=["opportunities"])

RESEARCH_TYPES = (OpportunityType.RESEARCH_OPENING, OpportunityType.RESEARCH_OUTREACH)

# "Recommended" is not fit alone: an eligible thing due next week beats a
# slightly better match with no deadline, because only one of them expires.
URGENCY_RANK = {"overdue": 5, "urgent": 0, "soon": 1, "later": 2, "rolling": 3, "unknown": 4}


def _base_query():
    return select(Opportunity).options(
        selectinload(Opportunity.requirements),
        selectinload(Opportunity.topics).selectinload(OpportunityTopic.topic),
        selectinload(Opportunity.matches),
        selectinload(Opportunity.source),
        selectinload(Opportunity.faculty),
        selectinload(Opportunity.lab),
    )


def _applications_by_opportunity(db: Session, profile: StudentProfile | None):
    if profile is None:
        return {}
    rows = db.scalars(select(Application).where(Application.profile_id == profile.id)).all()
    return {r.opportunity_id: r for r in rows}


def _reminder_ids(db: Session, profile: StudentProfile | None) -> set[uuid.UUID]:
    if profile is None:
        return set()
    rows = db.scalars(
        select(Reminder.opportunity_id).where(Reminder.profile_id == profile.id)
    ).all()
    return {r for r in rows if r is not None}


# A facet count is a promise about how many rows a filter will return, so every
# facet except ``confidence`` itself is measured over the recommended set only.
# Counting held rows here would offer "Stanford Programs · 12" and then show ten.
_RECOMMENDED = Opportunity.confidence_state == ConfidenceState.OK

CONFIDENCE_LABEL = {
    ConfidenceState.OK: "Recommended",
    ConfidenceState.HELD: "Low-confidence, not recommended",
}


def _facets(db: Session) -> S.OpportunityFacets:
    def counts(column):
        return db.execute(
            select(column, func.count()).where(_RECOMMENDED).group_by(column)
        ).all()

    type_counts = counts(Opportunity.type)
    status_counts = counts(Opportunity.status)

    source_rows = db.execute(
        select(OpportunitySource.slug, OpportunitySource.name, func.count(Opportunity.id))
        .join(
            Opportunity,
            (Opportunity.source_id == OpportunitySource.id) & _RECOMMENDED,
            isouter=True,
        )
        .group_by(OpportunitySource.slug, OpportunitySource.name)
    ).all()

    topic_rows = db.execute(
        select(ResearchTopic.slug, ResearchTopic.label, func.count(OpportunityTopic.id))
        .join(OpportunityTopic, OpportunityTopic.topic_id == ResearchTopic.id)
        .join(Opportunity, Opportunity.id == OpportunityTopic.opportunity_id)
        .where(_RECOMMENDED)
        .group_by(ResearchTopic.slug, ResearchTopic.label)
        .order_by(func.count(OpportunityTopic.id).desc())
        .limit(30)
    ).all()

    dept_rows = db.execute(
        select(Opportunity.department, func.count())
        .where(Opportunity.department.is_not(None), _RECOMMENDED)
        .group_by(Opportunity.department)
        .order_by(func.count().desc())
        .limit(20)
    ).all()

    confidence_rows = db.execute(
        select(Opportunity.confidence_state, func.count())
        .group_by(Opportunity.confidence_state)
    ).all()

    return S.OpportunityFacets(
        types=[S.FacetValue(value=t.value, label=t.value, count=c) for t, c in type_counts],
        statuses=[S.FacetValue(value=s.value, label=s.value, count=c) for s, c in status_counts],
        sources=[
            S.FacetValue(value=slug, label=name, count=c) for slug, name, c in source_rows if c
        ],
        topics=[S.FacetValue(value=slug, label=label, count=c) for slug, label, c in topic_rows],
        departments=[S.FacetValue(value=d, label=d, count=c) for d, c in dept_rows],
        confidence=[
            S.FacetValue(value=state.value, label=CONFIDENCE_LABEL[state], count=c)
            for state, c in confidence_rows
        ],
    )


@router.get("/opportunities", response_model=S.OpportunityListResponse)
def list_opportunities(
    db: Session = Depends(get_session),
    profile: StudentProfile | None = Depends(current_profile_optional),
    type: list[str] | None = Query(default=None),
    status_filter: list[str] | None = Query(default=None, alias="status"),
    source: list[str] | None = Query(default=None),
    topic: list[str] | None = Query(default=None),
    department: str | None = None,
    campus: str | None = None,
    eligibility: list[str] | None = Query(default=None),
    min_fit: float | None = None,
    q: str | None = None,
    # "interests" narrows to things that touch what the student said they care
    # about. A filter rather than a hidden ranking tweak, so it is visible and
    # reversible.
    focus: str | None = None,
    # Which side of the confidence gate to return. "ok" is the default because a
    # held row is one we could barely read; "held" is the explicit, honestly
    # labelled way to look at exactly those, and "all" is for auditing the gate.
    confidence: str = Query(default="ok", pattern="^(ok|held|all)$"),
    # Rows you hid leave the default list. Never deleted, never unreachable:
    # ask for them and they come back, and the response says how many there are.
    include_hidden: bool = False,
    sort: str = "recommended",
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> S.OpportunityListResponse:
    today = datetime.now(UTC).date()
    stmt = _base_query()

    if confidence != "all":
        stmt = stmt.where(Opportunity.confidence_state == ConfidenceState(confidence))

    if type:
        stmt = stmt.where(Opportunity.type.in_(type))
    if status_filter:
        stmt = stmt.where(Opportunity.status.in_(status_filter))
    if eligibility:
        stmt = stmt.where(Opportunity.eligibility.in_(eligibility))
    if department:
        stmt = stmt.where(Opportunity.department == department)
    if campus:
        stmt = stmt.where(Opportunity.location.ilike(f"%{campus}%"))
    if source:
        stmt = stmt.join(OpportunitySource, Opportunity.source_id == OpportunitySource.id).where(
            OpportunitySource.slug.in_(source)
        )
    if topic:
        stmt = (
            stmt.join(OpportunityTopic, OpportunityTopic.opportunity_id == Opportunity.id)
            .join(ResearchTopic, ResearchTopic.id == OpportunityTopic.topic_id)
            .where(ResearchTopic.slug.in_(topic))
        )
    # `q` is answered by intent, not by substring position: the query is expanded
    # through the canonical topic vocabulary and every candidate is scored. See
    # app/services/search.py.
    intent = search.build_intent(db, q)
    if intent is not None:
        stmt = stmt.options(
            selectinload(Opportunity.faculty).selectinload(Faculty.topics),
            selectinload(Opportunity.faculty).selectinload(Faculty.evidence),
            selectinload(Opportunity.faculty).selectinload(Faculty.labs),
        )
        if intent.kinds:
            # A kind word answers the question on its own: "part-time" asks for
            # jobs, and a robotics lab is not a wrong-order result, it is a
            # wrong answer.
            stmt = stmt.where(Opportunity.type.in_(intent.kinds))

    rows = list(db.scalars(stmt).unique())

    hits: dict[uuid.UUID, search.SearchHit] = {}
    if intent is not None:
        for row in rows:
            hit = search.score(row, intent)
            if hit is not None:
                hits[row.id] = hit
        rows = [row for row in rows if row.id in hits]

    apps = _applications_by_opportunity(db, profile)
    reminders = _reminder_ids(db, profile)
    wanted = ser.interest_slugs(profile)
    signals = fb.feedback_for_profile(db, profile)
    items = [
        ser.opportunity_item(
            o,
            today=today,
            profile_id=profile.id if profile else None,
            application=apps.get(o.id),
            has_reminder=o.id in reminders,
            wanted_slugs=wanted,
            profile_for_relevance=profile,
            feedback=signals.get(o.id),
        )
        for o in rows
    ]

    if min_fit is not None:
        items = [i for i in items if (i.fit_score or 0) >= min_fit]
    if focus == "interests":
        items = [i for i in items if i.matches_interests]

    # Counted after every other filter, so the number is a promise about what
    # asking for them would actually add rather than a global tally.
    hidden = [i for i in items if i.feedback and i.feedback.signal == FeedbackSignal.HIDDEN.value]
    if not include_hidden:
        items = [i for i in items if i.feedback is None or i.feedback.signal != FeedbackSignal.HIDDEN.value]

    items = _sort(items, sort)
    if intent is not None:
        # Relevance leads; the sort the student chose is the tie-break, so search
        # re-orders the product's ranking instead of replacing it.
        for item in items:
            hit = hits[item.id]
            item.search_score = hit.score
            item.search_reasons = list(hit.reasons)
        order = search.rank(hits, [item.id for item in items])
        items.sort(key=lambda item: order[item.id])

    total = len(items)
    return S.OpportunityListResponse(
        items=items[offset : offset + limit],
        total=total,
        limit=limit,
        offset=offset,
        facets=_facets(db),
        hidden_count=len(hidden),
        search=ser.search_explain(intent),
    )


def _sort(items: list[S.OpportunityListItem], sort: str) -> list[S.OpportunityListItem]:
    if sort == "deadline":
        # Upcoming dates first (soonest first), then rolling, then unknown, and
        # overdue LAST. A passed deadline is not the most urgent thing on the
        # screen, and an unknown deadline is not "far away" -- it is unknown, so
        # neither may sort ahead of a real upcoming date.
        def bucket(i: S.OpportunityListItem) -> int:
            if i.urgency == "overdue" or i.deadline_state == "expired":
                return 3
            if i.deadline:
                return 0
            return 1 if i.deadline_type == "rolling" else 2

        return sorted(
            items,
            key=lambda i: (bucket(i), i.deadline or date.max, -(i.fit_score or 0)),
        )
    if sort == "fit":
        return sorted(items, key=lambda i: (-(i.fit_score or 0), i.title))
    if sort == "discovered":
        return sorted(
            items,
            key=lambda i: (i.first_seen_at is None, i.first_seen_at or datetime.min),
            reverse=True,
        )
    # "Recommended" = act on what expires, then on what fits.
    #
    # An earlier version ranked by deadline urgency before fit, which meant every
    # rolling campus job outranked every research lead — because a lead has no
    # stated deadline and "unknown" sorted worse than "rolling". A 74-point AI lab
    # lost to a 38-point swim instructor. Urgency now only takes precedence when
    # a deadline is genuinely close; otherwise fit leads and the deadline is a
    # tiebreaker.
    def key(i: S.OpportunityListItem) -> tuple:
        signal = i.feedback.signal if i.feedback else None
        # A closed door is not a recommendation, so it sinks below everything
        # actionable rather than leading on urgency. Both spellings count: the
        # recorded lifecycle state, and a date that has passed but has not been
        # swept yet. "Already applied" joins them: still listed, no longer work.
        parked = (
            1
            if (
                i.urgency == "overdue"
                or i.deadline_state == "expired"
                or signal == FeedbackSignal.ALREADY_APPLIED.value
            )
            else 0
        )
        eligible = 0 if i.eligibility != "ineligible" else 1
        pressing = 0 if i.urgency in ("urgent", "soon") else 1
        # The feedback nudge lands here and nowhere else: a bounded number of
        # points on the sort key of THIS row. fit_score itself is untouched, so
        # the breakdown on screen still explains the number on screen.
        return (
            parked,
            eligible,
            pressing,
            URGENCY_RANK.get(i.urgency, 4) if pressing == 0 else 0,
            -((i.fit_score or 0) + fb.sort_adjustment(signal)),
        )

    return sorted(items, key=key)


def _load(db: Session, opportunity_id: uuid.UUID) -> Opportunity:
    opp = db.scalars(_base_query().where(Opportunity.id == opportunity_id)).unique().first()
    if opp is None:
        raise HTTPException(status_code=404, detail="Opportunity not found.")
    return opp


@router.get("/opportunities/{opportunity_id}", response_model=S.OpportunityDetail)
def get_opportunity(
    opportunity_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile | None = Depends(current_profile_optional),
) -> S.OpportunityDetail:
    opp = _load(db, opportunity_id)
    apps = _applications_by_opportunity(db, profile)
    return ser.opportunity_detail(
        db,
        opp,
        today=datetime.now(UTC).date(),
        profile=profile,
        application=apps.get(opp.id),
        has_reminder=opp.id in _reminder_ids(db, profile),
        feedback=fb.feedback_for_profile(db, profile).get(opp.id),
    )


class _Patch(S.Schema):
    status: str | None = None
    notes: str | None = None


@router.patch("/opportunities/{opportunity_id}", response_model=S.OpportunityDetail)
def patch_opportunity(
    opportunity_id: uuid.UUID,
    payload: _Patch,
    db: Session = Depends(get_session),
    profile: StudentProfile | None = Depends(current_profile_optional),
) -> S.OpportunityDetail:
    opp = _load(db, opportunity_id)
    if payload.status is not None:
        try:
            opp.status = OpportunityStatus(payload.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown status {payload.status!r}.") from exc
    if payload.notes is not None:
        opp.notes = payload.notes
    db.flush()
    return get_opportunity(opportunity_id, db, profile)


@router.post(
    "/opportunities/{opportunity_id}/feedback",
    response_model=S.FeedbackOut,
    status_code=status.HTTP_201_CREATED,
)
def set_feedback(
    opportunity_id: uuid.UUID,
    payload: E.FeedbackIn,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> S.FeedbackOut:
    """Record what you said about one opportunity.

    Re-posting replaces the previous signal; there is exactly one per row per
    student.  Nothing here writes to the opportunity itself — no status moves,
    no Application is created, no score is edited.  The only thing that changes
    is where this single row sits, and which surfaces will offer it.
    """
    opp = _load(db, opportunity_id)
    try:
        row = fb.set_feedback(
            db,
            opportunity_id=opp.id,
            profile=profile,
            signal=payload.signal,
            reason=payload.reason,
            note=payload.note,
        )
    except fb.FeedbackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ser.feedback_out(row)


@router.delete(
    "/opportunities/{opportunity_id}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_feedback(
    opportunity_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> None:
    """Undo. The row is deleted outright, so nothing of it survives in ranking."""
    opp = _load(db, opportunity_id)
    fb.clear_feedback(db, opportunity_id=opp.id, profile=profile)


@router.get("/feedback/options")
def feedback_options() -> dict[str, object]:
    """The controlled vocabulary, so the UI never hard-codes a value the API
    would reject."""
    return {
        "signals": [s.value for s in FeedbackSignal],
        # Only ever offered for not_relevant; the API rejects it anywhere else.
        "reasons": {
            FeedbackSignal.NOT_RELEVANT.value: [r.value for r in FeedbackReason],
        },
    }


@router.post("/opportunities/{opportunity_id}/rematch", response_model=S.OpportunityDetail)
def rematch(
    opportunity_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile | None = Depends(current_profile_optional),
) -> S.OpportunityDetail:
    if profile is None:
        raise HTTPException(status_code=409, detail="Complete onboarding before scoring matches.")
    opp = _load(db, opportunity_id)
    if opp.confidence_state == ConfidenceState.HELD:
        # Scoring this would put a confident-looking number on a page we could
        # barely read. The honest answer is the reason it was held.
        raise HTTPException(
            status_code=409,
            detail=(
                "This one is held as low-confidence, so it is not scored: "
                f"{opp.confidence_reason or 'too little was extracted from the page'}."
            ),
        )
    MatchingAgent().run(AgentContext(db=db), MatchRequest(profile=profile, opportunity=opp))
    db.flush()
    return get_opportunity(opportunity_id, db, profile)


@router.post(
    "/opportunities/import",
    response_model=S.OpportunityDetail,
    status_code=status.HTTP_201_CREATED,
)
def import_url(
    payload: E.ImportUrlIn,
    db: Session = Depends(get_session),
    profile: StudentProfile | None = Depends(current_profile_optional),
) -> S.OpportunityDetail:
    url = payload.url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Paste a full http(s) URL.")

    fetched = get_fetcher().fetch(url)
    if not fetched.ok:
        raise HTTPException(
            status_code=422,
            detail=f"Could not read that page: {fetched.error or 'unknown error'}.",
        )

    source = db.scalars(
        select(OpportunitySource).where(OpportunitySource.slug == "manual-url")
    ).first()
    if source is None:
        source = OpportunitySource(
            slug="manual-url",
            name="Pasted link",
            kind=SourceKind.MANUAL,
            adapter="app.sources.manual_url",
        )
        db.add(source)
        db.flush()

    doc = DiscoveredDocument(
        url=url,
        title=fetched.title,
        text=fetched.text,
        html=fetched.html,
        fetched_at=fetched.fetched_at,
        http_status=fetched.status,
    )
    ctx = AgentContext(db=db)
    extracted = WebExtractionAgent().run(ctx, ExtractionRequest(document=doc, source=source)).result
    if not extracted.data.get("title"):
        raise HTTPException(
            status_code=422,
            detail="That page did not look like a job or research posting — no title was found.",
        )

    # Deliberately not run through the confidence gate. That gate exists to stop
    # a crawl pushing half-read pages at the student; this page is one they
    # chose and pasted themselves, and silently filing their own link under
    # "not recommended" would be answering a question they did not ask. How
    # little was extracted is still visible on the detail view.
    opp, _outcome = upsert_opportunity(db, extracted.data, source=source)
    db.flush()
    persist_provenance(ctx, opp, extracted.provenance)
    DeadlineAgent().run(
        ctx, DeadlineRequest(opportunity=opp, text=extracted.text, source_url=url)
    )
    if profile is not None:
        MatchingAgent().run(ctx, MatchRequest(profile=profile, opportunity=opp))
    db.flush()
    return ser.opportunity_detail(
        db, _load(db, opp.id), today=ctx.today, profile=profile
    )


@router.post("/import/handshake")
def import_handshake(
    payload: E.HandshakeImportIn,
    db: Session = Depends(get_session),
    profile: StudentProfile | None = Depends(current_profile_optional),
) -> dict[str, object]:
    """Accept what the extension read from the student's own logged-in tab.

    We never fetch Handshake ourselves: this endpoint is the only way its jobs
    enter the system, and the data arrives already visible to the student.
    """
    from app.sources.handshake import normalize_extension_payload

    source = db.scalars(
        select(OpportunitySource).where(OpportunitySource.slug == "handshake")
    ).first()
    ctx = AgentContext(db=db)
    extractor = WebExtractionAgent()
    created = updated = unchanged = skipped = 0
    errors: list[str] = []

    for item in payload.items:
        try:
            doc = normalize_extension_payload(item.model_dump())
        except Exception as exc:
            skipped += 1
            errors.append(f"{item.url}: {exc}")
            continue
        result = extractor.run(ctx, ExtractionRequest(document=doc, source=source)).result
        if not result.data.get("title"):
            skipped += 1
            continue
        opp, outcome = upsert_opportunity(db, result.data, source=source)
        db.flush()
        if profile is not None:
            MatchingAgent().run(
                ctx, MatchRequest(profile=profile, opportunity=opp, polish=False)
            )
        if outcome == "created":
            created += 1
        elif outcome == "updated":
            updated += 1
        else:
            unchanged += 1

    db.flush()
    return {
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "skipped": skipped,
        "errors": errors,
    }


@router.post("/lifecycle/sweep")
def sweep_lifecycle(db: Session = Depends(get_session)) -> dict[str, object]:
    """Re-check every stored deadline against today.

    Also runs on API startup and at both ends of a discovery run — this route
    exists so the student can force it without waiting for either, and so the
    UI can refresh a list it suspects is stale.
    """
    report = sweep_expired(db, datetime.now(UTC).date())
    return {
        "expired": report.expired,
        "revived": report.revived,
        "titles": report.titles,
    }


@router.get("/opportunities/{opportunity_id}/urgency")
def opportunity_urgency(
    opportunity_id: uuid.UUID, db: Session = Depends(get_session)
) -> dict[str, object]:
    opp = _load(db, opportunity_id)
    today = datetime.now(UTC).date()
    return {
        "urgency": urgency_for(opp.deadline, opp.deadline_type, today),
        "deadline": opp.deadline.isoformat() if opp.deadline else None,
    }


@router.get("/changes")
def list_changes(
    limit: int = Query(default=25, le=100),
    db: Session = Depends(get_session),
) -> list[dict[str, object]]:
    """What moved recently. The reason to re-run discovery at all."""
    from app.models.change import OpportunityChange

    rows = db.execute(
        select(OpportunityChange, Opportunity)
        .join(Opportunity, Opportunity.id == OpportunityChange.opportunity_id)
        .order_by(OpportunityChange.noticed_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": str(change.id),
            "opportunity_id": str(opp.id),
            "opportunity_title": opp.title,
            "kind": change.kind.value,
            "field": change.field,
            "old_value": change.old_value,
            "new_value": change.new_value,
            "summary": change.summary,
            "source_url": change.source_url,
            "noticed_at": change.noticed_at.isoformat(),
            "seen": change.seen_at is not None,
        }
        for change, opp in rows
    ]
