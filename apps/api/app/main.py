from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.tasks.inprocess import get_queue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("trellis")

settings = get_settings()


def _sweep_lifecycle_on_boot() -> None:
    """Mark deadlines that lapsed while the API was not running.

    Expiry has to happen without anyone remembering to trigger it, so it runs
    here as well as at both ends of a discovery run. A database that is not up
    yet must not stop the API from starting — the next run or the /lifecycle/
    sweep route will catch up.
    """
    from app.db.session import session_scope
    from app.services.lifecycle import sweep_expired

    try:
        with session_scope() as db:
            report = sweep_expired(db)
        if report.changed:
            logger.info(
                "lifecycle sweep on boot | expired=%d revived=%d", report.expired, report.revived
            )
    except Exception as exc:
        logger.warning("lifecycle sweep on boot skipped: %s: %s", type(exc).__name__, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.llm.factory import get_llm

    provider = get_llm()
    logger.info(
        "Trellis API up | llm=%s reasoning=%s | db=%s",
        provider.name,
        provider.is_reasoning_capable,
        settings.database_url.rsplit("/", 1)[-1],
    )
    _sweep_lifecycle_on_boot()
    yield
    get_queue().shutdown()


app = FastAPI(
    title="Trellis API",
    version="0.1.0",
    description="Personal university opportunity agent",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # The browser extension posts from a chrome-extension:// origin.
    allow_origin_regex=r"^chrome-extension://[a-p]+$" if settings.allow_extension_origins else None,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, object]:
    from app.llm.factory import get_llm

    provider = get_llm()
    return {
        "status": "ok",
        "llm_provider": provider.name,
        "llm_reasoning": provider.is_reasoning_capable,
        "university": settings.default_university,
    }


def register_routers() -> None:
    """Wire routers. Kept in a function so tests can build a bare app."""
    from app.api.routes import (
        applications,
        onboarding,
        opportunities,
        overview,
        profile,
        reminders,
        research,
        resumes,
        searches,
    )
    from app.api.routes import (
        settings as settings_routes,
    )

    for module in (
        overview,
        onboarding,
        profile,
        resumes,
        opportunities,
        research,
        applications,
        searches,
        reminders,
        settings_routes,
    ):
        app.include_router(module.router, prefix="/api")


try:
    register_routers()
except ImportError as exc:  # routers not written yet during scaffolding
    logger.warning("routers not fully available: %s", exc)
