"""Current directions as evidence-backed claims, and the "why now?" signal.

Two derived structures, both computed from rows the caller already has loaded
(``faculty.evidence``), so adding them to a response costs no extra query and
they can never drift out of agreement with the evidence timeline:

``direction_claims``
    Each stated direction paired with the *specific* recent items that support
    it, and a ``why`` derived from the words the two texts actually share.  A
    direction nothing recent supports is dropped rather than shown unsupported
    -- a lab's 2018 work is history, not its current direction.

``why_now``
    A timing signal, or ``None``.  There is no fallback prose: if the evidence
    does not show a cluster, a new direction, fresh lab news or dated
    recruiting copy, the answer is nothing at all.  Manufactured urgency is
    the whole failure mode this is meant to avoid.

Both work on year granularity because that is the granularity the evidence
actually has (``research_evidence.published_on`` is empty for every row), so
statements name the years they mean instead of claiming "this month".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.agents.research_agent import RECRUITING_OPEN, harvest_recruiting_status
from app.core.config import get_settings
from app.models.enums import Certainty, EvidenceKind, SignalKind
from app.models.research import Faculty, ResearchEvidence
from app.services import taxonomy

# Words that overlap between any two pieces of academic prose and therefore
# prove nothing about a shared subject.
STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by", "can", "could", "did", "do", "does", "for", "from", "had", "has", "have", "how", "in", "into", "is", "it", "its", "of", "on", "or", "our", "out", "over", "per", "that", "the", "their", "them", "then", "there", "these", "they", "this", "those", "through", "to", "under", "until", "up", "upon", "using", "via", "was", "were", "what", "when", "where", "which", "while", "who", "why", "will", "with", "within", "without", "would", "your", "also", "more", "most", "much", "new", "non", "not", "now", "only", "other", "same", "some", "such", "than", "very", "about", "across", "after", "against", "all", "any", "because", "before", "both", "during", "each", "either", "every", "few", "from", "further", "here", "itself", "less", "many", "might", "must", "nor", "once", "other", "ought", "own", "she", "shall", "should", "since", "so", "still", "take", "taken", "that's", "them", "themselves", "thing", "things", "toward", "towards", "use", "used", "uses", "way", "well", "work", "works", "approach", "approaches", "based", "general", "generic", "method", "methods", "paper", "papers", "problem", "problems", "project", "projects", "research", "researcher", "researchers", "result", "results", "study", "studies", "system", "systems", "topic", "topics", "towards", "work",
     "actually", "additionally", "already", "alternatively", "always", "another",
     "anything", "become", "becomes", "certain", "common", "currently", "despite",
     "different", "directly", "entire", "especially", "everything", "explicitly",
     "however", "important", "including", "instead", "likely", "little", "mainly",
     "making", "merely", "notably", "often", "overall", "particular", "particularly",
     "possible", "primarily", "really", "recent", "recently", "regarding", "several",
     "similar", "simply", "something", "sometimes", "specifically", "typically",
     "usually", "whether", "whose"]
)
# Short but load-bearing: dropping everything under four characters would throw
# away exactly the terms a CS lab is identified by.
SHORT_KEEP = frozenset({"llm", "llms", "rl", "nlp", "hci", "3d", "4d", "ai", "vla", "cs"})

# Shared between a direction and an item, these prove only that both are about
# computer science.  They may be quoted in a ``why`` alongside a real term, but
# an overlap made of nothing but these is not support for anything.
FIELD_WORDS = frozenset(
    ["ai", "cs", "llm", "llms", "rl", "model", "models", "modeling", "modelling", "language", "languages", "learn", "learning", "data", "dataset", "datasets", "computer", "computing", "science", "sciences", "scientific", "intelligence", "intelligent", "artificial", "network", "networks", "neural", "student", "students", "university", "stanford", "course", "courses", "teaching", "teach", "training", "train", "large", "small", "deep", "machine"]
)

_WORD = re.compile(r"[a-z0-9]+")


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _terms(text: str | None) -> dict[str, str]:
    """Stem -> the surface form as written, so ``why`` can quote real words."""
    out: dict[str, str] = {}
    for word in _WORD.findall((text or "").lower()):
        if word in STOPWORDS:
            continue
        if len(word) < 4 and word not in SHORT_KEEP:
            continue
        out.setdefault(_stem(word), word)
    return out


def _topic_slugs(text: str | None, declared: list[str] | None = None) -> set[str]:
    slugs = {slug for slug, _ in taxonomy.match_topics(text)}
    for topic in declared or []:
        resolved = taxonomy.resolve_topic(topic)
        if resolved:
            slugs.add(resolved)
    return slugs


def _join(words: list[str]) -> str:
    if len(words) == 1:
        return words[0]
    return f"{', '.join(words[:-1])} and {words[-1]}"


@dataclass(frozen=True, slots=True)
class DirectionEvidence:
    evidence: ResearchEvidence
    why: str
    strength: int


@dataclass(frozen=True, slots=True)
class DirectionClaim:
    direction: str
    certainty: Certainty
    evidence: list[DirectionEvidence]


@dataclass(frozen=True, slots=True)
class WhyNow:
    statement: str
    evidence: list[ResearchEvidence] = field(default_factory=list)
    certainty: Certainty = Certainty.INFERRED


def recency_cutoffs(today: date) -> tuple[int, int]:
    """(current-direction cutoff year, timing-signal cutoff year).

    Year arithmetic on purpose: the evidence carries a year and nothing finer,
    so pretending to a month-level window would be a fabricated precision.
    """
    settings = get_settings()
    return (
        today.year - max(1, settings.recency_window_months // 12),
        today.year - max(1, settings.strong_recency_window_months // 12),
    )


def _support(direction: str, item: ResearchEvidence) -> DirectionEvidence | None:
    """Does this item support this direction, and in whose words?"""
    direction_terms = _terms(direction)
    title_terms = _terms(item.title)
    summary_terms = _terms(item.summary)

    shared_title = sorted(set(direction_terms) & set(title_terms))
    shared_summary = sorted((set(direction_terms) & set(summary_terms)) - set(shared_title))
    shared_topics = _topic_slugs(direction) & _topic_slugs(
        f"{item.title} {item.summary or ''}", item.topics
    )

    shared = shared_title + shared_summary
    # Every accepted link needs at least one word that is specific to the
    # subject.  "Both mention AI and models" is not evidence of anything.
    informative = [t for t in shared if len(t) >= 5 and t not in FIELD_WORDS]
    if not informative:
        return None
    # And one shared word is a coincidence unless the taxonomy agrees the two
    # texts are about the same thing.
    if len(shared) < 2 and not shared_topics:
        return None

    parts: list[str] = []
    if shared_title:
        parts.append(f"Title names {_join([title_terms[t] for t in shared_title][:4])}")
    if shared_summary:
        parts.append(f"summary names {_join([summary_terms[t] for t in shared_summary][:3])}")
    why = "; ".join(parts)
    if shared_topics:
        labels = sorted(taxonomy.topic_label(t) for t in shared_topics)[:2]
        why = f"{why}; both tagged {_join(labels)}"
    return DirectionEvidence(
        evidence=item,
        why=f"{why}.",
        strength=len(informative) * 2 + len(shared) + 3 * len(shared_topics),
    )


def direction_claims(faculty: Faculty, *, today: date) -> list[DirectionClaim]:
    """Each stated direction with the recent evidence that actually backs it."""
    directions = [d for d in (faculty.current_direction or []) if d and d.strip()]
    if not directions:
        return []
    cutoff, _ = recency_cutoffs(today)
    recent = [e for e in faculty.evidence if (e.year or 0) >= cutoff]
    if not recent:
        # The direction was never allowed to be built from stale evidence; it
        # must not be shown as if it were.
        return []

    ceiling = faculty.current_direction_certainty
    claims: list[DirectionClaim] = []
    for direction in directions:
        supports = [s for s in (_support(direction, item) for item in recent) if s]
        if not supports:
            continue
        supports.sort(key=lambda s: (-s.strength, -(s.evidence.year or 0)))
        certainty = Certainty.LIKELY if len(supports) >= 3 else Certainty.INFERRED
        # Never assert more than the faculty-level basis does.  UNKNOWN is not
        # a ceiling here: it means no direction could be *derived*, while these
        # claims are each backed by named, dated items.
        if ceiling == Certainty.INFERRED:
            certainty = Certainty.INFERRED
        claims.append(
            DirectionClaim(direction=direction, certainty=certainty, evidence=supports[:4])
        )
    return claims


_CERTAINTY_ORDER = {
    Certainty.UNKNOWN: 0,
    Certainty.INFERRED: 1,
    Certainty.LIKELY: 2,
    Certainty.VERIFIED: 3,
}

# A date in recruiting copy only means "recently posted" next to wording that
# says so.  "re-fetched 2026-08-31" is when *we* looked, not when they wrote.
_POSTED_DATE = re.compile(
    r"(?:posted|posting|date)\D{0,12}(20\d{2})-(\d{2})-(\d{2})", re.IGNORECASE
)
_POSTED_YEAR = re.compile(
    r"(?:date\s+posted|posted|posting\s+date)\b[^.]{0,30}?(20\d{2})\b", re.IGNORECASE
)
# "2026-27" is an academic year; "2026-08" is a fetch date wearing the same
# shape, so the tail has to be the following year.
_ACADEMIC_YEAR = re.compile(r"\b(20\d{2})\s*[-–/]\s*(\d{2})\b")
_TERM_YEAR = re.compile(r"\b(?:spring|summer|autumn|fall|winter)\s+(20\d{2})\b", re.IGNORECASE)


def _recent_recruiting_year(text: str, *, posted_floor: int, cycle: int) -> int | None:
    """The year a recruiting statement dates *itself* to, if it does at all.

    Only dates that sit next to posting words count.  "re-fetched 2026-08-31"
    is when we looked at the page, not when the lab wrote it, and reading that
    as freshness would invent exactly the urgency this must never invent.  An
    academic year has to be the *current* one: "2025-26" is over by now.
    """
    years: list[int] = []
    for pattern in (_POSTED_DATE, _POSTED_YEAR):
        years += [int(m.group(1)) for m in pattern.finditer(text) if int(m.group(1)) >= posted_floor]
    for match in _ACADEMIC_YEAR.finditer(text):
        start = int(match.group(1))
        if int(match.group(2)) == (start + 1) % 100 and start >= cycle:
            years.append(start)
    years += [int(m.group(1)) for m in _TERM_YEAR.finditer(text) if int(m.group(1)) >= cycle]
    return max(years) if years else None


def why_now(faculty: Faculty, *, today: date, claims: list[DirectionClaim] | None = None) -> WhyNow | None:
    """A real timing signal, or nothing at all.

    Four things count, in descending order of how directly they answer "why
    write this month rather than next year".  Nothing else is invented.
    """
    cutoff, strong = recency_cutoffs(today)
    recent = [e for e in faculty.evidence if (e.year or 0) >= strong]
    older = [e for e in faculty.evidence if cutoff <= (e.year or 0) < strong]
    if not recent:
        return None
    span = f"{min(e.year for e in recent if e.year)}–{today.year}"

    # 1. Lab news, a grant, or a new initiative -- dated, and about the lab
    #    rather than about a paper.
    news = [e for e in recent if e.kind in (EvidenceKind.NEWS, EvidenceKind.GRANT)]
    if news:
        newest = max(news, key=lambda e: (e.year or 0))
        kind = "Grant" if newest.kind == EvidenceKind.GRANT else "Lab news"
        return WhyNow(
            statement=f"{kind} dated {newest.year}: {newest.title}",
            evidence=[newest, *[e for e in news if e is not newest][:2]],
            certainty=Certainty.VERIFIED if newest.url else Certainty.LIKELY,
        )

    # 2. Several recent items clustered on one topic.
    clusters: dict[str, list[ResearchEvidence]] = {}
    for item in recent:
        for slug in _topic_slugs(f"{item.title} {item.summary or ''}", item.topics):
            clusters.setdefault(slug, []).append(item)
    best = max(clusters.items(), key=lambda kv: len(kv[1]), default=None)
    if best and len(best[1]) >= 3:
        slug, items = best
        return WhyNow(
            statement=(
                f"{len(items)} of their {span} items are on "
                f"{taxonomy.topic_label(slug)} — an active push, not a one-off."
            ),
            evidence=sorted(items, key=lambda e: -(e.year or 0))[:4],
            certainty=Certainty.LIKELY,
        )

    # 3. A direction that did not exist in the older evidence. Needs a real
    #    baseline to compare against, otherwise "new" just means "all we have".
    if claims and len(older) >= 2:
        old_topics: set[str] = set()
        for item in older:
            old_topics |= _topic_slugs(f"{item.title} {item.summary or ''}", item.topics)
        for claim in claims:
            fresh = [de for de in claim.evidence if (de.evidence.year or 0) >= strong]
            if not fresh:
                continue
            topics = _topic_slugs(claim.direction)
            if topics and not (topics & old_topics):
                return WhyNow(
                    statement=(
                        f"“{claim.direction}” appears only in their {span} work; "
                        f"nothing they published in {cutoff}–{strong - 1} touches it."
                    ),
                    evidence=[de.evidence for de in fresh[:3]],
                    certainty=Certainty.INFERRED,
                )

    # 4. Recruiting copy that dates itself to the current cycle.  A course
    #    listing that happens to say "Spring 2026" is not a recruiting call.
    cycle = today.year if today.month >= 7 else today.year - 1
    for signal in faculty.signals:
        if signal.kind != SignalKind.RECRUITING or not signal.source_url:
            continue
        text = signal.statement or signal.label or ""
        if harvest_recruiting_status(signal) != "open" and not any(
            phrase in text.lower() for phrase in RECRUITING_OPEN
        ):
            continue
        year = _recent_recruiting_year(text, posted_floor=strong, cycle=cycle)
        if year is not None:
            return WhyNow(
                statement=(
                    f"Their recruiting page dates its own call to {year}, "
                    "so it belongs to the current cycle rather than an old post."
                ),
                evidence=[],
                certainty=(
                    Certainty.LIKELY
                    if signal.certainty != Certainty.UNKNOWN
                    else Certainty.INFERRED
                ),
            )
    return None
