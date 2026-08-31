from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api import serializers as ser
from app.api.deps import current_profile_optional, get_session
from app.models.enums import OpportunityType
from app.models.opportunity import Opportunity, OpportunityTopic
from app.models.research import Faculty, FacultyTopic
from app.models.user import ResearchTopic, StudentProfile
from app.schemas import common as S

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
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(Opportunity.title.ilike(needle) | Opportunity.organization.ilike(needle))

    rows = list(db.scalars(stmt).unique())
    leads = [
        lead
        for lead in (ser.research_lead(o, today=today, profile=profile) for o in rows)
        if lead is not None
    ]

    if state:
        leads = [item for item in leads if item.lead_state in state]
    if topic:
        wanted = set(topic)
        leads = [item for item in leads if wanted & {t.slug for t in item.topics}]

    if sort == "recent":
        leads.sort(key=lambda item: item.faculty.last_evidence_year or 0, reverse=True)
    elif sort == "opening":
        rank = {"opening": 0, "outreach": 1, "watch": 2}
        leads.sort(key=lambda item: (rank.get(item.lead_state, 3), -(item.fit_score or 0)))
    else:
        leads.sort(key=lambda item: -(item.fit_score or 0))

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
    )


@router.get("/research/faculty/{faculty_id}", response_model=S.ResearchContext)
def get_faculty(
    faculty_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile | None = Depends(current_profile_optional),
) -> S.ResearchContext:
    opp = db.scalars(_leads_query().where(Opportunity.faculty_id == faculty_id)).unique().first()
    if opp is None:
        # A faculty record with no lead row is still worth showing.
        faculty = db.get(Faculty, faculty_id)
        if faculty is None:
            raise HTTPException(status_code=404, detail="Faculty member not found.")
        return S.ResearchContext(
            faculty=ser.faculty_ref(faculty),
            lab=ser.lab_ref(faculty.labs[0] if faculty.labs else None),
            lead_state="watch",
            evidence=[ser.evidence_item(e) for e in faculty.evidence][:15],
            signals=[ser.signal_item(s) for s in faculty.signals],
            topics=[],
            overlap=ser.topic_overlap(faculty, profile),
            suggested_next_step="No lead has been generated for this faculty member yet.",
        )
    context = ser.research_context(opp, profile)
    if context is None:
        raise HTTPException(status_code=404, detail="Faculty member not found.")
    return context


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
