"""Intent-aware search over opportunities, labs, faculty and research leads.

A student types two words.  Substring search answers them with whatever page
happens to contain those two characters in a row, which is why "agents" used to
return nothing at all (no title contains the word) while "library" returned four
rows in the order the database felt like.

This module answers the question instead of the string, in three deterministic
steps and with no new infrastructure:

1. **Expand.**  The query goes through the canonical vocabulary in
   :mod:`app.services.taxonomy` — ``resolve_topic`` and its alias table for the
   student's own wording, ``related_slugs`` for one hop of hand-checked
   neighbours, and ``resolve_kinds`` for words that describe the *shape* of the
   work ("part-time") rather than its subject.  The stored ontology
   (``research_topics``) supplies the rest: its labels and aliases are the same
   vocabulary the harvest tagged every lab with, so "agents" reaches
   ``llm-agents``, ``embodied LLM agents and test-time planning`` and
   ``curiosity and intrinsically-motivated agents`` without an embedding.

2. **Score.**  Every candidate earns points from a small fixed table
   (:data:`WEIGHTS`) — an exact title beats a topic, a topic beats a lab or PI
   name, a name beats a passing mention in prose.  Each component that fires
   records the words that made it fire, so a result can always say why it is
   here.  Nothing is learned, sampled or model-decided: the same query over the
   same database gives byte-identical output.

3. **Order.**  Relevance first, and the list's existing ranking
   (recommended / deadline / fit) as the tie-break, so search re-orders the same
   product ranking rather than replacing it with a second, invisible one.

What this deliberately does NOT do is invent a link.  A lab with no agent work
recorded anywhere in its topics, its directions or its evidence does not appear
under "agents", however famous it is for agents elsewhere.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import ResearchTopic
from app.services import taxonomy
from app.services.text import find_phrase, normalize, tokens

if TYPE_CHECKING:
    from app.models.opportunity import Opportunity

# How strongly each kind of evidence argues that a row answers the query.
#
# The order is the product decision: an exact title hit is the student naming
# the thing; a topic hit is the ontology saying the lab works on it; a lab or PI
# name is a weaker but still direct identification; prose is the weakest,
# because "agents" in a paragraph may be a passing aside.
WEIGHTS: dict[str, float] = {
    "title_exact": 100.0,
    "title_phrase": 70.0,
    "title_terms": 45.0,
    "topic": 55.0,
    "topic_depth": 8.0,
    "name": 40.0,
    "organization": 22.0,
    "concept": 12.0,
    "description": 14.0,
    "evidence": 8.0,
    "kind": 18.0,
}

#: How far a matched topic is from what was actually asked for.
TIER_WEIGHT: dict[str, float] = {
    # the query names this topic outright
    "exact": 1.0,
    # the query states one of the topic's own vocabulary terms
    "alias": 0.9,
    # the query's words appear in a harvested topic's label
    "label": 0.7,
    # one hop away on the hand-checked adjacency list
    "related": 0.5,
}

#: A department-wide label such as "Artificial Intelligence" is true of nearly
#: every lab here, so it may contribute something but never enough to outrank a
#: topic that actually distinguishes one lab from another.
GENERIC_TIER_WEIGHT = 0.15

#: At most this many additional distinct topic hits count toward ``topic_depth``.
MAX_TOPIC_DEPTH = 3

#: Terms shorter than this are too ambiguous to search prose with ("ai" matches
#: half the corpus; "rl" matches nothing useful).  They still reach the ontology
#: through the alias table, which is exactly where two-letter terms belong.
MIN_TERM_LENGTH = 3


@dataclass(frozen=True, slots=True)
class TopicHit:
    """One ontology topic the query was expanded onto, and how it got there."""

    slug: str
    label: str
    tier: str
    weight: float


@dataclass(frozen=True, slots=True)
class SearchIntent:
    """What a query turned out to be asking for."""

    query: str
    phrase: str
    #: Content words, plus a cheap singular/plural variant of each.
    needles: tuple[str, ...]
    #: The query's own content words, unexpanded, for reporting.
    terms: tuple[str, ...]
    topics: dict[str, TopicHit]
    #: Vocabulary of the topics the query named outright, used to notice the
    #: concept in prose that nobody got round to tagging.
    concept_terms: tuple[str, ...]
    kinds: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SearchHit:
    """Why one row is in the results, and how strongly."""

    score: float
    reasons: tuple[str, ...]


def _variants(term: str) -> tuple[str, ...]:
    """``term`` plus its obvious singular/plural twin.

    Deliberately four rules rather than a stemmer: "library" has to reach
    "Stanford Libraries" and "agents" has to reach "human-agent collaboration",
    and anything cleverer than this stops being auditable.
    """
    out = [term]
    if len(term) < MIN_TERM_LENGTH + 1:
        return tuple(out)
    if term.endswith("ies"):
        out.append(term[:-3] + "y")
    elif term.endswith("es") and len(term) > 4:
        out.append(term[:-2])
        out.append(term[:-1])
    elif term.endswith("s"):
        out.append(term[:-1])
    elif term.endswith("y"):
        out.append(term[:-1] + "ies")
    else:
        out.append(term + "s")
    return tuple(dict.fromkeys(out))


def _topic_vocabulary(db: Session) -> dict[str, tuple[str, tuple[str, ...]]]:
    """``slug -> (label, search terms)`` for the stored ontology.

    The stored rows are the union of the built-in ontology and everything the
    harvest tagged labs with, which is why this is read from the database rather
    than from the module-level ontology: the fine-grained labels
    ("generative AI for tutoring and education") only exist here.
    """
    rows = db.execute(
        select(ResearchTopic.slug, ResearchTopic.label, ResearchTopic.aliases)
    ).all()
    vocab: dict[str, tuple[str, tuple[str, ...]]] = {}
    for slug, label, aliases in rows:
        terms = [label or slug, *(aliases or [])]
        vocab[slug] = (
            taxonomy.clean_label(label, slug),
            tuple(dict.fromkeys(t for t in terms if t and t.strip())),
        )
    return vocab


def build_intent(db: Session, query: str | None) -> SearchIntent | None:
    """Read a query as a question about topics, names and kinds of work."""
    raw = (query or "").strip()
    if not raw:
        return None
    phrase = normalize(raw)
    terms = tuple(dict.fromkeys(tokens(raw, drop_stopwords=True)))
    long_terms = tuple(t for t in terms if len(t) >= MIN_TERM_LENGTH)
    needles: list[str] = [phrase] if phrase not in long_terms else []
    for term in long_terms:
        for variant in _variants(term):
            if variant not in needles:
                needles.append(variant)

    vocab = _topic_vocabulary(db)
    hits: dict[str, TopicHit] = {}
    notes: list[str] = []

    def put(slug: str, tier: str) -> None:
        label, _terms = vocab.get(slug, (taxonomy.topic_label(slug), ()))
        weight = (
            GENERIC_TIER_WEIGHT if slug in taxonomy.GENERIC_TOPICS else TIER_WEIGHT[tier]
        )
        current = hits.get(slug)
        if current is None or weight > current.weight:
            hits[slug] = TopicHit(slug=slug, label=label, tier=tier, weight=weight)

    # 1. the canonical vocabulary: alias table first, then labels and aliases.
    primary = taxonomy.resolve_topic(raw)
    if primary:
        put(primary, "exact")
        label, _ = vocab.get(primary, (taxonomy.topic_label(primary), ()))
        notes.append(f'"{raw}" reads as the topic {label}.')

    # 2. an ontology term the query states outright.
    for slug, (_label, topic_terms) in vocab.items():
        for term in topic_terms:
            if len(term) < MIN_TERM_LENGTH:
                continue
            if find_phrase(raw, term) is None:
                continue
            put(slug, "exact" if normalize(term) == phrase else "alias")
            break

    # 3. the query's own words inside a harvested topic label. This is what
    #    reaches the fine-grained tags the ontology never had names for.
    if long_terms:
        for slug, (label, _terms) in vocab.items():
            if slug in hits:
                continue
            if all(find_phrase(label, term) is not None for term in long_terms):
                put(slug, "label")

    # 4. one hop of hand-checked neighbours, from the topics actually named.
    for slug in [s for s, hit in hits.items() if hit.tier in ("exact", "alias")]:
        for neighbour in taxonomy.related_slugs(slug):
            if neighbour not in hits:
                put(neighbour, "related")

    concept: list[str] = []
    for hit in hits.values():
        if hit.tier not in ("exact", "alias"):
            continue
        _label, topic_terms = vocab.get(hit.slug, (hit.label, ()))
        for term in (hit.label, *topic_terms):
            cleaned = normalize(term)
            if len(cleaned) >= 4 and cleaned not in needles and cleaned not in concept:
                concept.append(cleaned)

    kinds = taxonomy.resolve_kinds(raw)
    if kinds:
        notes.append(
            "Narrowed to "
            + ", ".join(taxonomy.KIND_LABEL.get(k, k) for k in kinds)
            + " — that is a kind of work, not a research topic."
        )
    related = [h.label for h in hits.values() if h.tier == "related"]
    if related:
        notes.append("Also searched neighbouring topics: " + ", ".join(sorted(related)) + ".")

    return SearchIntent(
        query=raw,
        phrase=phrase,
        needles=tuple(needles),
        terms=long_terms or terms,
        topics=hits,
        concept_terms=tuple(concept),
        kinds=kinds,
        notes=tuple(notes),
    )


def _first_hit(text: str | None, needles: tuple[str, ...]) -> str | None:
    if not text:
        return None
    for needle in needles:
        if find_phrase(text, needle) is not None:
            return needle
    return None


def _term_coverage(text: str | None, intent: SearchIntent) -> tuple[float, list[str]]:
    """Fraction of the query's content words present in ``text``."""
    if not text or not intent.terms:
        return 0.0, []
    found = [
        term
        for term in intent.terms
        if any(find_phrase(text, variant) is not None for variant in _variants(term))
    ]
    return len(found) / len(intent.terms), found


def _topic_slugs(opp: Opportunity) -> dict[str, str]:
    """Every topic slug attached to a row, directly or through its PI."""
    out: dict[str, str] = {}
    for link in opp.topics:
        if link.topic is not None:
            out.setdefault(link.topic.slug, taxonomy.clean_label(link.topic.label, link.topic.slug))
    faculty = opp.faculty
    if faculty is not None:
        for link in faculty.topics:
            if link.topic is not None:
                out.setdefault(
                    link.topic.slug, taxonomy.clean_label(link.topic.label, link.topic.slug)
                )
    return out


def _names(opp: Opportunity) -> list[str]:
    out: list[str] = []
    if opp.lab is not None and opp.lab.name:
        out.append(opp.lab.name)
    faculty = opp.faculty
    if faculty is not None:
        if faculty.name:
            out.append(faculty.name)
        for lab in faculty.labs:
            if lab.name and lab.name not in out:
                out.append(lab.name)
    return out


def _prose(opp: Opportunity) -> list[str]:
    """Free text that describes the work, in descending order of authority."""
    out: list[str] = []
    for value in (opp.description, opp.organization, opp.hours_note, opp.pay_text):
        if value:
            out.append(value)
    if opp.lab is not None and opp.lab.description:
        out.append(opp.lab.description)
    faculty = opp.faculty
    if faculty is not None:
        out.extend(faculty.current_direction or [])
        out.extend(faculty.research_areas or [])
        if faculty.bio:
            out.append(faculty.bio)
    return out


def score(opp: Opportunity, intent: SearchIntent, *, evidence: bool = True) -> SearchHit | None:
    """Score one row against a query, or ``None`` when nothing at all matched."""
    total = 0.0
    reasons: list[str] = []

    def add(key: str, reason: str, factor: float = 1.0) -> None:
        nonlocal total
        total += WEIGHTS[key] * factor
        reasons.append(reason)

    title = opp.title or ""
    if normalize(title) == intent.phrase:
        add("title_exact", f'Title is exactly "{intent.query}"')
    elif find_phrase(title, intent.phrase) is not None:
        add("title_phrase", f'"{intent.query}" appears in the title')
    else:
        coverage, found = _term_coverage(title, intent)
        if coverage > 0:
            add("title_terms", "Title mentions " + ", ".join(found), coverage)

    slugs = _topic_slugs(opp)
    matched = sorted(
        (intent.topics[slug] for slug in slugs if slug in intent.topics),
        key=lambda hit: (-hit.weight, hit.slug),
    )
    if matched:
        best = matched[0]
        add(
            "topic",
            f"Tagged {best.label}" + ("" if best.tier == "exact" else f" ({best.tier} match)"),
            best.weight,
        )
        extra = matched[1 : 1 + MAX_TOPIC_DEPTH]
        if extra:
            add(
                "topic_depth",
                "Also tagged " + ", ".join(hit.label for hit in extra),
                float(len(extra)),
            )

    for name in _names(opp):
        hit = _first_hit(name, intent.needles)
        if hit is not None:
            add("name", f'Lab or professor name contains "{hit}" — {name}')
            break

    if opp.organization or opp.department:
        for value in (opp.organization, opp.department):
            hit = _first_hit(value, intent.needles)
            if hit is not None:
                add("organization", f'"{hit}" appears in {value}')
                break

    prose = _prose(opp)
    for value in prose:
        hit = _first_hit(value, intent.needles)
        if hit is not None:
            add("description", f'"{hit}" appears in the description')
            break

    if intent.concept_terms:
        for value in (title, *prose):
            hit = _first_hit(value, intent.concept_terms)
            if hit is not None:
                add("concept", f'Related wording: "{hit}"')
                break

    if evidence and opp.faculty is not None:
        for item in opp.faculty.evidence:
            hit = _first_hit(item.title, intent.needles)
            if hit is not None:
                add("evidence", f'Recent work mentions "{hit}": {item.title}')
                break

    if intent.kinds and opp.type.value in intent.kinds:
        add("kind", f"Is {taxonomy.KIND_LABEL.get(opp.type.value, opp.type.value)} work")

    if not reasons:
        return None
    return SearchHit(score=round(total, 3), reasons=tuple(reasons))


def rank(
    hits: dict[uuid.UUID, SearchHit], ordered_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Position of each id once relevance leads and the list's own sort follows.

    The caller has already sorted by whatever the student chose (recommended,
    deadline, fit). Passing that order in as the tie-break keeps search a
    re-ordering of the product's ranking rather than a second ranking that
    disagrees with it for reasons nobody can see.
    """
    existing = {opp_id: index for index, opp_id in enumerate(ordered_ids)}
    ranked = sorted(
        ordered_ids,
        key=lambda opp_id: (-(hits[opp_id].score if opp_id in hits else 0.0), existing[opp_id]),
    )
    return {opp_id: index for index, opp_id in enumerate(ranked)}
