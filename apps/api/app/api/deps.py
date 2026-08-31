"""Request dependencies.

Auth scope for the MVP: Trellis runs as a single-student local application, so
there is exactly one user row and no login.  Every route resolves the current
profile through :func:`current_profile`, which is the single seam to replace
when multi-user auth arrives — no route reads ``users`` directly.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import StudentProfile, User


def get_session() -> Iterator[Session]:
    yield from get_db()


def current_user_optional(db: Session = Depends(get_session)) -> User | None:
    return db.execute(select(User).order_by(User.created_at)).scalars().first()


def current_profile_optional(
    db: Session = Depends(get_session),
) -> StudentProfile | None:
    return db.execute(select(StudentProfile).order_by(StudentProfile.created_at)).scalars().first()


def current_profile(
    profile: StudentProfile | None = Depends(current_profile_optional),
) -> StudentProfile:
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No student profile yet. Complete onboarding first.",
        )
    return profile


def current_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No user yet. Complete onboarding first.",
        )
    return user
