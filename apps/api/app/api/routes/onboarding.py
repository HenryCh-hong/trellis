from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import get_session
from app.models.enums import SearchKind
from app.models.user import (
    ProfileResearchInterest,
    ProfileSkill,
    ResearchTopic,
    Skill,
    StudentProfile,
    User,
)
from app.schemas import entities as E
from app.services import taxonomy
from app.services.runs import start_run

router = APIRouter(tags=["onboarding"])


@router.post("/onboarding")
def onboard(
    payload: E.OnboardingIn, db: Session = Depends(get_session)
) -> dict[str, object]:
    """Create the student's profile and kick off the first discovery run.

    Five questions, not forty: everything else is editable later in /profile.
    """
    taxonomy.ensure_vocabulary(db)

    user = db.scalars(select(User)).first()
    if user is None:
        user = User(
            email=payload.email or "student@localhost",
            display_name=payload.display_name,
        )
        db.add(user)
        db.flush()
    elif payload.display_name:
        user.display_name = payload.display_name

    profile = db.scalars(select(StudentProfile)).first()
    if profile is None:
        profile = StudentProfile(user_id=user.id, university=payload.university)
        db.add(profile)
        db.flush()

    profile.university = payload.university
    profile.campus = payload.campus or profile.campus
    profile.major = payload.major or profile.major
    profile.degree = payload.degree or profile.degree
    profile.graduation_year = payload.graduation_year or profile.graduation_year
    profile.hours_per_week_min = payload.hours_per_week_min or profile.hours_per_week_min
    profile.hours_per_week_max = payload.hours_per_week_max or profile.hours_per_week_max
    if payload.job_types:
        profile.preferred_job_types = payload.job_types
    profile.onboarding_completed_at = datetime.now(UTC)

    existing_interests = {i.label.lower() for i in profile.interests}
    for label in payload.interests:
        label = label.strip()
        if not label or label.lower() in existing_interests:
            continue
        slug = taxonomy.resolve_topic(label)
        topic = (
            db.scalars(select(ResearchTopic).where(ResearchTopic.slug == slug)).first()
            if slug
            else None
        )
        db.add(
            ProfileResearchInterest(
                profile_id=profile.id,
                label=label,
                weight=1.5,
                topic_id=topic.id if topic else None,
            )
        )
        existing_interests.add(label.lower())

    existing_skills = {ps.skill.slug for ps in profile.skills if ps.skill is not None}
    for raw in payload.skills:
        slug = taxonomy.resolve_skill(raw) or raw.strip().lower().replace(" ", "-")
        if not slug or slug in existing_skills:
            continue
        skill = db.scalars(select(Skill).where(Skill.slug == slug)).first()
        if skill is None:
            skill = Skill(slug=slug[:120], label=raw.strip()[:160], aliases=[])
            db.add(skill)
            db.flush()
        db.add(ProfileSkill(profile_id=profile.id, skill_id=skill.id, origin="user"))
        existing_skills.add(slug)

    db.flush()

    run_ids: list[str] = []
    if payload.run_discovery:
        from app.tasks.inprocess import get_queue

        wants_research = any(t.startswith("research") for t in (payload.job_types or []))
        kinds = [SearchKind.JOBS]
        if wants_research or not payload.job_types:
            kinds.append(SearchKind.RESEARCH)

        for kind in kinds:
            run = start_run(db, kind=kind, trigger="onboarding", profile_id=profile.id)
            run_ids.append(str(run.id))
            db.commit()
            get_queue().enqueue(f"discovery:{kind.value}", _run_discovery, str(run.id), kind.value)

    db.refresh(profile)
    return {"profile": ser.profile_out(db, profile).model_dump(mode="json"), "run_ids": run_ids}


def _run_discovery(run_id: str, kind: str) -> dict[str, object]:
    """Background entry point. Owns its own session — the request's is gone."""
    import logging
    import uuid as _uuid

    from app.agents.base import AgentContext
    from app.agents.research_agent import ResearchDiscoveryAgent, ResearchRequest
    from app.agents.search_agent import OpportunitySearchAgent, SearchRequest
    from app.db.session import session_scope
    from app.models.enums import RunStatus
    from app.models.ops import SearchRun
    from app.services.runs import finish_run

    with session_scope() as db:
        run = db.get(SearchRun, _uuid.UUID(run_id))
        if run is None:
            return {"error": "run not found"}
        profile = db.scalars(select(StudentProfile)).first()
        ctx = AgentContext(db=db, search_run_id=run.id, profile_id=profile.id if profile else None)
        try:
            if kind == SearchKind.RESEARCH.value:
                outcome = ResearchDiscoveryAgent().run(
                    ctx, ResearchRequest(profile=profile, run=run)
                )
            else:
                outcome = OpportunitySearchAgent().run(
                    ctx, SearchRequest(profile=profile, run=run)
                )
            return {"status": run.status.value, "result": str(outcome.result)}
        except Exception as exc:
            # Commit the failure explicitly. Re-raising would unwind
            # session_scope(), roll the write back, and leave the run stuck on
            # RUNNING forever with nothing to explain why.
            finish_run(db, run, status=RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
            db.commit()
            logging.getLogger(__name__).exception("discovery run %s failed", run_id)
            return {"status": RunStatus.FAILED.value, "error": f"{type(exc).__name__}: {exc}"}
