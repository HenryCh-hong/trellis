"""Response models.

These mirror ``apps/web/src/lib/types.ts`` field for field. The TypeScript
contract is the fixed side: if these disagree, this file is wrong.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class EvidencedField(Schema):
    value: Any = None
    confidence: float = 0.0
    certainty: str = "unknown"
    method: str = "heuristic"
    source_text: str | None = None
    source_url: str | None = None


class TopicRef(Schema):
    slug: str
    label: str
    weight: float | None = None
    origin: str | None = None


class SourceRef(Schema):
    slug: str
    name: str
    kind: str
    base_url: str | None = None
    requires_auth: bool = False
    is_public: bool = True
    is_mocked: bool = False


class ScoreComponent(Schema):
    key: str
    label: str
    score: float
    weight: float
    weighted: float
    reason: str
    detail: list[str] = Field(default_factory=list)


class MatchDetail(Schema):
    fit_score: float
    confidence: float
    model: str
    breakdown: list[ScoreComponent] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    explanation: str | None = None
    why_interesting: str | None = None
    recommendation: str | None = None
    recommended_resume_id: uuid.UUID | None = None
    computed_at: datetime | None = None


class RequirementOut(Schema):
    id: uuid.UUID
    text: str
    kind: str
    category: str | None = None
    source_text: str | None = None
    source_url: str | None = None
    confidence: float = 0.0
    match_state: str = "unknown"
    match_reason: str | None = None


class Paginated[T](Schema):
    items: list[T]
    total: int
    limit: int
    offset: int


class FacetValue(Schema):
    value: str
    label: str | None = None
    count: int


class SearchTopicHit(Schema):
    """One topic a query was expanded onto, and how far it is from what was
    typed: exact | alias | label | related."""

    slug: str
    label: str
    tier: str
    weight: float


class SearchExplain(Schema):
    """How the server read the query. Present only when ``q`` was sent."""

    query: str
    terms: list[str] = Field(default_factory=list)
    topics: list[SearchTopicHit] = Field(default_factory=list)
    #: Opportunity types the query asked for ("part-time" is a kind, not a topic).
    types: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class OpportunityFacets(Schema):
    types: list[FacetValue] = Field(default_factory=list)
    statuses: list[FacetValue] = Field(default_factory=list)
    sources: list[FacetValue] = Field(default_factory=list)
    topics: list[FacetValue] = Field(default_factory=list)
    departments: list[FacetValue] = Field(default_factory=list)
    #: ok / held. The only facet counted across both sides of the gate, because
    #: it is the control that crosses it.
    confidence: list[FacetValue] = Field(default_factory=list)


class FeedbackOut(Schema):
    """The student's current signal on one opportunity, or absent.

    ``reason`` is only ever populated for ``not_relevant``. It travels to the
    client so the control can show what was chosen — nothing in the product
    reads it in aggregate.
    """

    signal: str
    reason: str | None = None
    note: str | None = None
    created_at: datetime


class OpportunityListItem(Schema):
    id: uuid.UUID
    title: str
    type: str
    status: str
    organization: str | None = None
    department: str | None = None
    lab_name: str | None = None
    pi_name: str | None = None
    source: SourceRef | None = None
    source_url: str | None = None
    location: str | None = None
    pay_text: str | None = None
    hours_per_week: int | None = None
    hours_note: str | None = None
    deadline: date | None = None
    deadline_type: str = "unknown"
    #: Recorded lifecycle: hard | rolling | unknown | expired. Distinct from
    #: ``urgency``, which is computed on read — this one was written down.
    deadline_state: str = "unknown"
    deadline_certainty: str = "unknown"
    days_until_deadline: int | None = None
    urgency: str = "unknown"
    eligibility: str = "unclear"
    fit_score: float | None = None
    fit_confidence: float | None = None
    recommendation: str | None = None
    lead_state: str | None = None
    topics: list[TopicRef] = Field(default_factory=list)
    first_seen_at: datetime | None = None
    last_checked_at: datetime | None = None
    #: "live" | "gone" — whether the posting is still on its source.
    source_status: str = "live"
    source_status_at: datetime | None = None
    is_new: bool = False
    has_application: bool = False
    application_id: uuid.UUID | None = None
    has_reminder: bool = False
    #: Touches something the student actually said they care about.
    matches_interests: bool = False
    #: Why, in the student's own words. Shown so the filter can be interrogated.
    relevance_reason: str | None = None
    #: "held" means the extraction was too thin to recommend. Never hidden from
    #: the client: a row that arrives held must be labelled as such.
    confidence_state: str = "ok"
    #: What was missing, in one sentence. Only ever set on a held row.
    confidence_reason: str | None = None
    #: What you said about this one: interested / not relevant / already applied
    #: / hidden. Null when you have said nothing.
    feedback: FeedbackOut | None = None
    #: Relevance to the ``q`` that produced this list. Null when there was none.
    search_score: float | None = None
    #: Why this row answers that query, in order of weight.
    search_reasons: list[str] = Field(default_factory=list)


class OpportunityListResponse(Schema):
    items: list[OpportunityListItem]
    total: int
    limit: int
    offset: int
    facets: OpportunityFacets
    #: How many rows these same filters matched but were dropped for being
    #: hidden. Stated so the omission is visible and one click reversible.
    hidden_count: int = 0
    #: How ``q`` was interpreted. Null when no query was sent.
    search: SearchExplain | None = None


class ResearchEvidenceItem(Schema):
    id: uuid.UUID
    kind: str
    title: str
    summary: str | None = None
    year: int | None = None
    url: str | None = None
    venue: str | None = None
    authors: list[str] = Field(default_factory=list)


class LabSignalItem(Schema):
    kind: str
    label: str
    certainty: str
    statement: str | None = None
    source_url: str | None = None
    note: str | None = None


class FacultyRef(Schema):
    id: uuid.UUID
    slug: str
    name: str
    title: str | None = None
    department: str | None = None
    university: str
    faculty_url: str | None = None
    email: str | None = None
    email_certainty: str = "unknown"
    email_source_url: str | None = None
    current_direction: list[str] = Field(default_factory=list)
    current_direction_basis: str | None = None
    current_direction_certainty: str = "unknown"
    last_evidence_year: int | None = None
    evidence_count: int = 0
    is_active: bool = False
    source_urls: list[str] = Field(default_factory=list)


class LabRef(Schema):
    id: uuid.UUID
    name: str
    slug: str
    url: str | None = None
    department: str | None = None
    description: str | None = None
    news_url: str | None = None
    people_url: str | None = None
    join_url: str | None = None


class TopicOverlap(Schema):
    topic: str
    why: str
    evidence_year: int | None = None
    evidence_title: str | None = None
    evidence_url: str | None = None


class FitOverlapItem(Schema):
    """An interest the student named that this lab's work demonstrably touches."""

    label: str
    kind: str = "interest"
    evidence: str
    source_url: str | None = None


class FitBackgroundItem(Schema):
    """Something the student already has. Only ever a profile row or resume line."""

    label: str
    kind: str
    detail: str | None = None
    #: The uploaded resume this was read from. Always set when ``verbatim``.
    resume: str | None = None
    #: ``detail`` is the student's own words, character for character.
    verbatim: bool = False


class FitGapItem(Schema):
    label: str
    #: True only for a stated hard requirement the student does not meet.
    blocking: bool = False
    note: str


class FitBreakdown(Schema):
    strong_overlap: list[FitOverlapItem] = Field(default_factory=list)
    relevant_background: list[FitBackgroundItem] = Field(default_factory=list)
    potential_gaps: list[FitGapItem] = Field(default_factory=list)
    resumes_read: list[str] = Field(default_factory=list)
    #: Set when there was no readable resume, so a short list is never silent.
    background_note: str | None = None


class LeadStateSignalItem(Schema):
    """One specific, sourced reason a lead is in the state it is in."""

    key: str
    label: str
    certainty: str
    source_url: str | None = None
    detail: str | None = None


class DirectionEvidenceItem(Schema):
    id: uuid.UUID
    year: int | None = None
    kind: str
    title: str
    url: str | None = None
    #: Which words this item and the direction actually share. Derived, never written.
    why: str


class DirectionClaimItem(Schema):
    """A current direction together with the recent work that backs it.

    A direction with no surviving supporting evidence is absent from this list
    rather than present-and-empty: an unsupported claim is not shown at all.
    """

    direction: str
    certainty: str
    evidence: list[DirectionEvidenceItem] = Field(default_factory=list)


class WhyNowItem(Schema):
    """A timing signal that real evidence supports, or the field is null."""

    statement: str
    evidence_ids: list[uuid.UUID] = Field(default_factory=list)
    certainty: str


class OutreachCitationItem(Schema):
    """One fact the draft leans on, so it can be checked before anything is sent."""

    label: str
    detail: str
    source_url: str | None = None
    side: str = "research"


class OutreachDraftOut(Schema):
    subject: str | None = None
    body: str | None = None
    word_count: int = 0
    research_citations: list[OutreachCitationItem] = Field(default_factory=list)
    student_citations: list[OutreachCitationItem] = Field(default_factory=list)
    #: Set when Trellis will not draft. Shown instead of an email, never beside one.
    refusal: str | None = None
    todos: list[str] = Field(default_factory=list)


class ResearchContext(Schema):
    faculty: FacultyRef
    lab: LabRef | None = None
    lead_state: str
    lead_state_signals: list[LeadStateSignalItem] = Field(default_factory=list)
    directions: list[DirectionClaimItem] = Field(default_factory=list)
    why_now: WhyNowItem | None = None
    evidence: list[ResearchEvidenceItem] = Field(default_factory=list)
    signals: list[LabSignalItem] = Field(default_factory=list)
    topics: list[TopicRef] = Field(default_factory=list)
    overlap: list[TopicOverlap] = Field(default_factory=list)
    fit: FitBreakdown | None = None
    suggested_next_step: str | None = None
    opening_statement: str | None = None
    opening_source_url: str | None = None


class ResumeRecommendationItem(Schema):
    resume_id: uuid.UUID
    resume_label: str
    score: float
    rank: int
    matched_strengths: list[str] = Field(default_factory=list)
    weak_or_missing: list[str] = Field(default_factory=list)
    emphasize: list[dict[str, str]] = Field(default_factory=list)
    rationale: str | None = None


class ReadinessItem(Schema):
    """One line of the "Can I apply right now?" list."""

    key: str
    label: str
    #: ReadinessState — ready | attention | blocked | unknown.
    state: str
    detail: str
    note: str | None = None


class ApplicationReadiness(Schema):
    """The same answer on the opportunity panel and on the kit page.

    ``cta`` is only ever "Continue preparation" or "Review application".
    Trellis does not submit, so it never offers "Apply".
    """

    ready: bool = False
    cta: str
    #: "prepare" (open or create the kit) or "review" (open the review panel).
    cta_action: str
    items: list[ReadinessItem] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    #: LinkVerification — verified | unverified | not_found.
    application_link: str = "not_found"
    application_link_note: str | None = None
    application_url: str | None = None
    has_application: bool = False
    application_id: uuid.UUID | None = None


class OpportunityDetail(OpportunityListItem):
    description: str | None = None
    application_method: str | None = None
    application_url: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    requirements: list[RequirementOut] = Field(default_factory=list)
    preferred: list[RequirementOut] = Field(default_factory=list)
    inferred: list[RequirementOut] = Field(default_factory=list)
    documents_required: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    eligibility_reasons: list[str] = Field(default_factory=list)
    extraction_confidence: float = 0.0
    match: MatchDetail | None = None
    fields: dict[str, EvidencedField] = Field(default_factory=dict)
    research: ResearchContext | None = None
    resume_recommendations: list[ResumeRecommendationItem] = Field(default_factory=list)
    #: "Can I apply right now?" — the same computation the kit page renders.
    readiness: ApplicationReadiness
    notes: str | None = None


class ResearchLead(Schema):
    opportunity_id: uuid.UUID
    faculty: FacultyRef
    lab: LabRef | None = None
    lead_state: str
    fit_score: float | None = None
    fit_confidence: float | None = None
    topics: list[TopicRef] = Field(default_factory=list)
    overlap: list[TopicOverlap] = Field(default_factory=list)
    latest_evidence: ResearchEvidenceItem | None = None
    evidence_count: int = 0
    signals: list[LabSignalItem] = Field(default_factory=list)
    status: str = "new"
    deadline: date | None = None
    deadline_state: str = "unknown"
    urgency: str = "unknown"
    #: Relevance to the ``q`` that produced this list. Null when there was none.
    search_score: float | None = None
    #: Why this lead answers that query, in order of weight.
    search_reasons: list[str] = Field(default_factory=list)


class ResearchFacets(Schema):
    departments: list[FacetValue] = Field(default_factory=list)
    topics: list[FacetValue] = Field(default_factory=list)
    states: list[FacetValue] = Field(default_factory=list)


class ResearchLeadsResponse(Schema):
    items: list[ResearchLead]
    total: int
    facets: ResearchFacets
    #: How ``q`` was interpreted. Null when no query was sent.
    search: SearchExplain | None = None
