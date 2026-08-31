"""Explainable ranking (spec §8).

Two scoring models — one for jobs, one for research leads — both returning a
:class:`ScoreResult` whose ``fit_score`` is nothing more than the weighted sum
of components you can read on screen.  Three rules shape the whole module:

* **No mystery numbers.**  Every component carries its raw score, its weight and
  a sentence naming the evidence that produced it.
* **Unknown is not zero.**  A factor we cannot observe scores neutrally and
  lowers ``confidence``; the one exception is pay, whose weight is redistributed
  across the other factors so an unpaid-looking posting is not silently punished
  for a missing field.
* **Recency is the differentiator for research.**  ``recent_work_alignment``
  divides by the total recency weight of *all* evidence, so a single stale item
  cannot produce a high score no matter how well it matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from app.core.config import get_settings
from app.models.enums import (
    Certainty,
    DeadlineType,
    EligibilityState,
    LeadState,
    OpportunityType,
    RequirementKind,
    RequirementMatch,
    SignalKind,
    WorkAuthorization,
)
from app.services import taxonomy
from app.services.text import (
    concat,
    contains_phrase,
    content_words,
    extract_course_codes,
    extract_hours_per_week,
    fuzzy_ratio,
    normalize,
    truncate,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.agents.base import AgentContext

__all__ = [
    "JOB_WEIGHTS",
    "RESEARCH_WEIGHTS",
    "ProfileView",
    "Recommendation",
    "RequirementAssessment",
    "ScoreComponent",
    "ScoreResult",
    "assess_requirements",
    "derive_eligibility",
    "explain",
    "recommend",
    "score_job",
    "score_research",
]

SCORER_VERSION = "1"
JOB_MODEL = "jobs-v1"
RESEARCH_MODEL = "research-v1"


class Recommendation(StrEnum):
    STRONG_APPLY = "strong_apply"
    APPLY = "apply"
    REACH_OUT = "reach_out"
    CONSIDER = "consider"
    SKIP = "skip"


JOB_WEIGHTS: dict[str, float] = {
    "qualification_match": 0.28,
    "skills_match": 0.18,
    "interest_alignment": 0.16,
    "hours_fit": 0.10,
    "location_fit": 0.08,
    "deadline_urgency": 0.08,
    "compensation": 0.06,
    "eligibility": 0.06,
}

RESEARCH_WEIGHTS: dict[str, float] = {
    "topic_similarity": 0.24,
    "recent_work_alignment": 0.20,
    "skills_overlap": 0.14,
    "undergrad_friendliness": 0.12,
    "coursework_overlap": 0.08,
    "lab_activity": 0.08,
    "opening_vs_outreach": 0.08,
    "campus_fit": 0.06,
}

COMPONENT_LABELS: dict[str, str] = {
    "qualification_match": "Stated qualifications",
    "skills_match": "Skills",
    "interest_alignment": "Interest alignment",
    "hours_fit": "Weekly hours",
    "location_fit": "Location",
    "deadline_urgency": "Deadline",
    "compensation": "Pay",
    "eligibility": "Eligibility",
    "topic_similarity": "Topic overlap",
    "recent_work_alignment": "Recent work (last 1–2 years)",
    "skills_overlap": "Skills",
    "undergrad_friendliness": "Undergraduate involvement",
    "coursework_overlap": "Coursework",
    "lab_activity": "Lab activity",
    "opening_vs_outreach": "Opening vs. cold outreach",
    "campus_fit": "Campus",
}

# Only these categories can make somebody actually *ineligible*; everything else
# is a fit question, not a gate.
BLOCKING_CATEGORIES = frozenset({"class_standing", "work_authorization", "gpa"})
# Process steps ("submit an application") are listed but never scored — they say
# nothing about whether the student is a good fit.
UNSCORED_CATEGORIES = frozenset({"process"})

_NEUTRAL = 0.5

_REQUIRED_CREDIT = {
    RequirementMatch.MATCHED: 1.0,
    RequirementMatch.PARTIAL: 0.6,
    RequirementMatch.UNKNOWN: 0.5,
    RequirementMatch.MISSING: 0.0,
}
_PREFERRED_CREDIT = {
    RequirementMatch.MATCHED: 1.0,
    RequirementMatch.PARTIAL: 0.5,
    RequirementMatch.UNKNOWN: 0.0,
    RequirementMatch.MISSING: 0.0,
}
_CERTAINTY_CREDIT = {
    Certainty.VERIFIED: 1.0,
    Certainty.LIKELY: 0.7,
    Certainty.INFERRED: 0.4,
    Certainty.UNKNOWN: 0.0,
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _attr(obj: object, name: str, default: Any = None) -> Any:
    value = getattr(obj, name, None)
    return default if value is None else value


def _strs(obj: object, name: str) -> list[str]:
    value = getattr(obj, name, None) or []
    return [str(v) for v in value if str(v).strip()]


def _sentence(text: str) -> str:
    cleaned = " ".join(str(text).split())
    if not cleaned:
        return ""
    cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned if cleaned[-1] in ".!?" else cleaned + "."


def _join(items: list[str], limit: int = 3) -> str:
    shown = [truncate(i, 70) for i in items[:limit]]
    extra = len(items) - len(shown)
    text = ", ".join(shown)
    return f"{text} and {extra} more" if extra > 0 else text


# --------------------------------------------------------------------------- #
# Data carriers
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class ScoreComponent:
    key: str
    label: str
    score: float
    weight: float
    weighted: float
    reason: str
    detail: list[str] = field(default_factory=list)
    # False means "we had nothing to score this on"; its weight was moved onto
    # the other components rather than counted as a zero.
    scored: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "score": round(self.score, 4),
            "weight": round(self.weight, 4),
            "weighted": round(self.weighted, 4),
            "reason": self.reason,
            "detail": list(self.detail),
        }


@dataclass(slots=True)
class RequirementAssessment:
    text: str
    kind: RequirementKind
    state: RequirementMatch
    reason: str
    category: str = "other"
    requirement_id: str | None = None
    evidence: str | None = None
    source_text: str | None = None

    @property
    def blocking(self) -> bool:
        return (
            self.kind == RequirementKind.REQUIRED
            and self.state == RequirementMatch.MISSING
            and self.category in BLOCKING_CATEGORIES
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "text": self.text,
            "kind": self.kind.value,
            "category": self.category,
            "state": self.state.value,
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclass(slots=True)
class ScoreResult:
    fit_score: float
    confidence: float
    components: list[ScoreComponent]
    strengths: list[str]
    gaps: list[str]
    explanation: str
    why_interesting: str | None
    recommendation: Recommendation
    requirement_matches: list[RequirementAssessment]
    model: str = JOB_MODEL
    eligibility: EligibilityState = EligibilityState.UNCLEAR
    eligibility_reasons: list[str] = field(default_factory=list)
    confidence_notes: list[str] = field(default_factory=list)

    def breakdown(self) -> list[dict[str, Any]]:
        return [c.as_dict() for c in self.components]

    def requirement_rows(self) -> list[dict[str, Any]]:
        return [r.as_dict() for r in self.requirement_matches]

    def component(self, key: str) -> ScoreComponent | None:
        return next((c for c in self.components if c.key == key), None)


# --------------------------------------------------------------------------- #
# Profile view
# --------------------------------------------------------------------------- #

_GRAD_MARKERS = ("phd", "ph.d", "doctoral", "masters", "master's", "ms", "ma", "mba", "coterm")
_UNDERGRAD_MARKERS = ("bs", "ba", "bachelor", "undergraduate", "undergrad", "b.s", "b.a", "ab")


@dataclass(slots=True)
class ProfileView:
    """Everything the scorers are allowed to know about the student.

    Built once per match so the two scorers, the eligibility rules and the
    explanations all read the same facts, and so tests can construct a student
    without a database.
    """

    profile_id: Any = None
    university: str = ""
    campus: str | None = None
    major: str | None = None
    degree: str | None = None
    graduation_year: int | None = None
    gpa: float | None = None
    work_authorization: WorkAuthorization = WorkAuthorization.NOT_SPECIFIED
    hours_min: int | None = None
    hours_max: int | None = None
    preferred_locations: tuple[str, ...] = ()
    preferred_job_types: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    skills: dict[str, str] = field(default_factory=dict)
    interests: tuple[str, ...] = ()
    interest_topics: dict[str, float] = field(default_factory=dict)
    coursework: tuple[str, ...] = ()
    coursework_codes: tuple[str, ...] = ()
    coursework_skills: frozenset[str] = frozenset()
    coursework_topics: dict[str, float] = field(default_factory=dict)
    experience_text: str = ""
    resume_text: str = ""
    resume_count: int = 0
    text: str = ""

    @property
    def is_undergraduate(self) -> bool | None:
        """``None`` when we genuinely do not know — never a guess."""
        degree = normalize(self.degree)
        if degree:
            if any(contains_phrase(degree, m) for m in _GRAD_MARKERS):
                return False
            if any(contains_phrase(degree, m) for m in _UNDERGRAD_MARKERS):
                return True
        return None

    @property
    def skill_slugs(self) -> frozenset[str]:
        return frozenset(self.skills)

    @property
    def is_sparse(self) -> bool:
        return len(self.skills) < 4 or (not self.interests and not self.keywords)

    def mentions(self, phrase: str) -> bool:
        return contains_phrase(self.text, phrase)

    @classmethod
    def of(cls, profile: Any, resumes: Any = ()) -> ProfileView:
        if isinstance(profile, ProfileView):
            return profile
        return cls.from_profile(profile, resumes)

    @classmethod
    def from_profile(cls, profile: Any, resumes: Any = ()) -> ProfileView:
        resume_list = list(resumes or [])
        skills: dict[str, str] = {}
        for row in getattr(profile, "skills", None) or []:
            skill = getattr(row, "skill", None)
            slug = taxonomy.resolve_skill(getattr(skill, "slug", None) or getattr(row, "slug", None))
            if slug:
                skills.setdefault(slug, str(_attr(row, "origin", "user")))

        resume_text_parts: list[str] = []
        for resume in resume_list:
            for slug in taxonomy.resolve_skills(_strs(resume, "detected_skills")):
                skills.setdefault(slug, "resume")
            text_value = _attr(resume, "text", "")
            if text_value:
                resume_text_parts.append(str(text_value))
                for slug in taxonomy.match_skill_slugs(str(text_value)):
                    skills.setdefault(slug, "resume")
            for highlight in getattr(resume, "highlights", None) or []:
                resume_text_parts.append(str(_attr(highlight, "text", "")))

        interests: list[str] = []
        interest_topics: dict[str, float] = {}
        for row in getattr(profile, "interests", None) or []:
            label = str(_attr(row, "label", "")).strip()
            if not label:
                continue
            interests.append(label)
            weight = float(_attr(row, "weight", 1.0))
            topic = getattr(row, "topic", None)
            slug = taxonomy.resolve_topic(getattr(topic, "slug", None) or label)
            if slug:
                interest_topics[slug] = max(interest_topics.get(slug, 0.0), _clamp(weight, 0.0, 1.0))
            for extra_slug, extra_weight in taxonomy.match_topics(label):
                scaled = _clamp(extra_weight * _clamp(weight, 0.0, 1.0))
                interest_topics[extra_slug] = max(interest_topics.get(extra_slug, 0.0), scaled)

        keywords = tuple(_strs(profile, "keywords"))
        for keyword in keywords:
            for slug, weight in taxonomy.match_topics(keyword):
                interest_topics[slug] = max(interest_topics.get(slug, 0.0), weight * 0.8)

        coursework: list[str] = []
        coursework_codes: list[str] = []
        coursework_skills: set[str] = set()
        coursework_topics: dict[str, float] = {}
        for row in getattr(profile, "coursework", None) or []:
            code = str(_attr(row, "code", "")).strip()
            title = str(_attr(row, "title", "")).strip()
            topics = _strs(row, "topics")
            entry = " ".join(part for part in (code, title) if part)
            if entry:
                coursework.append(entry)
            if code:
                coursework_codes.extend(extract_course_codes(code) or [code.upper().replace(" ", "")])
            blob = concat(entry, topics, separator=" ")
            coursework_skills |= taxonomy.match_skill_slugs(blob)
            for slug, weight in taxonomy.match_topics(blob):
                coursework_topics[slug] = max(coursework_topics.get(slug, 0.0), weight)
            for topic in topics:
                slug = taxonomy.resolve_topic(topic)
                if slug:
                    coursework_topics[slug] = max(coursework_topics.get(slug, 0.0), 1.0)

        experience_parts: list[str] = []
        for row in getattr(profile, "experiences", None) or []:
            experience_parts.append(
                concat(
                    _attr(row, "role", ""),
                    _attr(row, "organization", ""),
                    _attr(row, "summary", ""),
                    _strs(row, "highlights"),
                    _strs(row, "skills"),
                    separator=" ",
                )
            )
            for slug in taxonomy.resolve_skills(_strs(row, "skills")):
                skills.setdefault(slug, "user")

        experience_text = "\n".join(p for p in experience_parts if p)
        resume_text = "\n".join(p for p in resume_text_parts if p)
        blob = concat(
            _attr(profile, "major", ""),
            _attr(profile, "secondary_major", ""),
            interests,
            keywords,
            coursework,
            experience_text,
            resume_text[:20000],
        )

        return cls(
            profile_id=getattr(profile, "id", None),
            university=str(_attr(profile, "university", "")),
            campus=_attr(profile, "campus", None),
            major=_attr(profile, "major", None),
            degree=_attr(profile, "degree", None),
            graduation_year=_attr(profile, "graduation_year", None),
            gpa=_attr(profile, "gpa", None),
            work_authorization=_attr(
                profile, "work_authorization", WorkAuthorization.NOT_SPECIFIED
            ),
            hours_min=_attr(profile, "hours_per_week_min", None),
            hours_max=_attr(profile, "hours_per_week_max", None),
            preferred_locations=tuple(_strs(profile, "preferred_locations")),
            preferred_job_types=tuple(_strs(profile, "preferred_job_types")),
            keywords=keywords,
            skills=skills,
            interests=tuple(interests),
            interest_topics=interest_topics,
            coursework=tuple(coursework),
            coursework_codes=tuple(dict.fromkeys(coursework_codes)),
            coursework_skills=frozenset(coursework_skills),
            coursework_topics=coursework_topics,
            experience_text=experience_text,
            resume_text=resume_text,
            resume_count=len(resume_list),
            text=blob,
        )


# --------------------------------------------------------------------------- #
# Requirement interpretation
# --------------------------------------------------------------------------- #

_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "class_standing",
        (
            "undergraduate",
            "undergraduates",
            "undergrad",
            "graduate student",
            "graduate students",
            "graduate and coterm",
            "phd student",
            "doctoral student",
            "masters student",
            "master's student",
            "coterm",
            "co-term",
            "freshman",
            "sophomore",
            "junior standing",
            "senior standing",
            "bachelor",
        ),
    ),
    (
        "work_authorization",
        (
            "work authorization",
            "work authorisation",
            "eligible to work",
            "legally eligible",
            "i-9",
            "employment authorization",
            "us citizen",
            "u.s. citizen",
            "citizenship",
            "permanent resident",
            "green card",
            "visa",
            "cpt",
            "opt",
            "work permit",
        ),
    ),
    ("gpa", ("gpa", "grade point average")),
    (
        "background_check",
        ("background check", "live scan", "fingerprint", "tb test", "immunization", "drug screen"),
    ),
    (
        "enrollment",
        (
            "enrolled",
            "enrollment",
            "registered",
            "full-time",
            "units",
            "good standing",
            "academic progress",
            "matriculated",
            "tuition",
        ),
    ),
    (
        "availability",
        (
            "hours per week",
            "hours a week",
            "hours/week",
            "hours each week",
            "time commitment",
            "commit",
            "schedule",
            "shifts",
            "weekends",
            "evening",
            "availability",
            "full quarter",
            "10 weeks",
            "on campus",
        ),
    ),
    (
        "coursework",
        (
            "coursework",
            "course work",
            "completed the equivalent",
            "prerequisite",
            "have taken",
            "having taken",
            "completed cs",
        ),
    ),
    ("physical", ("lift", "push a cart", "stand for", "carry", "kneel", "reach and")),
    (
        "language",
        ("fluent", "native speaker", "english proficiency", "esol", "spanish", "mandarin"),
    ),
    (
        "process",
        (
            "submit an application",
            "submit the online",
            "must submit",
            "must apply",
            "everyone must",
            "fill out",
            "attend staff",
            "must take",
            "training course",
            "apply through",
            "contact the",
            "letter of recommendation",
            "recommendation",
            "participate in",
            "poster session",
            "progress report",
        ),
    ),
    (
        "experience",
        (
            "experience",
            "prior",
            "years of",
            "background in",
            "demonstrated",
            "record of",
            "familiar with",
            "proficiency",
            "proficient",
            "knowledge of",
            "ability to",
            "skilled",
        ),
    ),
)

_DURATION_RE = re.compile(
    r"\b(\d+|one|two|three|four|five|six)\s*\+?\s*(years?|terms?|quarters?|semesters?)\b",
    re.IGNORECASE,
)
_GPA_RE = re.compile(r"\b([0-4]\.\d{1,2})\b")
_CITIZEN_PHRASES = ("us citizen", "u.s. citizen", "citizenship", "permanent resident", "green card")
_GRAD_PHRASES = (
    "graduate student",
    "graduate students",
    "graduate and coterm",
    "phd student",
    "doctoral student",
    "masters student",
    "master's student",
    "coterm",
    "co-term",
)
_UNDERGRAD_PHRASES = ("undergraduate", "undergraduates", "undergrad", "bachelor")


def classify_requirement(text: str, hint: str | None = None) -> str:
    if hint and hint in {name for name, _ in _CATEGORY_RULES}:
        return hint
    for category, phrases in _CATEGORY_RULES:
        if any(contains_phrase(text, phrase) for phrase in phrases):
            return category
    return "skills" if taxonomy.match_skill_slugs(text) else "other"


def _skill_evidence(profile: ProfileView, slug: str) -> str | None:
    label = taxonomy.skill_label(slug)
    origin = profile.skills.get(slug)
    if origin == "resume":
        return f"{label} — found in your resume"
    if origin:
        return f"{label} — recorded in your profile"
    return None


def _assess_skill_like(
    text: str, profile: ProfileView, category: str
) -> tuple[RequirementMatch, str, str | None]:
    """Skills/experience style requirements — the common case."""
    wanted = taxonomy.match_skill_slugs(text)
    have = sorted(wanted & profile.skill_slugs)
    missing = sorted(wanted - profile.skill_slugs)
    duration = _DURATION_RE.search(text)

    if wanted:
        labels_have = [taxonomy.skill_label(s) for s in have]
        labels_missing = [taxonomy.skill_label(s) for s in missing]
        if not have:
            return (
                RequirementMatch.MISSING,
                f"Nothing in your profile or resumes evidences {_join(labels_missing)}.",
                None,
            )
        if missing:
            return (
                RequirementMatch.PARTIAL,
                f"You have {_join(labels_have)}, but {_join(labels_missing)} is not evidenced anywhere in your profile or resumes.",
                _skill_evidence(profile, have[0]),
            )
        if duration and category == "experience":
            return (
                RequirementMatch.PARTIAL,
                f"You have {_join(labels_have)}, but the posting asks for {duration.group(0)} and your profile does not record how long.",
                _skill_evidence(profile, have[0]),
            )
        return (
            RequirementMatch.MATCHED,
            f"You have {_join(labels_have)}.",
            _skill_evidence(profile, have[0]),
        )

    words = content_words(text)
    if len(words) >= 3 and profile.text:
        present = [w for w in words if contains_phrase(profile.text, w)]
        coverage = len(present) / len(words)
        if coverage >= 0.6:
            return (
                RequirementMatch.PARTIAL,
                f"Your profile and resumes mention {_join(sorted(set(present)), 4)}, which overlaps this requirement — worth checking yourself.",
                None,
            )
    return (
        RequirementMatch.UNKNOWN,
        "Trellis could not interpret this requirement automatically — read it and judge for yourself.",
        None,
    )


def _assess_class_standing(text: str, profile: ProfileView) -> tuple[RequirementMatch, str, str | None]:
    wants_undergrad = any(contains_phrase(text, p) for p in _UNDERGRAD_PHRASES)
    wants_grad = any(contains_phrase(text, p) for p in _GRAD_PHRASES)
    standing = profile.is_undergraduate
    degree = profile.degree or "your recorded degree"

    if wants_grad and not wants_undergrad:
        if standing is True:
            return (
                RequirementMatch.MISSING,
                "This is restricted to graduate or coterm students and your profile says you are an undergraduate.",
                None,
            )
        if standing is False:
            return (RequirementMatch.MATCHED, f"Your profile records {degree}.", None)
        return (
            RequirementMatch.UNKNOWN,
            "This is restricted to graduate or coterm students; your class standing is not recorded in your profile.",
            None,
        )

    if wants_undergrad:
        if standing is True:
            university = profile.university or "your university"
            return (
                RequirementMatch.MATCHED,
                f"You are an undergraduate at {university}.",
                f"Profile degree: {degree}",
            )
        if standing is False:
            return (
                RequirementMatch.MISSING,
                f"This is limited to undergraduates and your profile records {degree}.",
                None,
            )
        return (
            RequirementMatch.UNKNOWN,
            "Your class standing is not recorded in your profile, so this cannot be checked.",
            None,
        )

    if profile.university and contains_phrase(text, profile.university.split()[0]):
        return (
            RequirementMatch.MATCHED,
            f"You are enrolled at {profile.university}.",
            None,
        )
    return (
        RequirementMatch.UNKNOWN,
        "Trellis could not tell which students this restricts the role to.",
        None,
    )


def _assess_work_authorization(
    text: str, profile: ProfileView
) -> tuple[RequirementMatch, str, str | None]:
    demands_citizen = any(contains_phrase(text, p) for p in _CITIZEN_PHRASES)
    auth = profile.work_authorization
    if auth == WorkAuthorization.US_CITIZEN_OR_PR:
        return (
            RequirementMatch.MATCHED,
            "Your profile records US citizen or permanent resident status.",
            None,
        )
    if auth == WorkAuthorization.F1_CPT_OPT:
        if demands_citizen:
            return (
                RequirementMatch.MISSING,
                "This asks for US citizenship or permanent residency and your profile records F-1 status.",
                None,
            )
        return (
            RequirementMatch.PARTIAL,
            "Your profile records F-1 status; on-campus work is usually permitted but CPT/OPT limits apply — confirm with your international student office.",
            None,
        )
    if auth == WorkAuthorization.OTHER_VISA:
        return (
            RequirementMatch.UNKNOWN,
            "Your profile records a visa status Trellis cannot evaluate against this requirement.",
            None,
        )
    return (
        RequirementMatch.UNKNOWN,
        "Work authorisation is not recorded in your profile, so this cannot be checked.",
        None,
    )


def _assess_gpa(text: str, profile: ProfileView) -> tuple[RequirementMatch, str, str | None]:
    match = _GPA_RE.search(text)
    threshold = float(match.group(1)) if match else None
    if profile.gpa is None:
        return (
            RequirementMatch.UNKNOWN,
            "Your GPA is not recorded in your profile, so this cannot be checked.",
            None,
        )
    if threshold is None:
        return (
            RequirementMatch.UNKNOWN,
            "This mentions GPA but does not state a number Trellis can compare against.",
            None,
        )
    if profile.gpa + 1e-9 >= threshold:
        return (
            RequirementMatch.MATCHED,
            f"Your recorded GPA of {profile.gpa:.2f} meets the stated minimum of {threshold:.2f}.",
            None,
        )
    return (
        RequirementMatch.MISSING,
        f"Your recorded GPA of {profile.gpa:.2f} is below the stated minimum of {threshold:.2f}.",
        None,
    )


def _assess_availability(text: str, profile: ProfileView) -> tuple[RequirementMatch, str, str | None]:
    low, high = extract_hours_per_week(text)
    if low is None:
        return (
            RequirementMatch.UNKNOWN,
            "This describes a time commitment Trellis could not turn into weekly hours.",
            None,
        )
    if profile.hours_max is None and profile.hours_min is None:
        return (
            RequirementMatch.UNKNOWN,
            f"The role asks for {low}–{high} hours a week; your availability is not recorded in your profile.",
            None,
        )
    p_min = profile.hours_min if profile.hours_min is not None else 0
    p_max = profile.hours_max if profile.hours_max is not None else 80
    if low <= p_max and (high or low) >= p_min:
        return (
            RequirementMatch.MATCHED,
            f"The role asks for {low}–{high} hours a week, inside your stated {p_min}–{p_max}.",
            None,
        )
    if low > p_max:
        return (
            RequirementMatch.MISSING,
            f"The role asks for at least {low} hours a week, above the {p_max} you said you can work.",
            None,
        )
    return (
        RequirementMatch.PARTIAL,
        f"The role offers about {high} hours a week, below the {p_min} you said you wanted.",
        None,
    )


def _assess_coursework(text: str, profile: ProfileView) -> tuple[RequirementMatch, str, str | None]:
    codes = extract_course_codes(text)
    if codes:
        taken = [c for c in codes if c in profile.coursework_codes]
        if taken:
            return (
                RequirementMatch.MATCHED,
                f"Your coursework includes {_join(taken)}.",
                f"Recorded coursework: {_join(list(profile.coursework), 4)}",
            )
        related = [
            c
            for c in codes
            if any(taxonomy.normalize_prefix(c) == taxonomy.normalize_prefix(o) for o in profile.coursework_codes)
        ]
        if related:
            return (
                RequirementMatch.PARTIAL,
                f"You have not recorded {_join(codes)}, but you do have other courses in the same subject.",
                None,
            )
        if profile.coursework_codes:
            return (
                RequirementMatch.MISSING,
                f"{_join(codes)} is not in the coursework recorded on your profile.",
                None,
            )
        return (
            RequirementMatch.UNKNOWN,
            f"This asks for {_join(codes)}; no coursework is recorded on your profile.",
            None,
        )
    return _assess_skill_like(text, profile, "coursework")


def _assess_requirement_text(
    text: str, profile: ProfileView, category: str
) -> tuple[RequirementMatch, str, str | None]:
    if category == "class_standing":
        return _assess_class_standing(text, profile)
    if category == "work_authorization":
        return _assess_work_authorization(text, profile)
    if category == "gpa":
        return _assess_gpa(text, profile)
    if category == "availability":
        return _assess_availability(text, profile)
    if category == "coursework":
        return _assess_coursework(text, profile)
    if category == "enrollment":
        if any(contains_phrase(text, p) for p in _UNDERGRAD_PHRASES + _GRAD_PHRASES):
            return _assess_class_standing(text, profile)
        return (
            RequirementMatch.UNKNOWN,
            "This depends on your enrolment for the term, which Trellis does not track.",
            None,
        )
    if category == "process":
        return (
            RequirementMatch.UNKNOWN,
            "This is a step in the application process rather than a qualification, so it does not count for or against your fit.",
            None,
        )
    if category == "background_check":
        return (
            RequirementMatch.UNKNOWN,
            "This needs a background check you would have to consent to; nothing in your profile decides it.",
            None,
        )
    if category == "physical":
        return (
            RequirementMatch.UNKNOWN,
            "Physical requirements are not recorded in your profile — read this one yourself.",
            None,
        )
    if category == "language":
        return _assess_skill_like(text, profile, "language")
    return _assess_skill_like(text, profile, category)


def assess_requirement(
    text: str,
    kind: RequirementKind,
    profile: ProfileView,
    *,
    requirement_id: str | None = None,
    category_hint: str | None = None,
    source_text: str | None = None,
) -> RequirementAssessment:
    category = classify_requirement(text, category_hint)
    state, reason, evidence = _assess_requirement_text(text, profile, category)
    return RequirementAssessment(
        text=text,
        kind=kind,
        state=state,
        reason=reason,
        category=category,
        requirement_id=requirement_id,
        evidence=evidence,
        source_text=source_text,
    )


_ELIGIBILITY_CUES = (
    "eligible",
    "eligibility",
    "only open to",
    "open to",
    "must be a",
    "restricted to",
    "not eligible",
    "you must be",
    "applicants must",
)


def eligibility_statements(text: str | None, limit: int = 6) -> list[str]:
    """Sentences from a posting that talk about who may apply."""
    from app.services.text import sentences as split_sentences

    out: list[str] = []
    for sentence in split_sentences(text):
        if len(sentence) < 12 or len(sentence) > 400:
            continue
        if any(contains_phrase(sentence, cue) for cue in _ELIGIBILITY_CUES):
            out.append(sentence)
        if len(out) >= limit:
            break
    return out


def assess_requirements(
    profile: Any,
    opportunity: Any,
    *,
    include_inferred: bool = True,
) -> list[RequirementAssessment]:
    """Judge every stated requirement, plus eligibility sentences in the body.

    Sentences pulled out of the description are marked ``INFERRED`` — they are
    read, not stated as requirements, and the eligibility rules treat them more
    cautiously as a result.
    """
    view = ProfileView.of(profile)
    seen: set[str] = set()
    out: list[RequirementAssessment] = []
    for row in getattr(opportunity, "requirements", None) or []:
        text = str(_attr(row, "text", "")).strip()
        if not text:
            continue
        seen.add(normalize(text))
        out.append(
            assess_requirement(
                text,
                _attr(row, "kind", RequirementKind.REQUIRED),
                view,
                requirement_id=str(row.id) if getattr(row, "id", None) else None,
                category_hint=_attr(row, "category", None),
                source_text=_attr(row, "source_text", None),
            )
        )
    if include_inferred:
        for sentence in eligibility_statements(_attr(opportunity, "description", "")):
            if normalize(sentence) in seen:
                continue
            category = classify_requirement(sentence)
            if category not in BLOCKING_CATEGORIES:
                continue
            seen.add(normalize(sentence))
            out.append(
                assess_requirement(
                    sentence,
                    RequirementKind.INFERRED,
                    view,
                    source_text=sentence,
                )
            )
    return out


def derive_eligibility(
    assessments: list[RequirementAssessment],
    profile: Any = None,
    opportunity: Any = None,
) -> tuple[EligibilityState, list[str]]:
    """Turn per-requirement verdicts into one state plus human reasons.

    Only *stated, required* items in a blocking category can make somebody
    ineligible.  An inferred sentence from the body text can raise doubt but is
    never allowed to assert ineligibility on its own (docs/uncertainty.md).
    """
    required = [a for a in assessments if a.kind == RequirementKind.REQUIRED]
    blocking = [a for a in required if a.blocking]
    inferred_blocking = [
        a
        for a in assessments
        if a.kind == RequirementKind.INFERRED
        and a.state == RequirementMatch.MISSING
        and a.category in BLOCKING_CATEGORIES
    ]
    missing = [
        a
        for a in required
        if a.state == RequirementMatch.MISSING and a.category not in BLOCKING_CATEGORIES
    ]
    unknown = [
        a
        for a in required
        if a.state == RequirementMatch.UNKNOWN and a.category not in UNSCORED_CATEGORIES
    ]
    matched = [
        a for a in required if a.state in (RequirementMatch.MATCHED, RequirementMatch.PARTIAL)
    ]

    reasons: list[str] = []
    if blocking:
        reasons.extend(_sentence(a.reason) for a in blocking[:3])
        return EligibilityState.INELIGIBLE, reasons

    if inferred_blocking:
        reasons.append(
            _sentence(
                f"The posting text suggests a restriction Trellis read but could not confirm: {truncate(inferred_blocking[0].text, 140)}"
            )
        )
        reasons.extend(_sentence(a.reason) for a in inferred_blocking[:2])
        return EligibilityState.UNCLEAR, reasons

    if missing:
        reasons.append(
            _sentence(
                f"{len(missing)} required qualification{'s' if len(missing) > 1 else ''} could not be evidenced from your profile: {_join([a.text for a in missing])}"
            )
        )
        return EligibilityState.UNCLEAR, reasons

    if not required:
        reasons.append("No eligibility criteria were found on this posting, so nothing was checked.")
        return EligibilityState.UNCLEAR, reasons

    if unknown:
        reasons.append(
            _sentence(
                f"{len(matched)} of {len(required)} required items check out; {len(unknown)} could not be verified automatically"
            )
        )
        if len(matched) >= len(unknown):
            return EligibilityState.LIKELY_ELIGIBLE, reasons
        return EligibilityState.UNCLEAR, reasons

    reasons.append(
        _sentence(f"All {len(required)} stated requirements are supported by your profile")
    )
    return EligibilityState.ELIGIBLE, reasons


# --------------------------------------------------------------------------- #
# Component machinery
# --------------------------------------------------------------------------- #


def _make(
    key: str,
    score: float,
    reason: str,
    detail: list[str] | None = None,
    *,
    scored: bool = True,
) -> ScoreComponent:
    return ScoreComponent(
        key=key,
        label=COMPONENT_LABELS.get(key, key.replace("_", " ").title()),
        score=round(_clamp(score), 4),
        weight=0.0,
        weighted=0.0,
        reason=_sentence(reason),
        detail=[d for d in (detail or []) if d],
        scored=scored,
    )


def _finalize(components: list[ScoreComponent], weights: dict[str, float]) -> float:
    """Apply weights, redistributing any unscored component's share.

    Redistribution is proportional, so the relative importance of everything
    that *could* be scored is preserved.
    """
    nominal = {c.key: weights[c.key] for c in components}
    scored_total = sum(nominal[c.key] for c in components if c.scored)
    orphaned = sum(nominal[c.key] for c in components if not c.scored)
    for component in components:
        if not component.scored or scored_total <= 0:
            component.weight = 0.0
            component.weighted = 0.0
            continue
        share = nominal[component.key] * (1.0 + orphaned / scored_total)
        component.weight = round(share, 4)
        component.weighted = round(component.score * share, 4)
    return round(100.0 * sum(c.weighted for c in components), 1)


def _strengths_and_gaps(
    components: list[ScoreComponent], assessments: list[RequirementAssessment]
) -> tuple[list[str], list[str]]:
    ordered = sorted(components, key=lambda c: (-c.weighted, c.key))
    strengths = [c.reason for c in ordered if c.scored and c.score >= 0.7][:4]
    gaps: list[str] = []
    for assessment in assessments:
        if assessment.kind == RequirementKind.REQUIRED and assessment.state == RequirementMatch.MISSING:
            gaps.append(_sentence(f"{truncate(assessment.text, 90)} — {assessment.reason}"))
    weak = sorted(
        (c for c in components if c.scored and c.score <= 0.45),
        key=lambda c: (-c.weight, c.key),
    )
    gaps.extend(c.reason for c in weak)
    deduped: list[str] = []
    for gap in gaps:
        if gap not in deduped:
            deduped.append(gap)
    return strengths, deduped[:4]


def _band(fit: float) -> str:
    if fit >= 80:
        return "a strong match"
    if fit >= 65:
        return "a good match"
    if fit >= 45:
        return "a partial match"
    return "a weak match"


def explain(result: ScoreResult) -> str:
    """The deterministic "why should I apply?" text.

    This is the product's answer, not a fallback: the LLM may only rewrite it
    more fluently, and does not get to add facts.
    """
    parts: list[str] = [f"{result.fit_score:.0f} / 100 — {_band(result.fit_score)}."]
    drivers = [
        c
        for c in sorted(result.components, key=lambda c: (-c.weighted, c.key))
        if c.scored and c.score >= 0.6
    ][:3]
    if drivers:
        parts.append("It scores well on " + _join([c.label.lower() for c in drivers], 3) + ".")
        parts.extend(c.reason for c in drivers[:2])
    else:
        parts.append("Nothing in this posting scores strongly against your profile.")
    if result.gaps:
        parts.append("Watch out: " + " ".join(result.gaps[:2]))
    if result.eligibility == EligibilityState.INELIGIBLE:
        parts.append("You do not appear to be eligible, so this is ranked down regardless of fit.")
    unscored = [c.label.lower() for c in result.components if not c.scored]
    if unscored:
        parts.append(
            f"{_join(unscored, 2).capitalize()} could not be scored, so its weight was shared across the other factors."
        )
    parts.append(
        f"Confidence {result.confidence:.2f}"
        + (f" — {_join(result.confidence_notes, 3)}." if result.confidence_notes else ".")
    )
    return " ".join(_sentence(p) for p in parts if p)


def recommend(
    fit_score: float,
    eligibility: EligibilityState,
    *,
    is_outreach: bool = False,
) -> Recommendation:
    """Map a score onto the action we suggest.

    ``strong_apply`` is never reachable when the student is ineligible — the
    ranking may still surface the row, but the call to action must not lie.
    """
    if eligibility == EligibilityState.INELIGIBLE:
        return Recommendation.CONSIDER if fit_score >= 45 else Recommendation.SKIP
    eligible = eligibility in (EligibilityState.ELIGIBLE, EligibilityState.LIKELY_ELIGIBLE)
    if fit_score >= 80 and eligible:
        return Recommendation.STRONG_APPLY
    if fit_score >= 65:
        return Recommendation.REACH_OUT if is_outreach else Recommendation.APPLY
    if is_outreach and fit_score >= 55:
        return Recommendation.REACH_OUT
    if fit_score >= 45:
        return Recommendation.CONSIDER
    return Recommendation.SKIP


def _confidence(penalties: list[tuple[float, str]], base: float = 0.92) -> tuple[float, list[str]]:
    value = base
    notes: list[str] = []
    for amount, note in penalties:
        value -= amount
        notes.append(note)
    return round(_clamp(value, 0.05, 0.98), 3), notes


# --------------------------------------------------------------------------- #
# Job scoring
# --------------------------------------------------------------------------- #

_MONEY_RE = re.compile(r"\$\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
_HOURLY_WORDS = ("per hour", "an hour", "/hour", "/hr", "hourly", "per hr")


def _opportunity_text(opportunity: Any) -> str:
    return concat(
        _attr(opportunity, "title", ""),
        _attr(opportunity, "organization", ""),
        _attr(opportunity, "department", ""),
        _attr(opportunity, "description", ""),
        _attr(opportunity, "hours_note", ""),
        [str(_attr(r, "text", "")) for r in getattr(opportunity, "requirements", None) or []],
        _strs(opportunity, "skills"),
    )


def _opportunity_topics(opportunity: Any, blob: str) -> dict[str, float]:
    topics: dict[str, float] = {}
    for row in getattr(opportunity, "topics", None) or []:
        topic = getattr(row, "topic", None)
        slug = taxonomy.resolve_topic(getattr(topic, "slug", None))
        if slug:
            topics[slug] = max(topics.get(slug, 0.0), _clamp(float(_attr(row, "weight", 1.0))))
    for slug, weight in taxonomy.match_topics(blob):
        topics[slug] = max(topics.get(slug, 0.0), weight)
    return topics


def _qualification_component(assessments: list[RequirementAssessment]) -> ScoreComponent:
    required = [
        a
        for a in assessments
        if a.kind == RequirementKind.REQUIRED and a.category not in UNSCORED_CATEGORIES
    ]
    preferred = [a for a in assessments if a.kind == RequirementKind.PREFERRED]

    if not required:
        base = _NEUTRAL
        reason = "No required qualifications were extracted from this posting, so this factor is neutral."
        detail = []
    else:
        credit = sum(_REQUIRED_CREDIT[a.state] for a in required) / len(required)
        base = credit
        matched = [a for a in required if a.state == RequirementMatch.MATCHED]
        partial = [a for a in required if a.state == RequirementMatch.PARTIAL]
        missing = [a for a in required if a.state == RequirementMatch.MISSING]
        unknown = [a for a in required if a.state == RequirementMatch.UNKNOWN]
        reason = f"{len(matched)} of {len(required)} required qualifications matched"
        if partial:
            reason += f", {len(partial)} partly"
        if missing:
            reason += f"; missing: {_join([a.text for a in missing], 2)}"
        if unknown:
            reason += f"; {len(unknown)} could not be checked from the posting"
        detail = [f"{a.state.value}: {truncate(a.text, 90)} — {a.reason}" for a in required]

    score = base
    if preferred:
        pref_credit = sum(_PREFERRED_CREDIT[a.state] for a in preferred) / len(preferred)
        # Half credit, applied to the headroom only: preferred items can lift
        # the score but can never pull it below the required-only result.
        score = base + 0.5 * pref_credit * (1.0 - base)
        met = sum(1 for a in preferred if a.state == RequirementMatch.MATCHED)
        reason += f". {met} of {len(preferred)} preferred qualifications matched (bonus only — these never subtract)"
    return _make("qualification_match", score, reason, detail)


def _job_skills_component(profile: ProfileView, opportunity: Any, blob: str) -> ScoreComponent:
    explicit = set(taxonomy.resolve_skills(_strs(opportunity, "skills")))
    for row in getattr(opportunity, "requirements", None) or []:
        explicit |= set(taxonomy.resolve_skills(_strs(row, "skill_slugs")))
        explicit |= taxonomy.match_skill_slugs(str(_attr(row, "text", "")))
    inferred = taxonomy.match_skill_slugs(blob) - explicit
    if not explicit and not inferred:
        return _make(
            "skills_match",
            _NEUTRAL,
            "This posting does not name any specific skills, so this factor is neutral.",
        )
    weights = {slug: 2.0 for slug in explicit} | {slug: 1.0 for slug in inferred}
    have = {slug: w for slug, w in weights.items() if slug in profile.skill_slugs}
    score = sum(have.values()) / sum(weights.values())
    have_labels = [taxonomy.skill_label(s) for s in sorted(have)]
    missing_labels = [taxonomy.skill_label(s) for s in sorted(set(weights) - set(have))]
    if have:
        reason = f"You have {len(have)} of the {len(weights)} skills this posting mentions: {_join(have_labels, 4)}"
        if missing_labels:
            reason += f"; not evidenced: {_join(missing_labels, 3)}"
    else:
        reason = f"None of the {len(weights)} skills this posting mentions ({_join(missing_labels, 3)}) appear in your profile or resumes"
    detail = [f"{taxonomy.skill_label(s)} — {'you have this' if s in have else 'not evidenced'}" for s in sorted(weights)]
    return _make("skills_match", score, reason, detail[:12])


def _interest_component(
    profile: ProfileView, opportunity: Any, blob: str, key: str = "interest_alignment"
) -> ScoreComponent:
    if not profile.interest_topics and not profile.keywords and not profile.interests:
        return _make(
            key,
            _NEUTRAL,
            "You have not recorded research interests or keywords, so this factor is neutral.",
        )
    opp_topics = _opportunity_topics(opportunity, blob)
    parts: list[tuple[float, float, str]] = []
    shared_labels: list[str] = []
    if opp_topics and profile.interest_topics:
        shared = set(opp_topics) & set(profile.interest_topics)
        numerator = sum(min(opp_topics[s], profile.interest_topics[s]) for s in shared)
        denominator = sum(profile.interest_topics.values())
        parts.append((_clamp(numerator / denominator) if denominator else 0.0, 2.0, "topics"))
        shared_labels = [taxonomy.topic_label(s) for s in sorted(shared)]
    if profile.keywords:
        hits = [k for k in profile.keywords if contains_phrase(blob, k)]
        parts.append((len(hits) / len(profile.keywords), 1.0, "keywords"))
        shared_labels.extend(hits)
    if profile.interests:
        hits = [i for i in profile.interests if contains_phrase(blob, i) or fuzzy_ratio(i, _attr(opportunity, "title", "")) >= 0.8]
        parts.append((len(hits) / len(profile.interests), 1.0, "interests"))
        shared_labels.extend(hits)
    if not parts:
        return _make(key, _NEUTRAL, "There was nothing to compare your interests against.")
    score = sum(value * weight for value, weight, _ in parts) / sum(w for _, w, _ in parts)
    unique_labels = list(dict.fromkeys(shared_labels))
    if unique_labels:
        reason = f"Overlaps what you said you care about: {_join(unique_labels, 3)}"
    else:
        interests = list(profile.interests) or list(profile.keywords)
        reason = f"Nothing here overlaps your stated interests ({_join(interests, 3)})"
    return _make(key, score, reason, [f"Matched: {label}" for label in unique_labels[:8]])


def _hours_component(profile: ProfileView, opportunity: Any) -> ScoreComponent:
    stated = _attr(opportunity, "hours_per_week", None)
    low, high = (int(stated), int(stated)) if stated else extract_hours_per_week(
        concat(_attr(opportunity, "hours_note", ""), _attr(opportunity, "description", ""))
    )
    if low is None:
        return _make(
            "hours_fit",
            _NEUTRAL,
            "The posting does not state weekly hours, so this factor is neutral.",
        )
    high = high or low
    if profile.hours_min is None and profile.hours_max is None:
        return _make(
            "hours_fit",
            _NEUTRAL,
            f"The role is {low}–{high} hours a week; you have not recorded how much you can work.",
        )
    p_min = profile.hours_min if profile.hours_min is not None else 0
    p_max = profile.hours_max if profile.hours_max is not None else 80
    if low <= p_max and high >= p_min:
        return _make(
            "hours_fit",
            1.0,
            f"{low}–{high} hours a week fits the {p_min}–{p_max} you said you can work.",
        )
    if low > p_max:
        over = low - p_max
        score = _clamp(1.0 - over / max(p_max, 1))
        return _make(
            "hours_fit",
            score,
            f"The role needs at least {low} hours a week — {over} more than the {p_max} you said you can work.",
        )
    short = p_min - high
    return _make(
        "hours_fit",
        _clamp(0.65 - 0.05 * short),
        f"The role offers only {high} hours a week, below the {p_min} you wanted.",
    )


def _location_component(profile: ProfileView, opportunity: Any) -> ScoreComponent:
    location = str(_attr(opportunity, "location", "") or "")
    is_remote = _attr(opportunity, "is_remote", None)
    prefs = list(profile.preferred_locations)
    campus_terms = [t for t in (profile.campus, profile.university) if t]
    if is_remote and any(contains_phrase(p, "remote") for p in prefs):
        return _make("location_fit", 1.0, "This is remote, which is one of your stated preferences.")
    if not location and is_remote is None:
        return _make(
            "location_fit",
            _NEUTRAL,
            "No location is stated on the posting, so this factor is neutral.",
        )
    matched_pref = next((p for p in prefs if contains_phrase(location, p)), None)
    if matched_pref:
        return _make(
            "location_fit", 1.0, f"“{truncate(location, 60)}” matches your preferred location {matched_pref}."
        )
    matched_campus = next((c for c in campus_terms if contains_phrase(location, c.split()[0])), None)
    if matched_campus:
        return _make(
            "location_fit", 0.95, f"“{truncate(location, 60)}” is on or next to {matched_campus}."
        )
    if _attr(opportunity, "type", None) == OpportunityType.ON_CAMPUS:
        return _make("location_fit", 0.85, "This is an on-campus role.")
    if not prefs:
        return _make(
            "location_fit",
            0.6,
            f"The role is at “{truncate(location, 60)}”; you have not recorded any location preferences.",
        )
    return _make(
        "location_fit",
        0.35,
        f"“{truncate(location, 60)}” does not match your preferred locations ({_join(prefs, 3)}).",
    )


def _parse_pay(opportunity: Any) -> tuple[float | None, str | None, str | None]:
    """Return ``(amount, period, source_text)`` — never a guess."""
    low = _attr(opportunity, "pay_min", None)
    high = _attr(opportunity, "pay_max", None)
    period = _attr(opportunity, "pay_period", None)
    text = str(_attr(opportunity, "pay_text", "") or "")
    amounts = [float(v) for v in (low, high) if v]
    if not amounts and text:
        found = _MONEY_RE.findall(text)
        amounts = [float(v.replace(",", "")) for v in found]
    if not amounts:
        return (None, None, None)
    amount = sum(amounts) / len(amounts)
    if not period:
        haystack = normalize(text)
        if any(word in haystack for word in _HOURLY_WORDS) or amount <= 100:
            period = "hour"
        else:
            period = "total"
    return (amount, period, text or None)


def _compensation_component(opportunity: Any) -> ScoreComponent:
    amount, period, source = _parse_pay(opportunity)
    if amount is None:
        return _make(
            "compensation",
            0.0,
            "Pay is not stated on this posting, so it was not scored and its weight was shared across the other factors.",
            scored=False,
        )
    if period in ("hour", "hourly"):
        score = _clamp((amount - 15.0) / 15.0, 0.15, 1.0)
        return _make(
            "compensation",
            score,
            f"Pays about ${amount:,.2f} an hour, as stated on the posting.",
            [source] if source else None,
        )
    return _make(
        "compensation",
        0.7,
        f"Pay is stated as “{truncate(source or f'${amount:,.0f}', 80)}”, which is not directly comparable to an hourly rate.",
    )


def _deadline_component(opportunity: Any, today: date) -> ScoreComponent:
    deadline = _attr(opportunity, "deadline", None)
    deadline_type = _attr(opportunity, "deadline_type", DeadlineType.UNKNOWN)
    certainty = _attr(opportunity, "deadline_certainty", Certainty.UNKNOWN)
    if deadline is None:
        if deadline_type == DeadlineType.ROLLING:
            return _make(
                "deadline_urgency",
                0.75,
                "Applications are accepted on a rolling basis, so there is no cliff to miss.",
            )
        return _make(
            "deadline_urgency",
            _NEUTRAL,
            "No deadline was found on the posting, so this factor is neutral — check the source before relying on it.",
        )
    days = (deadline - today).days
    suffix = "" if certainty == Certainty.VERIFIED else f" (deadline certainty: {str(certainty)})"
    if days < 0:
        return _make(
            "deadline_urgency", 0.0, f"The deadline passed {abs(days)} days ago{suffix}."
        )
    if days <= 2:
        return _make(
            "deadline_urgency", 0.6, f"Due in {days} days — still open, but very tight{suffix}."
        )
    if days <= 21:
        return _make(
            "deadline_urgency",
            1.0,
            f"Due in {days} days — soon enough to act on, with time to prepare{suffix}.",
        )
    if days <= 60:
        return _make("deadline_urgency", 0.8, f"Due in {days} days{suffix}.")
    return _make(
        "deadline_urgency", 0.55, f"Not due for {days} days, so there is no urgency yet{suffix}."
    )


_ELIGIBILITY_SCORE = {
    EligibilityState.ELIGIBLE: 1.0,
    EligibilityState.LIKELY_ELIGIBLE: 0.8,
    EligibilityState.UNCLEAR: 0.5,
    EligibilityState.INELIGIBLE: 0.0,
}


def _eligibility_component(state: EligibilityState, reasons: list[str]) -> ScoreComponent:
    return _make(
        "eligibility",
        _ELIGIBILITY_SCORE[state],
        reasons[0] if reasons else f"Eligibility is {state.value.replace('_', ' ')}.",
        reasons[1:3],
    )


def score_job(
    profile: Any,
    opportunity: Any,
    ctx: AgentContext | None = None,
    *,
    assessments: list[RequirementAssessment] | None = None,
    eligibility: tuple[EligibilityState, list[str]] | None = None,
) -> ScoreResult:
    """Score an on-campus or part-time job against the student."""
    view = ProfileView.of(profile)
    today = getattr(ctx, "today", None) or date.today()
    checks = assessments if assessments is not None else assess_requirements(view, opportunity)
    state, reasons = eligibility if eligibility is not None else derive_eligibility(
        checks, view, opportunity
    )
    blob = _opportunity_text(opportunity)

    components = [
        _qualification_component(checks),
        _job_skills_component(view, opportunity, blob),
        _interest_component(view, opportunity, blob),
        _hours_component(view, opportunity),
        _location_component(view, opportunity),
        _deadline_component(opportunity, today),
        _compensation_component(opportunity),
        _eligibility_component(state, reasons),
    ]
    fit = _finalize(components, JOB_WEIGHTS)

    penalties: list[tuple[float, str]] = []
    required = [a for a in checks if a.kind == RequirementKind.REQUIRED]
    if not required:
        penalties.append((0.20, "no requirements could be extracted from this posting"))
    elif len(required) < 3:
        penalties.append((0.06, "only a few requirements were extracted"))
    unknown = [a for a in required if a.state == RequirementMatch.UNKNOWN]
    if unknown:
        penalties.append((min(0.15, 0.04 * len(unknown)), f"{len(unknown)} requirements could not be interpreted"))
    if _attr(opportunity, "deadline", None) is None:
        penalties.append((0.06, "the deadline is unknown"))
    if _parse_pay(opportunity)[0] is None:
        penalties.append((0.05, "pay is not stated"))
    if view.is_sparse:
        penalties.append((0.12, "your profile has little to match against yet"))
    extraction = float(_attr(opportunity, "extraction_confidence", 0.0) or 0.0)
    if extraction and extraction < 0.6:
        penalties.append((0.08, "the posting was only partly parsed"))
    confidence, notes = _confidence(penalties)

    strengths, gaps = _strengths_and_gaps(components, checks)
    interest = next(c for c in components if c.key == "interest_alignment")
    why = interest.reason if interest.score >= 0.55 and interest.detail else None
    result = ScoreResult(
        fit_score=fit,
        confidence=confidence,
        components=components,
        strengths=strengths,
        gaps=gaps,
        explanation="",
        why_interesting=why,
        recommendation=recommend(fit, state),
        requirement_matches=checks,
        model=JOB_MODEL,
        eligibility=state,
        eligibility_reasons=reasons,
        confidence_notes=notes,
    )
    result.explanation = explain(result)
    return result


# --------------------------------------------------------------------------- #
# Research scoring
# --------------------------------------------------------------------------- #

_NEGATIVE_UNDERGRAD = (
    "not accepting",
    "no undergraduate",
    "no undergraduates",
    "does not take",
    "do not take",
    "unable to take",
    "rarely takes",
    "not taking",
    "graduate students only",
)


def _evidence_date(item: Any) -> date | None:
    published = _attr(item, "published_on", None)
    if isinstance(published, date):
        return published
    year = _attr(item, "year", None)
    if year:
        # Only a year is known: assume mid-year rather than a flattering
        # January, so recency buckets are not silently generous.
        return date(int(year), 7, 1)
    return None


def _months_since(when: date, today: date) -> int:
    return (today.year - when.year) * 12 + (today.month - when.month)


def _recency_weight(months: int | None) -> float:
    settings = get_settings()
    strong = settings.strong_recency_window_months
    window = settings.recency_window_months
    stale = window + strong
    if months is None:
        return 0.05
    if months <= strong:
        return 1.0
    if months <= window:
        return 0.6
    if months <= stale:
        return 0.25
    return 0.05


def _evidence_text(item: Any) -> str:
    return concat(
        _attr(item, "title", ""),
        _attr(item, "summary", ""),
        _strs(item, "topics"),
        _attr(item, "venue", ""),
        separator=" ",
    )


def _alignment(profile: ProfileView, text: str, explicit_topics: list[str] | None = None) -> tuple[float, list[str]]:
    """How much of the student's stated interest this text covers (0..1)."""
    topics: dict[str, float] = {}
    for slug, weight in taxonomy.match_topics(text):
        topics[slug] = max(topics.get(slug, 0.0), weight)
    for raw in explicit_topics or []:
        slug = taxonomy.resolve_topic(raw)
        if slug:
            topics[slug] = max(topics.get(slug, 0.0), 1.0)

    matched: list[str] = []
    scores: list[float] = []
    if profile.interest_topics:
        shared = set(topics) & set(profile.interest_topics)
        numerator = sum(min(topics[s], profile.interest_topics[s]) for s in shared)
        denominator = sum(profile.interest_topics.values())
        scores.append(_clamp(numerator / denominator) if denominator else 0.0)
        matched.extend(taxonomy.topic_label(s) for s in sorted(shared))
    terms = list(profile.keywords) + list(profile.interests)
    if terms:
        hits = [t for t in terms if contains_phrase(text, t)]
        scores.append(len(hits) / len(terms))
        matched.extend(hits)
    if not scores:
        return (0.0, [])
    return (_clamp(max(scores) * 0.7 + (sum(scores) / len(scores)) * 0.3), list(dict.fromkeys(matched)))


def _item_alignment(
    profile: ProfileView, text: str, explicit_topics: list[str] | None = None
) -> tuple[float, list[str]]:
    """How strongly ONE artefact speaks to the student (0..1).

    Deliberately different from :func:`_alignment`. That one asks "how much of
    the student's interests does this body of work cover?", which is the right
    question for a lab as a whole. It is the wrong question for a single paper:
    a paper is about one thing, so dividing by the student's whole interest
    portfolio caps a perfect topical hit at 1/len(interests) and makes strong
    recent work look weak. Here we ask instead "is this item on one of the
    student's topics?" — the strongest single match, plus a small bonus when it
    touches more than one.
    """
    topics: dict[str, float] = {}
    for slug, weight in taxonomy.match_topics(text):
        topics[slug] = max(topics.get(slug, 0.0), weight)
    for raw in explicit_topics or []:
        slug = taxonomy.resolve_topic(raw)
        if slug:
            topics[slug] = max(topics.get(slug, 0.0), 1.0)

    matched: list[str] = []
    best = 0.0
    hit_count = 0

    shared = set(topics) & set(profile.interest_topics or {})
    for slug in sorted(shared):
        interest_weight = _clamp(profile.interest_topics[slug] / 1.5)
        strength = _clamp(min(topics[slug], 1.0) * max(interest_weight, 0.6))
        best = max(best, strength)
        hit_count += 1
        matched.append(taxonomy.topic_label(slug))

    for term in list(profile.keywords) + list(profile.interests):
        if contains_phrase(text, term):
            best = max(best, 0.85)
            hit_count += 1
            matched.append(term)

    if best <= 0.0:
        return (0.0, [])
    breadth_bonus = min(0.15, 0.05 * max(0, hit_count - 1))
    return (_clamp(best + breadth_bonus), list(dict.fromkeys(matched)))


def _lab_text(opportunity: Any, faculty: Any, evidence: list[Any]) -> str:
    lab = getattr(opportunity, "lab", None) or getattr(faculty, "labs", None)
    lab_description = ""
    if lab is not None and not isinstance(lab, list):
        lab_description = concat(_attr(lab, "name", ""), _attr(lab, "description", ""), separator=" ")
    return concat(
        _attr(opportunity, "title", ""),
        _attr(opportunity, "description", ""),
        lab_description,
        _strs(faculty, "research_areas"),
        _strs(faculty, "current_direction"),
        [_evidence_text(item) for item in evidence],
    )


def _lab_topics(opportunity: Any, faculty: Any, blob: str) -> dict[str, float]:
    topics = _opportunity_topics(opportunity, blob)
    for row in getattr(faculty, "topics", None) or []:
        topic = getattr(row, "topic", None)
        slug = taxonomy.resolve_topic(getattr(topic, "slug", None))
        if not slug:
            continue
        weight = _clamp(float(_attr(row, "weight", 1.0)))
        if str(_attr(row, "origin", "directory")) != "evidence":
            weight *= 0.8
        topics[slug] = max(topics.get(slug, 0.0), weight)
    for raw in _strs(faculty, "research_areas") + _strs(faculty, "current_direction"):
        slug = taxonomy.resolve_topic(raw)
        if slug:
            topics[slug] = max(topics.get(slug, 0.0), 0.9)
    return topics


def _topic_similarity_component(
    profile: ProfileView, lab_topics: dict[str, float], lab_blob: str
) -> ScoreComponent:
    if not profile.interest_topics and not profile.keywords and not profile.interests:
        return _make(
            "topic_similarity",
            _NEUTRAL,
            "You have not recorded research interests, so topic overlap cannot be judged.",
        )
    if not lab_topics:
        score, matched = _alignment(profile, lab_blob)
        return _make(
            "topic_similarity",
            score,
            f"No canonical topics were resolved for this lab; matched on wording alone: {_join(matched, 3)}"
            if matched
            else "Trellis could not resolve any research topics for this lab.",
        )
    shared = set(lab_topics) & set(profile.interest_topics)
    numerator = sum(min(lab_topics[s], profile.interest_topics[s]) for s in shared)
    interest_total = sum(profile.interest_topics.values())
    lab_total = sum(lab_topics.values())
    coverage_of_you = numerator / interest_total if interest_total else 0.0
    coverage_of_lab = numerator / lab_total if lab_total else 0.0
    score = _clamp(0.7 * coverage_of_you + 0.3 * coverage_of_lab)
    labels = [taxonomy.topic_label(s) for s in sorted(shared)]
    if labels:
        reason = f"The lab's topics overlap yours on {_join(labels, 3)}"
    else:
        reason = f"None of the lab's topics ({_join([taxonomy.topic_label(s) for s in sorted(lab_topics)], 3)}) match your stated interests"
    return _make(
        "topic_similarity",
        score,
        reason,
        [f"Lab topic: {taxonomy.topic_label(s)}" for s in sorted(lab_topics)][:10],
    )


def _recent_work_component(
    profile: ProfileView, evidence: list[Any], today: date
) -> ScoreComponent:
    settings = get_settings()
    strong = settings.strong_recency_window_months
    window = settings.recency_window_months
    if not evidence:
        return _make(
            "recent_work_alignment",
            0.0,
            "No dated evidence of recent work was found for this lab, so recent alignment cannot be shown.",
        )
    total_weight = 0.0
    numerator = 0.0
    per_item: list[tuple[float, float]] = []
    detail: list[str] = []
    highlights: list[tuple[float, str, int | None]] = []
    for item in evidence:
        when = _evidence_date(item)
        months = _months_since(when, today) if when else None
        weight = _recency_weight(months)
        align, matched = _item_alignment(profile, _evidence_text(item), _strs(item, "topics"))
        total_weight += weight
        numerator += weight * align
        per_item.append((weight, align))
        year = _attr(item, "year", None) or (when.year if when else None)
        title = truncate(str(_attr(item, "title", "untitled")), 80)
        detail.append(
            f"{year or 'undated'} · recency weight {weight:.2f} · overlap {align:.2f} — {title}"
        )
        if align > 0 and weight >= 0.6:
            highlights.append((weight * align, title, year))
    # A lab is a strong match when its RECENT work lands on the student's
    # topics — not when the average paper does. Averaging over everything
    # punishes a productive lab for breadth: 4 direct hits among 20 papers is
    # an excellent signal, but a mean reads it as 0.2. So score the best recent
    # hits, plus how many of them there are.
    #
    # Staleness is still handled, because each item's alignment is multiplied
    # by its recency weight before it competes: a perfect match from 2019
    # carries 0.05 and cannot carry the component.
    weighted_aligns = sorted(
        (weight * align for weight, align in per_item if align > 0.0), reverse=True
    )
    best = weighted_aligns[0] if weighted_aligns else 0.0
    strong_hits = sum(1 for value in weighted_aligns if value >= 0.3)
    breadth = min(1.0, strong_hits / 3.0)
    score = _clamp(0.65 * best + 0.35 * breadth)
    highlights.sort(reverse=True)
    recent = [i for i in evidence if (d := _evidence_date(i)) and _months_since(d, today) <= window]
    if highlights:
        best = highlights[0]
        reason = (
            f"{len(highlights)} of {len(evidence)} pieces of evidence from the last {window} months "
            f"overlap your interests, most recently “{best[1]}” ({best[2] or 'undated'})"
        )
    elif recent:
        reason = f"The lab has {len(recent)} items from the last {window} months, but none of them overlap your stated interests"
    else:
        years = [y for y in (_attr(i, "year", None) for i in evidence) if y]
        newest = max(years) if years else None
        reason = (
            f"The newest dated evidence is from {newest}, older than the {window}-month window, so recent alignment scores near zero"
            if newest
            else "None of the evidence for this lab is dated, so recent alignment cannot be established"
        )
    detail.insert(0, f"Recency windows: {strong} months at full weight, {window} months at 0.6.")
    return _make("recent_work_alignment", score, reason, detail[:12])


def _research_skills_component(profile: ProfileView, lab_blob: str) -> ScoreComponent:
    wanted = taxonomy.match_skill_slugs(lab_blob)
    if not wanted:
        return _make(
            "skills_overlap",
            _NEUTRAL,
            "Nothing in the lab's material names specific tools or skills, so this factor is neutral.",
        )
    have = sorted(wanted & profile.skill_slugs)
    score = len(have) / len(wanted)
    if have:
        reason = f"You have {len(have)} of the {len(wanted)} skills this lab's material mentions: {_join([taxonomy.skill_label(s) for s in have], 4)}"
    else:
        reason = f"None of the skills this lab mentions ({_join([taxonomy.skill_label(s) for s in sorted(wanted)], 3)}) are evidenced in your profile"
    return _make("skills_overlap", score, reason)


def _coursework_component(profile: ProfileView, lab_topics: dict[str, float], lab_blob: str) -> ScoreComponent:
    if not profile.coursework:
        return _make(
            "coursework_overlap",
            _NEUTRAL,
            "No coursework is recorded on your profile, so this factor is neutral.",
        )
    lab_skills = taxonomy.match_skill_slugs(lab_blob)
    skill_hits = sorted(profile.coursework_skills & lab_skills)
    topic_hits = sorted(set(profile.coursework_topics) & set(lab_topics))
    denominator = max(len(lab_skills) + len(lab_topics), 1)
    score = _clamp((len(skill_hits) + len(topic_hits)) / denominator * 2.0)
    labels = [taxonomy.skill_label(s) for s in skill_hits] + [
        taxonomy.topic_label(s) for s in topic_hits
    ]
    if labels:
        reason = f"Your coursework covers {_join(labels, 3)}, which this lab works on"
    else:
        reason = f"Your recorded coursework ({_join(list(profile.coursework), 2)}) does not obviously overlap this lab's work"
    return _make("coursework_overlap", score, reason)


def _undergrad_component(signals: list[Any]) -> ScoreComponent:
    relevant = [s for s in signals if _attr(s, "kind", None) == SignalKind.UNDERGRAD_PRESENCE]
    if not relevant:
        return _make(
            "undergrad_friendliness",
            0.0,
            "No evidence was found either way about undergraduates working in this lab.",
        )
    best: Any = None
    best_credit = -1.0
    for signal in relevant:
        credit = _CERTAINTY_CREDIT.get(_attr(signal, "certainty", Certainty.UNKNOWN), 0.0)
        if credit > best_credit:
            best, best_credit = signal, credit
    statement = concat(_attr(best, "label", ""), _attr(best, "statement", ""), separator=" ")
    negative = any(contains_phrase(statement, phrase) for phrase in _NEGATIVE_UNDERGRAD)
    certainty = _attr(best, "certainty", Certainty.UNKNOWN)
    if negative:
        return _make(
            "undergrad_friendliness",
            0.0,
            f"The lab's own material suggests it does not take undergraduates: “{truncate(statement, 120)}”.",
            [f"Certainty: {str(certainty)}", str(_attr(best, "source_url", "") or "")],
        )
    if best_credit == 0.0:
        return _make(
            "undergrad_friendliness",
            0.0,
            f"An undergraduate signal exists but is unverified, so it earns no credit: “{truncate(statement, 120)}”.",
        )
    return _make(
        "undergrad_friendliness",
        best_credit,
        f"{str(certainty).capitalize()} evidence of undergraduates in this lab: “{truncate(statement, 120)}”.",
        [str(_attr(best, "source_url", "") or "")],
    )


def _lab_activity_component(evidence: list[Any], today: date) -> ScoreComponent:
    dates = [d for d in (_evidence_date(i) for i in evidence) if d]
    if not dates:
        return _make(
            "lab_activity",
            0.0,
            f"No dated output was found for this lab across {len(evidence)} collected items.",
        )
    newest = max(dates)
    months = _months_since(newest, today)
    recency = _recency_weight(months)
    volume = _clamp(len(evidence) / 5.0)
    score = _clamp(0.65 * recency + 0.35 * volume)
    return _make(
        "lab_activity",
        score,
        f"{len(evidence)} collected items, the newest {months} months old ({newest.year}).",
    )


def _lead_state(opportunity: Any, signals: list[Any], evidence: list[Any], today: date) -> LeadState:
    raw = _attr(opportunity, "raw", {}) or {}
    stated = raw.get("lead_state") or raw.get("opportunity_state")
    if isinstance(stated, str):
        try:
            return LeadState(stated)
        except ValueError:
            pass
    if _attr(opportunity, "type", None) == OpportunityType.RESEARCH_OPENING:
        return LeadState.OPENING
    verified_recruiting = any(
        _attr(s, "kind", None) == SignalKind.RECRUITING
        and _attr(s, "certainty", Certainty.UNKNOWN) == Certainty.VERIFIED
        for s in signals
    )
    if verified_recruiting:
        return LeadState.OPENING
    recent = [
        d for d in (_evidence_date(i) for i in evidence) if d and _months_since(d, today) <= 36
    ]
    if not recent:
        return LeadState.WATCH
    return LeadState.OUTREACH


def _opening_component(
    opportunity: Any, signals: list[Any], lead_state: LeadState
) -> ScoreComponent:
    recruiting = [
        s
        for s in signals
        if _attr(s, "kind", None) == SignalKind.RECRUITING
        and _attr(s, "certainty", Certainty.UNKNOWN)
        in (Certainty.VERIFIED, Certainty.LIKELY)
    ]
    if lead_state == LeadState.OPENING:
        if recruiting or _attr(opportunity, "application_url", None):
            return _make(
                "opening_vs_outreach",
                1.0,
                f"There is a stated opening: “{truncate(str(_attr(recruiting[0], 'label', '') if recruiting else _attr(opportunity, 'title', '')), 100)}”.",
                [str(_attr(s, "source_url", "") or "") for s in recruiting][:2],
            )
        return _make(
            "opening_vs_outreach",
            0.85,
            "This is listed as a formal research opening, though Trellis found no separate recruiting statement to confirm it.",
        )
    if lead_state == LeadState.OUTREACH:
        return _make(
            "opening_vs_outreach",
            0.6,
            "There is no advertised opening — this would be a cold email to the PI.",
        )
    return _make(
        "opening_vs_outreach",
        0.3,
        "No opening and no recent activity: worth watching rather than contacting now.",
    )


def _campus_component(profile: ProfileView, opportunity: Any, faculty: Any) -> ScoreComponent:
    university = str(_attr(faculty, "university", "") or _attr(opportunity, "university", "") or "")
    if not university:
        return _make(
            "campus_fit", _NEUTRAL, "No university is recorded for this lab, so this is neutral."
        )
    if profile.university and fuzzy_ratio(profile.university, university) >= 0.85:
        department = str(_attr(faculty, "department", "") or "")
        return _make(
            "campus_fit",
            1.0,
            f"The lab is at {university}, where you study"
            + (f" ({department})." if department else "."),
        )
    if any(contains_phrase(university, p) for p in profile.preferred_locations):
        return _make("campus_fit", 0.7, f"{university} is one of your preferred locations.")
    return _make(
        "campus_fit",
        0.3,
        f"The lab is at {university}, not {profile.university or 'your university'}.",
    )


def score_research(
    profile: Any,
    opportunity: Any,
    faculty: Any = None,
    evidence: list[Any] | None = None,
    signals: list[Any] | None = None,
    ctx: AgentContext | None = None,
    *,
    assessments: list[RequirementAssessment] | None = None,
    eligibility: tuple[EligibilityState, list[str]] | None = None,
) -> ScoreResult:
    """Score a research opening or a cold-outreach lead against the student."""
    view = ProfileView.of(profile)
    today = getattr(ctx, "today", None) or date.today()
    faculty = faculty if faculty is not None else getattr(opportunity, "faculty", None)
    evidence_list = list(
        evidence if evidence is not None else (getattr(faculty, "evidence", None) or [])
    )
    signal_list = list(
        signals if signals is not None else (getattr(faculty, "signals", None) or [])
    )
    checks = assessments if assessments is not None else assess_requirements(view, opportunity)
    state, reasons = eligibility if eligibility is not None else derive_eligibility(
        checks, view, opportunity
    )

    lab_blob = _lab_text(opportunity, faculty, evidence_list)
    lab_topics = _lab_topics(opportunity, faculty, lab_blob)
    lead_state = _lead_state(opportunity, signal_list, evidence_list, today)

    components = [
        _topic_similarity_component(view, lab_topics, lab_blob),
        _recent_work_component(view, evidence_list, today),
        _research_skills_component(view, lab_blob),
        _undergrad_component(signal_list),
        _coursework_component(view, lab_topics, lab_blob),
        _lab_activity_component(evidence_list, today),
        _opening_component(opportunity, signal_list, lead_state),
        _campus_component(view, opportunity, faculty),
    ]
    fit = _finalize(components, RESEARCH_WEIGHTS)

    penalties: list[tuple[float, str]] = []
    if not evidence_list:
        penalties.append((0.25, "no dated evidence was collected for this lab"))
    elif len(evidence_list) < 3:
        penalties.append((0.08, "only a couple of pieces of evidence were collected"))
    if not any(_attr(s, "kind", None) == SignalKind.UNDERGRAD_PRESENCE for s in signal_list):
        penalties.append((0.08, "there is no signal about undergraduates in this lab"))
    if not view.interest_topics:
        penalties.append((0.15, "you have not recorded research interests to match against"))
    if not lab_topics:
        penalties.append((0.10, "no research topics could be resolved for this lab"))
    if state == EligibilityState.UNCLEAR:
        penalties.append((0.05, "eligibility for this lead is unclear"))
    confidence, notes = _confidence(penalties)

    strengths, gaps = _strengths_and_gaps(components, checks)
    recent = next(c for c in components if c.key == "recent_work_alignment")
    topic = next(c for c in components if c.key == "topic_similarity")
    why_parts = [c.reason for c in (recent, topic) if c.score >= 0.3]
    why = " ".join(why_parts) if why_parts else None

    result = ScoreResult(
        fit_score=fit,
        confidence=confidence,
        components=components,
        strengths=strengths,
        gaps=gaps,
        explanation="",
        why_interesting=why,
        recommendation=recommend(fit, state, is_outreach=lead_state != LeadState.OPENING),
        requirement_matches=checks,
        model=RESEARCH_MODEL,
        eligibility=state,
        eligibility_reasons=reasons,
        confidence_notes=notes,
    )
    result.explanation = explain(result)
    return result


def score_opportunity(
    profile: Any,
    opportunity: Any,
    ctx: AgentContext | None = None,
    **kwargs: Any,
) -> ScoreResult:
    """Pick the right model for the opportunity's type."""
    kind = _attr(opportunity, "type", OpportunityType.ON_CAMPUS)
    if kind in (OpportunityType.RESEARCH_OPENING, OpportunityType.RESEARCH_OUTREACH):
        return score_research(profile, opportunity, ctx=ctx, **kwargs)
    return score_job(profile, opportunity, ctx, **kwargs)


