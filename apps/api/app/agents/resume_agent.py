"""Which of the student's own resumes to send, and why.

This agent never writes resume content.  It reads the documents the student
already uploaded, ranks them against one opportunity, and explains the ranking
in terms that point back at real lines in the file:

* ``matched_strengths`` — a stated qualification with a resume line behind it.
  No line, no strength; we never credit a resume for something we cannot quote.
* ``weak_or_missing`` — what this *document* does not show.  A gap is a fact
  about the paper, never a claim about the student, and a "preferred" line is
  never reported as "required" (spec §20).
* ``emphasize`` — up to four verbatim lines worth leading with.  Selection only;
  the text is the student's, unchanged, and we never suggest adding anything.

Scoring is deterministic and component-wise, so the UI can show the arithmetic
instead of a mystery number.  The LLM is allowed to re-word ``rationale`` when a
reasoning provider is configured, and nothing else — the lists it might have
opinions about are computed before it is ever called.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import delete

from app.agents.base import Agent, AgentContext, AgentOutcome
from app.llm.base import LLMUnavailable
from app.models.application import ResumeRecommendation
from app.models.enums import OpportunityType, RequirementKind, RequirementMatch
from app.models.opportunity import Opportunity
from app.models.resume import Resume
from app.services import taxonomy
from app.services.resume_parser import PARSE_FAILED, extract_highlights, parse_text
from app.services.text import concat, content_words, normalize, truncate

MAX_EMPHASIS = 4
MAX_LIST_ITEMS = 8
QUOTE_LIMIT = 110

# A resume that carries three separate lines of evidence for one posting is
# already making the strongest case a single document can make.
_EVIDENCE_TARGET = 3

RESEARCH_TYPES = (OpportunityType.RESEARCH_OPENING, OpportunityType.RESEARCH_OUTREACH)

_WEIGHTS: dict[str, dict[str, float]] = {
    "research": {
        "required": 0.28,
        "preferred": 0.10,
        "skills": 0.16,
        "topics": 0.22,
        "evidence": 0.10,
        "shape": 0.14,
    },
    "jobs": {
        "required": 0.34,
        "preferred": 0.12,
        "skills": 0.20,
        "topics": 0.06,
        "evidence": 0.12,
        "shape": 0.16,
    },
}

_COMPONENT_LABELS = {
    "required": "Required qualifications evidenced",
    "preferred": "Preferred qualifications evidenced",
    "skills": "Skills the posting names",
    "topics": "Subject-matter overlap",
    "evidence": "Depth of evidence",
    "shape": "Right kind of resume",
}

_RESEARCH_ROLE_RE = re.compile(
    r"research|\blab\b|laborator|thesis|dissertation|\breu\b|advis(?:or|er)|"
    r"co-?author|preprint|manuscript|publication",
    re.IGNORECASE,
)
_SERVICE_ROLE_RE = re.compile(
    r"barista|server|cashier|dining|front desk|retail|customer|patron|guest|shift|"
    r"store|caf[eé]|catering|library|usher|lifeguard|counselor|receptionist|"
    r"tutor|assistant manager|host(?:ess)?\b|volunteer",
    re.IGNORECASE,
)

# Skill categories that say "this is a research document" / "this is a work document".
_RESEARCH_CATEGORIES = frozenset({"method", "domain"})
_JOB_CATEGORIES = frozenset({"service", "soft"})

_EMPHASIS_ARTICLE = {
    RequirementKind.REQUIRED: "a required qualification",
    RequirementKind.PREFERRED: "a preferred qualification",
    RequirementKind.INFERRED: "something this posting implies",
}
_EMPHASIS_WEIGHT = {
    RequirementKind.REQUIRED: 3.0,
    RequirementKind.PREFERRED: 2.0,
    RequirementKind.INFERRED: 1.0,
}

_DISJUNCTION_RE = re.compile(r"\bor\b", re.IGNORECASE)
_MATCH_THRESHOLD = 0.75
_PARTIAL_THRESHOLD = 0.5

# Words that would turn a re-worded rationale into resume-writing advice.
_ADVICE_RE = re.compile(
    r"\b(add|adding|rewrite|reword|rephrase|tailor|fabricat\w*|invent|pad|embellish)\b",
    re.IGNORECASE,
)


def _quote(text: str) -> str:
    return truncate(" ".join(text.split()), QUOTE_LIMIT)


# --------------------------------------------------------------------------
# What the opportunity asks for
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Need:
    """One thing the posting asks for, kept with the kind it was stated as."""

    text: str
    kind: RequirementKind
    slugs: frozenset[str]
    words: frozenset[str]
    disjunctive: bool

    @property
    def prefix(self) -> str:
        if self.kind is RequirementKind.REQUIRED:
            return "Required"
        if self.kind is RequirementKind.PREFERRED:
            return "Preferred"
        return "Likely wanted (inferred)"


def _need(text: str, kind: RequirementKind, slugs: Sequence[str]) -> Need | None:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return None
    resolved = set(taxonomy.resolve_skills(slugs)) if slugs else set()
    if not resolved:
        resolved = taxonomy.match_skill_slugs(cleaned)
    return Need(
        text=cleaned,
        kind=kind,
        slugs=frozenset(resolved),
        words=frozenset(content_words(cleaned)),
        disjunctive=bool(_DISJUNCTION_RE.search(cleaned)),
    )


@dataclass(slots=True)
class OpportunityAsk:
    """The opportunity, reduced to what a resume can be judged against."""

    title: str
    family: str
    required: list[Need]
    preferred: list[Need]
    inferred: list[Need]
    skills: list[str]
    topics: list[str]

    @property
    def states_anything(self) -> bool:
        return bool(self.required or self.preferred or self.skills or self.topics)


def _opportunity_topics(opportunity: Opportunity, blob: str) -> list[str]:
    slugs: list[str] = []
    for link in opportunity.topics or []:
        slug = getattr(getattr(link, "topic", None), "slug", None)
        if isinstance(slug, str) and slug not in slugs:
            slugs.append(slug)
    for slug, weight in taxonomy.match_topics(blob):
        if weight >= 0.6 and slug not in slugs:
            slugs.append(slug)
    return slugs


def build_ask(opportunity: Opportunity) -> OpportunityAsk:
    """Read one opportunity into the shape the scorer needs."""
    buckets: dict[RequirementKind, list[Need]] = {
        RequirementKind.REQUIRED: [],
        RequirementKind.PREFERRED: [],
        RequirementKind.INFERRED: [],
    }
    for requirement in opportunity.requirements or []:
        kind = requirement.kind or RequirementKind.INFERRED
        need = _need(requirement.text, kind, requirement.skill_slugs or [])
        if need is not None and need.text not in {n.text for n in buckets[kind]}:
            buckets[kind].append(need)

    faculty = getattr(opportunity, "faculty", None)
    # A research lead built from a faculty page carries no posted requirements.
    # Judging a resume against an empty ask would always say "nothing matches",
    # so the lab's CURRENT DIRECTION and topics become the thing to match — which
    # is what a student would actually tailor toward anyway.
    direction = list(getattr(faculty, "current_direction", None) or []) if faculty else []
    lab_topics: list[str] = []
    if faculty is not None:
        lab_topics = [
            ft.topic.label for ft in (getattr(faculty, "topics", None) or []) if ft.topic
        ]

    blob = concat(
        opportunity.title,
        opportunity.description,
        opportunity.skills,
        " ".join(direction),
        " ".join(lab_topics),
    )
    skills = taxonomy.resolve_skills(opportunity.skills or [])
    if not skills:
        skills = sorted(taxonomy.match_skill_slugs(blob))

    if not buckets[RequirementKind.REQUIRED] and not buckets[RequirementKind.PREFERRED]:
        # Marked INFERRED, never REQUIRED: the lab never posted these, we derived
        # them, and the UI must show them as inferred.
        for phrase in direction[:5]:
            need = _need(phrase, RequirementKind.INFERRED, [])
            if need is not None and need.text not in {
                n.text for n in buckets[RequirementKind.INFERRED]
            }:
                buckets[RequirementKind.INFERRED].append(need)

    return OpportunityAsk(
        title=opportunity.title or "this opportunity",
        family="research" if opportunity.type in RESEARCH_TYPES else "jobs",
        required=buckets[RequirementKind.REQUIRED],
        preferred=buckets[RequirementKind.PREFERRED],
        inferred=buckets[RequirementKind.INFERRED],
        skills=skills,
        topics=_opportunity_topics(opportunity, blob)
        or [t for t in (taxonomy.resolve_topic(x) or '' for x in lab_topics) if t],
    )


# --------------------------------------------------------------------------
# What the resume actually says
# --------------------------------------------------------------------------


@dataclass(slots=True)
class EvidenceLine:
    text: str
    section: str | None
    is_highlight: bool
    skills: frozenset[str]
    topics: frozenset[str]
    words: frozenset[str]


@dataclass(slots=True)
class ResumeEvidence:
    """One uploaded resume, read as evidence."""

    resume: Resume
    label: str
    lines: list[EvidenceLine]
    skills: frozenset[str]
    topics: frozenset[str]
    sections: frozenset[str]
    readable: bool
    problem: str | None = None

    @property
    def highlights(self) -> list[EvidenceLine]:
        return [line for line in self.lines if line.is_highlight]

    def has(self, pattern: re.Pattern[str]) -> bool:
        return any(pattern.search(line.text) for line in self.lines)


def read_resume(resume: Resume) -> ResumeEvidence:
    """Build the evidence view of a resume from its stored parse."""
    label = resume.label or resume.original_filename or "Resume"
    text = resume.text or ""
    stored = list(resume.highlights or [])

    if resume.parse_status == PARSE_FAILED or (not text.strip() and not stored):
        return ResumeEvidence(
            resume=resume,
            label=label,
            lines=[],
            skills=frozenset(),
            topics=frozenset(),
            sections=frozenset(),
            readable=False,
            problem=resume.parse_error or "This file has not been read yet, so it cannot be compared.",
        )

    parsed = parse_text(text)
    lines: list[EvidenceLine] = []

    highlight_rows = [
        (row.text, row.section, list(row.skills or []), list(row.topics or []))
        for row in stored
        if (row.text or "").strip()
    ]
    if not highlight_rows:
        highlight_rows = [(h.text, h.section, h.skills, h.topics) for h in extract_highlights(parsed)]

    quoted: list[str] = []
    for htext, section, skills, topics in highlight_rows:
        quoted.append(normalize(htext))
        lines.append(
            EvidenceLine(
                text=htext,
                section=section,
                is_highlight=True,
                skills=frozenset(skills or taxonomy.match_skill_slugs(htext)),
                topics=frozenset(topics or [slug for slug, _ in taxonomy.match_topics(htext)]),
                words=frozenset(content_words(htext)),
            )
        )

    for record in parsed.records:
        if record.is_heading:
            continue
        body = record.content.strip()
        normalized = normalize(body)
        if not normalized or any(normalized in seen for seen in quoted):
            continue
        lines.append(
            EvidenceLine(
                text=body,
                section=record.section,
                is_highlight=False,
                skills=frozenset(taxonomy.match_skill_slugs(body)),
                topics=frozenset(),
                words=frozenset(content_words(body)),
            )
        )

    doc_skills = {slug for line in lines for slug in line.skills}
    doc_topics = {slug for slug, weight in taxonomy.match_topics(text) if weight >= 0.5}
    doc_topics |= {slug for line in lines for slug in line.topics}
    return ResumeEvidence(
        resume=resume,
        label=label,
        lines=lines,
        skills=frozenset(doc_skills),
        topics=frozenset(doc_topics),
        sections=frozenset(parsed.sections),
        readable=True,
    )


# --------------------------------------------------------------------------
# Matching one requirement to one resume
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Support:
    """How (and whether) a resume backs one thing the posting asks for."""

    need: Need
    state: RequirementMatch
    evidence: EvidenceLine | None = None

    @property
    def credit(self) -> float:
        if self.state is RequirementMatch.MATCHED:
            return 1.0
        return 0.5 if self.state is RequirementMatch.PARTIAL else 0.0

    @property
    def counts(self) -> bool:
        """UNKNOWN means we could not judge — it must not count either way."""
        return self.state is not RequirementMatch.UNKNOWN


def _best_line_for_slugs(doc: ResumeEvidence, slugs: frozenset[str]) -> EvidenceLine | None:
    candidates = [line for line in doc.lines if line.skills & slugs]
    if not candidates:
        return None
    return max(candidates, key=lambda line: (line.is_highlight, len(line.skills & slugs)))


def _best_line_for_words(doc: ResumeEvidence, words: frozenset[str]) -> tuple[EvidenceLine | None, float]:
    """The line that covers most of the requirement's content words."""
    scored = [
        (len(words & line.words) / len(words), line.is_highlight, line)
        for line in doc.lines
        if line.words
    ]
    scored = [item for item in scored if item[0] > 0]
    if not scored:
        return None, 0.0
    score, _, line = max(scored, key=lambda item: (item[0], item[1]))
    return line, score


def support_for(need: Need, doc: ResumeEvidence) -> Support:
    """Judge one requirement against one resume, evidence-first."""
    if need.slugs:
        hits = need.slugs & doc.skills
        if hits:
            covered = len(hits) / len(need.slugs)
            matched = covered >= 1.0 or (need.disjunctive and bool(hits)) or covered >= 0.5
            return Support(
                need=need,
                state=RequirementMatch.MATCHED if matched else RequirementMatch.PARTIAL,
                evidence=_best_line_for_slugs(doc, need.slugs),
            )

    if len(need.words) < 2:
        # Nothing substantive to look for ("Enthusiasm!"): say so rather than
        # scoring the resume down for it.
        return Support(need=need, state=RequirementMatch.UNKNOWN)

    line, score = _best_line_for_words(doc, need.words)
    threshold = _PARTIAL_THRESHOLD if need.disjunctive else _MATCH_THRESHOLD
    if line is not None and score >= threshold:
        return Support(need=need, state=RequirementMatch.MATCHED, evidence=line)
    if line is not None and score >= _PARTIAL_THRESHOLD:
        return Support(need=need, state=RequirementMatch.PARTIAL, evidence=line)
    return Support(need=need, state=RequirementMatch.MISSING)


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


@dataclass(slots=True)
class ScoreComponent:
    key: str
    label: str
    raw: float
    weight: float
    reason: str
    applicable: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "raw": round(self.raw, 3),
            "weight": self.weight,
            "points": round(self.raw * self.weight * 100, 1),
            "reason": self.reason,
            "applicable": self.applicable,
        }


def _coverage(supports: Sequence[Support]) -> tuple[float, int, int]:
    judged = [s for s in supports if s.counts]
    if not judged:
        return 0.0, 0, 0
    credit = sum(s.credit for s in judged)
    full = sum(1 for s in judged if s.state is RequirementMatch.MATCHED)
    return credit / len(judged), full, len(judged)


def _shape_signals(ask: OpportunityAsk, doc: ResumeEvidence) -> list[tuple[float, str, bool]]:
    """Is this the right *kind* of document for this kind of opportunity?"""
    categories = {taxonomy.SKILL_BY_SLUG[s].category for s in doc.skills if s in taxonomy.SKILL_BY_SLUG}
    if ask.family == "research":
        return [
            (0.30, "has a research section", "research" in doc.sections),
            (0.20, "lists publications", "publications" in doc.sections),
            (0.30, "shows a research role or lab work", doc.has(_RESEARCH_ROLE_RE)),
            (
                0.20,
                "shows technical or method skills",
                bool(categories & _RESEARCH_CATEGORIES) or "projects" in doc.sections,
            ),
        ]
    return [
        (0.30, "has a work-experience section", "experience" in doc.sections),
        (0.30, "shows a customer-facing or campus role", doc.has(_SERVICE_ROLE_RE)),
        (0.20, "shows activities or leadership", "activities" in doc.sections),
        (0.20, "lists service or people skills", bool(categories & _JOB_CATEGORIES)),
    ]


def _components(
    ask: OpportunityAsk,
    doc: ResumeEvidence,
    required: Sequence[Support],
    preferred: Sequence[Support],
    matched_skills: set[str],
    matched_topics: set[str],
    evidence_lines: int,
) -> list[ScoreComponent]:
    weights = _WEIGHTS[ask.family]

    req_raw, req_full, req_judged = _coverage(required)
    pref_raw, pref_full, pref_judged = _coverage(preferred)

    skills_raw = len(matched_skills) / len(ask.skills) if ask.skills else 0.0
    topics_raw = len(matched_topics) / len(ask.topics) if ask.topics else 0.0
    evidence_raw = min(1.0, evidence_lines / _EVIDENCE_TARGET)

    signals = _shape_signals(ask, doc)
    shape_raw = sum(weight for weight, _, present in signals if present)
    shown = [name for _, name, present in signals if present]

    return [
        ScoreComponent(
            key="required",
            label=_COMPONENT_LABELS["required"],
            raw=req_raw,
            weight=weights["required"],
            reason=(
                f"{req_full} of {req_judged} required qualifications are evidenced by a line in this resume"
                if req_judged
                else "The posting states no required qualifications"
            ),
            applicable=bool(req_judged),
        ),
        ScoreComponent(
            key="preferred",
            label=_COMPONENT_LABELS["preferred"],
            raw=pref_raw,
            weight=weights["preferred"],
            reason=(
                f"{pref_full} of {pref_judged} preferred qualifications are evidenced"
                if pref_judged
                else "The posting states no preferred qualifications"
            ),
            applicable=bool(pref_judged),
        ),
        ScoreComponent(
            key="skills",
            label=_COMPONENT_LABELS["skills"],
            raw=skills_raw,
            weight=weights["skills"],
            reason=(
                f"{len(matched_skills)} of {len(ask.skills)} named skills appear in this resume"
                if ask.skills
                else "The posting names no specific skills"
            ),
            applicable=bool(ask.skills),
        ),
        ScoreComponent(
            key="topics",
            label=_COMPONENT_LABELS["topics"],
            raw=topics_raw,
            weight=weights["topics"],
            reason=(
                f"{len(matched_topics)} of {len(ask.topics)} subject areas overlap"
                if ask.topics
                else "No subject areas identified for this opportunity"
            ),
            applicable=bool(ask.topics),
        ),
        ScoreComponent(
            key="evidence",
            label=_COMPONENT_LABELS["evidence"],
            raw=evidence_raw,
            weight=weights["evidence"],
            reason=f"{evidence_lines} resume line(s) back up what the posting asks for",
            applicable=ask.states_anything,
        ),
        ScoreComponent(
            key="shape",
            label=_COMPONENT_LABELS["shape"],
            raw=shape_raw,
            weight=weights["shape"],
            reason=(
                "This resume " + ", ".join(shown)
                if shown
                else "This resume shows none of the usual signals for this kind of opportunity"
            ),
        ),
    ]


def _total(components: Sequence[ScoreComponent]) -> float:
    """Weights are renormalised over what the posting actually stated.

    A posting that lists no requirements must not push every resume's score
    down; it just means that component has nothing to say.
    """
    live = [c for c in components if c.applicable]
    denominator = sum(c.weight for c in live)
    if not live or denominator <= 0:
        return 0.0
    return round(sum(c.raw * c.weight for c in live) / denominator * 100, 1)


# --------------------------------------------------------------------------
# The per-resume verdict
# --------------------------------------------------------------------------


@dataclass(slots=True)
class ResumeFit:
    """One resume judged against one opportunity."""

    resume_id: uuid.UUID | None
    label: str
    score: float
    rank: int
    matched_strengths: list[str]
    weak_or_missing: list[str]
    emphasize: list[dict[str, str]]
    rationale: str
    components: list[ScoreComponent]
    supports: list[Support] = field(default_factory=list)
    readable: bool = True

    def as_row(self, opportunity_id: uuid.UUID) -> ResumeRecommendation:
        return ResumeRecommendation(
            opportunity_id=opportunity_id,
            resume_id=self.resume_id,
            score=self.score,
            rank=self.rank,
            matched_strengths=list(self.matched_strengths),
            weak_or_missing=list(self.weak_or_missing),
            emphasize=[dict(item) for item in self.emphasize],
            rationale=self.rationale,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "resume_id": str(self.resume_id) if self.resume_id else None,
            "resume_label": self.label,
            "score": self.score,
            "rank": self.rank,
            "matched_strengths": list(self.matched_strengths),
            "weak_or_missing": list(self.weak_or_missing),
            "emphasize": [dict(item) for item in self.emphasize],
            "rationale": self.rationale,
            "breakdown": [c.as_dict() for c in self.components],
        }


@dataclass(slots=True)
class ResumeMatchRequest:
    opportunity: Opportunity
    resumes: Sequence[Resume]


@dataclass(slots=True)
class ResumeMatchResult:
    fits: list[ResumeFit]
    rows: list[ResumeRecommendation]

    @property
    def best(self) -> ResumeFit | None:
        return self.fits[0] if self.fits else None

    def rationale_payload(self) -> dict[str, Any]:
        """What ``OpportunityMatch.resume_rationale`` should carry."""
        best = self.best
        if best is None:
            return {}
        return {
            "resume_id": str(best.resume_id) if best.resume_id else None,
            "resume_label": best.label,
            "score": best.score,
            "rationale": best.rationale,
            "breakdown": [c.as_dict() for c in best.components],
            "considered": len(self.fits),
        }


class _PolishedRationale(BaseModel):
    rationale: str = Field(max_length=600)


class ResumeMatchingAgent(Agent[ResumeMatchRequest, ResumeMatchResult]):
    """Rank the student's uploaded resumes for one opportunity."""

    name = "resume-matching"
    description = "Ranks the student's existing resumes against one opportunity and explains why."

    def __init__(self) -> None:
        # One instance usually ranks many opportunities against the same few
        # uploads; re-reading every line of every resume each time is waste.
        self._docs: dict[tuple[Any, Any], ResumeEvidence] = {}

    def _doc_for(self, resume: Resume) -> ResumeEvidence:
        key = (resume.id or id(resume), resume.updated_at)
        doc = self._docs.get(key)
        if doc is None:
            doc = read_resume(resume)
            self._docs[key] = doc
        return doc

    def run(self, ctx: AgentContext, payload: ResumeMatchRequest) -> AgentOutcome[ResumeMatchResult]:
        opportunity = payload.opportunity
        resumes = list(payload.resumes)
        notes: list[str] = []
        warnings: list[str] = []

        with self._record(ctx, subject_type="opportunity", subject_id=opportunity.id):
            if not resumes:
                return AgentOutcome(
                    result=ResumeMatchResult(fits=[], rows=[]),
                    notes=["No resume uploaded yet, so there is nothing to compare."],
                )

            ask = build_ask(opportunity)
            if not ask.states_anything:
                notes.append(
                    "This posting states no requirements or skills; ranking is based on which "
                    "resume is the right kind of document."
                )

            fits = [self._evaluate(ask, self._doc_for(resume)) for resume in resumes]
            fits.sort(key=lambda fit: (-fit.score, not fit.readable, fit.label.lower()))
            for position, fit in enumerate(fits, start=1):
                fit.rank = position

            if ctx.can_reason:
                self._polish(ctx, ask, fits, warnings)

            rows: list[ResumeRecommendation] = []
            if opportunity.id is None:
                warnings.append("This opportunity is unsaved, so the ranking was not persisted.")
            else:
                rows = [fit.as_row(opportunity.id) for fit in fits if fit.resume_id is not None]
                if len(rows) < len(fits):
                    warnings.append("Some resumes are unsaved, so their ranking was not persisted.")

            if rows and not ctx.dry_run:
                ctx.db.execute(
                    delete(ResumeRecommendation).where(
                        ResumeRecommendation.opportunity_id == opportunity.id
                    )
                )
                ctx.db.add_all(rows)

            unreadable = [fit.label for fit in fits if not fit.readable]
            if unreadable:
                warnings.append(f"Could not read: {', '.join(unreadable)}.")

            return AgentOutcome(
                result=ResumeMatchResult(fits=fits, rows=rows),
                notes=notes,
                warnings=warnings,
            )

    # -- one resume ------------------------------------------------------

    def _evaluate(self, ask: OpportunityAsk, doc: ResumeEvidence) -> ResumeFit:
        if not doc.readable:
            return ResumeFit(
                resume_id=doc.resume.id,
                label=doc.label,
                score=0.0,
                rank=0,
                matched_strengths=[],
                weak_or_missing=[doc.problem or "This file could not be read."],
                emphasize=[],
                rationale=(
                    f"{doc.label} could not be read, so it cannot be compared against "
                    f"{ask.title}. Upload a text-based PDF to include it."
                ),
                components=[],
                readable=False,
            )

        required = [support_for(need, doc) for need in ask.required]
        preferred = [support_for(need, doc) for need in ask.preferred]
        inferred = [support_for(need, doc) for need in ask.inferred]

        matched_skills = {slug for slug in ask.skills if slug in doc.skills}
        matched_topics = {slug for slug in ask.topics if slug in doc.topics}

        supports = [*required, *preferred, *inferred]
        evidence_lines = {
            id(s.evidence) for s in supports if s.evidence is not None and s.evidence.is_highlight
        }
        for slug in matched_skills:
            line = _best_line_for_slugs(doc, frozenset({slug}))
            if line is not None and line.is_highlight:
                evidence_lines.add(id(line))

        components = _components(
            ask, doc, required, preferred, matched_skills, matched_topics, len(evidence_lines)
        )
        strengths = self._strengths(supports, matched_skills, doc)
        gaps = self._gaps(required, preferred, inferred, ask, doc)
        emphasize = self._emphasize(ask, doc, supports, matched_skills, matched_topics)

        return ResumeFit(
            resume_id=doc.resume.id,
            label=doc.label,
            score=_total(components),
            rank=0,
            matched_strengths=strengths,
            weak_or_missing=gaps,
            emphasize=emphasize,
            rationale=self._rationale(ask, doc, required, preferred, matched_skills, gaps, emphasize),
            components=components,
            supports=supports,
        )

    # -- the three lists -------------------------------------------------

    @staticmethod
    def _strengths(supports: Sequence[Support], matched_skills: set[str], doc: ResumeEvidence) -> list[str]:
        """Only what a real line in this resume backs up."""
        out: list[str] = []
        credited: set[str] = set()
        for support in supports:
            if support.evidence is None or support.state not in (
                RequirementMatch.MATCHED,
                RequirementMatch.PARTIAL,
            ):
                continue
            shown = "shown" if support.state is RequirementMatch.MATCHED else "partly shown"
            out.append(
                f'{support.need.prefix}: {support.need.text} — {shown} in "{_quote(support.evidence.text)}"'
            )
            credited |= support.need.slugs

        for slug in sorted(matched_skills - credited):
            line = _best_line_for_slugs(doc, frozenset({slug}))
            if line is None:
                continue
            out.append(f'{taxonomy.skill_label(slug)} — shown in "{_quote(line.text)}"')
        return out[:MAX_LIST_ITEMS]

    @staticmethod
    def _gaps(
        required: Sequence[Support],
        preferred: Sequence[Support],
        inferred: Sequence[Support],
        ask: OpportunityAsk,
        doc: ResumeEvidence,
    ) -> list[str]:
        """Gaps in the DOCUMENT. Required and preferred are never merged."""
        out: list[str] = []
        for group in (required, preferred, inferred):
            for support in group:
                if support.state is RequirementMatch.MISSING:
                    out.append(f"{support.need.prefix}: {support.need.text} — not shown in this resume")
                elif support.state is RequirementMatch.UNKNOWN:
                    out.append(
                        f"{support.need.prefix}: {support.need.text} — nothing in this resume "
                        "speaks to this either way"
                    )
        for slug in ask.skills:
            if slug not in doc.skills:
                out.append(f"{taxonomy.skill_label(slug)} — not shown in this resume")
        return out[:MAX_LIST_ITEMS]

    @staticmethod
    def _emphasize(
        ask: OpportunityAsk,
        doc: ResumeEvidence,
        supports: Sequence[Support],
        matched_skills: set[str],
        matched_topics: set[str],
    ) -> list[dict[str, str]]:
        """Up to four verbatim lines, each with the reason it earns its place."""
        reasons: dict[int, tuple[float, str]] = {}

        def offer(line: EvidenceLine | None, weight: float, why: str) -> None:
            if line is None or not line.is_highlight:
                return
            current = reasons.get(id(line))
            if current is None or weight > current[0]:
                reasons[id(line)] = (weight, why)

        for support in supports:
            if support.evidence is None or support.state is RequirementMatch.MISSING:
                continue
            weight = _EMPHASIS_WEIGHT[support.need.kind]
            if support.state is RequirementMatch.PARTIAL:
                weight -= 0.5
            offer(
                support.evidence,
                weight,
                f"Evidence for {_EMPHASIS_ARTICLE[support.need.kind]}: {truncate(support.need.text, 90)}",
            )

        for slug in matched_skills:
            offer(
                _best_line_for_slugs(doc, frozenset({slug})),
                1.5,
                f"Shows {taxonomy.skill_label(slug)}, which the posting names.",
            )

        for slug in matched_topics:
            line = next((line for line in doc.highlights if slug in line.topics), None)
            offer(line, 1.2, f"Closest overlap with {taxonomy.topic_label(slug)}.")

        by_id = {id(line): line for line in doc.highlights}
        ranked = sorted(
            ((by_id[key], weight, why) for key, (weight, why) in reasons.items() if key in by_id),
            key=lambda item: -item[1],
        )
        return [{"text": line.text, "why": why} for line, _, why in ranked[:MAX_EMPHASIS]]

    # -- prose -----------------------------------------------------------

    @staticmethod
    def _rationale(
        ask: OpportunityAsk,
        doc: ResumeEvidence,
        required: Sequence[Support],
        preferred: Sequence[Support],
        matched_skills: set[str],
        gaps: Sequence[str],
        emphasize: Sequence[dict[str, str]],
    ) -> str:
        parts: list[str] = []
        _, req_full, req_judged = _coverage(required)
        _, pref_full, pref_judged = _coverage(preferred)
        if req_judged:
            parts.append(f"evidences {req_full} of {req_judged} required qualifications")
        if pref_judged:
            parts.append(f"{pref_full} of {pref_judged} preferred")
        if matched_skills:
            named = ", ".join(taxonomy.skill_label(s) for s in sorted(matched_skills)[:3])
            # "and" only reads correctly when it joins a preceding clause.
            parts.append(f"names {named}" if not parts else f"and names {named}")

        if parts:
            opening = f"{doc.label} {', '.join(parts)}."
        elif ask.states_anything:
            opening = f"{doc.label} does not visibly address what this posting asks for."
        else:
            opening = f"{doc.label} is being judged on shape alone — this posting states no requirements."

        middle = (
            f" {len(emphasize)} line(s) are worth leading with."
            if emphasize
            else " No line in it speaks directly to this posting."
        )
        tail = f" Not shown: {truncate(gaps[0].split(' — ')[0], 90)}." if gaps else ""
        return (opening + middle + tail).strip()

    def _polish(self, ctx: AgentContext, ask: OpportunityAsk, fits: Sequence[ResumeFit], warnings: list[str]) -> None:
        """Let the model re-word the rationale only. The lists are already fixed."""
        system = (
            "You rewrite one short explanation of why a resume fits an opportunity. "
            "You may only re-word the facts you are given. Never introduce a skill, "
            "experience, course or claim that is not in the input, never advise the "
            "student to add or change resume content, and keep required and preferred "
            "qualifications distinct. Two or three sentences."
        )
        for fit in fits:
            if not fit.readable:
                continue
            prompt = (
                f"Opportunity: {ask.title}\n"
                f"Resume: {fit.label}\n"
                f"Score: {fit.score}\n"
                f"Evidenced: {'; '.join(fit.matched_strengths) or 'nothing'}\n"
                f"Not shown in this resume: {'; '.join(fit.weak_or_missing) or 'nothing'}\n"
                f"Draft: {fit.rationale}"
            )
            try:
                result = ctx.llm.complete_json(
                    system=system,
                    prompt=prompt,
                    schema=_PolishedRationale,
                    task="resume-rationale",
                )
            except LLMUnavailable:
                warnings.append("Rationale left in its deterministic form (model unavailable).")
                return
            candidate = " ".join(result.data.rationale.split())
            if candidate and not _ADVICE_RE.search(candidate):
                fit.rationale = candidate
