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
from app.api.deps import current_profile_optional, get_session
from app.models.application import Application
from app.models.enums import OpportunityStatus, OpportunityType, SourceKind
from app.models.opportunity import (
    Opportunity,
    OpportunitySource,
    OpportunityTopic,
)
from app.models.ops import Reminder
from app.models.user import ResearchTopic, StudentProfile
from app.schemas import common as S
from app.schemas import entities as E
from app.services.dedup import upsert_opportunity
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


def _facets(db: Session) -> S.OpportunityFacets:
    def counts(column):
        return db.execute(select(column, func.count()).group_by(column)).all()

    type_counts = counts(Opportunity.type)
    status_counts = counts(Opportunity.status)

    source_rows = db.execute(
        select(OpportunitySource.slug, OpportunitySource.name, func.count(Opportunity.id))
        .join(Opportunity, Opportunity.source_id == OpportunitySource.id, isouter=True)
        .group_by(OpportunitySource.slug, OpportunitySource.name)
    ).all()

    topic_rows = db.execute(
        select(ResearchTopic.slug, ResearchTopic.label, func.count(OpportunityTopic.id))
        .join(OpportunityTopic, OpportunityTopic.topic_id == ResearchTopic.id)
        .group_by(ResearchTopic.slug, ResearchTopic.label)
        .order_by(func.count(OpportunityTopic.id).desc())
        .limit(30)
    ).all()

    dept_rows = db.execute(
        select(Opportunity.department, func.count())
        .where(Opportunity.department.is_not(None))
        .group_by(Opportunity.department)
        .order_by(func.count().desc())
        .limit(20)
    ).all()

    return S.OpportunityFacets(
        types=[S.FacetValue(value=t.value, label=t.value, count=c) for t, c in type_counts],
        statuses=[S.FacetValue(value=s.value, label=s.value, count=c) for s, c in status_counts],
        sources=[
            S.FacetValue(value=slug, label=name, count=c) for slug, name, c in source_rows if c
        ],
        topics=[S.FacetValue(value=slug, label=label, count=c) for slug, label, c in topic_rows],
        departments=[S.FacetValue(value=d, label=d, count=c) for d, c in dept_rows],
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
    sort: str = "recommended",
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> S.OpportunityListResponse:
    today = datetime.now(UTC).date()
    stmt = _base_query()

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
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            Opportunity.title.ilike(needle)
            | Opportunity.organization.ilike(needle)
            | Opportunity.description.ilike(needle)
        )

    rows = list(db.scalars(stmt).unique())

    apps = _applications_by_opportunity(db, profile)
    reminders = _reminder_ids(db, profile)
    wanted = ser.interest_slugs(profile)
    items = [
        ser.opportunity_item(
            o,
            today=today,
            profile_id=profile.id if profile else None,
            application=apps.get(o.id),
            has_reminder=o.id in reminders,
            wanted_slugs=wanted,
            profile_for_relevance=profile,
        )
        for o in rows
    ]

    if min_fit is not None:
        items = [i for i in items if (i.fit_score or 0) >= min_fit]
    if focus == "interests":
        items = [i for i in items if i.matches_interests]

    items = _sort(items, sort)
    total = len(items)
    return S.OpportunityListResponse(
        items=items[offset : offset + limit],
        total=total,
        limit=limit,
        offset=offset,
        facets=_facets(db),
    )


def _sort(items: list[S.OpportunityListItem], sort: str) -> list[S.OpportunityListItem]:
    if sort == "deadline":
        # Upcoming dates first (soonest first), then rolling, then unknown, and
        # overdue LAST. A passed deadline is not the most urgent thing on the
        # screen, and an unknown deadline is not "far away" -- it is unknown, so
        # neither may sort ahead of a real upcoming date.
        def bucket(i: S.OpportunityListItem) -> int:
            if i.urgency == "overdue":
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
        # Overdue is not a recommendation — it is a closed door, so it sinks
        # below everything actionable rather than leading on urgency.
        expired = 1 if i.urgency == "overdue" else 0
        eligible = 0 if i.eligibility != "ineligible" else 1
        pressing = 0 if i.urgency in ("urgent", "soon") else 1
        return (
            expired,
            eligible,
            pressing,
            URGENCY_RANK.get(i.urgency, 4) if pressing == 0 else 0,
            -(i.fit_score or 0),
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


@router.post("/opportunities/{opportunity_id}/rematch", response_model=S.OpportunityDetail)
def rematch(
    opportunity_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile | None = Depends(current_profile_optional),
) -> S.OpportunityDetail:
    if profile is None:
        raise HTTPException(status_code=409, detail="Complete onboarding before scoring matches.")
    opp = _load(db, opportunity_id)
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
