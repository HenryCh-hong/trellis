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


class DeadlineState(StrEnum):
    """The recorded lifecycle of a deadline, as opposed to ``DeadlineType``,
    which is only what the posting said.

    ``EXPIRED`` is a *stored* state, not an adjective computed on read: the
    moment a stated date lapses is written down (and logged as an
    OpportunityChange) so the student can see that it happened rather than
    discovering that a row quietly changed colour.
    """

    HARD = "hard"
    ROLLING = "rolling"
    UNKNOWN = "unknown"
    EXPIRED = "expired"


class SourceStatus(StrEnum):
    """Whether the posting is still on the page it came from.

    ``GONE`` is only ever written when the source itself answered and the
    posting was not in its answer.  A source that failed wholesale leaves every
    one of its opportunities alone — "we could not check" is not "it is gone".
    """

    LIVE = "live"
    GONE = "gone"


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


class ConfidenceState(StrEnum):
    """Whether an extraction is solid enough to put in front of the student.

    ``HELD`` is a *review* state, not a delete: the row, its provenance and the
    reason it was held all survive, and a later run that reads the page better
    promotes it back to ``OK`` automatically.  Nothing is thrown away, but
    nothing half-read is recommended either.
    """

    OK = "ok"
    HELD = "held"


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
    """How actionable a research lead is, in descending order of evidence.

    Four states rather than two because "outreach" was doing two jobs: a lab
    with nine undergraduates and a public contact form, and a lab we simply
    could not read anything useful about, are not the same lead.  UNKNOWN is
    never upgraded to OUTREACH to give the student something to click.
    """

    OPENING = "opening"
    OUTREACH = "outreach"
    WATCH = "watch"
    UNKNOWN = "unknown"


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


class AnswerCategory(StrEnum):
    """What kind of question an application form is asking.

    The category decides what software is *allowed* to do with the answer, so
    it is stored on the row rather than recomputed on read:

    * ``SAFE_PROFILE_FIELD`` may be filled from the student's profile.
    * ``SAFE_GENERATIVE`` may be drafted by the model, and is always reviewed.
    * ``SENSITIVE`` is never guessed, never drafted and never prefilled — not
      even from a profile field that happens to hold the value.
    * ``UNKNOWN`` is the default for anything unrecognised, and behaves like
      SAFE_GENERATIVE minus the drafting: the student answers it.
    """

    SAFE_PROFILE_FIELD = "safe_profile_field"
    SAFE_GENERATIVE = "safe_generative"
    SENSITIVE = "sensitive"
    UNKNOWN = "unknown"


class LinkVerification(StrEnum):
    """Whether we actually read the application link off the source page.

    ``VERIFIED`` requires a provenance row naming the page the URL came from.
    A URL with no such row is ``UNVERIFIED`` — we hold it, but nobody watched
    a page say "apply here" — and no URL at all is ``NOT_FOUND``.
    """

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    NOT_FOUND = "not_found"


class ReadinessState(StrEnum):
    """How one line of the readiness list reads.

    ``UNKNOWN`` is not a soft ``ATTENTION``: it means we could not establish
    the fact, and the student is told that rather than shown a green tick.
    """

    READY = "ready"
    ATTENTION = "attention"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


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
    #: Writes straight into the Reminders app when the API runs on the student's Mac.
    APPLE_REMINDERS = "apple_reminders"
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


class FeedbackSignal(StrEnum):
    """What the student said about one opportunity.

    Recorded so the product can be quietly less wrong next time; deliberately
    NOT a rating.  Every one of these is reversible and applies to exactly one
    row — see ``app/services/feedback.py`` for the (bounded) effect each has.
    """

    INTERESTED = "interested"
    NOT_RELEVANT = "not_relevant"
    ALREADY_APPLIED = "already_applied"
    HIDDEN = "hidden"


class FeedbackReason(StrEnum):
    """Why something was marked not relevant.

    Stored for later analysis only.  It may never be aggregated into a filter:
    one "wrong topic" is a fact about one posting, not a statement that the
    student has stopped caring about the topic.
    """

    WRONG_TOPIC = "wrong_topic"
    WRONG_JOB_TYPE = "wrong_job_type"
    TOO_FAR = "too_far"
    NOT_QUALIFIED = "not_qualified"
    NOT_INTERESTED = "not_interested"
