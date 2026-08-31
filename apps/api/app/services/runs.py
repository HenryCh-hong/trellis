"""Search run bookkeeping.

Step text is user-facing -- it drives the onboarding progress and the run
drawer -- so it names what actually happened ("Fetched 12 pages from
thehub.stanford.edu"), never "processing".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.enums import RunStatus, SearchKind
from app.models.ops import SavedSearch, SearchRun


def start_run(
    db: Session,
    *,
    kind: SearchKind,
    trigger: str = "manual",
    profile_id: uuid.UUID | None = None,
    saved_search: SavedSearch | None = None,
) -> SearchRun:
    run = SearchRun(
        kind=kind,
        trigger=trigger,
        profile_id=profile_id,
        saved_search_id=saved_search.id if saved_search else None,
        status=RunStatus.RUNNING,
        started_at=datetime.now(UTC),
        steps=[],
    )
    db.add(run)
    db.flush()
    return run


def record_step(
    run: SearchRun,
    step: str,
    detail: str,
    status: str = "ok",
    db: Session | None = None,
) -> None:
    # Reassigning is required: SQLAlchemy does not track in-place JSONB mutation.
    run.steps = [*(run.steps or []), {"step": step, "detail": detail, "status": status}]
    # Onboarding polls this run to show real progress. Without an immediate
    # commit the steps only become visible once the whole run finishes, which
    # is exactly when they stop being useful.
    if db is not None:
        db.commit()


def finish_run(
    db: Session,
    run: SearchRun,
    *,
    status: RunStatus | None = None,
    error: str | None = None,
) -> SearchRun:
    failures = sum(1 for s in (run.steps or []) if s.get("status") == "error")
    # "empty" and "skipped" are healthy outcomes, not partial failure.
    if status is None:
        if error:
            status = RunStatus.FAILED
        elif failures and (run.created_count or run.updated_count or run.unchanged_count):
            status = RunStatus.PARTIAL
        elif failures:
            status = RunStatus.FAILED
        else:
            status = RunStatus.SUCCEEDED
    run.status = status
    run.error = error
    run.finished_at = datetime.now(UTC)
    if run.saved_search is not None:
        run.saved_search.last_run_at = run.finished_at
    db.flush()
    return run
