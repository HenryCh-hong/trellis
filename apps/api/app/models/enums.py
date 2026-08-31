"""Controlled vocabularies.

These are stored as VARCHAR + CHECK (``native_enum=False``) rather than native
PostgreSQL enums: adding a value later is then a cheap constraint change rather
than an ``ALTER TYPE`` migration, which matters for a product whose taxonomy is
still moving.
"""

from __future__ import annotations

from enum import StrEnum


class OpportunityType(StrEnum):
    ON_CAMPUS = "on_campus"
    PART_TIME = "part_time"
    RESEARCH_OPENING = "research_opening"
    RESEARCH_OUTREACH = "research_outreach"


class DeadlineType(StrEnum):
    HARD = "hard"
    ROLLING = "rolling"
    UNKNOWN = "unknown"


class OpportunityStatus(StrEnum):
    """Single pipeline status shown in the UI.

    ``applications`` owns the transitions from PREPARING onwards and writes
    through to the opportunity so the list view has one sortable status column.
    """

    NEW = "new"
    SAVED = "saved"
    PREPARING = "preparing"
    READY_TO_APPLY = "ready_to_apply"
    APPLYING = "applying"
    SUBMITTED = "submitted"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    ARCHIVED = "archived"


ACTIVE_PIPELINE_STATUSES = (
    OpportunityStatus.PREPARING,
    OpportunityStatus.READY_TO_APPLY,
    OpportunityStatus.APPLYING,
    OpportunityStatus.SUBMITTED,
    OpportunityStatus.INTERVIEW,
)


class EligibilityState(StrEnum):
    ELIGIBLE = "eligible"
    LIKELY_ELIGIBLE = "likely_eligible"
    UNCLEAR = "unclear"
    INELIGIBLE = "ineligible"


class Certainty(StrEnum):
    """How much the UI is allowed to assert a value. See docs/uncertainty.md."""

    VERIFIED = "verified"
    LIKELY = "likely"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class RequirementKind(StrEnum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    INFERRED = "inferred"


class RequirementMatch(StrEnum):
    MATCHED = "matched"
    PARTIAL = "partial"
    MISSING = "missing"
    UNKNOWN = "unknown"


class EvidenceKind(StrEnum):
    PUBLICATION = "publication"
    PROJECT = "project"
    NEWS = "news"
    GRANT = "grant"
    COURSE = "course"
    TALK = "talk"
    STUDENT_PROJECT = "student_project"


class LeadState(StrEnum):
    OPENING = "opening"
    OUTREACH = "outreach"
    WATCH = "watch"


class SignalKind(StrEnum):
    UNDERGRAD_PRESENCE = "undergrad_presence"
    RECRUITING = "recruiting"
    ACTIVITY = "activity"


class SourceKind(StrEnum):
    CAMPUS_JOBS = "campus_jobs"
    FACULTY_DIRECTORY = "faculty_directory"
    LAB_SITE = "lab_site"
    PROGRAM = "program"
    SCHOLARLY = "scholarly"
    HANDSHAKE = "handshake"
    JOB_BOARD = "job_board"
    MANUAL = "manual"


class DocumentKind(StrEnum):
    RESUME = "resume"
    TRANSCRIPT = "transcript"
    COVER_LETTER = "cover_letter"
    WRITING_SAMPLE = "writing_sample"
    PORTFOLIO = "portfolio"
    REFERENCES = "references"
    STATEMENT = "statement"
    OTHER = "other"


class DocumentStatus(StrEnum):
    READY = "ready"
    MISSING = "missing"
    NEEDS_USER = "needs_user"


class AnswerSource(StrEnum):
    PROFILE = "profile"
    USER = "user"
    LLM_DRAFT = "llm_draft"


class ExtractionMethod(StrEnum):
    SOURCE = "source"
    REGEX = "regex"
    HEURISTIC = "heuristic"
    LLM = "llm"
    USER = "user"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SearchKind(StrEnum):
    JOBS = "jobs"
    RESEARCH = "research"


class ReminderProviderKind(StrEnum):
    ICS = "ics"
    APPLE_SHORTCUTS = "apple_shortcuts"
    NONE = "none"


class ReminderStatus(StrEnum):
    PENDING = "pending"
    EXPORTED = "exported"
    DISMISSED = "dismissed"


class WorkAuthorization(StrEnum):
    US_CITIZEN_OR_PR = "us_citizen_or_pr"
    F1_CPT_OPT = "f1_cpt_opt"
    OTHER_VISA = "other_visa"
    NOT_SPECIFIED = "not_specified"
