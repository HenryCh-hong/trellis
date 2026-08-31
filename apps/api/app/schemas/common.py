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


class OpportunityFacets(Schema):
    types: list[FacetValue] = Field(default_factory=list)
    statuses: list[FacetValue] = Field(default_factory=list)
    sources: list[FacetValue] = Field(default_factory=list)
    topics: list[FacetValue] = Field(default_factory=list)
    departments: list[FacetValue] = Field(default_factory=list)


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
    is_new: bool = False
    has_application: bool = False
    application_id: uuid.UUID | None = None
    has_reminder: bool = False
    #: Touches something the student actually said they care about.
    matches_interests: bool = False
    #: Why, in the student's own words. Shown so the filter can be interrogated.
    relevance_reason: str | None = None


class OpportunityListResponse(Schema):
    items: list[OpportunityListItem]
    total: int
    limit: int
    offset: int
    facets: OpportunityFacets


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


class ResearchContext(Schema):
    faculty: FacultyRef
    lab: LabRef | None = None
    lead_state: str
    evidence: list[ResearchEvidenceItem] = Field(default_factory=list)
    signals: list[LabSignalItem] = Field(default_factory=list)
    topics: list[TopicRef] = Field(default_factory=list)
    overlap: list[TopicOverlap] = Field(default_factory=list)
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
    urgency: str = "unknown"


class ResearchFacets(Schema):
    departments: list[FacetValue] = Field(default_factory=list)
    topics: list[FacetValue] = Field(default_factory=list)
    states: list[FacetValue] = Field(default_factory=list)


class ResearchLeadsResponse(Schema):
    items: list[ResearchLead]
    total: int
    facets: ResearchFacets
