"""The one list of source adapters, and the DB rows that mirror it.

Adding a source is meant to cost a class and one line here — nothing in ranking,
dedup, the API or the UI knows about individual sources.  ``ensure_sources``
keeps the ``opportunity_sources`` table in step with this list so every
opportunity can be attributed to a row the user can see, enable or disable.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.opportunity import OpportunitySource
from app.sources.base import SourceAdapter
from app.sources.handshake import HandshakeAdapter
from app.sources.lab_site import LabSiteAdapter
from app.sources.manual_url import ManualUrlAdapter
from app.sources.openalex import OpenAlexAdapter
from app.sources.stanford_careersearch import StanfordCareerSearchAdapter
from app.sources.stanford_cs_faculty import StanfordCsFacultyAdapter
from app.sources.stanford_programs import StanfordProgramsAdapter
from app.sources.stanford_student_jobs import StanfordStudentJobsAdapter

_ADAPTER_CLASSES: tuple[type[SourceAdapter], ...] = (
    StanfordStudentJobsAdapter,
    StanfordCareerSearchAdapter,
    HandshakeAdapter,
    StanfordCsFacultyAdapter,
    StanfordProgramsAdapter,
    LabSiteAdapter,
    OpenAlexAdapter,
    ManualUrlAdapter,
)

SOURCE_ADAPTERS: dict[str, type[SourceAdapter]] = {cls.slug: cls for cls in _ADAPTER_CLASSES}


def adapter_path(cls: type[SourceAdapter]) -> str:
    """Import path recorded on the DB row, so a row can be traced to its code."""
    return f"{cls.__module__}.{cls.__qualname__}"


def get_adapter(slug: str) -> SourceAdapter:
    """A ready-to-use adapter instance for ``slug``."""
    try:
        cls = SOURCE_ADAPTERS[slug]
    except KeyError as exc:
        known = ", ".join(sorted(SOURCE_ADAPTERS))
        raise LookupError(f"unknown source adapter {slug!r}; known slugs: {known}") from exc
    return cls()


def all_adapters() -> list[SourceAdapter]:
    """One instance of every registered adapter, in registration order."""
    return [cls() for cls in _ADAPTER_CLASSES]


def ensure_sources(db: Session) -> list[OpportunitySource]:
    """Upsert one ``opportunity_sources`` row per adapter. Idempotent.

    Descriptive columns are refreshed from the adapter each run; ``enabled`` and
    ``config`` are user state and are never overwritten here.
    """
    existing = {
        row.slug: row for row in db.scalars(select(OpportunitySource)).all()
    }
    rows: list[OpportunitySource] = []

    for cls in _ADAPTER_CLASSES:
        adapter = cls()
        row = existing.get(adapter.slug)
        if row is None:
            row = OpportunitySource(slug=adapter.slug, kind=adapter.kind, name=adapter.name)
            db.add(row)
        row.name = adapter.name
        row.kind = adapter.kind
        row.base_url = adapter.base_url
        row.adapter = adapter_path(cls)
        row.requires_auth = adapter.requires_auth
        row.is_public = adapter.is_public
        row.notes = adapter.notes or None
        rows.append(row)

    db.flush()
    return rows
