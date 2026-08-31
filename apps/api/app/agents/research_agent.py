"""Research discovery.

The pipeline the product is really built around:

    interests -> departments -> faculty -> lab site -> recent publications
    -> lab news -> CURRENT direction -> similarity to the student
    -> formal opening vs cold outreach vs watch

Two rules make this different from keyword-matching a faculty bio:

* ``current_direction`` is derived ONLY from evidence inside the recency
  window. If a lab has nothing recent, the direction is empty and its certainty
  is UNKNOWN. We never fall back to the biography, because a 2014 bio is
  exactly the thing that makes students email about work a lab stopped doing.
* OPENING requires a quoted, currently-open, undergraduate-relevant statement
  with a URL. Everything else is OUTREACH (lab is active) or WATCH.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.agents.base import Agent, AgentContext, AgentOutcome
from app.agents.matching_agent import MatchingAgent, MatchRequest
from app.core.config import get_settings
from app.models.enums import (
    Certainty,
    EvidenceKind,
    LeadState,
    OpportunityStatus,
    OpportunityType,
    RunStatus,
    SignalKind,
)
from app.models.opportunity import Opportunity, OpportunitySource
from app.models.ops import SearchRun
from app.models.research import Faculty, Lab, LabSignal, ResearchEvidence
from app.services import taxonomy
from app.services.runs import finish_run, record_step
from app.sources.base import SourceContext
from app.sources.registry import get_adapter

# Phrases that mean a lab is actively looking, as opposed to describing itself.
RECRUITING_OPEN = (
    "we are looking for",
    "we are actively looking",
    "we are recruiting",
    "currently recruiting",
    "openings for",
    "positions available",
    "now accepting applications",
    "join us",
    "join the lab",
    "apply here",
    "apply via",
    "seeking students",
    # An invitation does not have to be phrased as a vacancy. An earlier version
    # of this list missed "please get in touch", and downgraded a lab whose page
    # says "If you're an undergraduate ... please get in touch!" -- which is
    # plainly an open door.
    "get in touch",
    "reach out",
    "contact me",
    "please email",
    "fill this form",
    "fill out this form",
    "interested in joining",
    "happy to work with",
    "welcome applicants",
)
RECRUITING_CLOSED = (
    "not taking new students",
    "not accepting new students",
    "no openings",
    "not currently recruiting",
    "i am not taking",
    "cannot take on additional",
)
UNDERGRAD_TERMS = ("undergraduate", "undergrad", "bachelor", "curis", "b.s. student", "sophomore", "junior")
# Wording that invites undergraduates specifically rather than PhD applicants.
UNDERGRAD_INVITE = (
    "stanford undergraduate",
    "undergraduate students interested",
    "if you are an undergraduate",
    "undergraduate researchers",
    "we work with undergraduate",
    "happy to work with undergraduate",
    "undergraduate and masters",
)
PHD_ONLY = ("prospective phd", "phd applicants", "phd admissions", "graduate admissions")


# ------------------------------------------------------------------------- #
# Lead classification vocabulary
#
# The hard part is not the phrase lists.  It is that a harvested signal is
# often a *verification note* rather than a quote -- "POSTDOC ONLY - not an
# undergraduate opening", "No undergraduate members listed on the lab People
# page", "neither posting contains the word 'undergraduate'".  Matching
# "undergraduate" anywhere in those strings is exactly how the previous
# classifier promoted five labs to OPENING that plainly have none.  So every
# statement is cut into clauses and each clause is judged on its own, and a
# claim only counts as an invitation when it is phrased as one.
# ------------------------------------------------------------------------- #

_CLAUSE_SPLIT = re.compile(
    r"(?<=[.;!?])\s+"      # sentence end
    r"|\s*\|\|\s*"      # the harvester's own record separator
    r"|\s+[-\u2013\u2014]\s+"  # " - " asides
    r"|\n+"
)
# Kept out of the splitter so a negative tail ("..., but Guibas is not named on
# that page") can poison the clause it qualifies instead of standing alone.
_BUT_SPLIT = re.compile(r",?\s+(?:but|however|although|though|except that)\s+", re.IGNORECASE)

_NEGATION_TOKENS = frozenset(
    {
        "no", "not", "never", "none", "nor", "neither", "without", "cannot",
        "zero", "non", "nothing", "nowhere", "nobody", "declined",
        "discouraged", "empty", "unfunded",
    }
)
_NEGATION_PHRASES = ("n't", "commented out", "no longer", "not a current")

# Wording that rules undergraduates out rather than merely failing to mention
# them.  Only these block the OPENING path; a stray "not" elsewhere does not.
_UNDERGRAD_EXCLUSIONS = (
    "only",
    "no undergraduate",
    "not an undergraduate",
    "not undergraduate",
    "never",
    "neither",
    "does not",
    "do not",
    "cannot",
    "declined",
    "no degree level",
)
# An invitation has to be phrased as one.  A note that an undergraduate
# *exists* somewhere on the page is presence, not an opening.
_INVITE_CUES = (
    "if you are", "if you're", "please", "happy to work with", "we work with",
    "welcome", "opening", "position", "we are looking", "we are actively",
    "interested in joining", "may do", "can do", "can still", "invit",
    "apply", "email", "fill out", "fill this", "complete this", "submit this",
    "get in touch", "reach out", "send", "accepting", "we take", "we host",
    "pathway", "route", "points ", "join",
    # "form" alone matches "information"/"transform"; only these read as intake.
    "this form", "the form", "intake form", "interest form", "application form",
    "google form",
)
# Past involvement is a real signal (the spec asks for it) but it is not the
# same claim as "there are undergraduates in this lab today".
_PAST_MARKERS = (
    "alumni", "alum ", "former", "formerly", "previously", "historical",
    "historically", "track record", "used to", "graduated", "co-author",
    "coauthor", "co-first", "first-authored", "authorship", "past member",
)
# A for-credit route (CS 195/199/191, CURIS, an honours thesis) is how a
# Stanford undergraduate actually joins a lab, so it earns its own signal.
_COURSE_MARKERS = (
    "cs 195", "cs195", "cs 199", "cs199", "cs 191", "cs191",
    "independent stud", "independent work", "senior project", "senior-project",
    "supervised undergraduate research", "instructor of record",
    "honors thesis", "honours thesis", "course number", "research course",
    "for-credit", "curis", "reu", "surf",
)
_CONTACT_MARKERS = (
    "email", "e-mail", "form", "get in touch", "contact", "apply",
    "application", "reach out", "mailing list",
)
# Verified facts that make a cold email pointless whatever else is true.
_DISQUALIFIERS = (
    "retired from", "has retired", "is retired", "emeritus",
    "no longer at stanford", "no longer affiliated",
    "active institutional home is",
)
_GRADUATE_SCOPE = ("phd", "ph.d", "doctoral", "postdoc", "post-doc", "graduate student")

_CERTAINTY_RANK = {
    Certainty.VERIFIED: 3,
    Certainty.LIKELY: 2,
    Certainty.INFERRED: 1,
    Certainty.UNKNOWN: 0,
}


@dataclass(frozen=True, slots=True)
class LeadSignal:
    """One specific, sourced reason a lead is in the state it is in."""

    key: str
    label: str
    certainty: Certainty
    source_url: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "certainty": self.certainty.value,
            "source_url": self.source_url,
            "detail": self.detail,
        }


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z']+", text.lower()))


def _has(text: str, markers: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(marker in low for marker in markers)


def _is_negative(clause: str) -> bool:
    return _has(clause, _NEGATION_PHRASES) or bool(_tokens(clause) & _NEGATION_TOKENS)


def _clauses(text: str | None) -> list[str]:
    """Split a harvested statement into independently judgeable clauses.

    A ``but``-tail is folded back onto its head, because "has an
    'Undergraduates' category, but it is currently empty" must not read as a
    positive claim about undergraduates.
    """
    if not text:
        return []
    out: list[str] = []
    for chunk in _CLAUSE_SPLIT.split(text):
        parts = [p.strip() for p in _BUT_SPLIT.split(chunk) if p.strip()]
        if not parts:
            continue
        qualified = any(
            _is_negative(p) or _has(p, _PAST_MARKERS) for p in parts[1:]
        )
        out.extend([" but ".join(parts)] if qualified else parts)
    return [c for c in out if c]


def _mentions_undergrads(clause: str) -> bool:
    return _has(clause, UNDERGRAD_TERMS)


def harvest_recruiting_status(signal: LabSignal) -> str:
    """``recruiting.status`` as recorded when the page was actually read.

    open / closed / unverified / unknown.  This is a judgement made with the
    page in hand; re-deriving it from the prose afterwards is strictly worse.
    """
    match = re.search(r"recruiting\.status\s*=\s*(\w+)", (signal.note or "").lower())
    return match.group(1) if match else "unknown"


def _signal_clauses(signal: LabSignal) -> list[str]:
    return _clauses(signal.statement) + _clauses(signal.label)


def _invites_undergrads(clause: str) -> bool:
    """A clause that names undergraduates *and* is phrased as an invitation."""
    return (
        _mentions_undergrads(clause)
        and not _is_negative(clause)
        and _has(clause, _INVITE_CUES)
    )


def _excludes_undergrads(signal: LabSignal) -> bool:
    """True when the statement names undergraduates only to rule them out."""
    return any(
        _mentions_undergrads(c) and _has(c, _UNDERGRAD_EXCLUSIONS)
        for c in _signal_clauses(signal)
    )


def _blanket_close(signal: LabSignal) -> bool:
    """A 'not recruiting' that is not scoped to PhD or postdoc applicants.

    Scope is read from the statement, never from the label: the label is the
    harvester's own one-line summary ("Says it is not currently recruiting")
    and drops the scope that makes the difference between "no PhD students
    this cycle" and "do not write to us at all".
    """
    if harvest_recruiting_status(signal) != "closed":
        return False
    closed = [c for c in _clauses(signal.statement) if _has(c, RECRUITING_CLOSED)]
    if not closed:
        # Status says closed and nothing explains who it applies to.
        return True
    return any(not _has(c, _GRADUATE_SCOPE) for c in closed)


def _undergrad_bucket(clause: str) -> str | None:
    if _is_negative(clause) or not _mentions_undergrads(clause):
        return None
    if _has(clause, _PAST_MARKERS):
        return "undergrad_track_record"
    if _has(clause, _COURSE_MARKERS):
        return "undergrad_course_route"
    if _has(clause, _INVITE_CUES):
        return "undergrad_invited"
    return "undergrads_in_lab"


_BUCKET_LABEL = {
    "undergrad_invited": "Lab page addresses undergraduates directly",
    "undergrads_in_lab": "Undergraduates currently visible in the lab",
    "undergrad_course_route": "Supervises for-credit undergraduate research",
    "undergrad_track_record": "Track record of undergraduate involvement",
}


def _best(signals: list[LabSignal]) -> LabSignal:
    return max(signals, key=lambda s: _CERTAINTY_RANK[s.certainty])


@dataclass(slots=True)
class ResearchRequest:
    profile: Any
    run: SearchRun
    limit: int = 30
    refresh_labs: bool = True


@dataclass(slots=True)
class ResearchOutcome:
    faculty_seen: int = 0
    leads_created: int = 0
    leads_updated: int = 0
    openings: int = 0
    outreach: int = 0
    watch: int = 0
    unknown: int = 0
    failures: list[str] = field(default_factory=list)


class ResearchDiscoveryAgent(Agent[ResearchRequest, ResearchOutcome]):
    name = "research-discovery"
    description = "Finds labs worth contacting, grounded in what they published recently."

    def __init__(self) -> None:
        self._match = MatchingAgent()

    def run(self, ctx: AgentContext, payload: ResearchRequest) -> AgentOutcome[ResearchOutcome]:
        run = payload.run
        profile = payload.profile
        result = ResearchOutcome()
        settings = get_settings()

        interests = [i.label for i in getattr(profile, "interests", [])]
        record_step(
            run,
            "plan",
            f"Mapping {len(interests)} interest(s) onto Stanford departments and labs: "
            f"{', '.join(interests[:6]) or 'none set'}.",
        )

        faculty_rows = list(ctx.db.scalars(select(Faculty).limit(payload.limit)))
        if not faculty_rows:
            faculty_rows = self._discover_faculty(ctx, profile, run, result)

        result.faculty_seen = len(faculty_rows)
        record_step(run, "faculty", f"Assessing {len(faculty_rows)} faculty record(s).")

        source_row = ctx.db.scalars(
            select(OpportunitySource).where(OpportunitySource.slug == "stanford_cs_faculty")
        ).first()

        for faculty in faculty_rows:
            evidence = sorted(
                faculty.evidence, key=lambda e: (e.year or 0), reverse=True
            )
            direction, basis, certainty = self._current_direction(evidence, ctx, settings)
            # Never trade a specific direction for a generic one. What this agent
            # can derive are canonical topic labels ("Large Language Models");
            # a harvested or model-written direction reads like
            # "Auditing what AI agents actually do to human work", which is far
            # more useful to a student deciding whether to email. Only fill an
            # empty direction, or replace one the evidence no longer supports.
            existing = list(faculty.current_direction or [])
            existing_is_specific = any(len(phrase) > 40 for phrase in existing)
            if direction and not (existing_is_specific and faculty.is_active):
                faculty.current_direction = direction
                faculty.current_direction_basis = basis
                faculty.current_direction_certainty = certainty
            elif not direction and not existing:
                faculty.current_direction = []
                faculty.current_direction_basis = None
                faculty.current_direction_certainty = Certainty.UNKNOWN
            faculty.last_evidence_year = evidence[0].year if evidence else None
            faculty.evidence_count = len(evidence)
            faculty.is_active = self._is_active(evidence, ctx, settings)
            faculty.last_checked_at = datetime.now(UTC)

            state, lead_signals = self._classify(faculty, evidence, ctx, settings)
            if state == LeadState.OPENING:
                result.openings += 1
            elif state == LeadState.OUTREACH:
                result.outreach += 1
            elif state == LeadState.WATCH:
                result.watch += 1
            else:
                result.unknown += 1

            opp, created = self._upsert_lead(ctx, faculty, state, lead_signals, source_row)
            result.leads_created += int(created)
            result.leads_updated += int(not created)
            if profile is not None:
                self._match.run(ctx, MatchRequest(profile=profile, opportunity=opp, polish=False))

        ctx.db.flush()
        run.created_count = result.leads_created
        run.updated_count = result.leads_updated
        run.stats = {
            "openings": result.openings,
            "outreach": result.outreach,
            "watch": result.watch,
            "unknown": result.unknown,
        }
        record_step(
            run,
            "summary",
            f"{result.openings} verified opening(s), {result.outreach} outreach lead(s), "
            f"{result.watch} to watch, {result.unknown} with too little information.",
        )
        finish_run(
            ctx.db, run, status=RunStatus.PARTIAL if result.failures else None
        )
        return AgentOutcome(result=result, warnings=result.failures)

    # ------------------------------------------------------------------ #

    def _discover_faculty(
        self, ctx: AgentContext, profile: Any, run: SearchRun, result: ResearchOutcome
    ) -> list[Faculty]:
        """Live discovery, used when the database has no faculty yet."""
        try:
            adapter = get_adapter("stanford_cs_faculty")
        except (KeyError, LookupError):
            result.failures.append("stanford_cs_faculty adapter missing")
            return []
        source_ctx = SourceContext(
            university=getattr(profile, "university", "Stanford University"),
            topics=[i.label for i in getattr(profile, "interests", [])],
            limit=40,
        )
        rows: list[Faculty] = []
        try:
            for doc in adapter.discover(source_ctx):
                data = doc.structured or {}
                name = data.get("name")
                if not name:
                    continue
                slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
                existing = ctx.db.scalars(select(Faculty).where(Faculty.slug == slug)).first()
                if existing is None:
                    existing = Faculty(
                        slug=slug,
                        name=name,
                        title=data.get("title"),
                        university=source_ctx.university,
                        department=data.get("department") or "Computer Science",
                        faculty_url=data.get("profile_url") or doc.url,
                        first_seen_at=datetime.now(UTC),
                    )
                    ctx.db.add(existing)
                    ctx.db.flush()
                rows.append(existing)
        except Exception as exc:
            result.failures.append(f"faculty discovery: {exc}")
            record_step(run, "faculty", f"Faculty directory failed: {exc}", "error")
        return rows

    def _current_direction(
        self, evidence: list[ResearchEvidence], ctx: AgentContext, settings
    ) -> tuple[list[str], str | None, Certainty]:
        window = settings.recency_window_months
        cutoff_year = ctx.today.year - max(1, window // 12)
        recent = [e for e in evidence if (e.year or 0) >= cutoff_year]
        if not recent:
            # Deliberately empty rather than recycled from an old bio.
            return ([], None, Certainty.UNKNOWN)

        weights: dict[str, float] = {}
        for item in recent:
            blob = f"{item.title} {item.summary or ''}"
            recency = 1.0 if (item.year or 0) >= ctx.today.year else 0.6
            for slug, weight in taxonomy.match_topics(blob):
                weights[slug] = weights.get(slug, 0.0) + weight * recency
            for topic in item.topics or []:
                slug = taxonomy.resolve_topic(topic)
                if slug:
                    weights[slug] = weights.get(slug, 0.0) + recency

        ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:5]
        direction = [taxonomy.topic_label(slug) for slug, _ in ranked]
        cited = ", ".join(f"{e.title[:60]} ({e.year})" for e in recent[:3])
        basis = (
            f"Inferred from {len(recent)} item(s) since {cutoff_year}: {cited}."
            if direction
            else None
        )
        # Several recent, dated items is a solid basis; one is a hint.
        certainty = (
            Certainty.LIKELY
            if len(recent) >= 3 and direction
            else (Certainty.INFERRED if direction else Certainty.UNKNOWN)
        )
        return (direction, basis, certainty)

    def _is_active(self, evidence: list[ResearchEvidence], ctx: AgentContext, settings) -> bool:
        cutoff = ctx.today.year - max(1, settings.recency_window_months // 12)
        return any((e.year or 0) >= cutoff for e in evidence)

    def _classify(
        self,
        faculty: Faculty,
        evidence: list[ResearchEvidence],
        ctx: AgentContext,
        settings,
    ) -> tuple[LeadState, list[LeadSignal]]:
        """Four honest states, plus the specific sourced signals behind them.

        OPENING is the only state that asserts something on the lab's behalf,
        so it needs all of: an open recruiting statement, read from a page we
        can link to, at 'likely' certainty or better, whose undergraduate
        relevance is stated rather than inferred.

        OUTREACH says "a cold email is justified", which needs a route to send
        one and a reason to believe it will land: recent output, plus
        undergraduates in the picture, plus a public contact.

        WATCH is for labs we understand but cannot act on.  UNKNOWN is for
        labs we could not read enough about -- and it is never upgraded to
        OUTREACH just to give the student something to click.
        """
        signals: list[LeadSignal] = []
        recruiting = [s for s in faculty.signals if s.kind == SignalKind.RECRUITING]
        undergrad = [s for s in faculty.signals if s.kind == SignalKind.UNDERGRAD_PRESENCE]
        sourced_recruiting = [s for s in recruiting if s.source_url]

        # --- a verified opening ------------------------------------------ #
        blanket_closed = [s for s in recruiting if _blanket_close(s)]
        opening_signal: LeadSignal | None = None
        # A blanket "we are not taking students" anywhere on the lab's pages
        # outranks any open-sounding sentence elsewhere on them.
        for signal in [] if blanket_closed else sourced_recruiting:
            if _CERTAINTY_RANK[signal.certainty] < _CERTAINTY_RANK[Certainty.LIKELY]:
                continue
            if harvest_recruiting_status(signal) != "open":
                continue
            if _excludes_undergrads(signal):
                # The statement names undergraduates only to rule them out
                # ("POSTDOC ONLY - not an undergraduate opening").  No amount
                # of other evidence makes that an undergraduate opening.
                continue
            quoted = next(
                (c for c in _clauses(signal.statement) if _invites_undergrads(c)), None
            )
            if quoted is None:
                # The recruiting copy is open but silent on degree level.  A
                # separately verified statement that undergraduates may join
                # the group is allowed to supply that half, and nothing less.
                invitation = next(
                    (
                        s
                        for s in undergrad
                        if s.source_url
                        and s.certainty == Certainty.VERIFIED
                        and any(_invites_undergrads(c) for c in _signal_clauses(s))
                    ),
                    None,
                )
                if invitation is None:
                    continue
                quoted = next(
                    c for c in _signal_clauses(invitation) if _invites_undergrads(c)
                )
                opening_signal = LeadSignal(
                    key="verified_opening",
                    label="Open recruitment plus a stated undergraduate route",
                    certainty=min(
                        (signal.certainty, invitation.certainty),
                        key=lambda c: _CERTAINTY_RANK[c],
                    ),
                    source_url=invitation.source_url,
                    detail=quoted,
                )
            else:
                opening_signal = LeadSignal(
                    key="verified_opening",
                    label="Quoted, currently-open statement naming undergraduates",
                    certainty=signal.certainty,
                    source_url=signal.source_url,
                    detail=quoted,
                )
            break

        # --- everything the outreach decision rests on -------------------- #
        cutoff_year = ctx.today.year - max(1, settings.recency_window_months // 12)
        recent = [e for e in evidence if (e.year or 0) >= cutoff_year]
        if recent:
            newest = recent[0]
            signals.append(
                LeadSignal(
                    key="recent_output",
                    label=f"{len(recent)} dated item(s) since {cutoff_year}",
                    certainty=Certainty.VERIFIED if newest.url else Certainty.LIKELY,
                    source_url=newest.url,
                    detail=f"Most recent: {newest.title} ({newest.year}).",
                )
            )

        buckets: dict[str, list[tuple[LabSignal, str]]] = {}
        for signal in undergrad:
            if not signal.source_url:
                continue
            for clause in _signal_clauses(signal):
                bucket = _undergrad_bucket(clause)
                if bucket:
                    buckets.setdefault(bucket, []).append((signal, clause))
                    break
        for key in (
            "undergrad_invited",
            "undergrads_in_lab",
            "undergrad_course_route",
            "undergrad_track_record",
        ):
            hits = buckets.get(key)
            if not hits:
                continue
            signal, clause = max(hits, key=lambda h: _CERTAINTY_RANK[h[0].certainty])
            signals.append(
                LeadSignal(
                    key=key,
                    label=_BUCKET_LABEL[key],
                    certainty=signal.certainty,
                    source_url=signal.source_url,
                    detail=clause,
                )
            )

        invitation_signal: LeadSignal | None = None
        for signal in sourced_recruiting:
            if _blanket_close(signal):
                continue
            clause = next(
                (
                    c
                    for c in _clauses(signal.statement)
                    if _has(c, RECRUITING_OPEN) and not _is_negative(c)
                ),
                None,
            )
            if clause:
                invitation_signal = LeadSignal(
                    key="open_invitation",
                    label="Lab page invites people to make contact",
                    certainty=signal.certainty,
                    source_url=signal.source_url,
                    detail=clause,
                )
                break
        if invitation_signal:
            signals.append(invitation_signal)

        contact_signal = self._contact_signal(faculty, sourced_recruiting)
        if contact_signal:
            signals.append(contact_signal)

        for signal in faculty.signals:
            if not signal.source_url or _CERTAINTY_RANK[signal.certainty] < _CERTAINTY_RANK[
                Certainty.LIKELY
            ]:
                continue
            clause = next(
                (c for c in _signal_clauses(signal) if _has(c, _DISQUALIFIERS)), None
            )
            if clause:
                signals.append(
                    LeadSignal(
                        key="no_longer_reachable",
                        label="Not currently taking students at this university",
                        certainty=signal.certainty,
                        source_url=signal.source_url,
                        detail=clause,
                    )
                )
                break
        for signal in recruiting:
            if harvest_recruiting_status(signal) != "closed":
                continue
            signals.append(
                LeadSignal(
                    key="recruiting_closed" if _blanket_close(signal) else "recruiting_narrowed",
                    label=(
                        "Lab states it is not currently recruiting"
                        if _blanket_close(signal)
                        else "Not recruiting at some levels (see the quote)"
                    ),
                    certainty=signal.certainty,
                    source_url=signal.source_url,
                    detail=(signal.statement or signal.label)[:400],
                )
            )
            break

        keys = {s.key for s in signals}
        if opening_signal is not None:
            return LeadState.OPENING, [opening_signal, *signals]

        undergrad_evidence = keys & {
            "undergrad_invited",
            "undergrads_in_lab",
            "undergrad_course_route",
            "undergrad_track_record",
        }
        blocked = bool(keys & {"no_longer_reachable", "recruiting_closed"})
        actionable = (
            "recent_output" in keys
            and "public_contact" in keys
            and bool(undergrad_evidence or "open_invitation" in keys)
        )
        if actionable and not blocked:
            return LeadState.OUTREACH, signals

        # Enough read to be worth keeping an eye on, but nothing to act on.
        if len(recent) >= 2 or (recent and (undergrad_evidence or "public_contact" in keys)):
            return LeadState.WATCH, signals
        return LeadState.UNKNOWN, signals

    def _contact_signal(
        self, faculty: Faculty, recruiting: list[LabSignal]
    ) -> LeadSignal | None:
        """A way to actually send the email, or nothing. Never a guessed address."""
        email_source = faculty.email_source_url or faculty.faculty_url
        if (
            faculty.email
            and email_source
            and _CERTAINTY_RANK[faculty.email_certainty] >= _CERTAINTY_RANK[Certainty.LIKELY]
        ):
            # No source page, no claim: an address we cannot point at is the
            # same as an address we guessed.
            return LeadSignal(
                key="public_contact",
                label="Public email address",
                certainty=faculty.email_certainty,
                source_url=email_source,
                detail=faculty.email,
            )
        lab = faculty.labs[0] if faculty.labs else None
        if lab is not None and lab.join_url:
            return LeadSignal(
                key="public_contact",
                label="Public join / contact page",
                certainty=Certainty.VERIFIED,
                source_url=lab.join_url,
                detail=f"{lab.name} publishes a contact route.",
            )
        for signal in recruiting:
            clause = next(
                (
                    c
                    for c in _clauses(signal.statement)
                    if _has(c, _CONTACT_MARKERS) and not _is_negative(c)
                ),
                None,
            )
            if clause:
                return LeadSignal(
                    key="public_contact",
                    label="Contact route named on the lab's own page",
                    certainty=signal.certainty,
                    source_url=signal.source_url,
                    detail=clause,
                )
        return None

    def _upsert_lead(
        self,
        ctx: AgentContext,
        faculty: Faculty,
        state: LeadState,
        signals: list[LeadSignal],
        source: OpportunitySource | None,
    ) -> tuple[Opportunity, bool]:
        external_key = f"faculty:{faculty.slug}"
        opp = ctx.db.scalars(
            select(Opportunity).where(Opportunity.external_key == external_key)
        ).first()
        created = opp is None
        lab: Lab | None = faculty.labs[0] if faculty.labs else None

        if opp is None:
            opp = Opportunity(
                title=f"Undergraduate research — {lab.name if lab else faculty.name}",
                type=OpportunityType.RESEARCH_OUTREACH,
                status=OpportunityStatus.NEW,
                external_key=external_key,
                first_seen_at=datetime.now(UTC),
            )
            ctx.db.add(opp)

        opp.type = (
            OpportunityType.RESEARCH_OPENING
            if state == LeadState.OPENING
            else OpportunityType.RESEARCH_OUTREACH
        )
        opp.lead_state = state
        opp.lead_state_signals = [s.as_dict() for s in signals]
        opp.lead_state_at = datetime.now(UTC)
        opp.organization = lab.name if lab else (faculty.department or faculty.university)
        opp.university = faculty.university
        opp.department = faculty.department
        opp.faculty_id = faculty.id
        opp.lab_id = lab.id if lab else None
        opp.source_url = (lab.url if lab else None) or faculty.faculty_url
        opp.contact_name = faculty.name
        opp.contact_email = faculty.email if faculty.email_certainty != Certainty.UNKNOWN else None
        opp.last_checked_at = datetime.now(UTC)
        if source is not None:
            opp.source_id = source.id
        ctx.db.flush()
        return opp, created


def lead_state_for(opportunity: Opportunity) -> LeadState:
    """The lead state the UI shows.

    Reads the classifier's persisted verdict.  ``lead_state`` is NULL only for
    rows the classifier has never seen -- programme-level openings (CURIS,
    VPUE grants) carry no faculty and are not lab leads at all -- so those
    still fall back to the type they were extracted as.
    """
    if opportunity.lead_state is not None:
        return opportunity.lead_state
    if opportunity.type == OpportunityType.RESEARCH_OPENING:
        return LeadState.OPENING
    if opportunity.type == OpportunityType.RESEARCH_OUTREACH:
        return LeadState.OUTREACH
    return LeadState.UNKNOWN


def undergrad_summary(signals: list[LabSignal]) -> tuple[str, Certainty]:
    """One honest sentence about undergraduate involvement."""
    relevant = [s for s in signals if s.kind == SignalKind.UNDERGRAD_PRESENCE]
    if not relevant:
        return ("No undergraduate signal found", Certainty.UNKNOWN)
    best = max(
        relevant,
        key=lambda s: {
            Certainty.VERIFIED: 3,
            Certainty.LIKELY: 2,
            Certainty.INFERRED: 1,
            Certainty.UNKNOWN: 0,
        }[s.certainty],
    )
    return (best.label, best.certainty)


def evidence_kind_label(kind: EvidenceKind) -> str:
    return {
        EvidenceKind.PUBLICATION: "Paper",
        EvidenceKind.PROJECT: "Project",
        EvidenceKind.NEWS: "Lab news",
        EvidenceKind.GRANT: "Grant",
        EvidenceKind.COURSE: "Course",
        EvidenceKind.TALK: "Talk",
        EvidenceKind.STUDENT_PROJECT: "Student project",
    }[kind]
