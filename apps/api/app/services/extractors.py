"""Deterministic extraction of the facts a decision depends on.

Everything in this module is regex + heuristic: no model, no network, no
guessing.  Each function returns an :class:`Evidenced` value carrying the
confidence and the *quoted* source text behind it, so the UI can say
Verified / Likely / Inferred / Unknown honestly (spec §20/§23).

Two rules are load-bearing and are enforced here rather than downstream:

* A "preferred" qualification is never promoted to "required".  Demotion is
  always allowed (it is the safe direction); promotion never is.
* A date is never invented.  When a posting states a month and day but no
  year we say so in ``source_text`` and drop confidence; when a posting states
  nothing we return ``None`` with confidence 0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, NamedTuple
from urllib.parse import urlparse

from app.llm.base import Evidenced
from app.models.enums import DeadlineType, ExtractionMethod, RequirementKind

EXTRACTOR_VERSION = "extractors-1"

MAX_SOURCE_TEXT = 400
MAX_REQUIREMENTS = 60


class ApplicationMethod(StrEnum):
    """How a student actually submits.  Stored as a plain string on the
    opportunity; kept as an enum here so callers stop typing literals."""

    HANDSHAKE = "handshake"
    EMAIL = "email"
    FORM = "form"
    EXTERNAL = "external"
    IN_PERSON = "in_person"
    UNKNOWN = "unknown"


class HoursExtraction(NamedTuple):
    hours: Evidenced[int]
    note: str | None


# --------------------------------------------------------------------------
# text utilities
# --------------------------------------------------------------------------

_WS_RE = re.compile(r"[ \t ]+")
_BLANKS_RE = re.compile(r"\n{3,}")
# Sentence-ish boundaries.  ':' is deliberately NOT a boundary: it would cut
# "Deadline: 9/15/26" in half and throw away the cue that makes the date a
# deadline at all.
_BOUNDARY_RE = re.compile(r"(?<=[.!?;])\s+|\n+|•")


def normalize_text(raw: str | None) -> str:
    """Fold the punctuation variants pages actually ship, keep line structure."""
    if not raw:
        return ""
    text = raw.replace(" ", " ")
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = _WS_RE.sub(" ", text)
    text = _BLANKS_RE.sub("\n\n", text)
    return text.strip()


def _sentence_span(text: str, start: int, end: int) -> tuple[int, int]:
    left = 0
    for match in _BOUNDARY_RE.finditer(text, 0, start):
        left = match.end()
    match = _BOUNDARY_RE.search(text, end)
    right = match.start() if match else len(text)
    return left, right


def _clip(value: str, limit: int = MAX_SOURCE_TEXT) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _sentence(text: str, start: int, end: int) -> str:
    left, right = _sentence_span(text, start, end)
    return _clip(text[left:right])


# --------------------------------------------------------------------------
# deadlines
# --------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}  # fmt: skip

_MONTH_ALT = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)

_DATE_MDY_RE = re.compile(
    rf"\b(?P<month>{_MONTH_ALT})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?"
    rf"(?:\s*,?\s*(?P<year>\d{{4}}))?\b",
    re.I,
)
_DATE_DMY_RE = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<month>{_MONTH_ALT})\.?"
    rf"(?:\s*,?\s*(?P<year>\d{{4}}))?\b",
    re.I,
)
_DATE_NUM_RE = re.compile(r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{2,4}))?\b")
_DATE_ISO_RE = re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")

_HARD_DEADLINE_PATTERNS = (
    r"\bapplication\s+deadline\b",
    r"\bdeadline\b",
    r"\bdue\s+date\b",
    r"\bapplications?\s+(?:are|is|were|was)?\s*due\b",
    r"\bdue\s+(?:on|by|before|no\s+later\s+than)\b",
    r"\bare\s+due\b",
    r"\bis\s+due\b",
    r"\bsubmit(?:ted)?\s+by\b",
    r"\bapply\s+by\b",
    r"\bapply\s+before\b",
    r"\bapplications?\s+(?:close|closes|closed)\b",
    r"\bclosing\s+date\b",
    r"\blast\s+day\s+to\s+apply\b",
    r"\bmust\s+be\s+(?:received|submitted|postmarked)\s+by\b",
    r"\bsubmit\s+(?:your\s+)?applications?\s+by\b",
    r"\baccepting\s+applications?\s+until\b",
    r"\bno\s+later\s+than\b",
)
_STRONG_CUE_RE = re.compile("|".join(_HARD_DEADLINE_PATTERNS), re.I)
_WEAK_CUE_RE = re.compile(
    r"\bappl(?:y|ication|ications|icants|icants')\b|\bsubmit\b|\bdue\b|\bpriority\b", re.I
)
_PRIORITY_RE = re.compile(r"\bpriority\b", re.I)
_NEGATIVE_CUE_RE = re.compile(
    r"\boffers?\s+are\s+made\b|\boffer\s+letters?\b|\bstart\s+date\b|\bstarts?\s+on\b|"
    r"\bbegins?\s+on\b|\bwill\s+begin\b|\bposted\s+(?:on|:)\b|\bdate\s+posted\b|"
    r"\binterviews?\s+(?:will|are|take)\b|\borientation\b|\btraining\s+(?:begins|starts)\b|"
    r"\bnotified\s+by\b|\bdecisions?\s+are\b|\bprogram\s+runs\b|\bruns\s+from\b|"
    r"\bwill\s+be\s+held\b|\bmeets?\s+on\b|\blast\s+updated\b|\bcopyright\b",
    re.I,
)

_ROLLING_PATTERNS = (
    r"\brolling\s+basis\b",
    r"\bon\s+a\s+rolling\b",
    r"\brolling\s+(?:admissions?|deadline|review)\b",
    r"\bopen\s+until\s+filled\b",
    r"\buntil\s+(?:the\s+)?(?:positions?|roles?|spots?|slots?|it|they)?\s*(?:is|are)?\s*filled\b",
    r"\byear[-\s]round\b",
    r"\bno\s+(?:fixed|set|firm|hard|formal)\s+deadline\b",
    r"\bno\s+(?:application\s+)?deadline\b",
    r"\bcontinuous(?:ly)?\s+accept",
    r"\bongoing\s+basis\b",
    r"\bapplications?\s+are\s+accepted\s+from\b",
    r"\bapplications?\s+are\s+accepted\s+(?:year[-\s]round|continuously|throughout)\b",
    r"\brevie(?:w|wed|ws)\s+(?:applications\s+)?as\s+(?:they\s+are\s+)?(?:received|submitted)\b",
    r"\bas\s+(?:they\s+are\s+)?received\b",
    r"\bthroughout\s+the\s+(?:year|quarter|academic\s+year)\b",
    r"\bat\s+any\s+time\b",
    r"\baccepts?\s+applications?\s+on\s+a\s+rolling\b",
)
_ROLLING_RE = re.compile("|".join(_ROLLING_PATTERNS), re.I)


@dataclass(slots=True)
class _DateHit:
    value: date
    start: int
    end: int
    had_year: bool
    year_note: str | None
    needs_strong_cue: bool


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _context_year(text: str, span: tuple[int, int], today: date) -> tuple[int, str] | None:
    """A year stated near the date — e.g. "the 2026-2027 academic year".

    Restricted to a window around 'now' so a stale copyright footer can never
    supply the year for a deadline.
    """
    left, right = span
    for window, label, width in (
        ((left, right), "in the same sentence", 0),
        ((max(0, left - 400), min(len(text), right + 400)), "nearby on the page", 400),
    ):
        del width
        for match in _YEAR_RE.finditer(text, window[0], window[1]):
            year = int(match.group(1))
            if today.year - 1 <= year <= today.year + 3:
                return year, f'year taken from "{match.group(1)}" {label}'
    return None


def _date_candidates(text: str, today: date) -> list[_DateHit]:
    hits: list[_DateHit] = []
    taken: list[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < t_end and t_start < end for t_start, t_end in taken)

    for match in _DATE_ISO_RE.finditer(text):
        value = _safe_date(int(match.group("y")), int(match.group("m")), int(match.group("d")))
        if value:
            hits.append(_DateHit(value, match.start(), match.end(), True, None, False))
            taken.append((match.start(), match.end()))

    for match in _DATE_NUM_RE.finditer(text):
        if overlaps(match.start(), match.end()):
            continue
        month, day = int(match.group("m")), int(match.group("d"))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        raw_year = match.group("y")
        if raw_year:
            year = int(raw_year)
            if year < 100:
                year += 2000 if year < 70 else 1900
            value = _safe_date(year, month, day)
            if value:
                hits.append(_DateHit(value, match.start(), match.end(), True, None, False))
                taken.append((match.start(), match.end()))
            continue
        # "9/15" with no year: only ever a deadline when a strong cue says so.
        span = _sentence_span(text, match.start(), match.end())
        resolved = _resolve_missing_year(text, span, month, day, today)
        if resolved:
            value, note = resolved
            hits.append(_DateHit(value, match.start(), match.end(), False, note, True))
            taken.append((match.start(), match.end()))

    for pattern in (_DATE_MDY_RE, _DATE_DMY_RE):
        for match in pattern.finditer(text):
            if overlaps(match.start(), match.end()):
                continue
            month = _MONTHS.get(match.group("month").lower().rstrip("."))
            if month is None:
                continue
            day = int(match.group("day"))
            if not 1 <= day <= 31:
                continue
            raw_year = match.group("year")
            if raw_year:
                value = _safe_date(int(raw_year), month, day)
                if value:
                    hits.append(_DateHit(value, match.start(), match.end(), True, None, False))
                    taken.append((match.start(), match.end()))
                continue
            span = _sentence_span(text, match.start(), match.end())
            resolved = _resolve_missing_year(text, span, month, day, today)
            if resolved:
                value, note = resolved
                hits.append(_DateHit(value, match.start(), match.end(), False, note, False))
                taken.append((match.start(), match.end()))

    hits.sort(key=lambda hit: hit.start)
    return hits


def _resolve_missing_year(
    text: str, span: tuple[int, int], month: int, day: int, today: date
) -> tuple[date, str] | None:
    """Fill in an unstated year, never silently.

    Preference order: a year stated near the date, then the academic cycle —
    the *next* occurrence on or after today.  Rolling backwards would mean
    reading last year's page as this year's deadline, which we never do.
    """
    found = _context_year(text, span, today)
    if found:
        year, note = found
        value = _safe_date(year, month, day)
        if value:
            return value, note
    value = _safe_date(today.year, month, day)
    if value is None:
        return None
    if value < today:
        value = _safe_date(today.year + 1, month, day)
        if value is None:
            return None
    return value, (
        f"year not stated in the posting; taken as the next {value.strftime('%B %-d')} "
        f"on or after {today.isoformat()}"
    )


def extract_deadline(text: str, today: date) -> Evidenced[date]:
    """Find the application deadline actually stated on the page.

    Returns ``None`` with confidence 0 when the page states no date; when it
    states a rolling process the rolling sentence comes back as ``source_text``
    so the UI can explain *why* there is no date.
    """
    body = normalize_text(text)
    if not body:
        return Evidenced[date](value=None, confidence=0.0, method=ExtractionMethod.REGEX)

    best: tuple[float, int, _DateHit, str] | None = None
    for hit in _date_candidates(body, today):
        left, right = _sentence_span(body, hit.start, hit.end)
        sentence = body[left:right]
        strong = list(_STRONG_CUE_RE.finditer(sentence))
        weak = _WEAK_CUE_RE.search(sentence)
        negative = _NEGATIVE_CUE_RE.search(sentence)

        if strong:
            score = 0.9
            nearest = min(abs((left + m.start()) - hit.start) for m in strong)
            if nearest > 140:
                score -= 0.1
        elif hit.needs_strong_cue or negative:
            continue
        elif weak:
            score = 0.6
        else:
            continue

        if negative and not strong:
            continue
        if _PRIORITY_RE.search(sentence):
            score = min(score, 0.7)
        if not hit.had_year:
            score = min(score, 0.75 if hit.year_note and "next" not in hit.year_note else 0.55)

        candidate = (score, -hit.start, hit, sentence)
        if best is None or candidate[:2] > best[:2]:
            best = candidate

    if best is None:
        rolling = _ROLLING_RE.search(body)
        source = _sentence(body, rolling.start(), rolling.end()) if rolling else None
        return Evidenced[date](
            value=None,
            confidence=0.0,
            method=ExtractionMethod.REGEX,
            source_text=source,
        )

    score, _, hit, sentence = best
    source_text = _clip(sentence)
    if hit.year_note:
        source_text = _clip(f"{source_text} [{hit.year_note}]", MAX_SOURCE_TEXT + 120)
    return Evidenced[date](
        value=hit.value,
        confidence=round(score, 2),
        method=ExtractionMethod.REGEX,
        source_text=source_text,
    )


def classify_deadline_type(text: str) -> Evidenced[DeadlineType]:
    """hard | rolling | unknown.

    Rolling wins over a stated date: a posting that reviews applications as
    they arrive *and* publishes a priority date is a rolling process with a
    priority date, not a hard cutoff.
    """
    body = normalize_text(text)
    if not body:
        return Evidenced[DeadlineType](
            value=DeadlineType.UNKNOWN, confidence=0.0, method=ExtractionMethod.REGEX
        )

    rolling = _ROLLING_RE.search(body)
    if rolling:
        return Evidenced[DeadlineType](
            value=DeadlineType.ROLLING,
            confidence=0.9,
            method=ExtractionMethod.REGEX,
            source_text=_sentence(body, rolling.start(), rolling.end()),
        )

    hard = _STRONG_CUE_RE.search(body)
    if hard:
        sentence = _sentence(body, hard.start(), hard.end())
        dated = bool(
            _DATE_MDY_RE.search(sentence)
            or _DATE_DMY_RE.search(sentence)
            or _DATE_NUM_RE.search(sentence)
            or _DATE_ISO_RE.search(sentence)
        )
        return Evidenced[DeadlineType](
            value=DeadlineType.HARD,
            confidence=0.85 if dated else 0.65,
            method=ExtractionMethod.REGEX,
            source_text=sentence,
        )

    return Evidenced[DeadlineType](
        value=DeadlineType.UNKNOWN, confidence=0.0, method=ExtractionMethod.REGEX
    )


# --------------------------------------------------------------------------
# pay
# --------------------------------------------------------------------------

_PAY_RE = re.compile(
    r"\$\s?(?P<a>\d[\d,]*(?:\.\d{1,2})?)"
    r"(?:\s*(?:-|–|—|to)\s*\$?\s?(?P<b>\d[\d,]*(?:\.\d{1,2})?))?"
)
_PERIOD_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("hour", re.compile(r"(?:/\s*(?:hour|hr)|per\s+hour|an?\s+hour|hourly|\bhrs?\b|\bhours?\b)", re.I)),
    ("month", re.compile(r"(?:/\s*(?:month|mo)\b|per\s+month|a\s+month|monthly)", re.I)),
    ("year", re.compile(r"(?:/\s*(?:year|yr)\b|per\s+year|a\s+year|annually|annual\s+salary)", re.I)),
    ("stipend", re.compile(r"\bstipend\b", re.I)),
)
_UNPAID_RE = re.compile(
    r"\bunpaid\b|\bvolunteer\b|\bwithout\s+pay\b|\bno\s+(?:pay|compensation|salary)\b|"
    r"\b(?:course\s+)?credit\s+only\b|\bfor\s+credit\s+only\b",
    re.I,
)
_STIPEND_RE = re.compile(r"\bstipend\b", re.I)


def _amount(raw: str) -> float:
    return float(raw.replace(",", ""))


def _period_near(text: str, start: int, end: int) -> tuple[str, int]:
    """Period keyword closest to the amount; returns (period, end offset)."""
    after = text[end : end + 40]
    before = text[max(0, start - 60) : start]
    for period, pattern in _PERIOD_RES:
        match = pattern.search(after)
        if match:
            return period, end + match.end()
    for period, pattern in _PERIOD_RES:
        if pattern.search(before):
            return period, end
    return "unknown", end


def extract_pay(text: str) -> Evidenced[dict[str, Any]]:
    """``{min, max, period, text}`` with period in hour|month|year|stipend|unknown."""
    body = normalize_text(text)
    empty = Evidenced[dict](value=None, confidence=0.0, method=ExtractionMethod.REGEX)
    if not body:
        return empty

    chosen: tuple[re.Match[str], str, int] | None = None
    for match in _PAY_RE.finditer(body):
        period, period_end = _period_near(body, match.start(), match.end())
        if chosen is None:
            chosen = (match, period, period_end)
        if period != "unknown":
            chosen = (match, period, period_end)
            break

    if chosen is not None:
        match, period, period_end = chosen
        low = _amount(match.group("a"))
        high = _amount(match.group("b")) if match.group("b") else low
        if high < low:
            low, high = high, low
        phrase = _clip(body[match.start() : period_end], 120)
        return Evidenced[dict](
            value={"min": low, "max": high, "period": period, "text": phrase},
            confidence=0.9 if period != "unknown" else 0.6,
            method=ExtractionMethod.REGEX,
            source_text=_sentence(body, match.start(), match.end()),
        )

    unpaid = _UNPAID_RE.search(body)
    if unpaid:
        return Evidenced[dict](
            value={"min": 0.0, "max": 0.0, "period": "unknown", "text": "Unpaid"},
            confidence=0.75,
            method=ExtractionMethod.REGEX,
            source_text=_sentence(body, unpaid.start(), unpaid.end()),
        )

    stipend = _STIPEND_RE.search(body)
    if stipend:
        return Evidenced[dict](
            value={"min": None, "max": None, "period": "stipend", "text": "Stipend"},
            confidence=0.5,
            method=ExtractionMethod.REGEX,
            source_text=_sentence(body, stipend.start(), stipend.end()),
        )
    return empty


# --------------------------------------------------------------------------
# hours
# --------------------------------------------------------------------------

_HOURS_RE = re.compile(
    r"(?P<lead>minimum\s+of|at\s+least|up\s+to|no\s+more\s+than|maximum\s+of|approximately|"
    r"about|around|roughly|~)?\s*"
    r"(?P<a>\d{1,2})(?:\s*(?:-|–|—|to)\s*(?P<b>\d{1,2}))?\s*\+?\s*"
    r"(?:hours?|hrs?\.?)\b(?P<tail>[^.;\n]{0,30})",
    re.I,
)
_WEEKLY_RE = re.compile(r"(?:per|a|each|/)\s*(?:week|wk)\b|\bweekly\b|/\s*wk\b", re.I)
_OTHER_UNIT_RE = re.compile(
    r"(?:per|a|each|/)\s*(?:quarter|semester|term|month|year|day|session)\b|"
    r"\btotal\b|\bin\s+total\b|\bover\s+the\s+(?:quarter|summer|term)\b",
    re.I,
)
_HOURS_NOISE_RE = re.compile(r"\bwithin\b|\bnotice\b|\bturnaround\b|\bresponse\s+time\b", re.I)


def extract_hours(text: str) -> HoursExtraction:
    """Weekly hours plus the free-text commitment note the posting actually uses.

    A range yields its floor (the commitment a student must make); the full
    phrasing survives in the note so nothing is lost.
    """
    body = normalize_text(text)
    if not body:
        return HoursExtraction(
            Evidenced[int](value=None, confidence=0.0, method=ExtractionMethod.REGEX), None
        )

    fallback_note: str | None = None
    for match in _HOURS_RE.finditer(body):
        left, right = _sentence_span(body, match.start(), match.end())
        sentence = body[left:right]
        before = body[max(0, match.start() - 30) : match.start()]
        if _HOURS_NOISE_RE.search(before):
            continue

        tail = match.group("tail") or ""
        note = _clip(sentence, 280)
        weekly = bool(_WEEKLY_RE.search(tail))
        other_unit = bool(_OTHER_UNIT_RE.search(tail))
        confidence = 0.9
        if not weekly and not other_unit:
            if _OTHER_UNIT_RE.search(sentence):
                fallback_note = fallback_note or note
                continue
            if _WEEKLY_RE.search(sentence):
                weekly, confidence = True, 0.8
            else:
                weekly, confidence = True, 0.5
                note = _clip(f"{note} [period not stated; read as hours per week]", 280)
        elif other_unit:
            fallback_note = fallback_note or note
            continue

        lead = (match.group("lead") or "").lower().strip()
        low = int(match.group("a"))
        high = int(match.group("b")) if match.group("b") else None
        if high is not None and high < low:
            low, high = high, low
        if lead in ("up to", "no more than", "maximum of"):
            value = high if high is not None else low
        else:
            value = low
        if high is not None:
            confidence = min(confidence, 0.85)
        if lead in ("approximately", "about", "around", "roughly", "~"):
            confidence = min(confidence, 0.8)
        if value <= 0 or value > 60:
            continue

        return HoursExtraction(
            Evidenced[int](
                value=value,
                confidence=round(confidence, 2),
                method=ExtractionMethod.REGEX,
                source_text=note,
            ),
            note,
        )

    return HoursExtraction(
        Evidenced[int](
            value=None,
            confidence=0.0,
            method=ExtractionMethod.REGEX,
            source_text=fallback_note,
        ),
        fallback_note,
    )


# --------------------------------------------------------------------------
# requirements
# --------------------------------------------------------------------------

_BULLET_RE = re.compile(r"^\s*(?:[-–—*•·▪○◦o]|\(?\d{1,2}[.)]|[a-z][.)])\s+")
_HEADING_MAX = 90

_PREFERRED_HEADINGS = (
    "preferred qualification",
    "preferred skill",
    "preferred experience",
    "preferred",
    "desired qualification",
    "desired skill",
    "desired",
    "nice to have",
    "nice-to-have",
    "bonus",
    "pluses",
    "a plus",
    "ideal candidate",
    "we would love",
    "we'd love",
    "additional preferred",
    "not required but",
)
_REQUIRED_HEADINGS = (
    "required qualification",
    "minimum qualification",
    "basic qualification",
    "requirement",
    "required skill",
    "required experience",
    "qualification",
    "eligibility",
    "who can apply",
    "who should apply",
    "what you'll need",
    "what you will need",
    "you will need",
    "must have",
    "prerequisite",
    "required",
)
_OTHER_HEADINGS = (
    "responsibilit",
    "duties",
    "what you'll do",
    "what you will do",
    "about",
    "overview",
    "description",
    "job summary",
    "the role",
    "how to apply",
    "application process",
    "to apply",
    "compensation",
    "pay",
    "salary",
    "benefits",
    "schedule",
    "hours",
    "location",
    "contact",
    "timeline",
    "next steps",
    "training",
    "deadline",
    "why",
    "our lab",
)

_PREFERRED_MARKERS = (
    "preferred",
    "preferable",
    "preferably",
    "preference is given",
    "desired",
    "desirable",
    "nice to have",
    "nice-to-have",
    "a plus",
    "is a plus",
    "bonus",
    "ideally",
    "strongly encouraged",
    "especially encouraged",
    "encouraged to apply",
    "we would love",
    "we'd love",
    "helpful",
    "beneficial",
    "advantageous",
    "welcome to apply",
    "we look for",
    "we are looking for applicants",
    "we're looking for applicants",
)
_REQUIRED_MARKERS = (
    "required",
    "requires",
    "require ",
    "must ",
    "minimum",
    "at least",
    "you will need",
    "will need to",
    "need to be",
    "needs to be",
    "should be able to",
    "should have",
    "expected to",
    "is expected",
    "are expected",
    "mandatory",
    "prerequisite",
    "obligated to",
    "commitment of",
)
_ONLY_ELIGIBLE_RE = re.compile(r"\bonly\b[^.;]{0,80}\beligible\b|\beligible\b[^.;]{0,40}\bonly\b", re.I)
_NEGATED_REQUIREMENT_RE = re.compile(
    r"\b(?:not|no|neither|never|isn't|aren't|don't|doesn't|do\s+not|does\s+not)\b[^.;]{0,70}"
    r"\b(?:required|necessary|expected|need|needed|mandatory)\b"
    r"|\b(?:required|necessary|expected|needed)\b[^.;]{0,20}\bnot\b",
    re.I,
)


def _heading_kind(line: str) -> str | None:
    """'preferred' | 'required' | 'other' | None (not a heading)."""
    stripped = line.strip().strip("#*_ ").strip()
    if not stripped or len(stripped) > _HEADING_MAX:
        return None
    colon = stripped.endswith(":")
    normalized = stripped.rstrip(":").strip().lower()
    if not colon and len(normalized.split()) > 6:
        return None
    if not colon and normalized.endswith("."):
        return None
    for phrase in _PREFERRED_HEADINGS:
        if normalized.startswith(phrase):
            return "preferred"
    for phrase in _REQUIRED_HEADINGS:
        if normalized.startswith(phrase):
            return "required"
    for phrase in _OTHER_HEADINGS:
        if normalized.startswith(phrase):
            return "other"
    return None


def _split_heading_line(line: str) -> tuple[str | None, str]:
    """Handle "Preferred qualifications: familiarity with R" on one line."""
    if ":" not in line:
        return _heading_kind(line), ""
    head, _, rest = line.partition(":")
    kind = _heading_kind(head + ":")
    if kind and rest.strip():
        return kind, rest.strip()
    if kind:
        return kind, ""
    return _heading_kind(line), ""


def _has_marker(lowered: str, markers: tuple[str, ...]) -> bool:
    return any(marker in lowered for marker in markers)


def _clean_requirement(raw: str) -> str:
    text = _BULLET_RE.sub("", raw).strip()
    text = text.strip("•-*–— ").strip()
    return " ".join(text.split())


def split_requirements(text: str) -> list[dict[str, Any]]:
    """Segment a posting into ``{text, kind, source_text, confidence}``.

    ``kind`` comes from the section heading *and* the wording.  A line under a
    "Preferred Qualifications" heading stays preferred even when it says
    "must" — the heading is the stronger signal and promoting it would put a
    nice-to-have in front of the student as a bar they have to clear.
    """
    body = normalize_text(text)
    if not body:
        return []

    section: str | None = None
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        is_bullet = bool(_BULLET_RE.match(raw_line))
        if not is_bullet:
            heading, remainder = _split_heading_line(line)
            if heading is not None:
                section = heading
                if not remainder:
                    continue
                line = remainder

        segments: list[str]
        if is_bullet or len(line) <= 200:
            segments = [line]
        else:
            segments = [seg for seg in _BOUNDARY_RE.split(line) if seg and seg.strip()]

        for segment in segments:
            cleaned = _clean_requirement(segment)
            if len(cleaned) < 12 or cleaned.lower().startswith("http"):
                continue
            letters = sum(character.isalpha() for character in cleaned)
            if letters < len(cleaned) * 0.5:
                continue

            lowered = cleaned.lower()
            negated = bool(_NEGATED_REQUIREMENT_RE.search(cleaned))
            preferred_marker = _has_marker(lowered, _PREFERRED_MARKERS)
            required_marker = _has_marker(lowered, _REQUIRED_MARKERS) or bool(
                _ONLY_ELIGIBLE_RE.search(cleaned)
            )

            if section == "preferred":
                kind, confidence = RequirementKind.PREFERRED, 0.9 if preferred_marker else 0.85
            elif negated:
                kind, confidence = RequirementKind.PREFERRED, 0.7
            elif preferred_marker:
                kind, confidence = RequirementKind.PREFERRED, 0.85 if section else 0.8
            elif required_marker:
                kind, confidence = RequirementKind.REQUIRED, 0.9 if section == "required" else 0.8
            elif section == "required":
                kind, confidence = RequirementKind.REQUIRED, 0.75
            elif is_bullet and section is None:
                kind, confidence = RequirementKind.INFERRED, 0.4
            else:
                continue

            key = lowered[:160]
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "text": _clip(cleaned, 500),
                    "kind": kind,
                    "source_text": _clip(segment.strip(), 800),
                    "confidence": confidence,
                }
            )
            if len(results) >= MAX_REQUIREMENTS:
                return results
    return results


# --------------------------------------------------------------------------
# documents
# --------------------------------------------------------------------------

_SUBMIT_CUE_RE = re.compile(
    r"\bsubmit\b|\bsend\b|\bupload\b|\battach\b|\binclude\b|\bprovide\b|\bbring\b|\bprepare\b|"
    r"\bapplication\b|\brequired\s+documents?\b|\bmaterials?\b|\bemail\s+(?:us\s+)?your\b|"
    r"\bapply\b|\bshare\b",
    re.I,
)
_DOCUMENT_PATTERNS: tuple[tuple[str, re.Pattern[str], bool], ...] = (
    ("resume", re.compile(r"\bresum[eé]s?\b|\bcurriculum\s+vitae\b|\bCVs?\b"), False),
    ("cover letter", re.compile(r"\bcover\s+letters?\b|\bletters?\s+of\s+interest\b", re.I), False),
    ("transcript", re.compile(r"\btranscripts?\b", re.I), False),
    ("writing sample", re.compile(r"\bwriting\s+samples?\b", re.I), False),
    (
        "statement",
        re.compile(
            r"\bstatement\s+of\s+(?:purpose|interest|research)\b|\bpersonal\s+statement\b", re.I
        ),
        False,
    ),
    (
        "references",
        re.compile(
            r"\breferences?\b|\bletters?\s+of\s+recommendation\b|\brecommendation\s+letters?\b|"
            r"\brecommendations?\b|\breferees?\b",
            re.I,
        ),
        True,
    ),
    ("portfolio", re.compile(r"\bportfolios?\b|\bwork\s+samples?\b", re.I), True),
)
_DOCUMENT_ORDER = [name for name, _, _ in _DOCUMENT_PATTERNS]


def extract_documents(text: str) -> list[str]:
    """Documents the posting says to bring, in a canonical vocabulary."""
    body = normalize_text(text)
    if not body:
        return []
    found: set[str] = set()
    for name, pattern, needs_cue in _DOCUMENT_PATTERNS:
        for match in pattern.finditer(body):
            if needs_cue:
                sentence = _sentence(body, match.start(), match.end())
                if not _SUBMIT_CUE_RE.search(sentence):
                    continue
            found.add(name)
            break
    return [name for name in _DOCUMENT_ORDER if name in found]


# --------------------------------------------------------------------------
# contact
# --------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}\b")
_MAILTO_RE = re.compile(r"mailto:([^\"'>\s?&]+)", re.I)
_ANCHOR_MAILTO_RE = re.compile(
    r"<a\b[^>]*href=[\"']mailto:([^\"'?]+)[^>]*>(.*?)</a>", re.I | re.S
)
_TAG_RE = re.compile(r"<[^>]+>")
_BAD_LOCAL_PARTS = {"noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon", "postmaster"}
_BAD_DOMAINS = {"example.com", "domain.com", "email.com", "yourdomain.com", "sentry.io", "test.com"}
_CONTACT_CUE_RE = re.compile(
    r"\bcontact\b|\be-?mail\b|\bquestions?\b|\binquir(?:y|ies)\b|\breach\s+out\b|\bwrite\s+to\b|"
    r"\bsend\b|\bapply\b|\binterested\b|\bget\s+in\s+touch\b",
    re.I,
)
_NAME_BEFORE_RES = (
    re.compile(
        r"(?:contact|e-?mail|write\s+to|reach\s+out\s+to|questions?\s+to|please\s+contact|"
        r"send\s+(?:your\s+)?\w+\s+to)\s+"
        r"(?:Dr\.?|Prof\.?|Professor|Mr\.?|Ms\.?|Mrs\.?)?\s*"
        r"(?P<name>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'.\-]+){0,2})\s*$"
    ),
    re.compile(r"(?P<name>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'.\-]+){1,2})\s*(?:[(<,]|\bat\b)\s*$"),
)
_NAME_STOPWORDS = {"please", "email", "e-mail", "contact", "apply", "send", "the", "our", "you"}


def _plausible_name(candidate: str | None) -> str | None:
    if not candidate:
        return None
    name = " ".join(candidate.split()).strip(" .,;:")
    if len(name) < 4 or "@" in name:
        return None
    words = name.split()
    if not 2 <= len(words) <= 4:
        return None
    if any(word.lower() in _NAME_STOPWORDS for word in words):
        return None
    return name


def _usable_email(address: str) -> bool:
    address = address.strip().strip(".,;:)>")
    if "@" not in address:
        return False
    local, _, domain = address.partition("@")
    if local.lower() in _BAD_LOCAL_PARTS or domain.lower() in _BAD_DOMAINS:
        return False
    return not domain.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"))


def extract_contact(text: str, html: str | None = None) -> tuple[str | None, str | None]:
    """Return a contact name and address only when both are literally present.

    An address is never constructed from a person's name — a plausible-looking
    address that bounces (or reaches a stranger) is worse than no address.
    """
    body = normalize_text(text)
    candidates: list[tuple[int, str, str | None]] = []

    if html:
        for match in _ANCHOR_MAILTO_RE.finditer(html):
            address = match.group(1).strip()
            if _usable_email(address):
                anchor = _TAG_RE.sub(" ", match.group(2))
                candidates.append((3, address.strip().strip(".,;:)>"), _plausible_name(anchor)))
        for match in _MAILTO_RE.finditer(html):
            address = match.group(1).strip().strip(".,;:)>")
            if _usable_email(address):
                candidates.append((2, address, None))

    for match in _EMAIL_RE.finditer(body):
        address = match.group(0).strip(".,;:)>")
        if not _usable_email(address):
            continue
        left, _ = _sentence_span(body, match.start(), match.end())
        sentence = body[left : match.end()]
        score = 2 if _CONTACT_CUE_RE.search(sentence) else 1
        name = None
        prefix = body[max(0, match.start() - 140) : match.start()].rstrip(" (<:")
        for pattern in _NAME_BEFORE_RES:
            found = pattern.search(prefix)
            if found:
                name = _plausible_name(found.group("name"))
                if name:
                    break
        candidates.append((score, address, name))

    if not candidates:
        return None, None

    best_score = max(score for score, _, _ in candidates)
    best = next((c for c in candidates if c[0] == best_score), candidates[0])
    email = best[1]
    name = best[2]
    if name is None:
        name = next((n for score, addr, n in candidates if addr == email and n), None)
    return name, email


# --------------------------------------------------------------------------
# application method
# --------------------------------------------------------------------------

_HREF_RE = re.compile(r"<a\b[^>]*href=[\"'](?P<url>[^\"'#]+)[\"'][^>]*>(?P<label>.*?)</a>", re.I | re.S)
_BARE_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_APPLY_CUE_RE = re.compile(r"appl(?:y|ication|ications)|submit|register|sign\s*up|join", re.I)
_FORM_HOST_RE = re.compile(
    r"docs\.google\.com/forms|forms\.gle|forms\.office\.com|\.qualtrics\.com|airtable\.com|"
    r"jotform\.com|typeform\.com|wufoo\.com|smartsheet\.com|surveymonkey\.com|formstack\.com",
    re.I,
)
_HANDSHAKE_RE = re.compile(r"joinhandshake\.com|\bhandshake\b", re.I)
_IN_PERSON_RE = re.compile(
    r"\bin\s+person\b|\bstop\s+by\b|\bdrop\s+(?:off|by)\b|\bvisit\s+(?:the\s+)?office\b|"
    r"\bcome\s+to\s+the\s+office\b",
    re.I,
)
_EMAIL_APPLY_RE = re.compile(
    r"\bemail\s+(?:your|a|an|the|us|me)\b|\bsend\s+(?:your|a|an|the)\b|\bapply\s+by\s+e-?mail\b|"
    r"\be-?mail\s+(?:your\s+)?(?:resume|cv|cover\s+letter|application|materials)\b|"
    r"\bwrite\s+to\b|\bcontact\s+(?:us|me)\s+at\b",
    re.I,
)


def _links(text: str, html: str | None) -> list[tuple[str, str]]:
    """(url, label-or-context) pairs from the anchors and bare URLs we can see."""
    found: list[tuple[str, str]] = []
    if html:
        for match in _HREF_RE.finditer(html):
            url = match.group("url").strip()
            if url.lower().startswith(("mailto:", "javascript:", "tel:")):
                continue
            label = " ".join(_TAG_RE.sub(" ", match.group("label")).split())
            found.append((url, label))
    for match in _BARE_URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:)")
        found.append((url, _sentence(text, match.start(), match.end())))
    return found


def extract_application_method(
    text: str, html: str | None = None, url: str | None = None
) -> tuple[str, str | None]:
    """``(method, application_url)`` — method in ApplicationMethod."""
    body = normalize_text(text)
    page_host = urlparse(url).netloc.lower() if url else ""
    links = _links(body, html)

    apply_links = [
        (link, label)
        for link, label in links
        if _APPLY_CUE_RE.search(label or "") or _APPLY_CUE_RE.search(link)
    ]

    for link, label in apply_links or links:
        if _HANDSHAKE_RE.search(link) or (label and "handshake" in label.lower()):
            return ApplicationMethod.HANDSHAKE, link if link.startswith("http") else url
    if _HANDSHAKE_RE.search(body) and _APPLY_CUE_RE.search(body):
        return ApplicationMethod.HANDSHAKE, url

    for link, _ in apply_links:
        if _FORM_HOST_RE.search(link):
            return ApplicationMethod.FORM, link

    for link, _ in apply_links:
        if not link.startswith("http"):
            continue
        host = urlparse(link).netloc.lower()
        if page_host and host and host != page_host:
            return ApplicationMethod.EXTERNAL, link

    email_cue = _EMAIL_APPLY_RE.search(body)
    if email_cue:
        _, address = extract_contact(body, html)
        if address:
            return ApplicationMethod.EMAIL, f"mailto:{address}"

    for link, _ in apply_links:
        if link.startswith("http") or link.startswith("/"):
            return ApplicationMethod.FORM, link

    if _IN_PERSON_RE.search(body):
        return ApplicationMethod.IN_PERSON, None

    _, address = extract_contact(body, html)
    if address and _APPLY_CUE_RE.search(body):
        return ApplicationMethod.EMAIL, f"mailto:{address}"

    return ApplicationMethod.UNKNOWN, None


# --------------------------------------------------------------------------
# eligibility statements
# --------------------------------------------------------------------------

_ELIGIBILITY_RE = re.compile(
    r"\beligib\w*\b|\bmust\s+be\s+(?:a|an|enrolled|currently|available)\b|\bopen\s+to\b|"
    r"\bavailable\s+to\b|\bundergraduates?\b|\bgraduate\s+students?\b|\bcoterm\w*\b|"
    r"\bwork[-\s]study\b|\bfreshm\w+\b|\bsophomore\w*\b|\bjuniors?\b|\bseniors?\b|"
    r"\bcurrently\s+enrolled\b|\bclass\s+standing\b|\bGPA\b|\bwork\s+authoriz\w+\b|"
    r"\blegally\s+eligible\s+to\s+work\b|\binternational\s+students?\b",
    re.I,
)


def extract_eligibility(text: str) -> Evidenced[list[str]]:
    """Statements about *who may apply*, quoted verbatim.

    This deliberately stops at the statements: deciding whether the student in
    front of us qualifies is a separate, profile-aware step.
    """
    body = normalize_text(text)
    if not body:
        return Evidenced[list[str]](value=None, confidence=0.0, method=ExtractionMethod.HEURISTIC)

    statements: list[str] = []
    seen: set[str] = set()
    for match in _ELIGIBILITY_RE.finditer(body):
        sentence = _sentence(body, match.start(), match.end())
        key = sentence.lower()[:120]
        if len(sentence) < 15 or key in seen:
            continue
        seen.add(key)
        statements.append(sentence)
        if len(statements) >= 12:
            break

    if not statements:
        return Evidenced[list[str]](value=None, confidence=0.0, method=ExtractionMethod.HEURISTIC)
    return Evidenced[list[str]](
        value=statements,
        confidence=0.7,
        method=ExtractionMethod.HEURISTIC,
        source_text=_clip(" ".join(statements)),
    )
