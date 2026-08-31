from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user_optional, get_session
from app.core.config import get_settings
from app.models.opportunity import Opportunity, OpportunitySource
from app.models.ops import DataProvenance
from app.models.resume import Resume
from app.models.user import User
from app.schemas import entities as E

router = APIRouter(tags=["settings"])


@router.get("/sources", response_model=list[E.DataSourceInfo])
def list_sources(db: Session = Depends(get_session)) -> list[E.DataSourceInfo]:
    counts = dict(
        db.execute(
            select(Opportunity.source_id, func.count()).group_by(Opportunity.source_id)
        ).all()
    )
    rows = db.scalars(select(OpportunitySource).order_by(OpportunitySource.name)).all()
    return [
        E.DataSourceInfo(
            slug=s.slug,
            name=s.name,
            kind=s.kind.value,
            base_url=s.base_url,
            requires_auth=s.requires_auth,
            is_public=s.is_public,
            is_mocked=False,
            enabled=s.enabled,
            last_run_at=s.last_run_at,
            opportunity_count=counts.get(s.id, 0),
            notes=s.notes,
        )
        for s in rows
    ]


@router.get("/provenance", response_model=list[E.ProvenanceInfo])
def list_provenance(db: Session = Depends(get_session)) -> list[E.ProvenanceInfo]:
    rows = db.scalars(select(DataProvenance).order_by(DataProvenance.key)).all()
    return [
        E.ProvenanceInfo(
            key=r.key, label=r.label, generated_at=r.generated_at, detail=dict(r.detail or {})
        )
        for r in rows
    ]


@router.delete("/account", status_code=204)
def delete_account(
    db: Session = Depends(get_session),
    user: User | None = Depends(current_user_optional),
) -> None:
    """Delete the student's data, including their resume files on disk.

    Harvested public research data (faculty, labs, evidence) is not personal
    data and is left in place; everything tied to the user cascades away.
    """
    if user is None:
        return
    settings = get_settings()
    for resume in db.scalars(select(Resume).where(Resume.user_id == user.id)):
        (settings.resume_dir / resume.storage_path).unlink(missing_ok=True)
    db.delete(user)
    db.flush()
