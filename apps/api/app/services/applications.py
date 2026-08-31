"""Application kits and the rules that guard them.

Two invariants this module exists to hold:

1. ``opportunities.status`` is the one status the list view sorts on, and
   ``applications`` is the only thing allowed to move it past SAVED. The write
   is one-way (application -> opportunity) so the two can never disagree.
2. Nothing reaches an external site without an explicit approval bound to the
   exact payload the student reviewed.
"""

from __future__ import annotations

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
    DocumentKind,
    DocumentStatus,
    OpportunityStatus,
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


def _best_resume(db: Session, opportunity: Opportunity) -> uuid.UUID | None:
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
    app.resume_id = _best_resume(db, opportunity)
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


@dataclass(slots=True)
class SensitiveRule:
    category: str
    terms: tuple[str, ...]


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
            "immigration",
            "i-9",
            "citizenship",
            "permanent resident",
        ),
    ),
    SensitiveRule("race_ethnicity", ("race", "ethnicity", "hispanic", "latino")),
    SensitiveRule("gender", ("gender", "sex", "pronoun")),
    SensitiveRule("disability", ("disability", "disabled", "accommodation")),
    SensitiveRule("veteran", ("veteran", "military service", "protected veteran")),
    SensitiveRule("criminal_history", ("felony", "conviction", "criminal", "background check")),
    SensitiveRule("age", ("date of birth", "age", "birthdate")),
    SensitiveRule("self_identification", ("self-identify", "self identification", "voluntary disclosure", "eeo")),
)


def sensitivity_of(question: str) -> tuple[bool, str | None]:
    lowered = question.lower()
    for rule in SENSITIVE_RULES:
        if any(term in lowered for term in rule.terms):
            return True, rule.category
    return False, None


def profile_answer(profile: StudentProfile, question: str) -> tuple[str | None, str | None]:
    """Map a plain question onto a trusted profile field, or return nothing."""
    lowered = question.lower()
    user = profile.user
    table: list[tuple[tuple[str, ...], str, str | None]] = [
        (("full name", "your name", "first and last"), "full_name", user.display_name if user else None),
        (("email",), "email", user.email if user else None),
        (("university", "school", "institution"), "university", profile.university),
        (("major", "field of study"), "major", profile.major),
        (("degree",), "degree", profile.degree),
        (("graduation", "expected grad", "class year"), "graduation_year", str(profile.graduation_year) if profile.graduation_year else None),
        (("hours per week", "availability", "hours are you available"), "hours_per_week",
         f"{profile.hours_per_week_min}-{profile.hours_per_week_max}" if profile.hours_per_week_min else None),
    ]
    for terms, key, value in table:
        if any(t in lowered for t in terms) and value:
            return value, key
    if "gpa" in lowered and profile.gpa is not None and profile.gpa_is_public:
        return f"{profile.gpa:.2f}", "gpa"
    return None, None


def work_authorization_label(value: WorkAuthorization) -> str:
    return {
        WorkAuthorization.US_CITIZEN_OR_PR: "U.S. citizen or permanent resident",
        WorkAuthorization.F1_CPT_OPT: "F-1 student (CPT/OPT)",
        WorkAuthorization.OTHER_VISA: "Other visa status",
        WorkAuthorization.NOT_SPECIFIED: "Not specified",
    }[value]
