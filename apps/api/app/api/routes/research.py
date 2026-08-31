from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api import serializers as ser
from app.api.deps import current_profile_optional, get_session
from app.models.enums import LeadState, OpportunityType
from app.models.opportunity import Opportunity, OpportunityTopic
from app.models.research import Faculty, FacultyTopic
from app.models.user import ResearchTopic, StudentProfile
from app.schemas import common as S
from app.services import directions, outreach, search

router = APIRouter(tags=["research"])

RESEARCH_TYPES = (OpportunityType.RESEARCH_OPENING, OpportunityType.RESEARCH_OUTREACH)


def _leads_query():
    return (
        select(Opportunity)
        .where(Opportunity.type.in_(RESEARCH_TYPES))
        .options(
            selectinload(Opportunity.matches),
            selectinload(Opportunity.lab),
            selectinload(Opportunity.topics).selectinload(OpportunityTopic.topic),
            selectinload(Opportunity.faculty).selectinload(Faculty.evidence),
            selectinload(Opportunity.faculty).selectinload(Faculty.signals),
            selectinload(Opportunity.faculty).selectinload(Faculty.labs),
            selectinload(Opportunity.faculty)
            .selectinload(Faculty.topics)
            .selectinload(FacultyTopic.topic),
        )
    )


@router.get("/research/leads", response_model=S.ResearchLeadsResponse)
def list_leads(
    db: Session = Depends(get_session),
    profile: StudentProfile | None = Depends(current_profile_optional),
    state: list[str] | None = Query(default=None),
    topic: list[str] | None = Query(default=None),
    department: str | None = None,
    q: str | None = None,
    sort: str = "match",
    limit: int = Query(default=200, le=500),
) -> S.ResearchLeadsResponse:
    today = datetime.now(UTC).date()
    stmt = _leads_query()
    if department:
        stmt = stmt.where(Opportunity.department == department)
    # Same intent-aware expansion as the opportunities list, over the same
    # vocabulary — a lead answers "agents" because of what its PI works on, not
    # because the word happens to sit in a title. See app/services/search.py.
    intent = search.build_intent(db, q)
    if intent is not None and intent.kinds:
        stmt = stmt.where(Opportunity.type.in_(intent.kinds))

    rows = list(db.scalars(stmt).unique())

    hits: dict[uuid.UUID, search.SearchHit] = {}
    if intent is not None:
        for row in rows:
            hit = search.score(row, intent)
            if hit is not None:
                hits[row.id] = hit
        rows = [row for row in rows if row.id in hits]

    leads = [
        lead
        for lead in (ser.research_lead(o, today=today, profile=profile) for o in rows)
        if lead is not None
    ]
    for lead in leads:
        hit = hits.get(lead.opportunity_id)
        if hit is not None:
            lead.search_score = hit.score
            lead.search_reasons = list(hit.reasons)

    if state:
        leads = [item for item in leads if item.lead_state in state]
    if topic:
        wanted = set(topic)
        leads = [item for item in leads if wanted & {t.slug for t in item.topics}]

    if sort == "recent":
        leads.sort(key=lambda item: item.faculty.last_evidence_year or 0, reverse=True)
    elif sort == "opening":
        rank = {"opening": 0, "outreach": 1, "watch": 2, "unknown": 3}
        leads.sort(key=lambda item: (rank.get(item.lead_state, 3), -(item.fit_score or 0)))
    else:
        leads.sort(key=lambda item: -(item.fit_score or 0))

    if intent is not None:
        # Relevance leads, the chosen sort breaks ties.
        order = search.rank(hits, [item.opportunity_id for item in leads])
        leads.sort(key=lambda item: order[item.opportunity_id])

    dept_rows = db.execute(
        select(Opportunity.department, func.count())
        .where(Opportunity.type.in_(RESEARCH_TYPES), Opportunity.department.is_not(None))
        .group_by(Opportunity.department)
        .order_by(func.count().desc())
    ).all()

    topic_counts: dict[str, tuple[str, int]] = {}
    for lead in leads:
        for t in lead.topics:
            label, count = topic_counts.get(t.slug, (t.label, 0))
            topic_counts[t.slug] = (label, count + 1)

    state_counts: dict[str, int] = {}
    for lead in leads:
        state_counts[lead.lead_state] = state_counts.get(lead.lead_state, 0) + 1

    return S.ResearchLeadsResponse(
        items=leads[:limit],
        total=len(leads),
        facets=S.ResearchFacets(
            departments=[S.FacetValue(value=d, label=d, count=c) for d, c in dept_rows],
            topics=[
                S.FacetValue(value=slug, label=label, count=count)
                for slug, (label, count) in sorted(
                    topic_counts.items(), key=lambda kv: kv[1][1], reverse=True
                )[:24]
            ],
            states=[
                S.FacetValue(value=k, label=k, count=v)
                for k, v in sorted(state_counts.items(), key=lambda kv: kv[1], reverse=True)
            ],
        ),
        search=ser.search_explain(intent),
    )


@router.get("/research/faculty/{faculty_id}", response_model=S.ResearchContext)
def get_faculty(
    faculty_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile | None = Depends(current_profile_optional),
) -> S.ResearchContext:
    today = datetime.now(UTC).date()
    opp = db.scalars(_leads_query().where(Opportunity.faculty_id == faculty_id)).unique().first()
    if opp is None:
        # A faculty record with no lead row is still worth showing.
        faculty = db.get(Faculty, faculty_id)
        if faculty is None:
            raise HTTPException(status_code=404, detail="Faculty member not found.")
        claims = directions.direction_claims(faculty, today=today)
        return S.ResearchContext(
            faculty=ser.faculty_ref(faculty),
            lab=ser.lab_ref(faculty.labs[0] if faculty.labs else None),
            # No lead row means the classifier never ran on this record. That
            # is "we have not looked", not "we looked and found nothing".
            lead_state=LeadState.UNKNOWN.value,
            lead_state_signals=[],
            directions=ser.direction_items(claims),
            why_now=ser.why_now_item(faculty, today, claims),
            evidence=[ser.evidence_item(e) for e in faculty.evidence][:15],
            signals=[ser.signal_item(s) for s in faculty.signals],
            topics=[],
            overlap=ser.topic_overlap(faculty, profile),
            fit=ser.fit_breakdown(db, faculty, profile),
            suggested_next_step="No lead has been generated for this faculty member yet.",
        )
    context = ser.research_context(db, opp, profile, today=today)
    if context is None:
        raise HTTPException(status_code=404, detail="Faculty member not found.")
    return context


@router.get(
    "/research/faculty/{faculty_id}/outreach",
    response_model=S.OutreachDraftOut,
)
def get_outreach_draft(
    faculty_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile | None = Depends(current_profile_optional),
) -> S.OutreachDraftOut:
    """A first draft of a cold email, and everything it was built from.

    Nothing here sends mail. The response carries the facts the draft leans on
    precisely so the student can check each one before deciding to use a word
    of it — see :mod:`app.services.outreach` for what is admissible.
    """
    faculty = db.get(Faculty, faculty_id)
    if faculty is None:
        raise HTTPException(status_code=404, detail="Faculty member not found.")
    if profile is None:
        raise HTTPException(
            status_code=409,
            detail="Set up your profile first — a draft has to be built from something real about you.",
        )
    draft = outreach.build_draft(
        db, faculty, profile, this_year=datetime.now(UTC).year
    )
    assert draft is not None  # profile is not None, so build_draft always drafts
    return ser.outreach_draft(draft)


@router.get("/research/topics")
def list_topics(db: Session = Depends(get_session)) -> list[dict[str, object]]:
    rows = db.execute(
        select(
            ResearchTopic.slug,
            ResearchTopic.label,
            ResearchTopic.parent_id,
            func.count(FacultyTopic.id),
        )
        .join(FacultyTopic, FacultyTopic.topic_id == ResearchTopic.id, isouter=True)
        .group_by(ResearchTopic.slug, ResearchTopic.label, ResearchTopic.parent_id)
        .order_by(func.count(FacultyTopic.id).desc())
    ).all()
    by_id = {t.id: t.slug for t in db.scalars(select(ResearchTopic))}
    return [
        {
            "slug": slug,
            "label": label,
            "parent_slug": by_id.get(parent_id),
            "count": count,
        }
        for slug, label, parent_id, count in rows
        if count
    ]
