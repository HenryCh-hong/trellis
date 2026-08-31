"""Is this page actually an opportunity?

A crawler that follows links finds mostly *pages*, not *openings*. Without a
gate, a run over cs.stanford.edu turns "PhD", "Master's", "Joint Programs" and
"Eligibility Requirements for All Applicants" into things the student is invited
to apply for. That is worse than finding nothing: it buries the real postings
and costs the student attention.

So a document has to earn its place. The test is evidence-based rather than
keyword-based: something a student could act on — a way to apply, a stated
qualification, a deadline, pay, or hours — must be present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Titles that are navigation, not opportunities. Matched whole, case-folded.
NAVIGATION_TITLES = frozenset(
    {
        "bachelor's",
        "bachelors",
        "master's",
        "masters",
        "phd",
        "ph.d.",
        "overview",
        "academics",
        "admissions",
        "people",
        "faculty",
        "research",
        "home",
        "contact",
        "contact us",
        "students",
        "student resources",
        "courses",
        "programs",
        "joint programs",
        "honors program",
        "undergraduate",
        "graduate",
        "alumni",
        "news",
        "events",
        "about",
        "resources",
        "forms",
        "faq",
        "frequently asked questions",
        "eligibility",
        "financial aid",
        "tuition",
        "how to apply",
    }
)

# Phrases that mark a page as explanatory rather than an opening.
INFORMATIONAL_TITLE_PATTERNS = (
    re.compile(r"^what (type|kind|is|are)\b", re.I),
    re.compile(r"^(explore|about|understanding|introduction to)\b", re.I),
    re.compile(r"\b(requirements?|deadlines?|overview|guidelines?|policy|policies|handbook)\s*$", re.I),
    re.compile(r"^(degree|program|curriculum|course)\s+(requirements?|overview|sheet)", re.I),
    re.compile(r"\|\s*(computer science|stanford)\s*$", re.I),
)

APPLY_SIGNALS = (
    "apply",
    "application",
    "submit your",
    "how to apply",
    "deadline",
    "we are hiring",
    "now hiring",
    "position",
    "openings",
    "job description",
    "responsibilities",
    "qualifications",
    "compensation",
    "hourly",
    "per hour",
    "stipend",
    "hours per week",
)

MIN_TEXT_CHARS = 400

# "Professor of Linguistics", "Canon Professor in the School of Engineering",
# "Associate Professor of Computer Science and, by courtesy, of Psychology".
ACADEMIC_TITLE_RE = re.compile(
    r"^\s*(the\s+)?[\w.,'&\- ]*\b"
    r"(professor|lecturer|senior fellow|professor emerit\w+|chair|dean|provost)\b"
    r"(\s+(of|in|,|and|by courtesy|at)\b|\s*$)",
    re.I,
)


@dataclass(slots=True)
class Relevance:
    keep: bool
    reason: str
    signals: list[str]


def _clean_title(title: str | None) -> str:
    if not title:
        return ""
    # Strip the site-name suffix pattern "Page | Section | Site".
    head = title.split("|")[0]
    return " ".join(head.split()).strip().lower()


def looks_like_opportunity(
    data: dict[str, Any], text: str | None, *, require_body: bool = True
) -> Relevance:
    """Decide whether an extracted document should become an opportunity.

    ``require_body`` applies only on the crawl path, where the full page text is
    in hand and a thin page really is a navigation stub. Rows already in the
    database store a *summary*, not the page, so judging those on length would
    throw away real postings — CURIS and the R&DE dining roles both have short
    descriptions and are unquestionably real. For those, structured evidence
    alone decides.
    """
    title = _clean_title(data.get("title"))
    body = (text or "")[:12000]
    lowered = body.lower()

    if not title:
        return Relevance(False, "no title could be read from the page", [])

    if title in NAVIGATION_TITLES:
        return Relevance(False, f"title {title!r} is a navigation label, not an opening", [])

    # A faculty directory row's "title" is the person's academic title. Those
    # arrive from the faculty adapter and belong to the research pipeline, not
    # the opportunity table.
    if ACADEMIC_TITLE_RE.search(data.get("title") or ""):
        return Relevance(
            False, "reads as an academic title (a person), not a posting", []
        )

    for pattern in INFORMATIONAL_TITLE_PATTERNS:
        if pattern.search(data.get("title") or ""):
            # An informational title can still be a real posting if the page
            # carries hard evidence, so fall through to the signal check rather
            # than rejecting outright.
            break

    signals: list[str] = []
    if data.get("deadline"):
        signals.append("stated deadline")
    if data.get("pay_text") or data.get("pay_min"):
        signals.append("stated pay")
    if data.get("hours_per_week"):
        signals.append("stated hours")
    if data.get("contact_email"):
        signals.append("contact email")

    requirements = data.get("requirements") or []
    if len(requirements) >= 2:
        signals.append(f"{len(requirements)} stated qualifications")

    method = (data.get("application_method") or "").lower()
    if method and method not in ("unknown", "external"):
        signals.append(f"application method: {method}")
    elif data.get("application_url"):
        signals.append("application link")

    hits = [s for s in APPLY_SIGNALS if s in lowered]
    if len(hits) >= 3:
        signals.append("application language on the page")

    if require_body and len(body) < MIN_TEXT_CHARS and not signals:
        return Relevance(
            False,
            f"only {len(body)} characters of text and no application signal",
            signals,
        )

    # Informational titles need harder evidence than a posting-shaped title.
    informational = any(p.search(data.get("title") or "") for p in INFORMATIONAL_TITLE_PATTERNS)
    needed = 2 if informational else 1

    if len(signals) < needed:
        return Relevance(
            False,
            "no application signal: nothing to apply to, no deadline, pay, hours or qualifications",
            signals,
        )

    return Relevance(True, f"kept on {len(signals)} signal(s)", signals)
