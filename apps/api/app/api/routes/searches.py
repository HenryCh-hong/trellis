from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import current_profile, get_session
from app.models.enums import SearchKind
from app.models.ops import SavedSearch, SearchRun
from app.models.user import StudentProfile
from app.schemas import entities as E
from app.services.runs import start_run
from app.tasks.inprocess import get_queue

router = APIRouter(tags=["searches"])


def _search_item(row: SavedSearch) -> E.SavedSearchItem:
    return E.SavedSearchItem(
        id=row.id,
        name=row.name,
        kind=row.kind.value,
        query=row.query,
        source_slugs=list(row.source_slugs or []),
        enabled=row.enabled,
        last_run_at=row.last_run_at,
        filters=dict(row.filters or {}),
    )


@router.get("/searches", response_model=list[E.SavedSearchItem])
def list_searches(
    db: Session = Depends(get_session), profile: StudentProfile = Depends(current_profile)
) -> list[E.SavedSearchItem]:
    rows = db.scalars(
        select(SavedSearch)
        .where(SavedSearch.profile_id == profile.id)
        .order_by(SavedSearch.created_at)
    ).all()
    return [_search_item(r) for r in rows]


@router.post("/searches", response_model=E.SavedSearchItem, status_code=201)
def create_search(
    payload: E.SavedSearchIn,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.SavedSearchItem:
    try:
        kind = SearchKind(payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="kind must be 'jobs' or 'research'.") from exc
    row = SavedSearch(
        profile_id=profile.id,
        name=payload.name,
        kind=kind,
        query=payload.query,
        source_slugs=payload.source_slugs,
        filters=payload.filters,
    )
    db.add(row)
    db.flush()
    return _search_item(row)


def _enqueue(db: Session, profile: StudentProfile, kind: SearchKind, trigger: str,
             saved: SavedSearch | None = None) -> SearchRun:
    from app.api.routes.onboarding import _run_discovery

    run = start_run(db, kind=kind, trigger=trigger, profile_id=profile.id, saved_search=saved)
    db.commit()
    get_queue().enqueue(f"discovery:{kind.value}", _run_discovery, str(run.id), kind.value)
    return run


@router.post("/searches/discover", response_model=E.SearchRunSummary)
def discover(
    payload: E.DiscoverIn,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.SearchRunSummary:
    try:
        kind = SearchKind(payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="kind must be 'jobs' or 'research'.") from exc
    run = _enqueue(db, profile, kind, "manual")
    return ser.run_summary(run)


@router.post("/searches/{search_id}/run", response_model=E.SearchRunSummary)
def run_search(
    search_id: uuid.UUID,
    db: Session = Depends(get_session),
    profile: StudentProfile = Depends(current_profile),
) -> E.SearchRunSummary:
    saved = db.get(SavedSearch, search_id)
    if saved is None or saved.profile_id != profile.id:
        raise HTTPException(status_code=404, detail="Saved search not found.")
    run = _enqueue(db, profile, saved.kind, "saved_search", saved)
    return ser.run_summary(run)


@router.get("/runs", response_model=list[E.SearchRunSummary])
def list_runs(db: Session = Depends(get_session)) -> list[E.SearchRunSummary]:
    rows = db.scalars(
        select(SearchRun).order_by(SearchRun.created_at.desc()).limit(25)
    ).all()
    return [ser.run_summary(r) for r in rows]


@router.get("/runs/{run_id}", response_model=E.SearchRunSummary)
def get_run(run_id: uuid.UUID, db: Session = Depends(get_session)) -> E.SearchRunSummary:
    run = db.get(SearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return ser.run_summary(run)
