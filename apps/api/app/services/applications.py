"""Application kits and the rules that guard them.

Two invariants this module exists to hold:

1. ``opportunities.status`` is the one status the list view sorts on, and
   ``applications`` is the only thing allowed to move it past SAVED. The write
   is one-way (application -> opportunity) so the two can never disagree.
2. Nothing reaches an external site without an explicit approval bound to the
   exact payload the student reviewed.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationDocument,
    ApplicationEvent,
)
from app.models.enums import (
    AnswerCategory,
    DocumentKind,
    DocumentStatus,
    OpportunityStatus,
    OpportunityType,
    WorkAuthorization,
)
from app.models.opportunity import Opportunity
from app.models.resume import Resume
from app.models.user import StudentProfile

S = OpportunityStatus

# Where a status may go next. Everything not listed is rejected, which is what
# stops the UI from inventing a path like SUBMITTED -> PREPARING.
ALLOWED_TRANSITIONS: dict[OpportunityStatus, set[OpportunityStatus]] = {
    S.NEW: {S.SAVED, S.PREPARING, S.ARCHIVED},
    S.SAVED: {S.PREPARING, S.ARCHIVED, S.NEW},
    S.PREPARING: {S.READY_TO_APPLY, S.SAVED, S.ARCHIVED},
    S.READY_TO_APPLY: {S.APPLYING, S.PREPARING, S.SUBMITTED, S.ARCHIVED},
    S.APPLYING: {S.SUBMITTED, S.READY_TO_APPLY, S.ARCHIVED},
    S.SUBMITTED: {S.INTERVIEW, S.REJECTED, S.OFFER, S.ARCHIVED},
    S.INTERVIEW: {S.OFFER, S.REJECTED, S.ARCHIVED},
    S.OFFER: {S.ARCHIVED, S.REJECTED},
    S.REJECTED: {S.ARCHIVED},
    # Archiving must be reversible. Resuming lands back in PREPARING,
    # which is where a kit can actually be worked on again.
    S.ARCHIVED: {S.SAVED, S.NEW, S.PREPARING},
}

DOCUMENT_KINDS: dict[str, DocumentKind] = {
    "resume": DocumentKind.RESUME,
    "cv": DocumentKind.RESUME,
    "transcript": DocumentKind.TRANSCRIPT,
    "cover letter": DocumentKind.COVER_LETTER,
    "writing sample": DocumentKind.WRITING_SAMPLE,
    "portfolio": DocumentKind.PORTFOLIO,
    "references": DocumentKind.REFERENCES,
    "statement": DocumentKind.STATEMENT,
    "statement of purpose": DocumentKind.STATEMENT,
}

DOCUMENT_HELP: dict[DocumentKind, str] = {
    DocumentKind.TRANSCRIPT: "Download your unofficial transcript as a PDF from Axess.",
    DocumentKind.COVER_LETTER: "Write a short cover letter — Trellis will not draft one for you.",
    DocumentKind.WRITING_SAMPLE: "Pick a paper or report you wrote and export it as a PDF.",
    DocumentKind.PORTFOLIO: "Add a link to your portfolio or GitHub in the answers below.",
    DocumentKind.REFERENCES: "Ask your references first, then add their details.",
    DocumentKind.STATEMENT: "Write your statement — Trellis will not draft one for you.",
}


class TransitionError(ValueError):
    """A status move the pipeline does not allow."""


def classify_document(label: str) -> DocumentKind:
    lowered = label.strip().lower()
    for key, kind in DOCUMENT_KINDS.items():
        if key in lowered:
            return kind
    return DocumentKind.OTHER


def known_profile_fields(profile: StudentProfile) -> list[dict[str, str | None]]:
    """The values assisted apply may reuse without asking again.

    Work authorisation is deliberately absent: it is legally meaningful, so it
    is answered by the student every time unless they explicitly opt in to
    reuse (see ``ApplicationAnswer.reuse_approved``).
    """
    user = profile.user
    fields: list[dict[str, str | None]] = [
        {"key": "full_name", "label": "Full name", "value": user.display_name if user else None},
        {"key": "email", "label": "Email", "value": user.email if user else None},
        {"key": "university", "label": "University", "value": profile.university},
        {"key": "campus", "label": "Campus", "value": profile.campus},
        {"key": "major", "label": "Major", "value": profile.major},
        {"key": "degree", "label": "Degree", "value": profile.degree},
        {
            "key": "graduation_year",
            "label": "Expected graduation",
            "value": str(profile.graduation_year) if profile.graduation_year else None,
        },
        {
            "key": "hours_per_week",
            "label": "Hours available per week",
            "value": (
                f"{profile.hours_per_week_min}–{profile.hours_per_week_max}"
                if profile.hours_per_week_min and profile.hours_per_week_max
                else None
            ),
        },
    ]
    if profile.gpa is not None and profile.gpa_is_public:
        fields.append({"key": "gpa", "label": "GPA", "value": f"{profile.gpa:.2f}"})
    return fields


def best_resume(db: Session, opportunity: Opportunity) -> uuid.UUID | None:
    """The resume a kit would attach: the ranked pick, else the default, else the first."""
    from app.models.application import ResumeRecommendation

    row = db.scalars(
        select(ResumeRecommendation)
        .where(ResumeRecommendation.opportunity_id == opportunity.id)
        .order_by(ResumeRecommendation.rank)
    ).first()
    if row is not None:
        return row.resume_id
    default = db.scalars(select(Resume).where(Resume.is_default.is_(True))).first()
    if default is not None:
        return default.id
    return (db.scalars(select(Resume).order_by(Resume.created_at)).first() or Resume()).id


def create_kit(db: Session, profile: StudentProfile, opportunity: Opportunity) -> Application:
    """Build (or return) the Application Kit for this opportunity."""
    existing = db.scalars(
        select(Application).where(
            Application.opportunity_id == opportunity.id,
            Application.profile_id == profile.id,
        )
    ).first()
    if existing is not None:
        return existing

    app = Application(
        opportunity_id=opportunity.id,
        profile_id=profile.id,
        status=S.PREPARING,
        prepared_at=datetime.now(UTC),
    )
    app.resume_id = best_resume(db, opportunity)
    db.add(app)
    db.flush()

    required = list(opportunity.documents_required or [])
    if not required:
        required = ["Resume"]
    for label in required:
        kind = classify_document(label)
        ready = kind == DocumentKind.RESUME and app.resume_id is not None
        db.add(
            ApplicationDocument(
                application_id=app.id,
                kind=kind,
                label=label,
                required=True,
                status=DocumentStatus.READY if ready else DocumentStatus.MISSING,
                resume_id=app.resume_id if ready else None,
                note=None if ready else DOCUMENT_HELP.get(kind),
            )
        )

    db.add(
        ApplicationEvent(
            application_id=app.id,
            kind="created",
            to_status=S.PREPARING.value,
            actor="user",
            note="Application kit created.",
        )
    )
    _write_through(opportunity, S.PREPARING)
    db.flush()
    return app


def blocking_reasons(app: Application, today=None) -> list[str]:
    """What stands between here and 'ready to apply', in the order it matters."""
    reasons: list[str] = []
    no_resume = app.resume_id is None
    if no_resume:
        reasons.append("No resume selected.")

    missing = [d.label for d in app.documents if d.required and d.status != DocumentStatus.READY]
    for label in missing:
        # "No resume selected" and "Missing document: Resume" are the same
        # problem; listing both makes the blocker list look longer than it is.
        if no_resume and label.strip().lower() in ("resume", "cv"):
            continue
        reasons.append(f"Missing document: {label}")

    sensitive = [a for a in app.answers if a.is_sensitive and not a.answer]
    if sensitive:
        noun = "question" if len(sensitive) == 1 else "questions"
        reasons.append(
            f"{len(sensitive)} {noun} only you can answer "
            "(work authorisation, demographics or self-identification)."
        )

    open_questions = [
        a for a in app.answers if not a.is_sensitive and a.needs_user_input and not a.answer
    ]
    if open_questions:
        noun = "question" if len(open_questions) == 1 else "questions"
        verb = "needs" if len(open_questions) == 1 else "need"
        reasons.append(f"{len(open_questions)} {noun} still {verb} your input.")

    opp = app.opportunity
    if opp is not None and opp.deadline is not None and today is not None and opp.deadline < today:
        reasons.append(f"The deadline passed on {opp.deadline.isoformat()}.")
    return reasons


def _write_through(opportunity: Opportunity, status: OpportunityStatus) -> None:
    """Applications own the pipeline status; the opportunity mirrors it."""
    opportunity.status = status


def transition(
    db: Session,
    app: Application,
    to_status: OpportunityStatus,
    *,
    actor: str = "user",
    note: str | None = None,
) -> Application:
    current = app.status
    if to_status == current:
        return app
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if to_status not in allowed:
        raise TransitionError(
            f"Cannot move an application from {current.value} to {to_status.value}. "
            f"Allowed from here: {', '.join(sorted(s.value for s in allowed)) or 'nothing'}."
        )

    app.status = to_status
    now = datetime.now(UTC)
    if to_status == S.SUBMITTED and app.submitted_at is None:
        app.submitted_at = now
    if to_status in (S.REJECTED, S.OFFER, S.ARCHIVED):
        app.closed_at = now
    # Re-opening a kit invalidates any prior approval: the student must review
    # the payload again before anything can be submitted.
    if to_status in (S.PREPARING, S.SAVED):
        app.approved_at = None
        app.approved_payload_hash = None

    db.add(
        ApplicationEvent(
            application_id=app.id,
            kind="status",
            from_status=current.value,
            to_status=to_status.value,
            actor=actor,
            note=note,
        )
    )
    if app.opportunity is not None:
        _write_through(app.opportunity, to_status)
    return app


# --------------------------------------------------------------------------- #
# Question classification
#
# Every question an application form asks lands in exactly one of four
# categories, and the category — not a guess at the call site — decides what
# software is allowed to do with it.  See :class:`AnswerCategory`.
# --------------------------------------------------------------------------- #


def _phrase(term: str) -> re.Pattern[str]:
    """A whole-word matcher for one phrase.

    Substring matching is not safe here: ``"age"`` is inside "language" and
    "race" is inside "embrace", so a plain ``in`` test flags "What programming
    languages do you know?" as an age question.  Words may be joined by spaces
    or hyphens on a real form, so "self-identify" and "self identify" are the
    same phrase.
    """
    body = r"[\s\-]+".join(re.escape(word) for word in re.split(r"[\s\-]+", term) if word)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.I)


@dataclass(slots=True)
class SensitiveRule:
    category: str
    terms: tuple[str, ...]

    @property
    def patterns(self) -> tuple[re.Pattern[str], ...]:
        return tuple(_phrase(t) for t in self.terms)


# Order matters: the first rule that matches names the category, so the
# specific legal categories come before the catch-all attestation rule.
SENSITIVE_RULES: tuple[SensitiveRule, ...] = (
    SensitiveRule(
        "work_authorization",
        (
            "work authorization",
            "work authorisation",
            "authorized to work",
            "authorised to work",
            "legally authorized",
            "legally authorised",
            "right to work",
            "eligible to work",
            "employment eligibility",
            "sponsorship",
            "sponsor",
            "visa",
            "visa status",
            "immigration",
            "immigration status",
            "i-9",
            "citizenship",
            "permanent resident",
            "green card",
            "f-1",
            "j-1",
            "h-1b",
            "cpt",
            "curricular practical training",
            "optional practical training",
        ),
    ),
    SensitiveRule(
        "race_ethnicity",
        ("race", "ethnicity", "ethnic origin", "national origin", "hispanic", "latino"),
    ),
    SensitiveRule("gender", ("gender", "gender identity", "sex", "pronoun", "pronouns")),
    SensitiveRule(
        "disability",
        ("disability", "disabilities", "disabled", "accommodation", "accommodations"),
    ),
    SensitiveRule(
        "veteran", ("veteran", "veterans", "military service", "protected veteran", "armed forces")
    ),
    SensitiveRule(
        "criminal_history",
        ("felony", "conviction", "convicted", "criminal", "background check", "arrest record"),
    ),
    SensitiveRule(
        "age", ("date of birth", "age", "birthdate", "birth date", "over 18", "at least 18")
    ),
    SensitiveRule(
        "self_identification",
        (
            "self-identify",
            "self-identification",
            "voluntary disclosure",
            "voluntary self-identification",
            "eeo",
            "eeoc",
            "equal employment opportunity",
            "affirmative action",
            "demographic",
            "demographics",
        ),
    ),
    SensitiveRule(
        "legal_attestation",
        (
            "certify",
            "i certify",
            "attest",
            "attestation",
            "under penalty of perjury",
            "affirm",
            "acknowledge and agree",
            "legally binding",
            "signature",
            "electronic signature",
            "e-signature",
            "consent to a background check",
        ),
    ),
)

_SENSITIVE_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (rule.category, rule.patterns) for rule in SENSITIVE_RULES
)


@dataclass(slots=True)
class ProfileFieldRule:
    """A question that is answerable from the student's own profile."""

    key: str
    terms: tuple[str, ...]

    @property
    def patterns(self) -> tuple[re.Pattern[str], ...]:
        return tuple(_phrase(t) for t in self.terms)


PROFILE_FIELD_RULES: tuple[ProfileFieldRule, ...] = (
    ProfileFieldRule("full_name", ("full name", "your name", "first and last name", "legal name")),
    ProfileFieldRule("email", ("email", "e-mail", "email address")),
    ProfileFieldRule("university", ("university", "school", "institution", "college")),
    ProfileFieldRule("campus", ("campus",)),
    ProfileFieldRule("major", ("major", "field of study", "course of study")),
    ProfileFieldRule("degree", ("degree", "degree program", "degree programme")),
    ProfileFieldRule(
        "graduation_year",
        ("graduation", "graduation year", "expected grad", "class year", "year of graduation"),
    ),
    ProfileFieldRule(
        "hours_per_week",
        (
            "hours per week",
            "how many hours",
            "hours are you available",
            "availability",
            "weekly availability",
        ),
    ),
    ProfileFieldRule("gpa", ("gpa", "grade point average")),
)

_PROFILE_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (rule.key, rule.patterns) for rule in PROFILE_FIELD_RULES
)

# Cues that mark an open, essay-shaped question — the only kind the model is
# ever allowed to draft, and even then the draft is the student's to edit.
GENERATIVE_CUES: tuple[str, ...] = (
    "why are you",
    "why do you",
    "why this",
    "why our",
    "why us",
    "and why",
    "describe",
    "tell us",
    "tell me",
    "explain",
    "elaborate",
    "discuss",
    "in your own words",
    "what interests you",
    "what excites you",
    "what motivates you",
    "what makes you",
    "what relevant",
    "what do you hope",
    "what are you hoping",
    "how would you",
    "what would you",
    "walk us through",
    "give an example",
    "share an example",
    "cover letter",
    "personal statement",
    "statement of purpose",
    "research statement",
    "essay",
    "which of",
)

_GENERATIVE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(_phrase(c) for c in GENERATIVE_CUES)


@dataclass(frozen=True, slots=True)
class QuestionClass:
    """What one question is, and therefore what may be done with it."""

    category: AnswerCategory
    reason: str
    sensitive_category: str | None = None
    profile_field: str | None = None

    @property
    def is_sensitive(self) -> bool:
        return self.category is AnswerCategory.SENSITIVE

    @property
    def may_prefill_from_profile(self) -> bool:
        return self.category is AnswerCategory.SAFE_PROFILE_FIELD

    @property
    def may_draft(self) -> bool:
        return self.category is AnswerCategory.SAFE_GENERATIVE

    @property
    def needs_review(self) -> bool:
        """Everything except a straight profile field is the student's to confirm."""
        return self.category is not AnswerCategory.SAFE_PROFILE_FIELD


def classify_question(question: str) -> QuestionClass:
    """Sort one application question into the four categories.

    Sensitivity is tested first and wins outright: "What is your visa status?"
    is a visa question, not a profile field, even though the profile happens to
    hold a work-authorisation value.  Anything unrecognised is UNKNOWN, which
    is deliberately the *cautious* end of the scale — it is never prefilled and
    never drafted, so a question we have not seen before defaults to the
    student answering it.
    """
    text = (question or "").strip()
    if not text:
        return QuestionClass(AnswerCategory.UNKNOWN, "Empty question — only you can answer it.")

    for category, patterns in _SENSITIVE_PATTERNS:
        for pattern in patterns:
            if pattern.search(text):
                return QuestionClass(
                    AnswerCategory.SENSITIVE,
                    "Legally sensitive: Trellis never answers, drafts or prefills this.",
                    sensitive_category=category,
                )

    for key, patterns in _PROFILE_PATTERNS:
        for pattern in patterns:
            if pattern.search(text):
                return QuestionClass(
                    AnswerCategory.SAFE_PROFILE_FIELD,
                    "Answered from your profile.",
                    profile_field=key,
                )

    for pattern in _GENERATIVE_PATTERNS:
        if pattern.search(text):
            return QuestionClass(
                AnswerCategory.SAFE_GENERATIVE,
                "Open-ended: Trellis may draft from your own material, and you review it.",
            )

    return QuestionClass(
        AnswerCategory.UNKNOWN,
        "Trellis does not recognise this question, so it is left for you to answer.",
    )


def sensitivity_of(question: str) -> tuple[bool, str | None]:
    """The yes/no view of :func:`classify_question`, for the submission gate."""
    result = classify_question(question)
    return result.is_sensitive, result.sensitive_category


def profile_field_value(profile: StudentProfile, key: str) -> str | None:
    """One profile field as the string a form would receive."""
    user = profile.user
    if key == "full_name":
        return user.display_name if user else None
    if key == "email":
        return user.email if user else None
    if key == "university":
        return profile.university
    if key == "campus":
        return profile.campus
    if key == "major":
        return profile.major
    if key == "degree":
        return profile.degree
    if key == "graduation_year":
        return str(profile.graduation_year) if profile.graduation_year else None
    if key == "hours_per_week":
        if profile.hours_per_week_min and profile.hours_per_week_max:
            return f"{profile.hours_per_week_min}-{profile.hours_per_week_max}"
        return None
    if key == "gpa":
        # A private GPA stays private even though the profile holds it.
        if profile.gpa is not None and profile.gpa_is_public:
            return f"{profile.gpa:.2f}"
        return None
    return None


# --------------------------------------------------------------------------- #
# The question set a kit is built from
# --------------------------------------------------------------------------- #

# Asked on every application, plus type-specific ones. Real forms add their
# own; these are the ones a student can usefully prepare in advance.
BASE_QUESTIONS: tuple[str, ...] = (
    "Full name",
    "Email",
    "University",
    "Major",
    "Expected graduation year",
    "How many hours per week are you available?",
)

RESEARCH_QUESTIONS: tuple[str, ...] = (
    "Which of this lab's projects interests you most, and why?",
    "What relevant coursework or projects have you completed?",
    "When could you start, and for how many quarters?",
)

JOB_QUESTIONS: tuple[str, ...] = (
    "Why are you interested in this role?",
    "Describe relevant experience for this position.",
    "What is your availability during the week?",
)


def planned_questions(opportunity: Opportunity | None) -> list[str]:
    """Exactly the questions :class:`ApplicationPrepAgent` would create.

    Shared with the readiness summary so an opportunity with no kit yet can
    report what preparing one will actually ask, instead of a placeholder.
    """
    is_research = opportunity is not None and opportunity.type in (
        OpportunityType.RESEARCH_OPENING,
        OpportunityType.RESEARCH_OUTREACH,
    )
    questions = list(BASE_QUESTIONS)
    questions += list(RESEARCH_QUESTIONS if is_research else JOB_QUESTIONS)
    for req in opportunity.requirements if opportunity is not None else []:
        if req.category == "question":
            questions.append(req.text)
    return questions


def work_authorization_label(value: WorkAuthorization) -> str:
    return {
        WorkAuthorization.US_CITIZEN_OR_PR: "U.S. citizen or permanent resident",
        WorkAuthorization.F1_CPT_OPT: "F-1 student (CPT/OPT)",
        WorkAuthorization.OTHER_VISA: "Other visa status",
        WorkAuthorization.NOT_SPECIFIED: "Not specified",
    }[value]
