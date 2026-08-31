"""The student side of a research match.

:func:`app.api.serializers.relevance_to_me` answers "does this touch my
interests".  That is enough to rank a list and nowhere near enough to decide
whether to spend half an hour writing to a lab.  This module answers the
question that decision actually turns on:

* **Strong overlap** — which interest of mine does this lab's *recent, dated*
  work touch, and in which artefact.
* **Relevant background** — what do I already have that connects.  Every item
  is a row the student typed or a line they uploaded; a resume line is quoted
  character for character and named with its file.
* **Potential gaps** — what the lab's evidence is full of and the student's
  record is silent about.

Three rules hold everywhere below.

1. Nothing is invented.  ``relevant_background`` is assembled only from
   ``StudentProfile`` rows and ``Resume``/``ResumeHighlight`` text.  When there
   is no resume to read we say so (:attr:`FitBreakdown.background_note`) rather
   than quietly returning a shorter list.
2. A gap is never a verdict.  ``blocking`` is true only for a *stated hard
   requirement* the scorer marked missing in a category that can actually make
   somebody ineligible.  A missing preferred qualification is never blocking,
   and every gap is phrased as an absence in the evidence ("nothing in your
   profile mentions X"), never as a deficiency in the student.
3. Deterministic.  No model runs here; ordering is fixed so the same database
   always produces the same breakdown.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import EvidenceKind, RequirementKind
from app.models.opportunity import Opportunity, OpportunityMatch
from app.models.research import Faculty, ResearchEvidence
from app.models.resume import Resume, ResumeHighlight
from app.models.user import StudentProfile
from app.services import resume_parser, taxonomy
from app.services.scoring import BLOCKING_CATEGORIES
from app.services.taxonomy import GENERIC_TOPICS
from app.services.text import normalize

MAX_OVERLAP = 6
MAX_BACKGROUND = 10
MAX_GAPS = 4

# Skill categories that can be evidenced by a lab naming them in its own text.
TOOL_CATEGORIES = frozenset({"language", "framework", "tool"})

# How an evidence row is referred to in a sentence. "Their 2026 paper" reads as
# English; "Their 2026 publication" reads as a database column.
EVIDENCE_WORD: dict[EvidenceKind, str] = {
    EvidenceKind.PUBLICATION: "paper",
    EvidenceKind.PROJECT: "project",
    EvidenceKind.NEWS: "news post",
    EvidenceKind.GRANT: "grant",
    EvidenceKind.COURSE: "course listing",
    EvidenceKind.TALK: "talk",
    EvidenceKind.STUDENT_PROJECT: "student project",
}

# Course codes as a document prints them ("CS 224N"), so a quoted course keeps
# the student's own spacing instead of the storage form ("CS224N").
_PRINTED_CODE_RE = re.compile(r"\b[A-Za-z]{2,6}\s?\d{1,3}[A-Za-z]{0,3}\b")


@dataclass(slots=True)
class OverlapPoint:
    """One interest of the student's that this lab's work demonstrably touches."""

    label: str
    kind: str
    evidence: str
    source_url: str | None = None


@dataclass(slots=True)
class BackgroundPoint:
    """One thing the student already has. Never anything they do not."""

    label: str
    kind: str
    detail: str | None = None
    #: File name of the uploaded resume this was read from.
    resume: str | None = None
    #: ``detail`` is the student's own words, character for character.
    verbatim: bool = False


@dataclass(slots=True)
class GapPoint:
    label: str
    blocking: bool
    note: str


@dataclass(slots=True)
class FitBreakdown:
    strong_overlap: list[OverlapPoint] = field(default_factory=list)
    relevant_background: list[BackgroundPoint] = field(default_factory=list)
    potential_gaps: list[GapPoint] = field(default_factory=list)
    #: Every parsed resume this breakdown was allowed to read.
    resumes_read: list[str] = field(default_factory=list)
    #: Said out loud when there was no resume text to draw on.
    background_note: str | None = None


# --------------------------------------------------------------------------
# The lab's side
# --------------------------------------------------------------------------


@dataclass(slots=True)
class _LabTopic:
    slug: str
    label: str
    #: Evidence rows carrying this topic, newest first.
    evidence: list[ResearchEvidence] = field(default_factory=list)
    #: The subset whose own title or tags carry it, rather than only their
    #: description. Quoted in preference, so the sentence we print shows on its
    #: face why it was picked.
    headline: list[ResearchEvidence] = field(default_factory=list)
    origins: set[str] = field(default_factory=set)

    @property
    def cite(self) -> ResearchEvidence | None:
        if self.headline:
            return self.headline[0]
        return self.evidence[0] if self.evidence else None


def _evidence_topics(item: ResearchEvidence) -> tuple[set[str], set[str]]:
    """(everything this row carries, the subset its title or tags carry).

    The split matters for what we then say out loud.  Diyi Yang's course row is
    titled after CS 195 and CS 191; only its description mentions that she also
    teaches CS 224N.  Both are evidence of NLP, but quoting the title as proof
    of NLP would look like a mistake to anyone who clicked through.
    """
    titled = {slug for slug, _ in taxonomy.match_topics(item.title)}
    for raw in item.topics or []:
        if resolved := taxonomy.resolve_topic(raw):
            titled.add(resolved)
    found = titled | {slug for slug, _ in taxonomy.match_topics(item.summary or "")}
    return found, titled


def _lab_topics(faculty: Faculty) -> dict[str, _LabTopic]:
    """Everything this lab is on record as working on, and what backs each one."""
    out: dict[str, _LabTopic] = {}

    def entry(slug: str, label: str) -> _LabTopic:
        if slug not in out:
            out[slug] = _LabTopic(slug=slug, label=label)
        return out[slug]

    for item in sorted(faculty.evidence, key=lambda e: (e.year or 0), reverse=True):
        found, titled = _evidence_topics(item)
        for slug in sorted(found):
            topic = entry(slug, taxonomy.topic_label(slug))
            topic.evidence.append(item)
            topic.origins.add("evidence")
            if slug in titled:
                topic.headline.append(item)
    for link in faculty.topics:
        if link.topic is None:
            continue
        entry(link.topic.slug, link.topic.label).origins.add(link.origin)
    return out


def _lab_text(faculty: Faculty, opportunity: Opportunity | None) -> str:
    """Everything readable about the lab, for spotting named tools and methods."""
    parts: list[str] = [faculty.bio or "", " ".join(faculty.current_direction or [])]
    for lab in faculty.labs:
        parts.append(lab.description or "")
    for item in faculty.evidence:
        parts.append(f"{item.title} {item.summary or ''}")
    if opportunity is not None:
        parts.append(opportunity.description or "")
    return " ".join(p for p in parts if p)


def _phrase(item: ResearchEvidence) -> str:
    """"Their 2026 paper “…”" — the citable half of every sentence below."""
    word = EVIDENCE_WORD.get(item.kind, "work")
    when = str(item.year) if item.year else "recent"
    return f"Their {when} {word} “{item.title}”"


# --------------------------------------------------------------------------
# The student's side
# --------------------------------------------------------------------------


def _interest_terms(profile: StudentProfile) -> list[tuple[str, str, str | None]]:
    """(label, kind, resolved slug) for each thing the student named, in their
    own order.

    Keywords come after interests and never restate one.  This student's
    keywords are largely a second spelling of their interests ("multimodal" for
    "multimodal AI"), and listing an overlap twice under two spellings reads as
    two findings when it is one.
    """
    terms: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    for interest in profile.interests:
        slug = interest.topic.slug if interest.topic else taxonomy.resolve_topic(interest.label)
        keys = {normalize(interest.label)} | ({slug} if slug else set())
        if keys & seen:
            continue
        seen |= keys
        terms.append((interest.label, "interest", slug))
    for keyword in profile.keywords or []:
        slug = taxonomy.resolve_topic(keyword)
        keys = {normalize(keyword)} | ({slug} if slug else set())
        if keys & seen:
            continue
        seen |= keys
        terms.append((keyword, "keyword", slug))
    return terms


def _resume_coursework(resume: Resume) -> list[resume_parser.CourseworkEntry]:
    if not resume.text:
        return []
    parsed = resume_parser.parse_text(resume.text, source_name=resume.original_filename)
    return resume_parser.extract_coursework(parsed)


def _printed_code(source_text: str, code: str) -> str:
    """The course code as the document prints it, not as it is stored."""
    target = code.replace(" ", "").upper()
    for candidate in _PRINTED_CODE_RE.findall(source_text or ""):
        if candidate.replace(" ", "").upper() == target:
            return candidate
    return code


def _course_slugs(code: str | None, title: str, topics: Iterable[str]) -> set[str]:
    slugs = {resolved for raw in topics if (resolved := taxonomy.resolve_topic(raw))}
    slugs |= {slug for slug, _ in taxonomy.match_topics(f"{code or ''} {title}")}
    return slugs


def _skill_slugs(label: str) -> set[str]:
    """A skill counts as topical only when it *is* a topic. "PyTorch" is not a
    research area, so it is never used to claim topical overlap."""
    resolved = taxonomy.resolve_topic(label)
    return {resolved} if resolved else set()


def _student_topics(profile: StudentProfile, resumes: Sequence[Resume]) -> set[str]:
    """Every topic the student's own record literally mentions.

    Deliberately *not* widened to neighbouring topics.  This set decides what
    is not a gap, and the sentence a gap prints — "nothing in your profile or
    resumes mentions it" — is a claim about the words in those documents.  If
    the check were widened past what they say, the sentence would stop being
    true of them.
    """
    slugs: set[str] = set()
    for _, _, slug in _interest_terms(profile):
        if slug:
            slugs.add(slug)
    for course in profile.coursework:
        slugs |= _course_slugs(course.code, course.title, course.topics or [])
    for experience in profile.experiences:
        blob = " ".join(
            [experience.role, experience.summary or "", *(experience.highlights or [])]
        )
        slugs |= {slug for slug, _ in taxonomy.match_topics(blob)}
        for raw in experience.skills or []:
            slugs |= _skill_slugs(raw)
    for link in profile.skills:
        if link.skill is not None:
            slugs |= _skill_slugs(link.skill.label)
    for resume in resumes:
        slugs |= {
            resolved
            for raw in resume.detected_topics or []
            if (resolved := taxonomy.resolve_topic(raw))
        }
        slugs |= {slug for slug, _ in taxonomy.match_topics(resume.text or "")}
        for highlight in resume.highlights:
            slugs |= _highlight_slugs(highlight)
        for entry in _resume_coursework(resume):
            slugs |= _course_slugs(entry.code, entry.title, entry.topics)
    return slugs


def _attribute(snippet: str | None, resumes: Sequence[Resume]) -> str | None:
    """Which uploaded resume a stored evidence snippet was lifted from.

    ``ProfileSkill.evidence`` keeps the quote but not always the file it came
    from.  A quote we cannot name a source for is not shown as a quote at all,
    so this lookup is what decides between the two.
    """
    if not snippet:
        return None
    core = snippet.strip().strip("\u2026").strip()
    if len(core) < 12:
        return None
    needle = normalize(core)
    for resume in resumes:
        if needle and needle in normalize(resume.text or ""):
            return resume.original_filename
    return None


def _highlight_slugs(highlight: ResumeHighlight) -> set[str]:
    slugs = {resolved for raw in highlight.topics or [] if (resolved := taxonomy.resolve_topic(raw))}
    slugs |= {slug for slug, _ in taxonomy.match_topics(highlight.text)}
    return slugs


# --------------------------------------------------------------------------
# Strong overlap
# --------------------------------------------------------------------------


def _pick_topic(slug: str, topics: dict[str, _LabTopic]) -> tuple[_LabTopic, bool] | None:
    """The lab topic that best answers one interest, and whether it *is* that
    interest rather than a neighbour of it.

    The interest's own slug always wins.  Reporting "Large Language Models" for
    a student who wrote "NLP" — when the lab has recent NLP work on file — turns
    three different interests into three copies of one sentence, which is how
    the first cut of this read.
    """
    exact = topics.get(slug)
    if exact is not None and exact.evidence:
        return exact, True

    neighbours = [
        topics[s]
        for s in sorted(taxonomy.related_slugs(slug) - {slug} - GENERIC_TOPICS)
        if s in topics
    ]
    dated = [t for t in neighbours if t.evidence]
    if dated:
        dated.sort(key=lambda t: (-(t.cite.year or 0 if t.cite else 0), -len(t.evidence), t.slug))
        return dated[0], False

    if exact is not None:
        return exact, True
    return (neighbours[0], False) if neighbours else None


def _strong_overlap(
    faculty: Faculty, profile: StudentProfile, topics: dict[str, _LabTopic]
) -> tuple[list[OverlapPoint], set[str]]:
    points: list[OverlapPoint] = []
    cited: set[str] = set()
    for label, kind, slug in _interest_terms(profile):
        if not slug:
            continue
        picked = _pick_topic(slug, topics)
        if picked is None:
            continue
        topic, is_exact = picked
        # A hit on "Artificial Intelligence" is true of nearly every lab in the
        # department and tells the student nothing, so a generic topic counts
        # only when it is the interest they themselves named.
        if topic.slug in GENERIC_TOPICS and topic.slug != slug:
            continue
        if topic.slug in cited:
            continue
        cited.add(topic.slug)

        item = topic.cite
        if item is not None:
            if is_exact:
                evidence = f"{_phrase(item)} touches {topic.label}."
            else:
                evidence = (
                    f"{_phrase(item)} touches {topic.label} — the nearest thing in their "
                    f"recent work to {label}."
                )
            source_url = item.url
        else:
            evidence = (
                f"Listed under “{topic.label}” on their department profile. No recent work "
                "we could read shows it."
            )
            source_url = faculty.faculty_url
        points.append(
            OverlapPoint(label=label, kind=kind, evidence=evidence, source_url=source_url)
        )
    return points[:MAX_OVERLAP], cited


# --------------------------------------------------------------------------
# Relevant background
# --------------------------------------------------------------------------


def _wanted_topics(topics: dict[str, _LabTopic]) -> set[str]:
    """The lab topics a piece of the student's record may be matched against.

    Department-level areas are dropped before widening rather than after.
    Keeping them let "Artificial Intelligence" — which a graphics lab carries
    as readily as an NLP one — drag in its neighbour "LLM Agents", and a resume
    line about LLM agents then showed up as relevant background for a lab that
    does physically-based simulation.
    """
    wanted: set[str] = set()
    for slug in topics:
        if slug in GENERIC_TOPICS:
            continue
        wanted |= taxonomy.related_slugs(slug)
    return wanted - GENERIC_TOPICS


def _label_for(slug: str, topics: dict[str, _LabTopic]) -> str:
    topic = topics.get(slug)
    return topic.label if topic else taxonomy.topic_label(slug)


def _background_from_resumes(
    resumes: Sequence[Resume],
    wanted: set[str],
    topics: dict[str, _LabTopic],
    cited: set[str],
) -> list[BackgroundPoint]:
    """Verbatim lines, labelled with the lab topic that made them relevant.

    The label is the topic, never a summary of the line: naming a line
    "Agent evaluation harness" would be us writing the student's CV for them.
    The line itself is theirs, character for character, next to the file it
    came from.
    """
    points: list[BackgroundPoint] = []
    for resume in resumes:
        for highlight in sorted(resume.highlights, key=lambda h: (h.line_index or 0)):
            hit = sorted(_highlight_slugs(highlight) & wanted)
            if not hit:
                continue
            cited.update(hit)
            points.append(
                BackgroundPoint(
                    label=_label_for(hit[0], topics),
                    kind="resume_line",
                    detail=highlight.text,
                    resume=resume.original_filename,
                    verbatim=True,
                )
            )
    return points


def _background_from_coursework(
    profile: StudentProfile,
    resumes: Sequence[Resume],
    wanted: set[str],
    cited: set[str],
) -> list[BackgroundPoint]:
    points: list[BackgroundPoint] = []
    seen: set[str] = set()

    def add(label: str, detail: str, key: str, resume: str | None) -> None:
        if key in seen:
            return
        seen.add(key)
        points.append(
            BackgroundPoint(label=label, kind="coursework", detail=detail, resume=resume)
        )

    for course in profile.coursework:
        hit = _course_slugs(course.code, course.title, course.topics or []) & wanted
        if not hit:
            continue
        cited.update(hit)
        add(course.code or course.title, course.title, (course.code or course.title).lower(), None)
    # A course printed on a resume is as real as one typed into the profile,
    # and for this student coursework only ever arrived through a resume.
    for resume in resumes:
        for entry in _resume_coursework(resume):
            hit = _course_slugs(entry.code, entry.title, entry.topics) & wanted
            if not hit:
                continue
            cited.update(hit)
            code = entry.code or entry.title
            add(
                _printed_code(entry.source_text, code) if entry.code else entry.title,
                entry.title,
                code.lower(),
                resume.original_filename,
            )
    return points


def _background_from_experiences(
    profile: StudentProfile, wanted: set[str], cited: set[str]
) -> list[BackgroundPoint]:
    points: list[BackgroundPoint] = []
    for experience in profile.experiences:
        blob = " ".join([experience.role, experience.summary or "", *(experience.highlights or [])])
        slugs = {slug for slug, _ in taxonomy.match_topics(blob)}
        for raw in experience.skills or []:
            slugs |= _skill_slugs(raw)
        hit = slugs & wanted
        if not hit:
            continue
        cited.update(hit)
        points.append(
            BackgroundPoint(
                label=f"{experience.role} · {experience.organization}",
                kind="experience",
                detail=experience.summary,
            )
        )
    return points


def _background_from_skills(
    profile: StudentProfile,
    resumes: Sequence[Resume],
    wanted: set[str],
    lab_skills: set[str],
    cited: set[str],
) -> list[BackgroundPoint]:
    by_id = {resume.id: resume.original_filename for resume in resumes}
    points: list[BackgroundPoint] = []
    for link in sorted(profile.skills, key=lambda s: (s.skill.label if s.skill else "")):
        if link.skill is None:
            continue
        hit = _skill_slugs(link.skill.label) & wanted
        # A tool is only relevant background when the lab's own pages name it:
        # "PyTorch" is not a research area and proves nothing about fit on its
        # own, but a lab that advertises PyTorch work is a different matter.
        # Domains ("Machine Learning") are excluded from that path — every lab
        # in the school mentions one, and they already have the topic route.
        named = link.skill.slug in lab_skills and link.skill.category in TOOL_CATEGORIES
        # A skill that only restates a line or a course already quoted above is
        # the same finding twice, in a weaker form.
        fresh = hit - cited
        if not fresh and not named:
            continue
        cited.update(hit)

        detail = link.evidence if link.origin == "resume" else link.proficiency
        source = by_id.get(link.resume_id) if link.resume_id else _attribute(detail, resumes)
        if link.origin == "resume" and detail and source is None:
            # The quote is real but we cannot say which document it came from,
            # and an unattributed quote breaks the rule that made us keep it.
            detail = None
        points.append(
            BackgroundPoint(
                label=link.skill.label,
                kind="skill",
                detail=detail,
                resume=source if link.origin == "resume" and detail else None,
                verbatim=bool(link.origin == "resume" and detail),
            )
        )
    return points


def _relevant_background(
    profile: StudentProfile,
    resumes: Sequence[Resume],
    topics: dict[str, _LabTopic],
    lab_skills: set[str],
) -> tuple[list[BackgroundPoint], set[str]]:
    wanted = _wanted_topics(topics)
    cited: set[str] = set()
    points = [
        *_background_from_resumes(resumes, wanted, topics, cited),
        *_background_from_coursework(profile, resumes, wanted, cited),
        *_background_from_experiences(profile, wanted, cited),
        *_background_from_skills(profile, resumes, wanted, lab_skills, cited),
    ]
    deduped: list[BackgroundPoint] = []
    seen: set[tuple[str, str]] = set()
    for point in points:
        key = (point.kind, normalize(point.detail or point.label))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(point)
    return deduped[:MAX_BACKGROUND], cited


# --------------------------------------------------------------------------
# Gaps
# --------------------------------------------------------------------------


def _requirement_gaps(
    opportunity: Opportunity | None, match: OpportunityMatch | None
) -> list[GapPoint]:
    """Gaps that come from a *stated* qualification, split by kind.

    ``blocking`` is reachable only from here, and only for a REQUIRED line the
    scorer marked missing in a category that can genuinely make somebody
    ineligible. A preferred line can never set it — that split is the whole
    point of storing ``kind`` (docs/uncertainty.md).

    An INFERRED requirement raises no gap at all.  Nobody stated it, so telling
    a student they fall short of it would be inventing the bar and then failing
    them against it.
    """
    if opportunity is None or match is None:
        return []
    kinds = {str(r.id): r.kind for r in opportunity.requirements}
    gaps: list[GapPoint] = []
    for row in match.requirement_matches or []:
        if row.get("state") != "missing":
            continue
        stored = kinds.get(str(row.get("requirement_id")))
        kind = stored or next(
            (k for k in RequirementKind if k.value == row.get("kind")), None
        )
        text = str(row.get("text") or "").strip()
        if kind is None or not text:
            continue
        reason = str(row.get("reason") or "").strip()
        if kind == RequirementKind.REQUIRED:
            blocking = str(row.get("category") or "") in BLOCKING_CATEGORIES
            note = reason or "Stated as a requirement; nothing in your record satisfies it."
            if not blocking:
                note = f"{note} Stated as required, but it is not an eligibility gate."
            gaps.append(GapPoint(label=text, blocking=blocking, note=note))
        elif kind == RequirementKind.PREFERRED:
            gaps.append(
                GapPoint(
                    label=text,
                    blocking=False,
                    note=(
                        "Listed as preferred, not required. "
                        + (reason or "Nothing in your profile or resumes shows it.")
                    ),
                )
            )
    gaps.sort(key=lambda g: (not g.blocking,))
    return gaps


def _topic_gaps(
    topics: dict[str, _LabTopic],
    covered: set[str],
    total_evidence: int,
    resume_count: int,
    room: int,
) -> list[GapPoint]:
    """What the lab's dated work is about and the student's record never says.

    Only topics with an evidence row behind them are eligible, so every gap can
    quote the artefact that raised it.  A department listing with nothing dated
    behind it is not enough to tell somebody they are missing something.
    """
    if room <= 0:
        return []
    candidates = [
        topic
        for topic in topics.values()
        if topic.evidence and topic.slug not in GENERIC_TOPICS and topic.slug not in covered
    ]
    candidates.sort(key=lambda t: (-len(t.evidence), t.slug))

    record = "your profile or resumes" if resume_count else "your profile"
    gaps: list[GapPoint] = []
    spoken: set[str] = set()
    for topic in candidates:
        if len(gaps) >= room:
            break
        # "Robot Learning" and "Robotics" come off the same paper. Listing both
        # doubles the apparent size of one gap.
        if topic.slug in spoken:
            continue
        spoken |= taxonomy.related_slugs(topic.slug)

        count = len(topic.evidence)
        if count >= 2 and total_evidence:
            lab_side = (
                f"{count} of the {total_evidence} recent items we read from this lab are "
                f"about {topic.label}"
            )
        else:
            item = topic.cite
            if item is None:
                continue
            lab_side = f"{_phrase(item)} is about {topic.label}"
        gaps.append(
            GapPoint(
                label=f"No {topic.label} in {record}",
                blocking=False,
                note=f"{lab_side}; nothing in {record} mentions it.",
            )
        )
    return gaps


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def load_resumes(db: Session, profile: StudentProfile) -> list[Resume]:
    """Every resume the student uploaded, default first."""
    return list(
        db.scalars(
            select(Resume)
            .where(Resume.user_id == profile.user_id)
            .options(selectinload(Resume.highlights))
            .order_by(Resume.is_default.desc(), Resume.created_at)
        ).unique()
    )


def _background_note(resumes: Sequence[Resume], readable: Sequence[Resume]) -> str | None:
    if not resumes:
        return (
            "No resume has been uploaded, so nothing below was read from one — only what you "
            "entered in your profile."
        )
    if not readable:
        which = "Neither resume" if len(resumes) == 2 else f"None of your {len(resumes)} resumes"
        if len(resumes) == 1:
            which = "Your resume"
        return (
            f"{which} could be read, so nothing below was drawn from resume text — only what "
            "you entered in your profile."
        )
    return None


def compose_fit(
    faculty: Faculty,
    profile: StudentProfile,
    resumes: Sequence[Resume],
    *,
    opportunity: Opportunity | None = None,
    match: OpportunityMatch | None = None,
) -> FitBreakdown:
    """The breakdown itself, over data already in hand.

    Split from :func:`build_fit` so the rules can be exercised against plain
    objects: everything that decides what this product is allowed to say about
    a student should be testable without a database behind it.
    """
    readable = [r for r in resumes if r.parse_status == resume_parser.PARSE_OK and r.text]
    topics = _lab_topics(faculty)
    lab_skills = taxonomy.match_skill_slugs(_lab_text(faculty, opportunity))

    overlap, overlap_slugs = _strong_overlap(faculty, profile, topics)
    background, background_slugs = _relevant_background(profile, readable, topics, lab_skills)

    # Anything already reported above is, by definition, not a gap: saying
    # "their computer vision work is the nearest thing to your interest in
    # multimodal AI" and "nothing in your record mentions computer vision" in
    # the same panel reads as the page contradicting itself.
    covered = _student_topics(profile, readable) | overlap_slugs | background_slugs

    gaps = _requirement_gaps(opportunity, match)
    gaps += _topic_gaps(
        topics, covered, len(faculty.evidence), len(readable), MAX_GAPS - len(gaps)
    )

    return FitBreakdown(
        strong_overlap=overlap,
        relevant_background=background,
        potential_gaps=gaps[:MAX_GAPS],
        resumes_read=[r.original_filename for r in readable],
        background_note=_background_note(resumes, readable),
    )


def build_fit(
    db: Session,
    faculty: Faculty,
    profile: StudentProfile | None,
    *,
    opportunity: Opportunity | None = None,
    match: OpportunityMatch | None = None,
) -> FitBreakdown | None:
    """Why this lab is — or is not — worth this student's next half hour.

    Returns ``None`` when there is no profile: with nothing known about the
    student there is no honest answer, and an empty breakdown would read as
    "we looked and found nothing".
    """
    if profile is None:
        return None
    return compose_fit(
        faculty,
        profile,
        load_resumes(db, profile),
        opportunity=opportunity,
        match=match,
    )


__all__ = [
    "BackgroundPoint",
    "FitBreakdown",
    "GapPoint",
    "OverlapPoint",
    "build_fit",
    "compose_fit",
    "load_resumes",
]
