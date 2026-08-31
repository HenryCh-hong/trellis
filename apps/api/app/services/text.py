"""Pure text primitives shared by the taxonomy, the scorers and the agents.

Everything here is deterministic and dependency-light on purpose: matching has
to behave identically with or without an LLM, and every helper runs over every
opportunity on every re-score.

The one genuinely subtle function is :func:`find_phrase`.  Skill matching lives
or dies on its boundary rules — ``r`` must not match inside ``react`` and ``ai``
must not match inside ``chair``, while ``c++`` must still match at all — so the
boundaries are built from the phrase's own first/last character class rather
than from ``\\b``, which is wrong for ``+`` and ``#``.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from functools import lru_cache

from rapidfuzz import fuzz

__all__ = [
    "STOPWORDS",
    "concat",
    "content_words",
    "contains_phrase",
    "cosine_bag",
    "extract_course_codes",
    "extract_hours_per_week",
    "extract_years",
    "find_phrase",
    "fuzzy_ratio",
    "jaccard",
    "ngrams",
    "normalize",
    "phrase_snippet",
    "sentences",
    "tokens",
    "truncate",
]

_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9](?:[a-z0-9+#./'\-]*[a-z0-9+#])?")
_YEAR_RE = re.compile(r"(?<![0-9])((?:19|20)[0-9]{2})(?![0-9])")
_COURSE_RE = re.compile(r"\b([A-Z]{2,8})\s?-?\s?([0-9]{1,3}[A-Z]{0,2})\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
_BULLET_RE = re.compile(r"^\s*(?:[-*•‣●▪]|\d+[.)])\s+", re.MULTILINE)

# Straight-ASCII the characters that vary by source so that a phrase typed in a
# profile still matches the same phrase pasted from a web page.
_TRANSLATION = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        "⁄": "/",
        " ": " ",
        "…": " ",
        "\t": " ",
    }
)

STOPWORDS = frozenset(
    ["a", "about", "above", "after", "all", "also", "am", "an", "and", "any", "are", "as", "at", "be", "because", "been", "being", "but", "by", "can", "cannot", "could", "did", "do", "does", "doing", "done", "during", "each", "either", "else", "etc", "for", "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "him", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "may", "me", "might", "more", "most", "must", "my", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "others", "our", "ours", "out", "over", "own", "per", "should", "so", "some", "such", "than", "that", "the", "their", "theirs", "them", "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "upon", "us", "use", "used", "using", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with", "within", "would", "you", "your", "yours", "ability", "able", "applicant", "applicants", "candidate", "candidates", "experience", "experienced", "familiar", "good", "great", "including", "include", "includes", "knowledge", "must", "new", "position", "preferred", "prefer", "required", "require", "requirement", "requirements", "role", "skill", "skills", "strong", "student", "students", "work", "working"]
)


def normalize(value: str | None) -> str:
    """Lower-case, de-accent and collapse whitespace.

    Offsets from the normalised string do NOT map back onto the original, which
    is why phrase search below runs case-insensitively over the raw text.
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(_TRANSLATION)
    return _WS_RE.sub(" ", text).strip().lower()


def truncate(value: str | None, limit: int = 240) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def concat(*parts: object, separator: str = "\n") -> str:
    """Join heterogeneous fragments (strings, lists of strings, ``None``)."""
    chunks: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, str):
            if part.strip():
                chunks.append(part.strip())
        elif isinstance(part, Iterable):
            for item in part:  # type: ignore[union-attr]
                if isinstance(item, str) and item.strip():
                    chunks.append(item.strip())
        else:
            text = str(part).strip()
            if text:
                chunks.append(text)
    return separator.join(chunks)


def tokens(value: str | None, *, drop_stopwords: bool = False) -> list[str]:
    """Word tokens that keep ``c++``, ``node.js`` and ``scikit-learn`` whole."""
    found = _TOKEN_RE.findall(normalize(value))
    if drop_stopwords:
        return [t for t in found if t not in STOPWORDS]
    return found


def content_words(value: str | None, *, min_length: int = 3) -> list[str]:
    """Tokens that actually carry meaning — used to judge whether a sentence's
    substance appears somewhere in the student's own material."""
    return [t for t in tokens(value, drop_stopwords=True) if len(t) >= min_length]


def ngrams(source: str | Sequence[str], n: int) -> list[str]:
    toks = tokens(source) if isinstance(source, str) else [normalize(t) for t in source]
    if n <= 0 or len(toks) < n:
        return []
    return [" ".join(toks[i : i + n]) for i in range(len(toks) - n + 1)]


@lru_cache(maxsize=8192)
def _phrase_regex(phrase: str, case_sensitive: bool) -> re.Pattern[str] | None:
    """Compile a boundary-safe pattern for one phrase.

    Separators inside the phrase are made flexible so a single vocabulary entry
    covers ``scikit-learn``, ``scikit learn`` and ``scikit_learn``.
    """
    prepared = phrase.strip() if case_sensitive else normalize(phrase)
    if not prepared:
        return None
    parts = [re.escape(p) for p in re.split(r"[\s_/\-]+", prepared) if p]
    if not parts:
        return None
    body = r"[\s_/\-]*".join(parts)
    last = prepared[-1]
    # A trailing '+' or '#' is part of the token ("c++"), so digits are still
    # allowed to follow it ("c++11" does mention C++).
    right = r"(?![A-Za-z+#])" if last in "+#" else r"(?![A-Za-z0-9+#])"
    pattern = rf"(?<![A-Za-z0-9+#]){body}{right}"
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(pattern, flags)


def find_phrase(
    haystack: str | None, phrase: str, *, case_sensitive: bool = False
) -> tuple[int, int] | None:
    """Return the ``(start, end)`` span of ``phrase`` in ``haystack``.

    Offsets index the ORIGINAL string so callers can quote real source text.
    """
    if not haystack or not phrase:
        return None
    regex = _phrase_regex(phrase, case_sensitive)
    if regex is None:
        return None
    match = regex.search(haystack)
    return match.span() if match else None


def contains_phrase(haystack: str | None, phrase: str, *, case_sensitive: bool = False) -> bool:
    return find_phrase(haystack, phrase, case_sensitive=case_sensitive) is not None


def phrase_snippet(text: str, span: tuple[int, int], width: int = 90) -> str:
    """A quotable window around a match, clipped to word edges."""
    start, end = span
    left = max(0, start - width // 2)
    right = min(len(text), end + width // 2)
    if left > 0:
        space = text.find(" ", left, start)
        left = space + 1 if space != -1 else left
    if right < len(text):
        space = text.rfind(" ", end, right)
        right = space if space != -1 else right
    snippet = _WS_RE.sub(" ", text[left:right]).strip()
    if left > 0:
        snippet = "…" + snippet
    if right < len(text):
        snippet = snippet + "…"
    return snippet


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _bag(value: str | Iterable[str]) -> Counter[str]:
    if isinstance(value, str):
        return Counter(tokens(value, drop_stopwords=True))
    return Counter(t for t in (normalize(item) for item in value) if t and t not in STOPWORDS)


def cosine_bag(left: str | Iterable[str], right: str | Iterable[str]) -> float:
    """Cosine similarity over term counts, stopwords removed."""
    a, b = _bag(left), _bag(right)
    if not a or not b:
        return 0.0
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    dot = sum(a[t] * b[t] for t in shared)
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    if norm == 0.0:
        return 0.0
    return min(1.0, dot / norm)


def fuzzy_ratio(left: str | None, right: str | None) -> float:
    """0..1 similarity tolerant of word order and small typos."""
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    best = max(fuzz.ratio(a, b), fuzz.token_set_ratio(a, b))
    return round(best / 100.0, 4)


def extract_years(text: str | None) -> list[int]:
    """Four-digit years in order of appearance, de-duplicated."""
    seen: list[int] = []
    for raw in _YEAR_RE.findall(text or ""):
        year = int(raw)
        if year not in seen:
            seen.append(year)
    return seen


def extract_course_codes(text: str | None) -> list[str]:
    """Course codes such as ``CS106B`` or ``PWR 195``, normalised to ``CS106B``."""
    codes: list[str] = []
    for dept, number in _COURSE_RE.findall(text or ""):
        code = f"{dept.upper()}{number.upper()}"
        if code not in codes:
            codes.append(code)
    return codes


_HOURS_RANGE_RE = re.compile(
    r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*(?:\+\s*)?(?:hours?|hrs?)\b", re.IGNORECASE
)
_HOURS_SINGLE_RE = re.compile(r"(\d{1,2})\s*(?:\+\s*)?(?:hours?|hrs?)\b", re.IGNORECASE)


def extract_hours_per_week(text: str | None) -> tuple[int | None, int | None]:
    """Best-effort ``(min, max)`` weekly hours stated in prose.

    Returns ``(None, None)`` rather than a guess when nothing is stated.
    """
    if not text:
        return (None, None)
    match = _HOURS_RANGE_RE.search(text)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        if low <= high <= 80:
            return (low, high)
    values = [int(v) for v in _HOURS_SINGLE_RE.findall(text) if 0 < int(v) <= 80]
    if not values:
        return (None, None)
    return (min(values), max(values))


_ABBREVIATIONS = (
    "e.g.",
    "i.e.",
    "etc.",
    "vs.",
    "u.s.",
    "ph.d.",
    "b.s.",
    "m.s.",
    "dr.",
    "mr.",
    "ms.",
    "mrs.",
    "prof.",
    "approx.",
    "no.",
    "fig.",
)


def sentences(text: str | None) -> list[str]:
    """Split prose into sentences, keeping bullets and lines as their own units."""
    if not text:
        return []
    working = str(text).translate(_TRANSLATION)
    for index, abbreviation in enumerate(_ABBREVIATIONS):
        working = re.sub(re.escape(abbreviation), f"\x00{index}\x00", working, flags=re.IGNORECASE)
    out: list[str] = []
    for line in _BULLET_RE.sub("\n", working).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for piece in _SENTENCE_SPLIT_RE.split(stripped):
            candidate = piece.strip()
            if candidate:
                out.append(candidate)
    restored: list[str] = []
    for item in out:
        text_out = item
        for index, abbreviation in enumerate(_ABBREVIATIONS):
            text_out = text_out.replace(f"\x00{index}\x00", abbreviation)
        cleaned = _WS_RE.sub(" ", text_out).strip()
        if cleaned:
            restored.append(cleaned)
    return restored
