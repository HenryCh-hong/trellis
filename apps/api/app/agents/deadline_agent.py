"""Deadlines — the field most likely to cost a student something if wrong.

Everything here is deterministic. The agent's job is to attach a date *and*
the sentence it came from, so the UI can show "Sep 18 — verified from the job
posting" rather than an unsourced date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.agents.base import Agent, AgentContext, AgentOutcome
from app.models.enums import Certainty, DeadlineType, ExtractionMethod
from app.models.opportunity import ExtractedField, Opportunity
from app.services.extractors import classify_deadline_type, extract_deadline

URGENT_DAYS = 3
SOON_DAYS = 14


def urgency_for(
    deadline: date | None,
    deadline_type: DeadlineType | str,
    today: date,
) -> str:
    """One vocabulary for deadline pressure, shared by the API and the UI."""
    kind = deadline_type.value if isinstance(deadline_type, DeadlineType) else str(deadline_type)
    if deadline is None:
        return "rolling" if kind == "rolling" else "unknown"
    days = (deadline - today).days
    if days < 0:
        return "overdue"
    if days <= URGENT_DAYS:
        return "urgent"
    if days <= SOON_DAYS:
        return "soon"
    return "later"


def days_until(deadline: date | None, today: date) -> int | None:
    return None if deadline is None else (deadline - today).days


@dataclass(slots=True)
class DeadlineRequest:
    opportunity: Opportunity
    text: str | None = None
    source_url: str | None = None


@dataclass(slots=True)
class DeadlineResult:
    deadline: date | None
    deadline_type: DeadlineType
    certainty: Certainty
    confidence: float
    source_text: str | None
    urgency: str


class DeadlineAgent(Agent[DeadlineRequest, DeadlineResult]):
    name = "deadline"
    description = "Reads a deadline out of a posting and records the sentence that supports it."

    def run(self, ctx: AgentContext, payload: DeadlineRequest) -> AgentOutcome[DeadlineResult]:
        opp = payload.opportunity
        text = payload.text or opp.description or ""
        notes: list[str] = []

        found = extract_deadline(text, ctx.today)
        kind = classify_deadline_type(text)
        deadline_type = kind.value or DeadlineType.UNKNOWN

        # A stated date always wins over a "rolling" phrase elsewhere on the page:
        # "applications reviewed on a rolling basis, apply by Sep 15" has a date.
        if found.value is not None and deadline_type == DeadlineType.UNKNOWN:
            deadline_type = DeadlineType.HARD
        if found.value is None and deadline_type == DeadlineType.HARD:
            deadline_type = DeadlineType.UNKNOWN
            notes.append("Page reads as a hard deadline but states no date.")

        if not ctx.dry_run:
            opp.deadline = found.value
            opp.deadline_type = deadline_type
            opp.deadline_confidence = found.confidence
            opp.deadline_certainty = found.certainty
            opp.deadline_source_text = found.source_text
            self._record_field(ctx, opp, found, payload.source_url)

        return AgentOutcome(
            result=DeadlineResult(
                deadline=found.value,
                deadline_type=deadline_type,
                certainty=found.certainty,
                confidence=found.confidence,
                source_text=found.source_text,
                urgency=urgency_for(found.value, deadline_type, ctx.today),
            ),
            notes=notes,
        )

    def _record_field(
        self, ctx: AgentContext, opp: Opportunity, found, source_url: str | None
    ) -> None:
        if opp.id is None:
            return
        from sqlalchemy import select

        row = ctx.db.scalars(
            select(ExtractedField).where(
                ExtractedField.opportunity_id == opp.id, ExtractedField.field == "deadline"
            )
        ).first()
        if row is None:
            row = ExtractedField(opportunity_id=opp.id, field="deadline")
            ctx.db.add(row)
        row.value = {"value": found.value.isoformat() if found.value else None}
        row.confidence = found.confidence
        row.certainty = found.certainty
        row.method = found.method if found.value else ExtractionMethod.HEURISTIC
        row.source_text = found.source_text
        row.source_url = source_url or found.source_url or opp.source_url
        row.extractor_version = "deadline-1"
