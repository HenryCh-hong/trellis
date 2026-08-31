"""Turning a fetched page into a structured opportunity.

Order of trust, highest first:

1. ``structured`` data the adapter read from a real API — that is the source
   speaking, so it is recorded with ``ExtractionMethod.SOURCE`` at confidence 1.
2. Deterministic extractors over the page text.
3. The model, and only for fields still empty after (1) and (2), and only when
   a provider that can actually reason is configured.

Nothing is ever filled in by guessing. A field we cannot support stays null.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.base import Agent, AgentContext, AgentOutcome
from app.llm.base import Evidenced, LLMUnavailable
from app.models.enums import (
    Certainty,
    ExtractionMethod,
    OpportunityType,
)
from app.models.opportunity import ExtractedField, Opportunity, OpportunitySource
from app.services import taxonomy
from app.services.extractors import (
    classify_deadline_type,
    extract_application_method,
    extract_contact,
    extract_deadline,
    extract_documents,
    extract_eligibility,
    extract_hours,
    extract_pay,
    normalize_text,
    split_requirements,
)
from app.sources.base import DiscoveredDocument

# Canonical field name -> the names adapters actually use upstream.
STRUCTURED_ALIASES: dict[str, tuple[str, ...]] = {
    "deadline": ("apply_by", "apply_by_date", "closes_at", "expires_at"),
    "pay": ("pay_text", "compensation", "salary"),
    "organization": ("employer", "company", "org"),
    "application_url": ("external_application_url", "apply_url"),
    "application_method": ("apply_method",),
    "posted_at": ("posted", "posted_date"),
    "hours_per_week": ("hours",),
}

def _as_date(value: Any) -> date | None:
    """Structured data arrives over JSON, so a date is a string until coerced.

    Passing the string straight through reached the scorer and raised there,
    which is a long way from where the mistake was made.
    """
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit())
        return int(digits) if digits else None
    return None


RESEARCH_HINTS = (
    "research assistant",
    "undergraduate research",
    "lab",
    "laboratory",
    "principal investigator",
    "curis",
    "research opportunity",
    "research internship",
)


class _LlmFields(BaseModel):
    """Only the fields worth asking a model for, all optional."""

    summary: str | None = Field(default=None, max_length=1200)
    documents_required: list[str] = Field(default_factory=list, max_length=12)
    application_method: str | None = None


@dataclass(slots=True)
class ExtractionRequest:
    document: DiscoveredDocument
    source: OpportunitySource | None = None
    default_type: OpportunityType | None = None


@dataclass(slots=True)
class ExtractionResult:
    data: dict[str, Any]
    text: str
    provenance: list[dict[str, Any]] = field(default_factory=list)


class WebExtractionAgent(Agent[ExtractionRequest, ExtractionResult]):
    name = "web-extraction"
    description = "Normalises one fetched page into the unified opportunity schema with provenance."

    def run(self, ctx: AgentContext, payload: ExtractionRequest) -> AgentOutcome[ExtractionResult]:
        doc = payload.document
        structured = doc.structured or {}
        text = normalize_text(doc.text or "")
        warnings: list[str] = []
        provenance: list[dict[str, Any]] = []

        def take(key: str, fallback: Any = None) -> Any:
            """Structured value wins; it came straight from the source.

            Adapters name their fields the way their upstream does — the
            Handshake extension emits ``apply_by``/``pay_text``/``employer``
            while this schema calls them ``deadline``/``pay``/``organization``.
            Resolving aliases here keeps that mismatch from silently dropping
            the most valuable fields an adapter captured.
            """
            for candidate in (key, *STRUCTURED_ALIASES.get(key, ())):
                value = structured.get(candidate)
                if value not in (None, "", []):
                    return value
            return fallback

        deadline = extract_deadline(text, ctx.today)
        deadline_kind = classify_deadline_type(text)
        pay = extract_pay(text)
        hours = extract_hours(text)
        contact_name, contact_email = extract_contact(text, doc.html)
        method, apply_url = extract_application_method(text, doc.html, doc.url)
        documents = extract_documents(text)
        eligibility = extract_eligibility(text)
        requirements = split_requirements(text)

        title = take("title") or doc.title or ""
        organization = take("organization")
        opp_type = self._classify(doc, payload.default_type, title, text)

        data: dict[str, Any] = {
            "title": (title or "").strip()[:400],
            "type": opp_type.value,
            "organization": organization,
            "university": take("university"),
            "department": take("department"),
            "location": take("location"),
            "source_url": doc.url,
            "external_key": doc.external_key or take("external_key"),
            "description": text[:20000] or None,
            "deadline": _as_date(take("deadline")) or deadline.value,
            "deadline_type": (deadline_kind.value or "unknown"),
            # A date the source stated outright is verified; one we parsed out of
            # prose keeps whatever confidence the extractor earned.
            "deadline_confidence": 1.0 if _as_date(take("deadline")) else deadline.confidence,
            "deadline_certainty": (
                Certainty.VERIFIED if _as_date(take("deadline")) else deadline.certainty
            ),
            "deadline_source_text": deadline.source_text,
            "pay_text": take("pay", (pay.value or {}).get("text") if pay.value else None),
            "pay_min": (pay.value or {}).get("min") if pay.value else None,
            "pay_max": (pay.value or {}).get("max") if pay.value else None,
            "pay_period": (pay.value or {}).get("period") if pay.value else None,
            # hours.hours is an Evidenced[int]; the column wants the int.
            "hours_per_week": _as_int(take("hours_per_week")) or hours.hours.value,
            "hours_note": hours.note,
            "application_method": take("application_method", method.value if method else None),
            "application_url": take("application_url", apply_url),
            "contact_name": take("contact_name", contact_name),
            "contact_email": take("contact_email", contact_email),
            "documents_required": documents,
            "skills": sorted({slug for slug, _ in taxonomy.match_skills(text)}),
            "requirements": requirements,
            "posted_at": _as_date(take("posted_at")),
            "raw": {"structured": structured} if structured else {},
        }

        # A stated date beats a "rolling" phrase found elsewhere on the page.
        if data["deadline"] is not None and data["deadline_type"] == "unknown":
            data["deadline_type"] = "hard"

        for key, source_field in (
            ("deadline", deadline),
            ("pay", pay),
            ("eligibility", eligibility),
        ):
            provenance.append({"field": key, **source_field.as_field()})

        missing = [k for k in ("documents_required", "application_method") if not data.get(k)]
        if missing and ctx.can_reason and text:
            try:
                filled = self._ask_model(ctx, title, text)
                if filled.documents_required and not data["documents_required"]:
                    data["documents_required"] = filled.documents_required
                if filled.application_method and not data["application_method"]:
                    data["application_method"] = filled.application_method
                if filled.summary:
                    data["description"] = filled.summary
            except LLMUnavailable as exc:
                warnings.append(f"Model pass skipped ({exc}).")
        elif missing:
            warnings.append(
                f"{', '.join(missing)} not stated on the page; left empty rather than guessed."
            )

        data["extraction_confidence"] = self._confidence(data, deadline.confidence)

        # Belt and braces: an Evidenced[...] reaching a scalar column fails deep
        # inside psycopg with an opaque message, so unwrap any that slipped through.
        for key, value in list(data.items()):
            if isinstance(value, Evidenced):
                data[key] = value.value

        return AgentOutcome(
            result=ExtractionResult(data=data, text=text, provenance=provenance),
            warnings=warnings,
        )

    # ------------------------------------------------------------------ #

    def _classify(
        self,
        doc: DiscoveredDocument,
        default: OpportunityType | None,
        title: str,
        text: str,
    ) -> OpportunityType:
        if doc.kind_hint is not None:
            return doc.kind_hint
        if default is not None:
            return default
        blob = f"{title}\n{text[:4000]}".lower()
        if any(h in blob for h in RESEARCH_HINTS):
            explicit = any(
                phrase in blob
                for phrase in ("apply by", "application deadline", "now accepting applications")
            )
            return (
                OpportunityType.RESEARCH_OPENING if explicit else OpportunityType.RESEARCH_OUTREACH
            )
        return OpportunityType.ON_CAMPUS

    def _ask_model(self, ctx: AgentContext, title: str, text: str) -> _LlmFields:
        system = (
            "You read a job or research posting and report only what it actually says. "
            "If the posting does not state a field, return null or an empty list. "
            "Never infer a document requirement that is not written down."
        )
        prompt = f"Posting title: {title}\n\n{text[:8000]}"
        return ctx.llm.complete_json(
            system=system, prompt=prompt, schema=_LlmFields, task="opportunity-extraction"
        ).data

    def _confidence(self, data: dict[str, Any], deadline_confidence: float) -> float:
        """Confidence in the extraction as a whole, not in any one field."""
        score = 0.35
        if data.get("title"):
            score += 0.15
        if data.get("organization"):
            score += 0.1
        if data.get("requirements"):
            score += 0.15
        if data.get("application_url"):
            score += 0.1
        score += 0.15 * deadline_confidence
        return round(min(score, 1.0), 3)


def persist_provenance(
    ctx: AgentContext, opportunity: Opportunity, provenance: list[dict[str, Any]]
) -> None:
    """Write the {value, confidence, source} rows the detail view shows."""
    if opportunity.id is None:
        return
    for entry in provenance:
        name = entry.get("field")
        if not name:
            continue
        row = ctx.db.scalars(
            select(ExtractedField).where(
                ExtractedField.opportunity_id == opportunity.id,
                ExtractedField.field == name,
            )
        ).first()
        if row is None:
            row = ExtractedField(opportunity_id=opportunity.id, field=name)
            ctx.db.add(row)
        row.value = {"value": entry.get("value")}
        row.confidence = float(entry.get("confidence") or 0.0)
        row.certainty = Certainty(entry.get("certainty") or Certainty.UNKNOWN)
        row.method = ExtractionMethod(entry.get("method") or ExtractionMethod.HEURISTIC)
        row.source_text = entry.get("source_text")
        row.source_url = entry.get("source_url") or opportunity.source_url
        row.extractor_version = "extraction-1"
