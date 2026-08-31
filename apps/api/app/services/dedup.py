"""Dedup and refresh.

Running a search twice must update, never duplicate. Identity is resolved in
precedence order, strongest signal first, because a fuzzy title match is a last
resort: two different lab postings can easily share a title.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.change import ChangeKind
from app.models.enums import DeadlineType, OpportunityStatus, OpportunityType
from app.models.opportunity import Opportunity, OpportunitySource, Requirement
from app.services.lifecycle import deadline_change_summary, log_change, sync_deadline_state

TITLE_MATCH_THRESHOLD = 92
ORG_MATCH_THRESHOLD = 82

# Changing any of these is a real change the student might care about; anything
# else (whitespace, a reworded blurb) is not worth flagging as updated.
MATERIAL_FIELDS = (
    "title",
    "organization",
    "deadline",
    "deadline_type",
    "pay_text",
    "hours_per_week",
    "application_url",
    "application_method",
    "location",
    "contact_email",
)


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    netloc = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    # Query strings on job pages are usually tracking noise; the path is identity.
    return urlunsplit((parts.scheme.lower() or "https", netloc, path, "", ""))


def _norm(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def fingerprint(data: dict[str, Any]) -> str:
    material = {k: str(data.get(k) or "") for k in MATERIAL_FIELDS}
    requirements = sorted(
        f"{r.get('kind')}:{_norm(str(r.get('text')))}" for r in data.get("requirements") or []
    )
    material["requirements"] = "|".join(requirements)
    blob = "".join(f"{k}={material[k]}" for k in sorted(material))
    return hashlib.sha256(blob.encode()).hexdigest()


def find_existing(
    db: Session,
    *,
    source_id: uuid.UUID | None,
    external_key: str | None,
    source_url: str | None,
    title: str | None,
    organization: str | None,
) -> Opportunity | None:
    if source_id and external_key:
        row = db.scalars(
            select(Opportunity).where(
                Opportunity.source_id == source_id,
                Opportunity.external_key == external_key,
            )
        ).first()
        if row is not None:
            return row

    if external_key:
        row = db.scalars(select(Opportunity).where(Opportunity.external_key == external_key)).first()
        if row is not None:
            return row

    normalized = normalize_url(source_url)
    if normalized:
        for candidate in db.scalars(select(Opportunity).where(Opportunity.source_url.is_not(None))):
            if normalize_url(candidate.source_url) == normalized:
                return candidate

    if title:
        wanted_title, wanted_org = _norm(title), _norm(organization)
        for candidate in db.scalars(select(Opportunity)):
            if fuzz.token_sort_ratio(_norm(candidate.title), wanted_title) < TITLE_MATCH_THRESHOLD:
                continue
            if (
                wanted_org
                and _norm(candidate.organization)
                and fuzz.token_sort_ratio(_norm(candidate.organization), wanted_org)
                < ORG_MATCH_THRESHOLD
            ):
                continue
            return candidate
    return None


@dataclass(slots=True)
class UpsertReport:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    notes: list[str] = field(default_factory=list)

    def add(self, outcome: str) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)


def upsert_opportunity(
    db: Session,
    data: dict[str, Any],
    *,
    source: OpportunitySource | None = None,
    now: datetime | None = None,
    run_id: uuid.UUID | None = None,
) -> tuple[Opportunity, str]:
    """Create or refresh one opportunity. Returns (row, created|updated|unchanged)."""
    now = now or datetime.now(UTC)
    source_id = source.id if source is not None else data.get("source_id")

    existing = find_existing(
        db,
        source_id=source_id,
        external_key=data.get("external_key"),
        source_url=data.get("source_url"),
        title=data.get("title"),
        organization=data.get("organization"),
    )
    new_fingerprint = fingerprint(data)

    if existing is None:
        opp = Opportunity(
            title=data["title"],
            type=OpportunityType(data.get("type", OpportunityType.ON_CAMPUS)),
            status=OpportunityStatus.NEW,
            first_seen_at=now,
        )
        db.add(opp)
        outcome = "created"
    else:
        opp = existing
        # first_seen_at records when WE first saw it and must never move.
        outcome = "unchanged" if opp.content_fingerprint == new_fingerprint else "updated"

    # Capture the before-state while it is still in memory: the whole value of
    # re-running discovery is knowing what moved, and _apply overwrites it.
    before = _snapshot(opp) if outcome == "updated" else None

    _apply(opp, data, source_id, now.astimezone(UTC).date())
    opp.last_checked_at = now
    if outcome != "unchanged":
        opp.last_changed_at = now
        opp.content_fingerprint = new_fingerprint
        db.flush()
        removed, added = _replace_requirements(db, opp, data.get("requirements") or [])
        if outcome == "created":
            log_change(db, opp, ChangeKind.DISCOVERED, None, None, None,
                       f"Found on {opp.source_url or 'the web'}", now, run_id)
        elif before is not None:
            _log_field_changes(db, opp, before, now, run_id, added, removed)

    return opp, outcome


# What a student would actually want to be told about.
_TRACKED: tuple[tuple[str, ChangeKind, str], ...] = (
    ("deadline", ChangeKind.DEADLINE, "Deadline"),
    ("pay_text", ChangeKind.PAY, "Pay"),
    ("hours_per_week", ChangeKind.HOURS, "Hours per week"),
    ("application_url", ChangeKind.APPLICATION_URL, "Application link"),
)


def _snapshot(opp: Opportunity) -> dict[str, Any]:
    return {name: getattr(opp, name) for name, _, _ in _TRACKED}


def _log_field_changes(
    db: Session,
    opp: Opportunity,
    before: dict[str, Any],
    now: datetime,
    run_id: uuid.UUID | None,
    added: list[str],
    removed: list[str],
) -> None:
    for name, kind, label in _TRACKED:
        old, new = before.get(name), getattr(opp, name)
        if old == new:
            continue
        if name == "deadline":
            # A date that VANISHES is the case worth spelling out: rendering it
            # as a bare "Unknown" reads as "we never knew", when the truth is
            # that the posting used to say a date and stopped saying it.
            summary = deadline_change_summary(old, new)
        elif old is None:
            summary = f"{label} added: {new}"
        elif new is None:
            summary = f"{label} removed (was {old})"
        else:
            summary = f"{label} changed: {old} → {new}"
        log_change(db, opp, kind, name, old, new, summary, now, run_id)

    for text in added[:5]:
        log_change(db, opp, ChangeKind.REQUIREMENT_ADDED, "requirements", None, text,
                   f"New requirement: {text[:120]}", now, run_id)
    for text in removed[:5]:
        log_change(db, opp, ChangeKind.REQUIREMENT_REMOVED, "requirements", text, None,
                   f"Requirement removed: {text[:120]}", now, run_id)


def _apply(
    opp: Opportunity, data: dict[str, Any], source_id: uuid.UUID | None, today: date
) -> None:
    simple = (
        "title",
        "organization",
        "university",
        "department",
        "location",
        "pay_text",
        "pay_min",
        "pay_max",
        "pay_period",
        "hours_per_week",
        "hours_note",
        "description",
        "application_method",
        "application_url",
        "contact_name",
        "contact_email",
        "source_url",
        "external_key",
        "posted_at",
        "notes",
    )
    for key in simple:
        if key in data and data[key] is not None:
            setattr(opp, key, data[key])
    if data.get("type"):
        opp.type = OpportunityType(data["type"])
    if source_id:
        opp.source_id = source_id
    if "deadline" in data:
        opp.deadline = data["deadline"]
    if data.get("deadline_type"):
        opp.deadline_type = DeadlineType(data["deadline_type"])
    for key in ("deadline_confidence", "deadline_certainty", "deadline_source_text"):
        if data.get(key) is not None:
            setattr(opp, key, data[key])
    for key in ("skills", "documents_required"):
        if data.get(key) is not None:
            setattr(opp, key, list(data[key]))
    if data.get("extraction_confidence") is not None:
        opp.extraction_confidence = float(data["extraction_confidence"])
    if data.get("raw") is not None:
        opp.raw = data["raw"]
    # The stored lifecycle state has to follow the dates we just wrote, or a
    # posting that extends its deadline would stay marked expired.
    sync_deadline_state(opp, today)


def _replace_requirements(
    db: Session, opp: Opportunity, rows: list[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """Returns (removed, added) requirement texts so changes can be reported."""
    if not rows:
        return ([], [])
    old_texts = {_norm(r.text): r.text for r in opp.requirements}
    new_texts = {_norm(str(r["text"])): str(r["text"]) for r in rows}
    removed = [old_texts[k] for k in old_texts.keys() - new_texts.keys()]
    added = [new_texts[k] for k in new_texts.keys() - old_texts.keys()]

    for existing in list(opp.requirements):
        db.delete(existing)
    db.flush()
    for index, row in enumerate(rows):
        db.add(
            Requirement(
                opportunity_id=opp.id,
                text=row["text"],
                kind=row["kind"],
                category=row.get("category"),
                skill_slugs=list(row.get("skill_slugs") or []),
                source_text=row.get("source_text"),
                source_url=row.get("source_url"),
                confidence=float(row.get("confidence") or 0.0),
                order_index=index,
            )
        )
    return (removed, added)
