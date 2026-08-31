from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import current_profile, current_profile_optional, get_session
from app.models.enums import WorkAuthorization
from app.models.user import (
    Coursework,
    ProfileResearchInterest,
    ProfileSkill,
    ResearchTopic,
    Skill,
    StudentProfile,
)
from app.schemas import entities as E
from app.services import taxonomy

router = APIRouter(tags=["profile"])


@router.get("/profile", response_model=E.StudentProfileOut | None)
def get_profile(
    db: Session = Depends(get_session),
    profile: StudentProfile | None = Depends(current_profile_optional),
) -> E.StudentProfileOut | None:
    # 200 with null rather than 404: "not onboarded yet" is a normal state, not
    # an error, and the client branches on it.
    return ser.profile_out(db, profile) if profile else None


@router.patch("/profile", response_model=E.StudentProfileOut)
def patch_profile(
    payload: E.ProfilePatch,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.StudentProfileOut:
    data = payload.model_dump(exclude_unset=True)
    if "display_name" in data and profile.user is not None:
        profile.user.display_name = data.pop("display_name")
    if "work_authorization" in data and data["work_authorization"] is not None:
        try:
            data["work_authorization"] = WorkAuthorization(data["work_authorization"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Unknown work authorization value.") from exc
    if "preferences" in data:
        # Merge: a client updating one preference must not wipe the others.
        incoming = data.pop("preferences") or {}
        profile.preferences = {**(profile.preferences or {}), **incoming}
    for key, value in data.items():
        setattr(profile, key, value)
    db.flush()
    return ser.profile_out(db, profile)


def _resolve_skill(db: Session, label: str) -> Skill:
    slug = taxonomy.resolve_skill(label)
    if slug:
        row = db.scalars(select(Skill).where(Skill.slug == slug)).first()
        if row is not None:
            return row
    normalized = label.strip().lower().replace(" ", "-")
    row = db.scalars(select(Skill).where(Skill.slug == normalized)).first()
    if row is None:
        row = Skill(slug=normalized[:120], label=label.strip()[:160], aliases=[])
        db.add(row)
        db.flush()
    return row


@router.post("/profile/skills", response_model=E.StudentProfileOut)
def add_skill(
    payload: E.LabelIn,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.StudentProfileOut:
    skill = _resolve_skill(db, payload.label)
    exists = db.scalars(
        select(ProfileSkill).where(
            ProfileSkill.profile_id == profile.id, ProfileSkill.skill_id == skill.id
        )
    ).first()
    if exists is None:
        db.add(ProfileSkill(profile_id=profile.id, skill_id=skill.id, origin="user"))
        db.flush()
    db.refresh(profile)
    return ser.profile_out(db, profile)


@router.delete("/profile/skills/{item_id}", response_model=E.StudentProfileOut)
def remove_skill(
    item_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.StudentProfileOut:
    row = db.get(ProfileSkill, item_id)
    if row is not None and row.profile_id == profile.id:
        db.delete(row)
        db.flush()
    db.refresh(profile)
    return ser.profile_out(db, profile)


@router.post("/profile/interests", response_model=E.StudentProfileOut)
def add_interest(
    payload: E.LabelIn,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.StudentProfileOut:
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="An interest needs a label.")
    exists = db.scalars(
        select(ProfileResearchInterest).where(
            ProfileResearchInterest.profile_id == profile.id,
            ProfileResearchInterest.label == label,
        )
    ).first()
    if exists is None:
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
                weight=payload.weight,
                topic_id=topic.id if topic else None,
            )
        )
        db.flush()
    db.refresh(profile)
    return ser.profile_out(db, profile)


@router.delete("/profile/interests/{item_id}", response_model=E.StudentProfileOut)
def remove_interest(
    item_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.StudentProfileOut:
    row = db.get(ProfileResearchInterest, item_id)
    if row is not None and row.profile_id == profile.id:
        db.delete(row)
        db.flush()
    db.refresh(profile)
    return ser.profile_out(db, profile)


@router.post("/profile/coursework", response_model=E.StudentProfileOut)
def add_course(
    payload: E.CourseIn,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.StudentProfileOut:
    db.add(
        Coursework(
            profile_id=profile.id,
            code=payload.code,
            title=payload.title,
            term=payload.term,
            grade=payload.grade,
            topics=[slug for slug, _ in taxonomy.match_topics(payload.title)],
            origin="user",
        )
    )
    db.flush()
    db.refresh(profile)
    return ser.profile_out(db, profile)


@router.delete("/profile/coursework/{item_id}", response_model=E.StudentProfileOut)
def remove_course(
    item_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.StudentProfileOut:
    row = db.get(Coursework, item_id)
    if row is not None and row.profile_id == profile.id:
        db.delete(row)
        db.flush()
    db.refresh(profile)
    return ser.profile_out(db, profile)
