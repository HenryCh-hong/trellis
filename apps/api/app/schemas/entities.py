"""Profile, resume, application, reminder and ops response models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import Field

from app.schemas.common import (
    ApplicationReadiness,
    OpportunityListItem,
    ResumeRecommendationItem,
    Schema,
)

# --------------------------------------------------------------------- profile


class ProfileSkillItem(Schema):
    id: uuid.UUID
    slug: str
    label: str
    category: str | None = None
    origin: str = "user"
    proficiency: str | None = None
    evidence: str | None = None


class ProfileInterestItem(Schema):
    id: uuid.UUID
    label: str
    topic_slug: str | None = None
    weight: float = 1.0
    note: str | None = None


class CourseworkItem(Schema):
    id: uuid.UUID
    code: str | None = None
    title: str
    term: str | None = None
    grade: str | None = None
    topics: list[str] = Field(default_factory=list)


class ExperienceItem(Schema):
    id: uuid.UUID
    organization: str
    role: str
    kind: str | None = None
    started_on: date | None = None
    ended_on: date | None = None
    summary: str | None = None
    highlights: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    origin: str = "user"


class StudentProfileOut(Schema):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    display_name: str | None = None
    university: str
    campus: str | None = None
    major: str | None = None
    secondary_major: str | None = None
    degree: str | None = None
    graduation_year: int | None = None
    gpa: float | None = None
    gpa_is_public: bool = False
    work_authorization: str = "not_specified"
    work_authorization_note: str | None = None
    hours_per_week_min: int | None = None
    hours_per_week_max: int | None = None
    preferred_job_types: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    availability_note: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)
    onboarding_completed_at: datetime | None = None
    skills: list[ProfileSkillItem] = Field(default_factory=list)
    interests: list[ProfileInterestItem] = Field(default_factory=list)
    coursework: list[CourseworkItem] = Field(default_factory=list)
    experiences: list[ExperienceItem] = Field(default_factory=list)
    resume_count: int = 0


class ProfilePatch(Schema):
    display_name: str | None = None
    university: str | None = None
    campus: str | None = None
    major: str | None = None
    secondary_major: str | None = None
    degree: str | None = None
    graduation_year: int | None = None
    gpa: float | None = None
    gpa_is_public: bool | None = None
    work_authorization: str | None = None
    work_authorization_note: str | None = None
    hours_per_week_min: int | None = None
    hours_per_week_max: int | None = None
    preferred_job_types: list[str] | None = None
    preferred_locations: list[str] | None = None
    keywords: list[str] | None = None
    availability_note: str | None = None
    preferences: dict[str, Any] | None = None


class LabelIn(Schema):
    label: str
    weight: float = 1.0


class CourseIn(Schema):
    code: str | None = None
    title: str
    term: str | None = None
    grade: str | None = None


class OnboardingIn(Schema):
    email: str | None = None
    display_name: str | None = None
    university: str = "Stanford University"
    campus: str | None = None
    major: str | None = None
    degree: str | None = None
    graduation_year: int | None = None
    interests: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    job_types: list[str] = Field(default_factory=list)
    hours_per_week_min: int | None = None
    hours_per_week_max: int | None = None
    run_discovery: bool = True


# ---------------------------------------------------------------------- resume


class ResumeItem(Schema):
    id: uuid.UUID
    label: str
    original_filename: str
    size_bytes: int
    page_count: int | None = None
    is_default: bool = False
    parse_status: str = "pending"
    parse_error: str | None = None
    detected_skills: list[str] = Field(default_factory=list)
    detected_topics: list[str] = Field(default_factory=list)
    highlight_count: int = 0
    created_at: datetime


class ResumeHighlightItem(Schema):
    id: uuid.UUID
    section: str | None = None
    text: str
    skills: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class ResumeDetail(ResumeItem):
    text_preview: str | None = None
    highlights: list[ResumeHighlightItem] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


# ----------------------------------------------------------------- application


class ApplicationDocumentItem(Schema):
    id: uuid.UUID
    kind: str
    label: str
    status: str
    required: bool = True
    resume_id: uuid.UUID | None = None
    filename: str | None = None
    note: str | None = None
    source_text: str | None = None


class ApplicationAnswerItem(Schema):
    id: uuid.UUID
    question: str
    field_key: str | None = None
    answer: str | None = None
    source: str = "user"
    profile_field: str | None = None
    #: AnswerCategory — what Trellis is allowed to do with this question.
    category: str = "unknown"
    is_sensitive: bool = False
    sensitive_category: str | None = None
    reuse_approved: bool = False
    needs_user_input: bool = True
    max_length: int | None = None


class ApplicationEventItem(Schema):
    id: uuid.UUID
    kind: str
    from_status: str | None = None
    to_status: str | None = None
    actor: str
    note: str | None = None
    created_at: datetime


class KnownField(Schema):
    key: str
    label: str
    value: str | None = None


class ApplicationKit(Schema):
    id: uuid.UUID
    status: str
    opportunity: OpportunityListItem
    application_url: str | None = None
    application_method: str | None = None
    resume_id: uuid.UUID | None = None
    resume_label: str | None = None
    resume_locked_by_user: bool = False
    resume_recommendations: list[ResumeRecommendationItem] = Field(default_factory=list)
    documents: list[ApplicationDocumentItem] = Field(default_factory=list)
    answers: list[ApplicationAnswerItem] = Field(default_factory=list)
    known_profile_fields: list[KnownField] = Field(default_factory=list)
    readiness: ApplicationReadiness
    blocking: list[str] = Field(default_factory=list)
    ready: bool = False
    prepared_at: datetime | None = None
    approved_at: datetime | None = None
    submitted_at: datetime | None = None
    notes: str | None = None
    events: list[ApplicationEventItem] = Field(default_factory=list)


class SubmissionPlanField(Schema):
    key: str
    label: str
    value: str | None = None
    source: str
    is_sensitive: bool = False
    will_submit: bool = True
    note: str | None = None


class SubmissionPlan(Schema):
    application_id: str
    target_url: str | None = None
    method: str | None = None
    fields: list[SubmissionPlanField] = Field(default_factory=list)
    attachments: list[dict[str, str]] = Field(default_factory=list)
    withheld: list[dict[str, str]] = Field(default_factory=list)
    manual_steps: list[str] = Field(default_factory=list)
    requires_user_at: list[str] = Field(default_factory=list)
    payload_hash: str
    approved: bool = False


class ApplicationCreate(Schema):
    opportunity_id: uuid.UUID


class ApplicationPatch(Schema):
    status: str | None = None
    resume_id: uuid.UUID | None = None
    notes: str | None = None


class AnswerPatch(Schema):
    answer: str | None = None
    reuse_approved: bool | None = None


class ApprovalIn(Schema):
    payload_hash: str


# -------------------------------------------------------------------- overview


class ActionItem(Schema):
    opportunity: OpportunityListItem
    reason: str
    blocking: list[str] = Field(default_factory=list)
    resume_ready: bool = False
    application_id: uuid.UUID | None = None
    cta: str


class PipelineStage(Schema):
    status: str
    label: str
    count: int


class SearchRunSummary(Schema):
    id: uuid.UUID
    kind: str
    status: str
    trigger: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # The six buckets every document the run looked at lands in, plus the
    # feedback-suppression count. Reported in full so "we found nothing" and
    # "we threw things away" can never look like the same run.
    created_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    expired_count: int = 0
    held_count: int = 0
    skipped_count: int = 0
    suppressed_count: int = 0
    documents_fetched: int = 0
    sources_attempted: list[str] = Field(default_factory=list)
    error: str | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)


class OverviewCounts(Schema):
    total: int = 0
    saved: int = 0
    lab_leads: int = 0
    verified_openings: int = 0
    outreach: int = 0
    research_programs: int = 0
    unread: int = 0


class Overview(Schema):
    profile_name: str | None = None
    university: str
    action_needed: list[ActionItem] = Field(default_factory=list)
    due_soon: list[OpportunityListItem] = Field(default_factory=list)
    best_matches: list[OpportunityListItem] = Field(default_factory=list)
    #: Things you marked interested. Small, and only ever what you chose
    #: yourself — the Overview never promotes a row you did not point at.
    interested: list[OpportunityListItem] = Field(default_factory=list)
    research_leads: list[Any] = Field(default_factory=list)
    recent_discoveries: list[OpportunityListItem] = Field(default_factory=list)
    pipeline: list[PipelineStage] = Field(default_factory=list)
    counts: OverviewCounts = Field(default_factory=OverviewCounts)
    last_run: SearchRunSummary | None = None
    needs_onboarding: bool = False


# ------------------------------------------------------------------- searching


class SavedSearchItem(Schema):
    id: uuid.UUID
    name: str
    kind: str
    query: str | None = None
    source_slugs: list[str] = Field(default_factory=list)
    enabled: bool = True
    last_run_at: datetime | None = None
    filters: dict[str, Any] = Field(default_factory=dict)


class SavedSearchIn(Schema):
    name: str
    kind: str = "jobs"
    query: str | None = None
    source_slugs: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)


class DiscoverIn(Schema):
    kind: str = "jobs"


class ImportUrlIn(Schema):
    url: str


# -------------------------------------------------------------------- feedback


class FeedbackIn(Schema):
    """interested | not_relevant | already_applied | hidden.

    ``reason`` is accepted only alongside ``not_relevant``; anything else is a
    400 rather than a silently dropped field.
    """

    signal: str
    reason: str | None = None
    note: str | None = None


# ------------------------------------------------------------------- reminders


class ReminderItem(Schema):
    id: uuid.UUID
    title: str
    due_on: date | None = None
    offsets_days: list[int] = Field(default_factory=list)
    provider: str = "ics"
    status: str = "pending"
    opportunity_id: uuid.UUID | None = None
    url: str | None = None
    documents: list[str] = Field(default_factory=list)
    notes: str | None = None


class ReminderIn(Schema):
    opportunity_id: uuid.UUID
    provider: str = "ics"
    offsets_days: list[int] | None = None
    notes: str | None = None


class ReminderProviderInfo(Schema):
    slug: str
    label: str
    description: str
    requires_user_action: bool = True


# -------------------------------------------------------------------- settings


class DataSourceInfo(Schema):
    slug: str
    name: str
    kind: str
    base_url: str | None = None
    requires_auth: bool = False
    is_public: bool = True
    is_mocked: bool = False
    enabled: bool = True
    last_run_at: datetime | None = None
    opportunity_count: int = 0
    notes: str | None = None


class ProvenanceInfo(Schema):
    key: str
    label: str
    generated_at: datetime | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class HandshakeImportItem(Schema):
    """One job the extension read from the student's own logged-in tab."""

    url: str
    title: str
    employer: str | None = None
    location: str | None = None
    job_type: str | None = None
    pay: str | None = None
    posted_at: str | None = None
    apply_by: str | None = None
    description: str | None = None
    application_method: str | None = None
    external_key: str | None = None


class HandshakeImportIn(Schema):
    items: list[HandshakeImportItem]
    captured_at: datetime | None = None
