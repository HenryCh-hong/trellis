from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.application_agent import (
    ApplicationPrepAgent,
    ApprovalError,
    PrepRequest,
    approve,
    build_submission_plan,
)
from app.agents.base import AgentContext
from app.api import serializers as ser
from app.api.deps import current_profile, get_session
from app.models.application import Application
from app.models.enums import DocumentStatus, OpportunityStatus
from app.models.opportunity import Opportunity
from app.models.resume import Resume
from app.models.user import StudentProfile
from app.schemas import entities as E
from app.services.applications import (
    TransitionError,
    blocking_reasons,
    create_kit,
    known_profile_fields,
    transition,
)

router = APIRouter(tags=["applications"])


def _load(db: Session, application_id: uuid.UUID, profile: StudentProfile) -> Application:
    app = db.scalars(
        select(Application)
        .where(Application.id == application_id, Application.profile_id == profile.id)
        .options(
            selectinload(Application.documents),
            selectinload(Application.answers),
            selectinload(Application.events),
            selectinload(Application.opportunity).selectinload(Opportunity.matches),
            selectinload(Application.opportunity).selectinload(Opportunity.source),
            selectinload(Application.opportunity).selectinload(Opportunity.faculty),
            selectinload(Application.opportunity).selectinload(Opportunity.lab),
        )
    ).first()
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    return app


def _kit(db: Session, app: Application, profile: StudentProfile) -> E.ApplicationKit:
    today = datetime.now(UTC).date()
    opp = app.opportunity
    resume = db.get(Resume, app.resume_id) if app.resume_id else None
    blocking = blocking_reasons(app, today)
    return E.ApplicationKit(
        id=app.id,
        status=app.status.value,
        opportunity=ser.opportunity_item(
            opp, today=today, profile_id=profile.id, application=app
        ),
        application_url=opp.application_url or opp.source_url,
        application_method=opp.application_method,
        resume_id=app.resume_id,
        resume_label=resume.label if resume else None,
        resume_locked_by_user=app.resume_locked_by_user,
        resume_recommendations=ser.resume_recommendations(db, opp.id),
        documents=[
            E.ApplicationDocumentItem(
                id=d.id,
                kind=d.kind.value,
                label=d.label,
                status=d.status.value,
                required=d.required,
                resume_id=d.resume_id,
                filename=d.filename,
                note=d.note,
                source_text=d.source_text,
            )
            for d in app.documents
        ],
        answers=[
            E.ApplicationAnswerItem(
                id=a.id,
                question=a.question,
                field_key=a.field_key,
                answer=a.answer,
                source=a.source.value,
                profile_field=a.profile_field,
                is_sensitive=a.is_sensitive,
                sensitive_category=a.sensitive_category,
                reuse_approved=a.reuse_approved,
                needs_user_input=a.needs_user_input,
                max_length=a.max_length,
            )
            for a in sorted(app.answers, key=lambda a: a.order_index)
        ],
        known_profile_fields=[E.KnownField(**f) for f in known_profile_fields(profile)],
        blocking=blocking,
        ready=not blocking,
        prepared_at=app.prepared_at,
        approved_at=app.approved_at,
        submitted_at=app.submitted_at,
        notes=app.notes,
        events=[
            E.ApplicationEventItem(
                id=e.id,
                kind=e.kind,
                from_status=e.from_status,
                to_status=e.to_status,
                actor=e.actor,
                note=e.note,
                created_at=e.created_at,
            )
            for e in app.events
        ],
    )


@router.get("/applications", response_model=list[E.ApplicationKit])
def list_applications(
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> list[E.ApplicationKit]:
    rows = db.scalars(
        select(Application)
        .where(Application.profile_id == profile.id)
        .order_by(Application.updated_at.desc())
        .options(
            selectinload(Application.documents),
            selectinload(Application.answers),
            selectinload(Application.events),
            selectinload(Application.opportunity).selectinload(Opportunity.matches),
            selectinload(Application.opportunity).selectinload(Opportunity.source),
        )
    ).unique()
    return [_kit(db, app, profile) for app in rows]


@router.post("/applications", response_model=E.ApplicationKit, status_code=201)
def create_application(
    payload: E.ApplicationCreate,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.ApplicationKit:
    opp = db.get(Opportunity, payload.opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail="Opportunity not found.")
    app = create_kit(db, profile, opp)
    ApplicationPrepAgent().run(
        AgentContext(db=db), PrepRequest(application=app, profile=profile)
    )
    db.flush()
    # The prep agent added answers through the session, not the relationship, so
    # the loaded collection is stale until we expire it.
    db.expire(app)
    return _kit(db, _load(db, app.id, profile), profile)


@router.get("/applications/{application_id}", response_model=E.ApplicationKit)
def get_application(
    application_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.ApplicationKit:
    return _kit(db, _load(db, application_id, profile), profile)


@router.patch("/applications/{application_id}", response_model=E.ApplicationKit)
def patch_application(
    application_id: uuid.UUID,
    payload: E.ApplicationPatch,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.ApplicationKit:
    app = _load(db, application_id, profile)
    if payload.resume_id is not None:
        resume = db.get(Resume, payload.resume_id)
        if resume is None:
            raise HTTPException(status_code=404, detail="Resume not found.")
        app.resume_id = resume.id
        app.resume_locked_by_user = True
        for doc in app.documents:
            if doc.kind.value == "resume":
                doc.resume_id = resume.id
                doc.status = DocumentStatus.READY
                doc.filename = resume.original_filename
    if payload.notes is not None:
        app.notes = payload.notes
    if payload.status is not None:
        try:
            transition(db, app, OpportunityStatus(payload.status))
        except ValueError as exc:
            code = 409 if isinstance(exc, TransitionError) else 400
            raise HTTPException(status_code=code, detail=str(exc)) from exc
    db.flush()
    db.expire(app)
    return _kit(db, _load(db, application_id, profile), profile)


@router.patch("/applications/{application_id}/answers/{answer_id}", response_model=E.ApplicationKit)
def patch_answer(
    application_id: uuid.UUID,
    answer_id: uuid.UUID,
    payload: E.AnswerPatch,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.ApplicationKit:
    app = _load(db, application_id, profile)
    answer = next((a for a in app.answers if a.id == answer_id), None)
    if answer is None:
        raise HTTPException(status_code=404, detail="Question not found on this application.")
    if payload.answer is not None:
        # The student typing an answer always makes it theirs, never a draft.
        answer.answer = payload.answer or None
        answer.source = answer.source.__class__.USER
        answer.needs_user_input = not payload.answer
    if payload.reuse_approved is not None:
        answer.reuse_approved = payload.reuse_approved
    # Any edit invalidates a prior approval: the payload changed.
    app.approved_at = None
    app.approved_payload_hash = None
    db.flush()
    return _kit(db, _load(db, application_id, profile), profile)


@router.get("/applications/{application_id}/plan", response_model=E.SubmissionPlan)
def get_plan(
    application_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.SubmissionPlan:
    app = _load(db, application_id, profile)
    plan = build_submission_plan(app, profile, datetime.now(UTC).date())
    return E.SubmissionPlan(**{k: v for k, v in plan.items() if k != "blocking"})


@router.post("/applications/{application_id}/approve", response_model=E.ApplicationKit)
def approve_application(
    application_id: uuid.UUID,
    payload: E.ApprovalIn,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.ApplicationKit:
    app = _load(db, application_id, profile)
    try:
        approve(db, app, profile, payload.payload_hash, datetime.now(UTC).date())
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if app.status == OpportunityStatus.PREPARING:
        transition(db, app, OpportunityStatus.READY_TO_APPLY, note="Approved for assisted apply.")
    db.flush()
    db.expire(app)
    return _kit(db, _load(db, application_id, profile), profile)


@router.post("/applications/{application_id}/submitted", response_model=E.ApplicationKit)
def mark_submitted(
    application_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.ApplicationKit:
    app = _load(db, application_id, profile)
    try:
        if app.status == OpportunityStatus.PREPARING:
            transition(db, app, OpportunityStatus.READY_TO_APPLY)
        if app.status == OpportunityStatus.READY_TO_APPLY:
            transition(db, app, OpportunityStatus.APPLYING)
        transition(db, app, OpportunityStatus.SUBMITTED, note="Marked submitted by the student.")
    except TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.flush()
    db.expire(app)
    return _kit(db, _load(db, application_id, profile), profile)
