"""A first draft of a cold email, assembled only from things we can point at.

A cold email to a professor is the single highest-leverage thing an undergraduate
can send, and it is also the easiest thing in this product to get dishonestly
wrong. The failure mode is not a clumsy sentence. It is a fluent one that says
"I was fascinated by your recent work on X" when the student has not read it, or
"my background in Y" when Y appears nowhere in their resume. That email is worse
than no email: it is the kind a professor recognises immediately, and the claim
is the student's to answer for, not ours.

So this composes rather than generates. Every sentence is stitched from a fact
that already survived verification elsewhere in Trellis:

* the lab's side comes from :mod:`app.services.fit` overlaps and dated
  :class:`ResearchEvidence` rows — a title and a year we actually read;
* the student's side comes only from their profile and the resumes they
  uploaded, quoted verbatim where it is their own words;
* nothing else is admissible. Not inference, not "you seem interested in".

Deliberate limits, each of which is a refusal to write a better-sounding lie:

* We never write that the student *read*, *enjoyed* or *was inspired by* a
  paper. We write that it is why they are writing, which is true of a draft
  they are about to edit. What they have actually read is theirs to say.
* We never name a skill or course that is not in their profile or resume text.
* With no dated recent work, or nothing real in common, we refuse to draft at
  all and say which of the two is missing, because a generic email sent to a
  named professor is worse than an honest blank page.

The draft is a starting point, and the API says so. Nothing here sends mail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.enums import EvidenceKind
from app.models.research import Faculty, ResearchEvidence
from app.models.user import StudentProfile
from app.services import fit as fit_service

#: A cold email that runs past this stops being read. Below the floor it has not
#: said anything specific enough to be worth a reply.
MIN_WORDS = 100
MAX_WORDS = 160

#: Evidence this old is not "recent work" and opening with it looks careless.
RECENT_YEARS = 2


@dataclass(slots=True)
class Citation:
    """One fact the draft leans on, so the student can check it before sending."""

    label: str
    detail: str
    source_url: str | None = None
    #: "research" (the lab's own output) or "student" (their profile/resume).
    side: str = "research"


@dataclass(slots=True)
class OutreachDraft:
    subject: str | None = None
    body: str | None = None
    word_count: int = 0
    research_citations: list[Citation] = field(default_factory=list)
    student_citations: list[Citation] = field(default_factory=list)
    #: Set when we will not draft. The UI shows this instead of an email.
    refusal: str | None = None
    #: Things the student must fix themselves before this is sendable.
    todos: list[str] = field(default_factory=list)


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _surname(name: str) -> str:
    """The form of address for an email: family name only.

    Cleans the honorifics and post-nominals that appear in scraped directory
    names ("J Kenneth Salisbury, Jr.") so the greeting does not read as a mail
    merge. Falls back to the whole name rather than guessing wrongly.
    """
    cleaned = re.sub(r",.*$", "", name).strip()
    cleaned = re.sub(r"\b(Jr|Sr|III|II|PhD|Ph\.D\.|Dr\.?|Prof\.?)\b\.?", "", cleaned).strip()
    parts = [p for p in cleaned.split() if len(p) > 1]
    return parts[-1] if parts else name


def _recent_evidence(faculty: Faculty, this_year: int) -> list[ResearchEvidence]:
    """Dated *publications* from the window we are willing to call recent.

    Restricted to real papers on purpose. The evidence table also holds course
    listings, news items and research-thrust blurbs, and opening an email with
    "your 2026 paper '2025-26 teaching, including Supervised Undergraduate
    Research'" is not a small infelicity — it tells the professor immediately
    that nobody read anything.
    """
    rows = [
        item
        for item in (faculty.evidence or [])
        if item.year is not None
        and item.year >= this_year - RECENT_YEARS
        and (item.title or "").strip()
        and item.kind == EvidenceKind.PUBLICATION
    ]
    rows.sort(key=lambda item: (item.year or 0), reverse=True)
    return rows


def _pick_paper(
    faculty: Faculty, overlaps: list[fit_service.OverlapPoint], this_year: int
) -> tuple[ResearchEvidence, fit_service.OverlapPoint | None] | None:
    """The work to open on: the most recent item an overlap actually names.

    Opening on a paper the student has no connection to is how a cold email
    reads as a template. If nothing recent connects, we return None and the
    caller refuses rather than reaching for the newest thing on the list.
    """
    recent = _recent_evidence(faculty, this_year)
    if not recent:
        return None
    for item in recent:
        title = (item.title or "").strip().lower()
        if not title:
            continue
        for overlap in overlaps:
            # Pair the paper with the interest that named it. Naming a different
            # interest in the same breath — "your NLP work", to a robotics lab,
            # because NLP happens to be first in the student's list — reads as a
            # mail merge and is the kind of small wrongness a professor notices.
            if title in (overlap.evidence or "").lower():
                return item, overlap
    return None


def compose_draft(
    faculty: Faculty,
    profile: StudentProfile,
    breakdown: fit_service.FitBreakdown | None,
    *,
    this_year: int,
) -> OutreachDraft:
    """Build the draft from facts already in hand.

    Separated from :func:`build_draft` so the honesty rules can be tested
    against plain objects — what this product is allowed to claim about a
    student should never need a database to verify.
    """
    draft = OutreachDraft()
    overlaps = list(breakdown.strong_overlap) if breakdown else []
    background = list(breakdown.relevant_background) if breakdown else []

    picked = _pick_paper(faculty, overlaps, this_year)
    if picked is None:
        recent = _recent_evidence(faculty, this_year)
        draft.refusal = (
            "There is nothing recent from this lab that connects to anything in your profile or "
            "resumes, so any email we drafted would be generic. Read one of their papers first — "
            "then the first line is yours to write and it will be true."
            if recent
            else "We have not read any dated work from this lab in the last "
            f"{RECENT_YEARS} years, so there is nothing current to open on. Check the lab site "
            "yourself before writing."
        )
        return draft

    if not background:
        draft.refusal = (
            "Your profile and resumes do not yet give us anything concrete to say about you, and "
            "an email that describes your background in words you did not write is not one you "
            "should send. Upload a resume, or add your coursework, and this becomes possible."
        )
        return draft

    paper, connection = picked
    surname = _surname(faculty.name)
    topic = connection.label if connection is not None else None
    year = paper.year

    # --- the opening: their work, named exactly, with no claim about reading it
    lines: list[str] = [f"Dear Professor {surname},"]
    opening = (
        f"I am writing because of your {year} paper “{(paper.title or '').strip()}”"
        + (f" and the lab's work on {topic}." if topic else ".")
    )
    lines.append(opening)

    # --- the student: their own words, or a plain statement of a stored fact
    quoted = next((b for b in background if b.verbatim and b.detail), None)
    plain = [b for b in background if not (b.verbatim and b.detail)]

    about: list[str] = []
    year_label = _study_line(profile)
    if year_label:
        about.append(year_label)
    if quoted is not None:
        about.append(f"From my resume: “{(quoted.detail or '').strip()}”")
        draft.student_citations.append(
            Citation(
                label=quoted.label,
                detail=(quoted.detail or "").strip(),
                source_url=None,
                side="student",
            )
        )
    for item in plain[:2]:
        detail = (item.detail or "").strip()
        about.append(_background_sentence(item))
        draft.student_citations.append(
            Citation(label=item.label, detail=detail or item.label, side="student")
        )
    lines.extend(about)

    # --- the ask: small, specific, and answerable in one line
    ask = (
        "I am looking for a research assistant position for the coming term and would be glad to "
        "start on whatever is most useful, including the unglamorous parts."
    )
    hours = _hours_line(profile)
    if hours:
        ask += f" {hours}"
    lines.append(ask)
    lines.append(
        "Would you be open to a short conversation about whether there is a project I could help with? "
        "I am happy to send a transcript or code samples if that is useful."
    )
    lines.append("Thank you for your time.")
    lines.append(_signature(profile))

    body = "\n\n".join(line for line in lines if line.strip())

    draft.research_citations.append(
        Citation(
            label=f"{year} — {(paper.title or '').strip()}",
            detail="The paper the opening line names.",
            source_url=paper.url,
            side="research",
        )
    )
    for overlap in ([connection] if connection is not None else [])[:1] + [
        o for o in overlaps if o is not connection
    ][:1]:
        draft.research_citations.append(
            Citation(
                label=overlap.label,
                detail=(overlap.evidence or "").strip(),
                source_url=overlap.source_url,
                side="research",
            )
        )

    draft.body = body
    draft.subject = _subject(topic)
    draft.word_count = _words(body)
    draft.todos = _todos(draft, profile)
    return draft


def _background_sentence(item: fit_service.BackgroundPoint) -> str:
    """State one stored fact plainly, in the register it belongs to."""
    detail = (item.detail or "").strip()
    if item.kind == "coursework":
        return f"I have taken {item.label}" + (f" ({detail})." if detail else ".")
    if item.kind == "skill":
        return f"I have worked with {item.label}."
    return f"I have experience with {item.label}."


def _signature(profile: StudentProfile) -> str:
    """The sign-off. Blank rather than invented if we do not know their name."""
    user = getattr(profile, "user", None)
    return ((getattr(user, "display_name", None) or "") if user else "").strip()


def _study_line(profile: StudentProfile) -> str | None:
    """One sentence about who is writing, from stored fields only."""
    major = (profile.major or "").strip()
    if not major:
        return None
    year = f" graduating in {profile.graduation_year}" if profile.graduation_year else ""
    return f"I am a Stanford undergraduate studying {major}{year}."


def _hours_line(profile: StudentProfile) -> str | None:
    """Availability, but only the numbers the student actually entered."""
    low = getattr(profile, "hours_per_week_min", None)
    high = getattr(profile, "hours_per_week_max", None)
    if low and high:
        return f"I can commit {low}\u2013{high} hours a week."
    if high:
        return f"I can commit up to {high} hours a week."
    if low:
        return f"I can commit at least {low} hours a week."
    return None


def _subject(topic: str | None) -> str:
    return (
        f"Stanford undergraduate interested in your {topic} work"
        if topic
        else "Stanford undergraduate interested in joining your lab"
    )


def _todos(draft: OutreachDraft, profile: StudentProfile) -> list[str]:
    """What the student must do before this is sendable. Never silent."""
    todos = [
        "Read the paper named in the first line before you send this — the email says it is why "
        "you are writing, and you should be able to say something about it.",
        "Rewrite at least one sentence in your own voice. A professor can tell.",
    ]
    if draft.word_count and draft.word_count < MIN_WORDS:
        todos.append(
            f"This is {draft.word_count} words, which is thin. Add one specific sentence about "
            "what you would want to work on."
        )
    if draft.word_count > MAX_WORDS:
        todos.append(
            f"This is {draft.word_count} words. Cut it to about {MAX_WORDS} — long cold emails "
            "do not get read."
        )
    if not _signature(profile):
        todos.append("Add your name to your profile — the sign-off is currently blank.")
    return todos


def build_draft(
    db: Session,
    faculty: Faculty,
    profile: StudentProfile | None,
    *,
    this_year: int,
) -> OutreachDraft | None:
    """The draft for a real lab and a real student, or ``None`` with no profile."""
    if profile is None:
        return None
    breakdown = fit_service.build_fit(db, faculty, profile)
    return compose_draft(faculty, profile, breakdown, this_year=this_year)
