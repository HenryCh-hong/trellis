from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api import serializers as ser
from app.api.deps import current_profile_optional, get_session
from app.core.config import get_settings
from app.models.application import Application
from app.models.enums import OpportunityStatus, OpportunityType
from app.models.opportunity import Opportunity, OpportunityTopic
from app.models.ops import Reminder, SearchRun
from app.models.research import Faculty, FacultyTopic
from app.models.user import StudentProfile
from app.schemas import entities as E
from app.services.applications import blocking_reasons

router = APIRouter(tags=["overview"])

RESEARCH_TYPES = (OpportunityType.RESEARCH_OPENING, OpportunityType.RESEARCH_OUTREACH)

PIPELINE = [
    (OpportunityStatus.PREPARING, "Preparing"),
    (OpportunityStatus.READY_TO_APPLY, "Ready"),
    (OpportunityStatus.APPLYING, "Applying"),
    (OpportunityStatus.SUBMITTED, "Submitted"),
    (OpportunityStatus.INTERVIEW, "Interview"),
    (OpportunityStatus.OFFER, "Offer"),
    (OpportunityStatus.REJECTED, "Rejected"),
]

DUE_SOON_DAYS = 30


@router.get("/overview", response_model=E.Overview)
def overview(
    db: Session = Depends(get_session),
    profile: StudentProfile | None = Depends(current_profile_optional),
) -> E.Overview:
    settings = get_settings()
    today = datetime.now(UTC).date()

    if profile is None:
        return E.Overview(
            profile_name=None,
            university=settings.default_university,
            needs_onboarding=True,
        )

    opportunities = list(
        db.scalars(
            select(Opportunity).options(
                selectinload(Opportunity.matches),
                selectinload(Opportunity.source),
                selectinload(Opportunity.lab),
                selectinload(Opportunity.topics).selectinload(OpportunityTopic.topic),
                selectinload(Opportunity.faculty).selectinload(Faculty.evidence),
                selectinload(Opportunity.faculty).selectinload(Faculty.signals),
                selectinload(Opportunity.faculty).selectinload(Faculty.labs),
                selectinload(Opportunity.faculty)
                .selectinload(Faculty.topics)
                .selectinload(FacultyTopic.topic),
            )
        ).unique()
    )

    apps = {
        a.opportunity_id: a
        for a in db.scalars(
            select(Application)
            .where(Application.profile_id == profile.id)
            .options(selectinload(Application.documents), selectinload(Application.answers))
        ).unique()
    }
    reminder_ids = {
        r for r in db.scalars(select(Reminder.opportunity_id)).all() if r is not None
    }

    items = [
        ser.opportunity_item(
            o,
            today=today,
            profile_id=profile.id,
            application=apps.get(o.id),
            has_reminder=o.id in reminder_ids,
        )
        for o in opportunities
    ]
    by_id = {i.id: i for i in items}

    leads_all = sorted(
        [
            lead
            for lead in (
                ser.research_lead(o, today=today, profile=profile)
                for o in opportunities
                if o.type in RESEARCH_TYPES and o.faculty_id is not None
            )
            if lead is not None
        ],
        key=lambda item: -(item.fit_score or 0),
    )
    leads = leads_all[:6]

    # 1. Action needed: something is in flight and blocked, or a good match is
    #    about to expire. Ordered by how soon it stops being actionable.
    actions: list[E.ActionItem] = []
    for app in apps.values():
        item = by_id.get(app.opportunity_id)
        if item is None or app.status in (
            OpportunityStatus.SUBMITTED,
            OpportunityStatus.INTERVIEW,
            OpportunityStatus.OFFER,
            OpportunityStatus.REJECTED,
            OpportunityStatus.ARCHIVED,
        ):
            continue
        blocking = blocking_reasons(app, today)
        # Summarise rather than echo: the blockers are listed underneath, so
        # repeating the first one here just prints it twice.
        if not blocking:
            reason = "Everything Trellis can check is ready — review and apply."
        elif len(blocking) == 1:
            reason = f"One thing left: {blocking[0].rstrip('.').lower()}."
        else:
            reason = f"{len(blocking)} things still needed before you can apply."
        actions.append(
            E.ActionItem(
                opportunity=item,
                reason=reason,
                blocking=blocking,
                resume_ready=app.resume_id is not None,
                application_id=app.id,
                cta="Review application" if not blocking else "Finish preparing",
            )
        )

    # With nothing in flight, "action needed" must still answer "what should I do
    # next?" — an empty panel in the most valuable slot on the page helps nobody.
    # These are the two things a student would actually regret missing, in order.
    def _candidate(item, reason: str, cta: str) -> None:
        if len(actions) >= 5 or item.has_application:
            return
        if item.status not in (OpportunityStatus.NEW.value, OpportunityStatus.SAVED.value):
            return
        if any(a.opportunity.id == item.id for a in actions):
            return
        actions.append(
            E.ActionItem(
                opportunity=item,
                reason=reason,
                blocking=[],
                resume_ready=False,
                application_id=None,
                cta=cta,
            )
        )

    # a) a real deadline actually approaching. A date three months out is not
    # "what to do next", and listing it as such devalues the section.
    ACTIONABLE_WINDOW_DAYS = 45
    for item in sorted(
        (
            i
            for i in items
            if i.days_until_deadline is not None
            and 0 <= i.days_until_deadline <= ACTIONABLE_WINDOW_DAYS
        ),
        key=lambda i: i.days_until_deadline or 0,
    )[:3]:
        days = item.days_until_deadline or 0
        when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
        _candidate(item, f"Closes {when} ({item.deadline.isoformat()}).", "Open")

    # b) a lab that has actually said it takes undergraduates, ranked by fit
    for lead in leads_all:
        if lead.lead_state != "opening":
            continue
        item = by_id.get(lead.opportunity_id)
        if item is None:
            continue
        _candidate(
            item,
            f"Stated opening, and their recent work matches you at {round(lead.fit_score or 0)}%.",
            "Review lead",
        )

    urgency_rank = {"overdue": 0, "urgent": 1, "soon": 2, "later": 3, "rolling": 4, "unknown": 5}
    actions.sort(key=lambda a: urgency_rank.get(a.opportunity.urgency, 5))

    upcoming = sorted(
        [
            i
            for i in items
            if i.deadline
            and i.days_until_deadline is not None
            and i.days_until_deadline >= 0
            and i.status not in ("archived", "rejected")
        ],
        key=lambda i: i.deadline,
    )
    due_soon = [i for i in upcoming if i.days_until_deadline <= DUE_SOON_DAYS]
    if not due_soon:
        # Nothing inside the window, but showing the next real deadlines beats an
        # empty panel. Each row still renders its true date and urgency, so this
        # never makes a distant deadline look imminent.
        due_soon = upcoming[:5]

    best = sorted(
        [i for i in items if i.status in ("new", "saved")],
        key=lambda i: -(i.fit_score or 0),
    )[:8]


    recent = sorted(
        [i for i in items if i.first_seen_at],
        key=lambda i: i.first_seen_at,
        reverse=True,
    )[:6]

    status_counts: dict[str, int] = {}
    for app in apps.values():
        status_counts[app.status.value] = status_counts.get(app.status.value, 0) + 1

    last_run = db.scalars(
        select(SearchRun).order_by(SearchRun.created_at.desc()).limit(1)
    ).first()

    return E.Overview(
        profile_name=profile.user.display_name if profile.user else None,
        university=profile.university,
        action_needed=actions[:6],
        due_soon=due_soon[:8],
        best_matches=best,
        research_leads=leads,
        recent_discoveries=recent,
        pipeline=[
            E.PipelineStage(status=s.value, label=label, count=status_counts.get(s.value, 0))
            for s, label in PIPELINE
        ],
        counts=E.OverviewCounts(
            total=len(items),
            saved=sum(1 for i in items if i.status == "saved"),
            # Lab leads and formal programmes are different things and must not
            # be added together: /research shows only the faculty-linked leads,
            # so a combined figure here contradicted that page.
            lab_leads=len(leads_all),
            verified_openings=sum(1 for lead in leads_all if lead.lead_state == "opening"),
            outreach=sum(1 for lead in leads_all if lead.lead_state == "outreach"),
            research_programs=sum(
                1 for o in opportunities
                if o.type == OpportunityType.RESEARCH_OPENING and o.faculty_id is None
            ),
            unread=sum(1 for i in items if i.is_new),
        ),
        last_run=ser.run_summary(last_run) if last_run else None,
        needs_onboarding=profile.onboarding_completed_at is None,
    )
