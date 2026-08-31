"""Read a resume the student uploaded. Never rewrite one.

Three rules shape this module:

1. **The upload is immutable.**  We open files read-only and keep the original
   bytes on disk untouched; everything here produces a *derived* view.
2. **Quoted text is verbatim.**  Anything the UI will show back as "your
   experience" is lifted character-for-character from the document.  Only
   formatting is normalised (a leading bullet glyph, a soft line wrap) — never
   wording, casing or punctuation inside the line.
3. **Precision over recall.**  ``extract_coursework`` and ``extract_experiences``
   feed the student's profile, so a wrong entry is a defect while a missing one
   is merely a gap the student can fill in by hand.  When the text does not
   clearly support an entry, we emit nothing.

The product never generates or tailors resume content; ``app.agents.resume_agent``
only ranks the documents the student already uploaded.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.services.taxonomy import match_skills, match_topics
from app.services.text import extract_course_codes

PARSE_OK = "parsed"
PARSE_FAILED = "failed"

SCANNED_PDF_ERROR = (
    "This PDF has no extractable text — it may be a scan. Upload a text-based PDF."
)

PDF_SUFFIXES = frozenset({".pdf"})
TEXT_SUFFIXES = frozenset({".txt", ".text", ".md", ".markdown"})
SUPPORTED_SUFFIXES = PDF_SUFFIXES | TEXT_SUFFIXES

# Enough non-whitespace characters that we believe a text layer really exists.
_MIN_EXTRACTABLE_CHARS = 40


# --------------------------------------------------------------------------
# Canonical vocabulary
#
# Skill and topic recognition belongs to ``app.services.taxonomy`` so that a
# resume line, a profile and a job posting are all read against exactly one
# vocabulary — otherwise "matched strength" would compare different alphabets.
# --------------------------------------------------------------------------


def detect_skills(text: str | None) -> list[str]:
    """Canonical skill slugs evidenced by ``text``. Empty when nothing matches."""
    return [slug for slug, _ in match_skills(text)]


def detect_skill_evidence(text: str | None) -> dict[str, str]:
    """Skill slug -> the quotable fragment of ``text`` that supports it."""
    return dict(match_skills(text))


def detect_topics(text: str | None, *, min_weight: float = 0.0) -> list[str]:
    """Topic slugs evidenced by ``text``, strongest first."""
    return [slug for slug, weight in match_topics(text) if weight >= min_weight]


# --------------------------------------------------------------------------
# Section headings
# --------------------------------------------------------------------------

SECTION_NAMES: tuple[str, ...] = (
    "education",
    "experience",
    "projects",
    "research",
    "skills",
    "coursework",
    "publications",
    "awards",
    "activities",
)

# Ordered most-specific first: "Research Experience" is research, not experience.
_SECTION_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("publications", ("publication", "publications", "preprint", "preprints", "papers", "posters")),
    ("coursework", ("coursework", "course work", "courses", "classes")),
    ("research", ("research",)),
    ("projects", ("project", "projects")),
    (
        "awards",
        (
            "award",
            "awards",
            "honor",
            "honors",
            "honours",
            "fellowship",
            "fellowships",
            "scholarship",
            "scholarships",
            "distinctions",
        ),
    ),
    (
        "activities",
        (
            "activity",
            "activities",
            "extracurricular",
            "extracurriculars",
            "leadership",
            "involvement",
            "service",
            "volunteer",
            "volunteering",
            "clubs",
            "organizations",
        ),
    ),
    ("skills", ("skill", "skills", "technologies", "tools", "proficiencies")),
    ("education", ("education", "academics")),
    (
        "experience",
        (
            "experience",
            "employment",
            "internship",
            "internships",
            "positions",
            "work history",
        ),
    ),
)

# Words allowed to decorate a heading without making it body text.
_HEADING_FILLER = frozenset(
    ["relevant", "selected", "technical", "professional", "work", "academic", "other", "additional", "personal", "related", "key", "notable", "recent", "and", "or", "of", "in", "my", "the", "history", "community", "interests", "industry", "background", "current", "ongoing", "university", "college", "campus", "misc", "miscellaneous", "summary", "select", "core"]
)

_SECTION_TOKENS = frozenset(
    token for _, phrases in _SECTION_KEYWORDS for phrase in phrases for token in phrase.split()
)

BULLET_CHARS = "•·‣▪▫◦●○∙▸▹►■□-–—*"
_BULLET_RE = re.compile(rf"^[{re.escape(BULLET_CHARS)}]+\s+")
_WS_RE = re.compile(r"\s+")

# PDF fonts encode these as single glyphs; they are spellings of ordinary words.
_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "\u00a0": " ",
}


def _clean_text(raw: str) -> str:
    """Fix the artefacts PDF text extraction leaves behind. Wording is untouched."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    for bad, good in _LIGATURES.items():
        text = text.replace(bad, good)
    # Drop control/format characters (zero-width joiners, BOMs) but keep layout.
    text = "".join(
        ch for ch in text if ch in "\n\t" or not unicodedata.category(ch).startswith("C")
    )
    return "\n".join(line.strip() for line in text.split("\n"))


def _normalize_heading(candidate: str) -> str:
    lowered = candidate.lower().replace("&", " ")
    stripped = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return _WS_RE.sub(" ", stripped).strip()


def _match_section(normalized: str) -> str | None:
    for name, phrases in _SECTION_KEYWORDS:
        for phrase in phrases:
            if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized):
                return name
    return None


def classify_heading(line: str) -> tuple[str, str] | None:
    """Return ``(section, inline_content)`` when ``line`` opens a known section.

    ``inline_content`` is non-empty for one-liners like ``Skills: Python, C++``,
    where the heading and its content share a line.
    """
    raw = line.strip()
    if not raw or raw[0] in BULLET_CHARS:
        return None
    head, sep, rest = raw.partition(":")
    candidate = (head if sep else raw).strip()
    # The label itself must be short; an inline heading's content may not be.
    if not candidate or len(candidate) > 64 or len(candidate.split()) > 5:
        return None
    normalized = _normalize_heading(candidate)
    if not normalized:
        return None
    tokens = normalized.split()
    if any(token not in _SECTION_TOKENS and token not in _HEADING_FILLER for token in tokens):
        return None
    section = _match_section(normalized)
    if section is None:
        return None
    # A heading is set apart from body text: a colon, ALL CAPS, or Title Case.
    if sep or candidate.isupper() or _is_title_case(candidate):
        return section, rest.strip()
    return None


def _is_title_case(candidate: str) -> bool:
    words = [w for w in re.split(r"[\s/&-]+", candidate) if w]
    if not words:
        return False
    return all(w[0].isupper() or not w[0].isalpha() for w in words)


def _is_continuation(previous: str, current: str) -> bool:
    """A soft-wrapped tail of the previous line rather than a new item."""
    if not current:
        return False
    first_alpha = next((ch for ch in current if ch.isalpha()), "")
    if first_alpha and first_alpha.islower():
        return True
    return previous.rstrip().endswith((",", ";", "/", "&", "+", "-"))


@dataclass(slots=True)
class LineRecord:
    """One physical line, with where it sits in the document."""

    index: int
    text: str
    section: str | None
    is_heading: bool
    is_bullet: bool
    content: str


def segment_lines(lines: Sequence[str]) -> list[LineRecord]:
    """Assign every line to a section.

    A block heading (``EXPERIENCE`` on its own line) stays open until the next
    heading.  An inline heading (``Relevant Coursework: CS 106B, CS 107``) covers
    only that line and its wrapped continuations, so the rest of the enclosing
    section is not swallowed by it.
    """
    records: list[LineRecord] = []
    block_section: str | None = None
    inline_section: str | None = None
    previous_text = ""

    for index, raw in enumerate(lines):
        text = raw.strip()
        if not text:
            previous_text = ""
            continue
        heading = classify_heading(text)
        is_bullet = bool(_BULLET_RE.match(text))
        if heading is not None:
            section, inline_content = heading
            if inline_content:
                inline_section = section
                records.append(
                    LineRecord(index, text, section, is_heading=True, is_bullet=False, content=inline_content)
                )
            else:
                block_section = section
                inline_section = None
                records.append(
                    LineRecord(index, text, section, is_heading=True, is_bullet=False, content=text)
                )
            previous_text = text
            continue

        if inline_section is not None and not (is_bullet or _is_continuation(previous_text, text)):
            inline_section = None

        section = inline_section or block_section
        content = _BULLET_RE.sub("", text).strip() if is_bullet else text
        records.append(
            LineRecord(index, text, section, is_heading=False, is_bullet=is_bullet, content=content)
        )
        previous_text = text

    return records


@dataclass(slots=True)
class ParsedResume:
    """The derived, read-only view of an uploaded resume."""

    text: str
    page_count: int | None
    sections: dict[str, str]
    lines: list[str]
    stats: dict[str, Any]
    records: list[LineRecord] = field(default_factory=list)
    parse_status: str = PARSE_OK
    parse_error: str | None = None
    source_name: str | None = None

    @property
    def ok(self) -> bool:
        return self.parse_status == PARSE_OK

    def section(self, name: str) -> str:
        return self.sections.get(name, "")


def _failed(reason: str, *, page_count: int | None, source_name: str | None) -> ParsedResume:
    return ParsedResume(
        text="",
        page_count=page_count,
        sections={},
        lines=[],
        stats={"characters": 0, "words": 0, "lines": 0, "bullets": 0, "sections": []},
        records=[],
        parse_status=PARSE_FAILED,
        parse_error=reason,
        source_name=source_name,
    )


def parse_text(text: str, *, page_count: int | None = None, source_name: str | None = None) -> ParsedResume:
    """Build a ``ParsedResume`` from already-extracted text."""
    cleaned = _clean_text(text)
    lines = [line for line in cleaned.split("\n") if line.strip()]
    records = segment_lines(lines)

    sections: dict[str, str] = {}
    for record in records:
        body = record.content.strip()
        # A block heading is a label, not content; an inline one carries the
        # part after the colon.
        if record.section is None or not body or (record.is_heading and body == record.text.strip()):
            continue
        sections.setdefault(record.section, "")
        sections[record.section] = f"{sections[record.section]}\n{body}".strip()

    words = len(cleaned.split())
    stats: dict[str, Any] = {
        "characters": len(cleaned),
        "words": words,
        "lines": len(lines),
        "bullets": sum(1 for r in records if r.is_bullet),
        "sections": [name for name in SECTION_NAMES if name in sections],
        "headings": [r.text for r in records if r.is_heading],
        "page_count": page_count,
        "has_email": bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", cleaned)),
        "has_link": bool(re.search(r"https?://|github\.com|linkedin\.com", cleaned, re.IGNORECASE)),
    }
    if page_count:
        stats["words_per_page"] = round(words / page_count, 1)

    return ParsedResume(
        text=cleaned,
        page_count=page_count,
        sections=sections,
        lines=lines,
        stats=stats,
        records=records,
        source_name=source_name,
    )


def parse_pdf(path: str | Path) -> ParsedResume:
    """Extract text from a PDF. The file is only ever opened for reading."""
    from pypdf import PdfReader  # noqa: PLC0415 — keeps import cost off app startup

    source = Path(path)
    name = source.name
    page_count: int | None = None
    try:
        with source.open("rb") as handle:
            reader = PdfReader(handle)
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception:  # noqa: BLE001 — any failure means "we cannot read it"
                    return _failed(
                        "This PDF is password-protected. Upload an unlocked copy.",
                        page_count=None,
                        source_name=name,
                    )
            page_count = len(reader.pages)
            pages: list[str] = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:  # noqa: BLE001 — one bad page must not lose the rest
                    pages.append("")
    except FileNotFoundError:
        return _failed(f"File not found: {name}", page_count=None, source_name=name)
    except Exception as exc:  # noqa: BLE001 — pypdf raises a wide range on damaged files
        return _failed(
            f"This PDF could not be read ({type(exc).__name__}). Try re-exporting it.",
            page_count=page_count,
            source_name=name,
        )

    raw = "\n".join(pages)
    if len(re.sub(r"\s", "", raw)) < _MIN_EXTRACTABLE_CHARS:
        return _failed(SCANNED_PDF_ERROR, page_count=page_count, source_name=name)

    parsed = parse_text(raw, page_count=page_count, source_name=name)
    parsed.stats["empty_pages"] = sum(1 for p in pages if not p.strip())
    return parsed


_MD_EMPHASIS_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+")


def parse_plain_text(path: str | Path) -> ParsedResume:
    """Read a .txt / .md resume. Markdown *formatting* markers are dropped; words are not."""
    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return _failed(f"File not found: {source.name}", page_count=None, source_name=source.name)
    except OSError as exc:
        return _failed(f"This file could not be read ({exc.strerror}).", page_count=None, source_name=source.name)

    if source.suffix.lower() in {".md", ".markdown"}:
        lines = [_MD_HEADING_RE.sub("", line) for line in raw.split("\n")]
        raw = "\n".join(_MD_EMPHASIS_RE.sub(r"\2", line) for line in lines)

    if len(re.sub(r"\s", "", raw)) < _MIN_EXTRACTABLE_CHARS:
        return _failed(
            "This file is empty or too short to read as a resume.",
            page_count=None,
            source_name=source.name,
        )
    return parse_text(raw, source_name=source.name)


def parse_resume(path: str | Path, *, content_type: str | None = None) -> ParsedResume:
    """Parse an upload by extension, falling back to its declared content type."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix in PDF_SUFFIXES or (not suffix and content_type == "application/pdf"):
        return parse_pdf(source)
    if suffix in TEXT_SUFFIXES or (content_type or "").startswith("text/"):
        return parse_plain_text(source)
    return _failed(
        f"Unsupported file type '{suffix or content_type or 'unknown'}'. Upload a PDF, .txt or .md resume.",
        page_count=None,
        source_name=source.name,
    )


# --------------------------------------------------------------------------
# Highlights — the verbatim lines the UI quotes back
# --------------------------------------------------------------------------

_MIN_UNBULLETED_CHARS = 60
_MIN_UNBULLETED_WORDS = 9

_MONTHS = (
    "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
    "january|february|march|april|june|july|august|september|october|november|december"
)
_DATE_TOKEN = rf"(?:(?:{_MONTHS})\.?\s+\d{{4}}|\d{{4}}|present|current|now|ongoing)"
_DATE_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE_TOKEN})\s*(?:–|—|-|to|until)\s*(?P<end>{_DATE_TOKEN})", re.IGNORECASE
)
_MONTH_YEAR_RE = re.compile(rf"(?P<month>{_MONTHS})\.?\s+(?P<year>\d{{4}})", re.IGNORECASE)
_MONTH_INDEX = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9,
    "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12,
    "december": 12,
}


def _looks_like_entry_header(text: str) -> bool:
    """A role/company/date line rather than an accomplishment."""
    if _DATE_RANGE_RE.search(text):
        return True
    return text.count("|") >= 2 or bool(re.search(r"\b\d{4}\s*[–—-]\s*(?:\d{4}|present)\b", text, re.I))


@dataclass(slots=True)
class Highlight:
    """A line lifted from the resume, unchanged."""

    text: str
    section: str | None
    line_index: int
    skills: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)


def extract_highlights(parsed: ParsedResume) -> list[Highlight]:
    """Bullet lines, verbatim, with the skills and topics each one evidences.

    Soft-wrapped bullets are re-joined with a single space — the wrap is a
    property of the page, not of what the student wrote.
    """
    if not parsed.ok:
        return []

    records = parsed.records
    highlights: list[Highlight] = []
    seen: set[str] = set()
    consumed: set[int] = set()

    for position, record in enumerate(records):
        if record.is_heading or position in consumed:
            continue

        pieces = [record.content]
        if record.is_bullet:
            cursor = position + 1
            while cursor < len(records):
                nxt = records[cursor]
                if nxt.is_heading or nxt.is_bullet or nxt.section != record.section:
                    break
                if not _is_continuation(pieces[-1], nxt.text):
                    break
                pieces.append(nxt.text)
                consumed.add(cursor)
                cursor += 1
        else:
            # No bullet glyph survived extraction: only accept a line that is
            # unmistakably prose about work done, never a header or contact line.
            words = record.content.split()
            if (
                len(record.content) < _MIN_UNBULLETED_CHARS
                or len(words) < _MIN_UNBULLETED_WORDS
                or record.section in {"skills", "coursework", "education", None}
                or _looks_like_entry_header(record.content)
                or record.content.isupper()
            ):
                continue

        text = " ".join(piece.strip() for piece in pieces).strip()
        key = _WS_RE.sub(" ", text.lower())
        if len(text) < 12 or key in seen:
            continue
        seen.add(key)
        highlights.append(
            Highlight(
                text=text,
                section=record.section,
                line_index=record.index,
                skills=detect_skills(text),
                topics=detect_topics(text),
            )
        )
    return highlights


# --------------------------------------------------------------------------
# Coursework
# --------------------------------------------------------------------------

# Locates the code; ``text.extract_course_codes`` owns its canonical spelling,
# so a course on a resume compares equal to the same course in a posting.
_COURSE_CODE_RE = re.compile(r"\b[A-Z]{2,8}\s?-?\s?\d{1,3}[A-Z]{0,2}\b")
_COURSE_SPLIT_RE = re.compile(r"\s*[;,]\s*|\s+[•·|]\s+")
_COURSE_BANNED = frozenset(
    ["gpa", "dean", "list", "honors", "honor", "award", "awards", "scholarship", "fellowship", "expected", "graduation", "minor", "major", "degree", "bachelor", "bs", "ba", "university", "college", "school", "class", "rank", "president"]
)


@dataclass(slots=True)
class CourseworkEntry:
    code: str | None
    title: str
    term: str | None
    topics: list[str]
    source_text: str
    confidence: float


def _clean_course_item(item: str) -> str:
    return item.strip(" \t.-–—•*()").strip()


def extract_coursework(parsed: ParsedResume) -> list[CourseworkEntry]:
    """Courses the resume actually lists.

    Only a coursework section counts, and only items carrying a course code or
    sitting in a list that clearly is one.  "Dean's List" is not a course.
    """
    if not parsed.ok:
        return []
    body = parsed.section("coursework")
    if not body.strip():
        return []

    entries: list[CourseworkEntry] = []
    seen: set[str] = set()
    for line in body.split("\n"):
        items = [_clean_course_item(part) for part in _COURSE_SPLIT_RE.split(line)]
        items = [item for item in items if item]
        if not items:
            continue
        coded = sum(1 for item in items if _COURSE_CODE_RE.search(item))
        list_is_courses = coded >= max(1, len(items) // 2)

        for item in items:
            if len(item) > 90 or len(item.split()) > 8:
                continue
            lowered = set(re.findall(r"[a-z']+", item.lower()))
            if lowered & _COURSE_BANNED:
                continue
            match = _COURSE_CODE_RE.search(item)
            canonical = extract_course_codes(match.group(0)) if match else []
            code = canonical[0] if canonical else None
            title = _clean_course_item(item[: match.start()] + item[match.end() :]) if match else item
            title = title.strip(" :–—-") or (code or "")
            # With no course code, accept the line only inside a list that is
            # evidently courses, and only when it reads like a course title.
            if code is None and (
                not list_is_courses or len(item.split()) < 2 or not item[0].isupper()
            ):
                continue
            if not title:
                continue
            key = (code or title).lower()
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                CourseworkEntry(
                    code=code,
                    title=title,
                    term=None,
                    topics=detect_topics(item),
                    source_text=line.strip(),
                    confidence=0.9 if code else 0.6,
                )
            )
    return entries


# --------------------------------------------------------------------------
# Experiences
# --------------------------------------------------------------------------

_ROLE_KEYWORDS = (
    "research assistant", "research intern", "undergraduate researcher", "researcher",
    "teaching assistant", "course assistant", "section leader", "tutor", "grader", "instructor",
    "software engineer", "engineer", "developer", "programmer", "data scientist", "analyst",
    "intern", "assistant", "associate", "fellow", "ambassador", "coordinator", "manager",
    "supervisor", "lead", "director", "president", "treasurer", "secretary", "chair",
    "barista", "server", "cashier", "host", "hostess", "attendant", "clerk", "technician",
    "lifeguard", "counselor", "volunteer", "consultant", "designer", "writer", "editor",
)
_ROLE_RE = re.compile(
    "|".join(rf"(?<!\w){re.escape(kw)}(?!\w)" for kw in _ROLE_KEYWORDS), re.IGNORECASE
)
_ORG_HINT_RE = re.compile(
    r"\b(university|college|lab|laboratory|institute|center|centre|department|school|group|"
    r"inc\.?|llc|ltd|corp\.?|company|foundation|library|dining|hall|café|cafe|coffee|"
    r"restaurant|store|hospital|clinic|museum|studio|society|club|association)\b",
    re.IGNORECASE,
)
_PART_SPLIT_RE = re.compile(r"\s+[–—|·]\s+|\s+-\s+|\s{2,}|\t+")
_RESEARCH_ROLE_RE = re.compile(r"research|\blab\b|thesis|scientist", re.IGNORECASE)


@dataclass(slots=True)
class ExperienceEntry:
    organization: str
    role: str
    kind: str | None
    started_on: date | None
    ended_on: date | None
    is_current: bool
    date_text: str | None
    highlights: list[str]
    skills: list[str]
    source_text: str
    confidence: float


def _parse_month_year(token: str) -> date | None:
    match = _MONTH_YEAR_RE.search(token)
    if not match:
        return None
    month = _MONTH_INDEX.get(match.group("month").lower())
    if month is None:
        return None
    return date(int(match.group("year")), month, 1)


def _split_header(text: str) -> tuple[list[str], str | None]:
    """Split an entry header into its parts, pulling out the date range."""
    date_text: str | None = None
    remainder = text
    match = _DATE_RANGE_RE.search(text)
    if match:
        date_text = match.group(0)
        remainder = (text[: match.start()] + " " + text[match.end() :]).strip()
    else:
        solo = _MONTH_YEAR_RE.search(text)
        if solo and solo.start() > 0:
            date_text = solo.group(0)
            remainder = (text[: solo.start()] + " " + text[solo.end() :]).strip()
    parts = [p.strip(" ,;()–—-|") for p in _PART_SPLIT_RE.split(remainder)]
    if len(parts) < 2:
        parts = [p.strip() for p in re.split(r"\s+at\s+|,\s+", remainder, maxsplit=1)]
    return [p for p in parts if p], date_text


def extract_experiences(parsed: ParsedResume) -> list[ExperienceEntry]:
    """Roles the resume states outright.

    An entry is emitted only when one part of the header names a recognisable
    role and another names the organisation.  Anything ambiguous is skipped:
    these rows become the student's profile, so a wrong one is worse than none.
    """
    if not parsed.ok:
        return []

    wanted = {"experience", "research", "activities"}
    entries: list[ExperienceEntry] = []
    records = parsed.records

    for position, record in enumerate(records):
        if record.is_heading or record.is_bullet or record.section not in wanted:
            continue
        text = record.content.strip()
        if len(text) < 8 or len(text) > 180:
            continue

        parts, date_text = _split_header(text)
        if len(parts) < 2:
            continue
        role_parts = [p for p in parts if _ROLE_RE.search(p)]
        if len(role_parts) != 1:
            continue
        role = role_parts[0]
        others = [p for p in parts if p is not role]
        org = next((p for p in others if _ORG_HINT_RE.search(p)), others[0])
        if not org or len(org) < 2 or org == role:
            continue

        started = ended = None
        is_current = False
        if date_text:
            bounds = _DATE_RANGE_RE.search(date_text)
            if bounds:
                started = _parse_month_year(bounds.group("start"))
                end_token = bounds.group("end").lower()
                if end_token in {"present", "current", "now", "ongoing"}:
                    is_current = True
                else:
                    ended = _parse_month_year(bounds.group("end"))
            else:
                started = _parse_month_year(date_text)

        bullets: list[str] = []
        cursor = position + 1
        while cursor < len(records):
            nxt = records[cursor]
            if nxt.is_heading or nxt.section != record.section:
                break
            if nxt.is_bullet:
                bullets.append(nxt.content)
            elif bullets or _ROLE_RE.search(nxt.content):
                break
            cursor += 1

        blob = "\n".join([text, *bullets])
        kind = "research" if record.section == "research" or _RESEARCH_ROLE_RE.search(role) else None
        if kind is None:
            kind = "activity" if record.section == "activities" else "job"

        entries.append(
            ExperienceEntry(
                organization=org,
                role=role,
                kind=kind,
                started_on=started,
                ended_on=ended,
                is_current=is_current,
                date_text=date_text,
                highlights=bullets,
                skills=detect_skills(blob),
                source_text=text,
                confidence=0.9 if date_text and len(parts) >= 2 else 0.7,
            )
        )
    return entries


# --------------------------------------------------------------------------
# One-call ingestion
# --------------------------------------------------------------------------


@dataclass(slots=True)
class ResumeAnalysis:
    """Everything the upload endpoint needs to persist a ``Resume`` row."""

    parsed: ParsedResume
    highlights: list[Highlight]
    coursework: list[CourseworkEntry]
    experiences: list[ExperienceEntry]
    skills: list[str]
    topics: list[str]

    @property
    def parse_status(self) -> str:
        return self.parsed.parse_status

    @property
    def parse_error(self) -> str | None:
        return self.parsed.parse_error


def analyze(parsed: ParsedResume) -> ResumeAnalysis:
    highlights = extract_highlights(parsed)
    skills = detect_skills(parsed.text) if parsed.ok else []
    topics = detect_topics(parsed.text) if parsed.ok else []
    return ResumeAnalysis(
        parsed=parsed,
        highlights=highlights,
        coursework=extract_coursework(parsed),
        experiences=extract_experiences(parsed),
        skills=skills,
        topics=topics,
    )


def analyze_resume(path: str | Path, *, content_type: str | None = None) -> ResumeAnalysis:
    """Parse and analyse an uploaded file in one call. Never writes to it."""
    return analyze(parse_resume(path, content_type=content_type))
