"""Can I apply right now?

One answer, computed in one place.  The opportunity detail panel and the
application kit page both render this, so they cannot drift apart and tell a
student two different stories about the same application.

Three rules this module exists to hold:

1. The call to action is never "Apply".  Trellis does not submit anything, so
   offering a button that implies it would be a lie about what happens next.
   The only two labels are :data:`CTA_CONTINUE` and :data:`CTA_REVIEW`.
2. "Application link — Verified" is claimed only when a provenance row records
   the page the URL was read from.  A URL we merely hold is *Unverified*, and
   no URL at all is *Not found*.
3. Nothing here is a guess.  A fact we could not establish is reported as
   ``UNKNOWN`` rather than rounded to a green tick.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationDocument
from app.models.enums import (
    AnswerCategory,
    Certainty,
    DeadlineState,
    DeadlineType,
    DocumentKind,
    DocumentStatus,
    LinkVerification,
    ReadinessState,
)
from app.models.opportunity import ExtractedField, Opportunity
from app.models.resume import Resume
from app.services.applications import (
    DOCUMENT_HELP,
    best_resume,
    blocking_reasons,
    classify_document,
    classify_question,
    planned_questions,
)

#: The provenance row that licences the word "Verified" on an application link.
APPLICATION_URL_FIELD = "application_url"

# Trellis never submits, so it never says "Apply". Both labels describe work
# the student does here, in Trellis, before they go to the site themselves.
CTA_CONTINUE = "Continue preparation"
CTA_REVIEW = "Review application"

NOT_PREPARED = "The application kit has not been prepared yet."


@dataclass(frozen=True, slots=True)
class ReadinessRow:
    """One line of the readiness list."""

    key: str
    label: str
    state: ReadinessState
    detail: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class LinkState:
    verification: LinkVerification
    url: str | None
    detail: str
    note: str


@dataclass(frozen=True, slots=True)
class Readiness:
    ready: bool
    cta: str
    #: What the button does — "prepare" opens/creates the kit, "review" opens
    #: the submission review. The label is :attr:`cta`; this is the behaviour.
    cta_action: str
    rows: list[ReadinessRow] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    link: LinkState | None = None
    has_application: bool = False
    application_id: uuid.UUID | None = None


# --------------------------------------------------------------------------- #
# application link
# --------------------------------------------------------------------------- #


def application_link_state(
    fields: Iterable[ExtractedField], url: str | None
) -> LinkState:
    """Whether we may say the application link was read from the source.

    Pure on purpose: the caller supplies the opportunity's provenance rows, so
    this is testable without a database and cannot quietly fall back to a
    guess when none exist.
    """
    if not url:
        return LinkState(
            LinkVerification.NOT_FOUND,
            None,
            "Not found",
            "No apply link was stated on the page we read, so there is nothing to verify.",
        )

    row = next((f for f in fields if f.field == APPLICATION_URL_FIELD), None)
    recorded = (row.value or {}).get("value") if row is not None else None
    if row is not None and row.certainty is Certainty.VERIFIED and recorded == url:
        where = row.source_url or "the source page"
        return LinkState(
            LinkVerification.VERIFIED,
            url,
            "Verified",
            row.source_text or f"Read from {where}.",
        )
    return LinkState(
        LinkVerification.UNVERIFIED,
        url,
        "Unverified",
        "Trellis holds this link, but no page was recorded as stating that this is "
        "where you apply. Check it before you rely on it.",
    )


# --------------------------------------------------------------------------- #
# rows
# --------------------------------------------------------------------------- #


def _format_date(value: date, today: date) -> str:
    """"Sep 12", or "Sep 12, 2027" once the year stops being obvious."""
    stem = f"{value:%b} {value.day}"
    return stem if value.year == today.year else f"{stem}, {value.year}"


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _deadline_row(opp: Opportunity, today: date) -> ReadinessRow:
    deadline = opp.deadline
    if deadline is not None and (deadline < today or opp.deadline_state is DeadlineState.EXPIRED):
        return ReadinessRow(
            "deadline",
            "Deadline",
            ReadinessState.BLOCKED,
            f"Passed {_format_date(deadline, today)}",
            "The stated deadline has gone by. Anything you send now is late.",
        )
    if deadline is not None:
        days = (deadline - today).days
        when = (
            "Closes today"
            if days == 0
            else "Closes tomorrow"
            if days == 1
            else f"{days} days left"
        )
        return ReadinessRow(
            "deadline", "Deadline", ReadinessState.READY, _format_date(deadline, today), when
        )
    if opp.deadline_type is DeadlineType.ROLLING or opp.deadline_state is DeadlineState.ROLLING:
        return ReadinessRow(
            "deadline",
            "Deadline",
            ReadinessState.READY,
            "Rolling",
            "The posting says applications are reviewed as they arrive.",
        )
    return ReadinessRow(
        "deadline",
        "Deadline",
        ReadinessState.UNKNOWN,
        "Not stated",
        "No date was found on the page. Trellis will not invent one.",
    )


def _resume_row(resume: Resume | None, *, attached: bool) -> ReadinessRow:
    if resume is None:
        return ReadinessRow(
            "resume",
            "Resume",
            ReadinessState.ATTENTION,
            "None selected",
            "Upload a resume, or pick one of yours for this application.",
        )
    name = resume.original_filename or resume.label
    return ReadinessRow(
        "resume",
        "Resume",
        ReadinessState.READY,
        name,
        None if attached else "Trellis will attach this one when you prepare the application.",
    )


def _document_rows(documents: Sequence[ApplicationDocument]) -> list[ReadinessRow]:
    rows: list[ReadinessRow] = []
    for doc in documents:
        # The resume has its own line above; listing it twice makes the same
        # single problem look like two.
        if doc.kind is DocumentKind.RESUME or not doc.required:
            continue
        if doc.status is DocumentStatus.READY:
            rows.append(
                ReadinessRow(
                    f"document:{doc.id}",
                    doc.label,
                    ReadinessState.READY,
                    doc.filename or "Ready",
                )
            )
        else:
            rows.append(
                ReadinessRow(
                    f"document:{doc.id}",
                    doc.label,
                    ReadinessState.ATTENTION,
                    "Needs you" if doc.status is DocumentStatus.NEEDS_USER else "Missing",
                    doc.note or DOCUMENT_HELP.get(doc.kind),
                )
            )
    return rows


def _planned_document_rows(opp: Opportunity, has_resume: bool) -> list[ReadinessRow]:
    """What ``create_kit`` will ask for, before a kit exists."""
    rows: list[ReadinessRow] = []
    labels = list(opp.documents_required or []) or ["Resume"]
    for index, label in enumerate(labels):
        kind = classify_document(label)
        if kind is DocumentKind.RESUME:
            continue
        rows.append(
            ReadinessRow(
                f"document:planned:{index}",
                label,
                ReadinessState.ATTENTION,
                "Missing",
                DOCUMENT_HELP.get(kind),
            )
        )
    if not rows and not has_resume:
        return []
    return rows


def _answer_rows(app: Application) -> list[ReadinessRow]:
    answers = list(app.answers)
    sensitive = [a for a in answers if a.is_sensitive]
    ordinary = [a for a in answers if not a.is_sensitive]

    # The same predicate ``blocking_reasons`` uses, so the count and the
    # blocker list can never disagree.
    open_questions = [a for a in ordinary if a.needs_user_input and not a.answer]
    drafts = [a for a in ordinary if a.answer and a.needs_user_input]
    unrecognised = [a for a in ordinary if a.category is AnswerCategory.UNKNOWN]

    if not ordinary:
        questions = ReadinessRow(
            "questions", "Questions", ReadinessState.READY, "None on this form"
        )
    elif open_questions:
        note_parts = []
        if drafts:
            note_parts.append(f"{len(drafts)} drafted for you to edit")
        if unrecognised:
            note_parts.append(
                f"{len(unrecognised)} Trellis does not recognise, so it left {_plural(len(unrecognised), 'it', 'them')} to you"
            )
        questions = ReadinessRow(
            "questions",
            "Questions",
            ReadinessState.ATTENTION,
            f"{len(open_questions)} unanswered",
            " · ".join(note_parts) or None,
        )
    else:
        questions = ReadinessRow(
            "questions",
            "Questions",
            ReadinessState.READY,
            f"All {len(ordinary)} answered",
            f"{len(drafts)} still a draft — read {_plural(len(drafts), 'it', 'them')} before you send"
            if drafts
            else None,
        )

    if not sensitive:
        sensitive_row = ReadinessRow(
            "sensitive", "Sensitive", ReadinessState.READY, "None asked"
        )
    else:
        outstanding = [a for a in sensitive if not a.answer]
        if outstanding:
            sensitive_row = ReadinessRow(
                "sensitive",
                "Sensitive",
                ReadinessState.ATTENTION,
                f"{len(outstanding)} {_plural(len(outstanding), 'requires', 'require')} your input",
                "Trellis never answers work-authorisation, demographic, disability, "
                "veteran-status, criminal-history or attestation questions for you.",
            )
        else:
            sensitive_row = ReadinessRow(
                "sensitive",
                "Sensitive",
                ReadinessState.READY,
                f"{len(sensitive)} answered by you",
            )
    return [questions, sensitive_row]


def _planned_answer_rows(opp: Opportunity) -> list[ReadinessRow]:
    classes = [classify_question(q) for q in planned_questions(opp)]
    sensitive = [c for c in classes if c.is_sensitive]
    ordinary = [c for c in classes if not c.is_sensitive and c.needs_review]

    questions = ReadinessRow(
        "questions",
        "Questions",
        ReadinessState.ATTENTION if ordinary else ReadinessState.READY,
        f"{len(ordinary)} to answer" if ordinary else "None on this form",
        "Preparing the kit will ask these." if ordinary else None,
    )
    sensitive_row = ReadinessRow(
        "sensitive",
        "Sensitive",
        ReadinessState.ATTENTION if sensitive else ReadinessState.READY,
        f"{len(sensitive)} will need you" if sensitive else "None asked",
        "Only you can answer these, and Trellis will not draft them."
        if sensitive
        else None,
    )
    return [questions, sensitive_row]


# --------------------------------------------------------------------------- #
# the whole answer
# --------------------------------------------------------------------------- #


def readiness_for(
    db: Session,
    *,
    opportunity: Opportunity,
    application: Application | None,
    today: date,
) -> Readiness:
    """"Can I apply right now?" for one opportunity, with or without a kit.

    With no kit the answer is never "ready": there is nothing to review yet,
    so the readiness list previews what preparing one will ask for and the
    call to action stays :data:`CTA_CONTINUE`.
    """
    link = application_link_state(opportunity.fields, opportunity.application_url)
    link_row = ReadinessRow(
        "application_link",
        "Application link",
        ReadinessState.READY
        if link.verification is LinkVerification.VERIFIED
        else ReadinessState.UNKNOWN,
        link.detail,
        link.note,
    )

    if application is not None:
        resume = db.get(Resume, application.resume_id) if application.resume_id else None
        rows = [
            _resume_row(resume, attached=True),
            *_document_rows(application.documents),
            *_answer_rows(application),
            _deadline_row(opportunity, today),
            link_row,
        ]
        blocking = blocking_reasons(application, today)
        ready = not blocking
        return Readiness(
            ready=ready,
            cta=CTA_REVIEW if ready else CTA_CONTINUE,
            cta_action="review" if ready else "prepare",
            rows=rows,
            blocking=blocking,
            link=link,
            has_application=True,
            application_id=application.id,
        )

    resume_id = best_resume(db, opportunity)
    resume = db.get(Resume, resume_id) if resume_id else None
    document_rows = _planned_document_rows(opportunity, resume is not None)
    deadline_row = _deadline_row(opportunity, today)
    rows = [
        _resume_row(resume, attached=False),
        *document_rows,
        *_planned_answer_rows(opportunity),
        deadline_row,
        link_row,
    ]

    blocking = [NOT_PREPARED]
    if resume is None:
        blocking.append("No resume uploaded yet.")
    blocking += [f"Missing document: {row.label}" for row in document_rows]
    if deadline_row.state is ReadinessState.BLOCKED and opportunity.deadline is not None:
        blocking.append(f"The deadline passed on {opportunity.deadline.isoformat()}.")

    return Readiness(
        # Nothing to review until a kit exists, whatever else is in order.
        ready=False,
        cta=CTA_CONTINUE,
        cta_action="prepare",
        rows=rows,
        blocking=blocking,
        link=link,
        has_application=False,
        application_id=None,
    )
