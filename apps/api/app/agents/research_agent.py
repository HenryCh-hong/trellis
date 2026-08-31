"""Research discovery.

The pipeline the product is really built around:

    interests -> departments -> faculty -> lab site -> recent publications
    -> lab news -> CURRENT direction -> similarity to the student
    -> formal opening vs cold outreach vs watch

Two rules make this different from keyword-matching a faculty bio:

* ``current_direction`` is derived ONLY from evidence inside the recency
  window. If a lab has nothing recent, the direction is empty and its certainty
  is UNKNOWN. We never fall back to the biography, because a 2014 bio is
  exactly the thing that makes students email about work a lab stopped doing.
* OPENING requires a quoted, currently-open, undergraduate-relevant statement
  with a URL. Everything else is OUTREACH (lab is active) or WATCH.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.agents.base import Agent, AgentContext, AgentOutcome
from app.agents.matching_agent import MatchingAgent, MatchRequest
from app.core.config import get_settings
from app.models.enums import (
    Certainty,
    EvidenceKind,
    LeadState,
    OpportunityStatus,
    OpportunityType,
    RunStatus,
    SignalKind,
)
from app.models.opportunity import Opportunity, OpportunitySource
from app.models.ops import SearchRun
from app.models.research import Faculty, Lab, LabSignal, ResearchEvidence
from app.services import taxonomy
from app.services.runs import finish_run, record_step
from app.sources.base import SourceContext
from app.sources.registry import get_adapter

# Phrases that mean a lab is actively looking, as opposed to describing itself.
RECRUITING_OPEN = (
    "we are looking for",
    "we are actively looking",
    "we are recruiting",
    "currently recruiting",
    "openings for",
    "positions available",
    "now accepting applications",
    "join us",
    "join the lab",
    "apply here",
    "apply via",
    "seeking students",
    # An invitation does not have to be phrased as a vacancy. An earlier version
    # of this list missed "please get in touch", and downgraded a lab whose page
    # says "If you're an undergraduate ... please get in touch!" -- which is
    # plainly an open door.
    "get in touch",
    "reach out",
    "contact me",
    "please email",
    "fill this form",
    "fill out this form",
    "interested in joining",
    "happy to work with",
    "welcome applicants",
)
RECRUITING_CLOSED = (
    "not taking new students",
    "not accepting new students",
    "no openings",
    "not currently recruiting",
    "i am not taking",
    "cannot take on additional",
)
UNDERGRAD_TERMS = ("undergraduate", "undergrad", "bachelor", "curis", "b.s. student", "sophomore", "junior")
# Wording that invites undergraduates specifically rather than PhD applicants.
UNDERGRAD_INVITE = (
    "stanford undergraduate",
    "undergraduate students interested",
    "if you are an undergraduate",
    "undergraduate researchers",
    "we work with undergraduate",
    "happy to work with undergraduate",
    "undergraduate and masters",
)
PHD_ONLY = ("prospective phd", "phd applicants", "phd admissions", "graduate admissions")


@dataclass(slots=True)
class ResearchRequest:
    profile: Any
    run: SearchRun
    limit: int = 30
    refresh_labs: bool = True


@dataclass(slots=True)
class ResearchOutcome:
    faculty_seen: int = 0
    leads_created: int = 0
    leads_updated: int = 0
    openings: int = 0
    outreach: int = 0
    watch: int = 0
    failures: list[str] = field(default_factory=list)


class ResearchDiscoveryAgent(Agent[ResearchRequest, ResearchOutcome]):
    name = "research-discovery"
    description = "Finds labs worth contacting, grounded in what they published recently."

    def __init__(self) -> None:
        self._match = MatchingAgent()

    def run(self, ctx: AgentContext, payload: ResearchRequest) -> AgentOutcome[ResearchOutcome]:
        run = payload.run
        profile = payload.profile
        result = ResearchOutcome()
        settings = get_settings()

        interests = [i.label for i in getattr(profile, "interests", [])]
        record_step(
            run,
            "plan",
            f"Mapping {len(interests)} interest(s) onto Stanford departments and labs: "
            f"{', '.join(interests[:6]) or 'none set'}.",
        )

        faculty_rows = list(ctx.db.scalars(select(Faculty).limit(payload.limit)))
        if not faculty_rows:
            faculty_rows = self._discover_faculty(ctx, profile, run, result)

        result.faculty_seen = len(faculty_rows)
        record_step(run, "faculty", f"Assessing {len(faculty_rows)} faculty record(s).")

        source_row = ctx.db.scalars(
            select(OpportunitySource).where(OpportunitySource.slug == "stanford_cs_faculty")
        ).first()

        for faculty in faculty_rows:
            evidence = sorted(
                faculty.evidence, key=lambda e: (e.year or 0), reverse=True
            )
            direction, basis, certainty = self._current_direction(evidence, ctx, settings)
            # Never trade a specific direction for a generic one. What this agent
            # can derive are canonical topic labels ("Large Language Models");
            # a harvested or model-written direction reads like
            # "Auditing what AI agents actually do to human work", which is far
            # more useful to a student deciding whether to email. Only fill an
            # empty direction, or replace one the evidence no longer supports.
            existing = list(faculty.current_direction or [])
            existing_is_specific = any(len(phrase) > 40 for phrase in existing)
            if direction and not (existing_is_specific and faculty.is_active):
                faculty.current_direction = direction
                faculty.current_direction_basis = basis
                faculty.current_direction_certainty = certainty
            elif not direction and not existing:
                faculty.current_direction = []
                faculty.current_direction_basis = None
                faculty.current_direction_certainty = Certainty.UNKNOWN
            faculty.last_evidence_year = evidence[0].year if evidence else None
            faculty.evidence_count = len(evidence)
            faculty.is_active = self._is_active(evidence, ctx, settings)
            faculty.last_checked_at = datetime.now(UTC)

            state = self._classify(faculty, evidence, ctx, settings)
            if state == LeadState.OPENING:
                result.openings += 1
            elif state == LeadState.OUTREACH:
                result.outreach += 1
            else:
                result.watch += 1

            opp, created = self._upsert_lead(ctx, faculty, state, source_row)
            result.leads_created += int(created)
            result.leads_updated += int(not created)
            if profile is not None:
                self._match.run(ctx, MatchRequest(profile=profile, opportunity=opp, polish=False))

        ctx.db.flush()
        run.created_count = result.leads_created
        run.updated_count = result.leads_updated
        run.stats = {
            "openings": result.openings,
            "outreach": result.outreach,
            "watch": result.watch,
        }
        record_step(
            run,
            "summary",
            f"{result.openings} formal opening(s), {result.outreach} outreach lead(s), "
            f"{result.watch} to watch.",
        )
        finish_run(
            ctx.db, run, status=RunStatus.PARTIAL if result.failures else None
        )
        return AgentOutcome(result=result, warnings=result.failures)

    # ------------------------------------------------------------------ #

    def _discover_faculty(
        self, ctx: AgentContext, profile: Any, run: SearchRun, result: ResearchOutcome
    ) -> list[Faculty]:
        """Live discovery, used when the database has no faculty yet."""
        try:
            adapter = get_adapter("stanford_cs_faculty")
        except (KeyError, LookupError):
            result.failures.append("stanford_cs_faculty adapter missing")
            return []
        source_ctx = SourceContext(
            university=getattr(profile, "university", "Stanford University"),
            topics=[i.label for i in getattr(profile, "interests", [])],
            limit=40,
        )
        rows: list[Faculty] = []
        try:
            for doc in adapter.discover(source_ctx):
                data = doc.structured or {}
                name = data.get("name")
                if not name:
                    continue
                slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
                existing = ctx.db.scalars(select(Faculty).where(Faculty.slug == slug)).first()
                if existing is None:
                    existing = Faculty(
                        slug=slug,
                        name=name,
                        title=data.get("title"),
                        university=source_ctx.university,
                        department=data.get("department") or "Computer Science",
                        faculty_url=data.get("profile_url") or doc.url,
                        first_seen_at=datetime.now(UTC),
                    )
                    ctx.db.add(existing)
                    ctx.db.flush()
                rows.append(existing)
        except Exception as exc:
            result.failures.append(f"faculty discovery: {exc}")
            record_step(run, "faculty", f"Faculty directory failed: {exc}", "error")
        return rows

    def _current_direction(
        self, evidence: list[ResearchEvidence], ctx: AgentContext, settings
    ) -> tuple[list[str], str | None, Certainty]:
        window = settings.recency_window_months
        cutoff_year = ctx.today.year - max(1, window // 12)
        recent = [e for e in evidence if (e.year or 0) >= cutoff_year]
        if not recent:
            # Deliberately empty rather than recycled from an old bio.
            return ([], None, Certainty.UNKNOWN)

        weights: dict[str, float] = {}
        for item in recent:
            blob = f"{item.title} {item.summary or ''}"
            recency = 1.0 if (item.year or 0) >= ctx.today.year else 0.6
            for slug, weight in taxonomy.match_topics(blob):
                weights[slug] = weights.get(slug, 0.0) + weight * recency
            for topic in item.topics or []:
                slug = taxonomy.resolve_topic(topic)
                if slug:
                    weights[slug] = weights.get(slug, 0.0) + recency

        ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:5]
        direction = [taxonomy.topic_label(slug) for slug, _ in ranked]
        cited = ", ".join(f"{e.title[:60]} ({e.year})" for e in recent[:3])
        basis = (
            f"Inferred from {len(recent)} item(s) since {cutoff_year}: {cited}."
            if direction
            else None
        )
        # Several recent, dated items is a solid basis; one is a hint.
        certainty = (
            Certainty.LIKELY
            if len(recent) >= 3 and direction
            else (Certainty.INFERRED if direction else Certainty.UNKNOWN)
        )
        return (direction, basis, certainty)

    def _is_active(self, evidence: list[ResearchEvidence], ctx: AgentContext, settings) -> bool:
        cutoff = ctx.today.year - max(1, settings.recency_window_months // 12)
        return any((e.year or 0) >= cutoff for e in evidence)

    def _classify(
        self,
        faculty: Faculty,
        evidence: list[ResearchEvidence],
        ctx: AgentContext,
        settings,
    ) -> LeadState:
        recruiting = [s for s in faculty.signals if s.kind == SignalKind.RECRUITING]
        undergrad = [s for s in faculty.signals if s.kind == SignalKind.UNDERGRAD_PRESENCE]

        for signal in recruiting:
            statement = (signal.statement or signal.label or "").lower()
            if any(term in statement for term in RECRUITING_CLOSED):
                return LeadState.WATCH if not faculty.is_active else LeadState.OUTREACH

        # A signal a human verified, that names undergraduates and cites a page,
        # is stronger evidence than any phrase list. Trust it directly rather
        # than re-deriving it from keywords that will always be incomplete.
        for signal in recruiting:
            statement = (signal.statement or signal.label or "").lower()
            if (
                signal.certainty == Certainty.VERIFIED
                and signal.source_url
                and any(term in statement for term in UNDERGRAD_TERMS)
                and not any(term in statement for term in RECRUITING_CLOSED)
            ):
                return LeadState.OPENING

        # OPENING needs all three: open language, undergraduate relevance, a source.
        for signal in recruiting:
            statement = (signal.statement or signal.label or "").lower()
            if not signal.source_url:
                continue
            if not any(term in statement for term in RECRUITING_OPEN):
                continue
            invites_undergrads = any(term in statement for term in UNDERGRAD_INVITE) or (
                any(term in statement for term in UNDERGRAD_TERMS)
                and not all(term in statement for term in PHD_ONLY)
            )
            if invites_undergrads or any(
                s.certainty == Certainty.VERIFIED
                and any(t in (s.statement or s.label or "").lower() for t in UNDERGRAD_INVITE)
                for s in undergrad
            ):
                return LeadState.OPENING

        if faculty.is_active:
            return LeadState.OUTREACH
        return LeadState.WATCH

    def _upsert_lead(
        self,
        ctx: AgentContext,
        faculty: Faculty,
        state: LeadState,
        source: OpportunitySource | None,
    ) -> tuple[Opportunity, bool]:
        external_key = f"faculty:{faculty.slug}"
        opp = ctx.db.scalars(
            select(Opportunity).where(Opportunity.external_key == external_key)
        ).first()
        created = opp is None
        lab: Lab | None = faculty.labs[0] if faculty.labs else None

        if opp is None:
            opp = Opportunity(
                title=f"Undergraduate research — {lab.name if lab else faculty.name}",
                type=OpportunityType.RESEARCH_OUTREACH,
                status=OpportunityStatus.NEW,
                external_key=external_key,
                first_seen_at=datetime.now(UTC),
            )
            ctx.db.add(opp)

        opp.type = (
            OpportunityType.RESEARCH_OPENING
            if state == LeadState.OPENING
            else OpportunityType.RESEARCH_OUTREACH
        )
        opp.organization = lab.name if lab else (faculty.department or faculty.university)
        opp.university = faculty.university
        opp.department = faculty.department
        opp.faculty_id = faculty.id
        opp.lab_id = lab.id if lab else None
        opp.source_url = (lab.url if lab else None) or faculty.faculty_url
        opp.contact_name = faculty.name
        opp.contact_email = faculty.email if faculty.email_certainty != Certainty.UNKNOWN else None
        opp.last_checked_at = datetime.now(UTC)
        if source is not None:
            opp.source_id = source.id
        ctx.db.flush()
        return opp, created


def lead_state_for(opportunity: Opportunity) -> LeadState:
    """The lead state the UI shows, derived from the opportunity type + signals."""
    if opportunity.type == OpportunityType.RESEARCH_OPENING:
        return LeadState.OPENING
    if opportunity.type == OpportunityType.RESEARCH_OUTREACH:
        faculty = opportunity.faculty
        if faculty is not None and not faculty.is_active:
            return LeadState.WATCH
        return LeadState.OUTREACH
    return LeadState.WATCH


def undergrad_summary(signals: list[LabSignal]) -> tuple[str, Certainty]:
    """One honest sentence about undergraduate involvement."""
    relevant = [s for s in signals if s.kind == SignalKind.UNDERGRAD_PRESENCE]
    if not relevant:
        return ("No undergraduate signal found", Certainty.UNKNOWN)
    best = max(
        relevant,
        key=lambda s: {
            Certainty.VERIFIED: 3,
            Certainty.LIKELY: 2,
            Certainty.INFERRED: 1,
            Certainty.UNKNOWN: 0,
        }[s.certainty],
    )
    return (best.label, best.certainty)


def evidence_kind_label(kind: EvidenceKind) -> str:
    return {
        EvidenceKind.PUBLICATION: "Paper",
        EvidenceKind.PROJECT: "Project",
        EvidenceKind.NEWS: "Lab news",
        EvidenceKind.GRANT: "Grant",
        EvidenceKind.COURSE: "Course",
        EvidenceKind.TALK: "Talk",
        EvidenceKind.STUDENT_PROJECT: "Student project",
    }[kind]
