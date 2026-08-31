"""ORM -> response shaping.

Kept in one place so every endpoint returns the same shape for the same entity,
and so the honesty rules (certainty words, required/preferred split, provenance)
are applied once rather than per route.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.deadline_agent import days_until, urgency_for
from app.agents.research_agent import lead_state_for
from app.models.application import Application, ResumeRecommendation
from app.models.enums import (
    Certainty,
    FeedbackSignal,
    LeadState,
    OpportunityStatus,
    OpportunityType,
    RequirementKind,
    SignalKind,
)
from app.models.feedback import OpportunityFeedback
from app.models.opportunity import ExtractedField, Opportunity, OpportunityMatch
from app.models.ops import Reminder, SearchRun
from app.models.research import Faculty
from app.models.resume import Resume
from app.models.user import StudentProfile
from app.schemas import common as S
from app.schemas import entities as E
from app.services import directions, fit, search, taxonomy
from app.services import outreach as outreach_service
from app.services.readiness import Readiness, readiness_for

NEW_WINDOW_DAYS = 7

#: Re-exported so the name stays importable from here, where it was defined
#: before the fit breakdown needed the same list.
GENERIC_TOPICS = taxonomy.GENERIC_TOPICS


def interest_slugs(profile: StudentProfile | None) -> set[str]:
    """Every slug that counts as one of the student's interests, widened once.

    Widening here (rather than at each comparison) means the list, the Overview
    and the focus filter all agree on what "matches my interests" means.
    """
    if profile is None:
        return set()
    out: set[str] = set()
    for interest in profile.interests:
        slug = interest.topic.slug if interest.topic else taxonomy.resolve_topic(interest.label)
        if slug:
            out |= taxonomy.related_slugs(slug)
    return out


def _match_for(opp: Opportunity, profile_id: uuid.UUID | None) -> OpportunityMatch | None:
    if not opp.matches:
        return None
    if profile_id is None:
        return opp.matches[0]
    return next((m for m in opp.matches if m.profile_id == profile_id), None)


def search_explain(intent: search.SearchIntent | None) -> S.SearchExplain | None:
    """What the server understood the query to mean.

    Returned alongside the results so an ordering the student did not expect can
    be interrogated rather than guessed at — "part-time" narrowing to jobs and
    "agents" reaching LLM Agents are both decisions worth showing.
    """
    if intent is None:
        return None
    return S.SearchExplain(
        query=intent.query,
        terms=list(intent.terms),
        topics=[
            S.SearchTopicHit(slug=hit.slug, label=hit.label, tier=hit.tier, weight=hit.weight)
            for hit in sorted(
                intent.topics.values(), key=lambda h: (-h.weight, h.label.lower())
            )
        ],
        types=list(intent.kinds),
        notes=list(intent.notes),
    )


def source_ref(opp: Opportunity) -> S.SourceRef | None:
    src = opp.source
    if src is None:
        return None
    return S.SourceRef(
        slug=src.slug,
        name=src.name,
        kind=src.kind.value,
        base_url=src.base_url,
        requires_auth=src.requires_auth,
        is_public=src.is_public,
        is_mocked=False,
    )


def relevance_to_me(
    opp: Opportunity, profile: StudentProfile | None, wanted: set[str]
) -> str | None:
    """Why this is relevant to *this* student, or None.

    Returns the reason rather than a bare boolean so the UI can say what it
    matched on. A filter the student cannot interrogate is just a mystery
    ranking with extra steps.

    Three ways to qualify, in descending strength:
      1. a topic the student named, on the opportunity or its lab
      2. their own words appearing in the text
      3. research in their own field of study — CURIS is the obvious case: a CS
         research programme is plainly relevant to a CS student even though it
         names no specific topic
    """
    if profile is None:
        return None

    faculty = opp.faculty

    # Walk the student's interests in their own order and name the one that
    # matched, not the broadest ancestor. Reporting "Artificial Intelligence"
    # for every lead is technically true and tells the student nothing.
    present: set[str] = {
        link.topic.slug for link in opp.topics if link.topic is not None
    }
    if faculty is not None:
        present |= {ft.topic.slug for ft in faculty.topics if ft.topic is not None}

    resolved = [
        (
            interest.label,
            interest.topic.slug if interest.topic else taxonomy.resolve_topic(interest.label),
        )
        for interest in profile.interests
    ]

    # Exact matches first, across ALL interests. Otherwise a broad neighbour
    # like "artificial-intelligence" — which nearly every lab carries — wins the
    # race against a precise hit on a later interest, and every lead ends up
    # reported with the same uninformative reason.
    for label, slug in resolved:
        if slug and slug in present:
            return f"Matches your interest in {label}"

    for label, slug in resolved:
        if not slug:
            continue
        near = taxonomy.related_slugs(slug) & present
        specific = sorted(near - GENERIC_TOPICS) or sorted(near)
        if specific:
            return f"{taxonomy.topic_label(specific[0])}, close to your interest in {label}"

    terms: list[tuple[str, str]] = []
    for interest in profile.interests:
        terms.append((interest.label.lower(), f"Mentions {interest.label}"))
    for keyword in profile.keywords or []:
        terms.append((keyword.lower(), f"Mentions {keyword}"))

    haystack = " ".join(
        filter(
            None,
            [
                opp.title,
                opp.organization,
                opp.department,
                (opp.description or "")[:4000],
                " ".join(faculty.current_direction or []) if faculty else "",
            ],
        )
    ).lower()
    for term, reason in terms:
        if len(term) >= 3 and term in haystack:
            return reason

    major = (profile.major or "").strip().lower()
    if major and len(major) >= 3:
        is_research = opp.type in (
            OpportunityType.RESEARCH_OPENING,
            OpportunityType.RESEARCH_OUTREACH,
        ) or "research" in (opp.title or "").lower()
        field = f"{opp.department or ''} {opp.title or ''} {opp.organization or ''}".lower()
        if is_research and major in field:
            return f"Research in {profile.major}"

    return None


def opportunity_item(
    opp: Opportunity,
    *,
    today: date,
    profile_id: uuid.UUID | None = None,
    application: Application | None = None,
    has_reminder: bool = False,
    wanted_slugs: set[str] | None = None,
    profile_for_relevance: StudentProfile | None = None,
    feedback: OpportunityFeedback | None = None,
) -> S.OpportunityListItem:
    match = _match_for(opp, profile_id)
    faculty = opp.faculty
    lab = opp.lab
    is_research = opp.type in (
        OpportunityType.RESEARCH_OPENING,
        OpportunityType.RESEARCH_OUTREACH,
    )

    relevance = relevance_to_me(opp, profile_for_relevance, wanted_slugs or set())
    first_seen = opp.first_seen_at
    is_new = bool(
        first_seen and (today - first_seen.date()).days <= NEW_WINDOW_DAYS
    ) and opp.status == OpportunityStatus.NEW
    # Something you hid is never "new" again. Re-running discovery re-reads the
    # page and may well log what changed on it, but it may not walk the row back
    # onto the screen wearing the badge that means "you have not seen this".
    if feedback is not None and feedback.signal == FeedbackSignal.HIDDEN:
        is_new = False

    return S.OpportunityListItem(
        id=opp.id,
        title=opp.title,
        type=opp.type.value,
        status=opp.status.value,
        organization=opp.organization,
        department=opp.department,
        lab_name=lab.name if lab else None,
        pi_name=faculty.name if faculty else None,
        source=source_ref(opp),
        source_url=opp.source_url,
        location=opp.location,
        pay_text=opp.pay_text,
        hours_per_week=opp.hours_per_week,
        hours_note=opp.hours_note,
        deadline=opp.deadline,
        deadline_type=opp.deadline_type.value,
        # The RECORDED state, not a recomputation: "expired" is a thing that
        # happened to this row on a particular day, and the change log says so.
        deadline_state=opp.deadline_state.value,
        deadline_certainty=opp.deadline_certainty.value,
        days_until_deadline=days_until(opp.deadline, today),
        urgency=urgency_for(opp.deadline, opp.deadline_type, today),
        source_status=opp.source_status.value,
        source_status_at=opp.source_status_at,
        eligibility=opp.eligibility.value,
        fit_score=match.fit_score if match else None,
        fit_confidence=match.confidence if match else None,
        recommendation=match.recommendation if match else None,
        lead_state=lead_state_for(opp).value if is_research else None,
        topics=[
            S.TopicRef(slug=t.topic.slug, label=t.topic.label, weight=t.weight)
            for t in opp.topics
            if t.topic is not None
        ][:6],
        first_seen_at=first_seen,
        last_checked_at=opp.last_checked_at,
        is_new=is_new,
        has_application=application is not None,
        application_id=application.id if application else None,
        has_reminder=has_reminder,
        matches_interests=relevance is not None,
        relevance_reason=relevance,
        confidence_state=opp.confidence_state.value,
        confidence_reason=opp.confidence_reason,
        feedback=feedback_out(feedback),
    )


def feedback_out(row: OpportunityFeedback | None) -> S.FeedbackOut | None:
    if row is None:
        return None
    return S.FeedbackOut(
        signal=row.signal.value,
        reason=row.reason.value if row.reason else None,
        note=row.note,
        created_at=row.created_at,
    )


def requirement_out(req, assessment: dict[str, Any] | None) -> S.RequirementOut:
    return S.RequirementOut(
        id=req.id,
        text=req.text,
        kind=req.kind.value,
        category=req.category,
        source_text=req.source_text,
        source_url=req.source_url,
        confidence=req.confidence,
        match_state=(assessment or {}).get("state", "unknown"),
        match_reason=(assessment or {}).get("reason"),
    )


def match_detail(match: OpportunityMatch | None) -> S.MatchDetail | None:
    if match is None:
        return None
    return S.MatchDetail(
        fit_score=match.fit_score,
        confidence=match.confidence,
        model=match.model,
        breakdown=[S.ScoreComponent(**c) for c in match.breakdown or []],
        strengths=list(match.strengths or []),
        gaps=list(match.gaps or []),
        explanation=match.explanation,
        why_interesting=match.why_interesting,
        recommendation=match.recommendation,
        recommended_resume_id=match.recommended_resume_id,
        computed_at=match.computed_at,
    )


def faculty_ref(faculty: Faculty) -> S.FacultyRef:
    return S.FacultyRef(
        id=faculty.id,
        slug=faculty.slug,
        name=faculty.name,
        title=faculty.title,
        department=faculty.department,
        university=faculty.university,
        faculty_url=faculty.faculty_url,
        email=faculty.email,
        email_certainty=faculty.email_certainty.value,
        email_source_url=faculty.email_source_url,
        current_direction=list(faculty.current_direction or []),
        current_direction_basis=faculty.current_direction_basis,
        current_direction_certainty=faculty.current_direction_certainty.value,
        last_evidence_year=faculty.last_evidence_year,
        evidence_count=faculty.evidence_count,
        is_active=faculty.is_active,
        source_urls=list(faculty.source_urls or []),
    )


def lab_ref(lab) -> S.LabRef | None:
    if lab is None:
        return None
    return S.LabRef(
        id=lab.id,
        name=lab.name,
        slug=lab.slug,
        url=lab.url,
        department=lab.department,
        description=lab.description,
        news_url=lab.news_url,
        people_url=lab.people_url,
        join_url=lab.join_url,
    )


def evidence_item(e) -> S.ResearchEvidenceItem:
    return S.ResearchEvidenceItem(
        id=e.id,
        kind=e.kind.value,
        title=e.title,
        summary=e.summary,
        year=e.year,
        url=e.url,
        venue=e.venue,
        authors=list(e.authors or []),
    )


def signal_item(s) -> S.LabSignalItem:
    return S.LabSignalItem(
        kind=s.kind.value,
        label=s.label,
        certainty=s.certainty.value,
        statement=s.statement,
        source_url=s.source_url,
        note=s.note,
    )


def topic_overlap(
    faculty: Faculty, profile: StudentProfile | None
) -> list[S.TopicOverlap]:
    """Which of the student's interests this lab's RECENT work touches, and where."""
    if profile is None:
        return []
    interests = {
        taxonomy.resolve_topic(i.label) or i.label.lower(): i.label for i in profile.interests
    }
    if not interests:
        return []

    # Widen each interest to its hand-checked neighbours before intersecting.
    # A student who wrote "LLM agents" should match a paper the extractor tagged
    # "large-language-models"; requiring identical slugs made the UI claim "no
    # overlap" about labs that plainly overlap.
    interest_expansion: dict[str, str] = {}
    for slug, label in interests.items():
        for related in taxonomy.related_slugs(slug):
            interest_expansion.setdefault(related, label)

    overlaps: list[S.TopicOverlap] = []
    seen: set[str] = set()
    for item in sorted(faculty.evidence, key=lambda e: (e.year or 0), reverse=True):
        blob = f"{item.title} {item.summary or ''}"
        matched = {slug for slug, _ in taxonomy.match_topics(blob)}
        for topic in item.topics or []:
            resolved = taxonomy.resolve_topic(topic)
            if resolved:
                matched.add(resolved)
        for slug in sorted(matched & set(interest_expansion)):
            # Dedupe on the student's own wording, not the slug: several related
            # slugs collapse to one interest, and showing "NLP" twice is noise.
            label = interest_expansion[slug]
            if label in seen:
                continue
            seen.add(label)
            overlaps.append(
                S.TopicOverlap(
                    topic=interest_expansion[slug],
                    why=f"Their {item.year or 'recent'} work touches {taxonomy.topic_label(slug)}.",
                    evidence_year=item.year,
                    evidence_title=item.title,
                    evidence_url=item.url,
                )
            )
        if len(overlaps) >= 5:
            break
    return overlaps


def _opening_statement(faculty: Faculty) -> tuple[str | None, str | None]:
    for signal in faculty.signals:
        if signal.kind == SignalKind.RECRUITING and signal.statement:
            return signal.statement, signal.source_url
    return None, None


def _next_step(state: LeadState, faculty: Faculty) -> str:
    if state == LeadState.OPENING:
        return (
            "Apply through the channel quoted below, and mention the specific recent "
            "work that drew you in."
        )
    if state == LeadState.OUTREACH:
        target = "the lab's contact form" if not faculty.email else f"{faculty.name}"
        return (
            f"No advertised opening. A short, specific email to {target} referencing one "
            "recent paper is the realistic path here."
        )
    if state == LeadState.WATCH:
        return (
            "Recent work is there, but nothing on any page we could read says an "
            "undergraduate can join right now. Worth watching rather than contacting."
        )
    return (
        "Too little could be read about this lab to advise anything. Check the sources "
        "below yourself before spending time on an email."
    )


def fit_breakdown(
    db: Session,
    faculty: Faculty,
    profile: StudentProfile | None,
    *,
    opportunity: Opportunity | None = None,
    match: OpportunityMatch | None = None,
) -> S.FitBreakdown | None:
    """The student side of the match, shaped for the wire.

    Every string in here was built by :mod:`app.services.fit` from a profile row
    or a line of an uploaded resume; nothing is composed on this side.
    """
    breakdown = fit.build_fit(db, faculty, profile, opportunity=opportunity, match=match)
    if breakdown is None:
        return None
    return S.FitBreakdown(
        strong_overlap=[
            S.FitOverlapItem(
                label=p.label, kind=p.kind, evidence=p.evidence, source_url=p.source_url
            )
            for p in breakdown.strong_overlap
        ],
        relevant_background=[
            S.FitBackgroundItem(
                label=p.label,
                kind=p.kind,
                detail=p.detail,
                resume=p.resume,
                verbatim=p.verbatim,
            )
            for p in breakdown.relevant_background
        ],
        potential_gaps=[
            S.FitGapItem(label=p.label, blocking=p.blocking, note=p.note)
            for p in breakdown.potential_gaps
        ],
        resumes_read=list(breakdown.resumes_read),
        background_note=breakdown.background_note,
    )


def lead_state_signals(opp: Opportunity) -> list[S.LeadStateSignalItem]:
    """The classifier's own reasons, as persisted. Never re-derived here."""
    return [
        S.LeadStateSignalItem(
            key=str(row.get("key", "")),
            label=str(row.get("label", "")),
            certainty=str(row.get("certainty", "unknown")),
            source_url=row.get("source_url"),
            detail=row.get("detail"),
        )
        for row in (opp.lead_state_signals or [])
        if row.get("key") and row.get("label")
    ]


def direction_items(claims: list[directions.DirectionClaim]) -> list[S.DirectionClaimItem]:
    """Directions paired with the recent items that support them.

    Computed rather than stored: :mod:`app.services.directions` reads
    ``faculty.evidence``, which every caller has already loaded, so this costs
    no extra query and cannot disagree with the evidence timeline beside it.
    """
    return [
        S.DirectionClaimItem(
            direction=claim.direction,
            certainty=claim.certainty.value,
            evidence=[
                S.DirectionEvidenceItem(
                    id=support.evidence.id,
                    year=support.evidence.year,
                    kind=support.evidence.kind.value,
                    title=support.evidence.title,
                    url=support.evidence.url,
                    why=support.why,
                )
                for support in claim.evidence
            ],
        )
        for claim in claims
    ]


def why_now_item(
    faculty: Faculty, today: date, claims: list[directions.DirectionClaim]
) -> S.WhyNowItem | None:
    signal = directions.why_now(faculty, today=today, claims=claims)
    if signal is None:
        return None
    return S.WhyNowItem(
        statement=signal.statement,
        evidence_ids=[e.id for e in signal.evidence],
        certainty=signal.certainty.value,
    )


def research_context(
    db: Session,
    opp: Opportunity,
    profile: StudentProfile | None,
    *,
    today: date | None = None,
) -> S.ResearchContext | None:
    faculty = opp.faculty
    if faculty is None:
        return None
    state = lead_state_for(opp)
    statement, statement_url = _opening_statement(faculty)
    day = today or datetime.now(UTC).date()
    claims = directions.direction_claims(faculty, today=day)
    return S.ResearchContext(
        faculty=faculty_ref(faculty),
        lab=lab_ref(opp.lab or (faculty.labs[0] if faculty.labs else None)),
        lead_state=state.value,
        lead_state_signals=lead_state_signals(opp),
        directions=direction_items(claims),
        why_now=why_now_item(faculty, day, claims),
        evidence=[evidence_item(e) for e in faculty.evidence][:15],
        signals=[signal_item(s) for s in faculty.signals],
        topics=[
            S.TopicRef(slug=t.topic.slug, label=t.topic.label, weight=t.weight, origin=t.origin)
            for t in faculty.topics
            if t.topic is not None
        ][:12],
        overlap=topic_overlap(faculty, profile),
        fit=fit_breakdown(
            db,
            faculty,
            profile,
            opportunity=opp,
            match=_match_for(opp, profile.id if profile else None),
        ),
        suggested_next_step=_next_step(state, faculty),
        opening_statement=statement if state == LeadState.OPENING else None,
        opening_source_url=statement_url if state == LeadState.OPENING else None,
    )


def resume_recommendations(
    db: Session, opportunity_id: uuid.UUID
) -> list[S.ResumeRecommendationItem]:
    rows = db.scalars(
        select(ResumeRecommendation)
        .where(ResumeRecommendation.opportunity_id == opportunity_id)
        .order_by(ResumeRecommendation.rank)
    ).all()
    out: list[S.ResumeRecommendationItem] = []
    for row in rows:
        resume = db.get(Resume, row.resume_id)
        out.append(
            S.ResumeRecommendationItem(
                resume_id=row.resume_id,
                resume_label=resume.label if resume else "(deleted resume)",
                score=row.score,
                rank=row.rank,
                matched_strengths=list(row.matched_strengths or []),
                weak_or_missing=list(row.weak_or_missing or []),
                emphasize=list(row.emphasize or []),
                rationale=row.rationale,
            )
        )
    return out


def extracted_fields(db: Session, opportunity_id: uuid.UUID) -> dict[str, S.EvidencedField]:
    rows = db.scalars(
        select(ExtractedField).where(ExtractedField.opportunity_id == opportunity_id)
    ).all()
    return {
        row.field: S.EvidencedField(
            value=(row.value or {}).get("value"),
            confidence=row.confidence,
            certainty=row.certainty.value,
            method=row.method.value,
            source_text=row.source_text,
            source_url=row.source_url,
        )
        for row in rows
    }


def readiness_out(readiness: Readiness) -> S.ApplicationReadiness:
    """The readiness dataclass as the one shape both screens render."""
    link = readiness.link
    return S.ApplicationReadiness(
        ready=readiness.ready,
        cta=readiness.cta,
        cta_action=readiness.cta_action,
        items=[
            S.ReadinessItem(
                key=row.key,
                label=row.label,
                state=row.state.value,
                detail=row.detail,
                note=row.note,
            )
            for row in readiness.rows
        ],
        blocking=list(readiness.blocking),
        application_link=(link.verification.value if link else "not_found"),
        application_link_note=(link.note if link else None),
        application_url=(link.url if link else None),
        has_application=readiness.has_application,
        application_id=readiness.application_id,
    )


def opportunity_detail(
    db: Session,
    opp: Opportunity,
    *,
    today: date,
    profile: StudentProfile | None,
    application: Application | None = None,
    has_reminder: bool = False,
    feedback: OpportunityFeedback | None = None,
) -> S.OpportunityDetail:
    profile_id = profile.id if profile else None
    base = opportunity_item(
        opp,
        today=today,
        profile_id=profile_id,
        application=application,
        has_reminder=has_reminder,
        wanted_slugs=interest_slugs(profile),
        profile_for_relevance=profile,
        feedback=feedback,
    )
    match = _match_for(opp, profile_id)
    assessments = {
        a.get("requirement_id"): a for a in (match.requirement_matches or []) if match
    }

    def bucket(kind: RequirementKind):
        return [
            requirement_out(r, assessments.get(str(r.id)))
            for r in sorted(opp.requirements, key=lambda r: r.order_index)
            if r.kind == kind
        ]

    return S.OpportunityDetail(
        **base.model_dump(),
        description=opp.description,
        application_method=opp.application_method,
        application_url=opp.application_url,
        contact_name=opp.contact_name,
        contact_email=opp.contact_email,
        requirements=bucket(RequirementKind.REQUIRED),
        preferred=bucket(RequirementKind.PREFERRED),
        inferred=bucket(RequirementKind.INFERRED),
        documents_required=list(opp.documents_required or []),
        skills=taxonomy.skill_labels(opp.skills or []),
        eligibility_reasons=list(opp.eligibility_reasons or []),
        extraction_confidence=opp.extraction_confidence,
        match=match_detail(match),
        fields=extracted_fields(db, opp.id),
        research=research_context(db, opp, profile),
        resume_recommendations=resume_recommendations(db, opp.id),
        readiness=readiness_out(
            readiness_for(db, opportunity=opp, application=application, today=today)
        ),
        notes=opp.notes,
    )


def research_lead(
    opp: Opportunity, *, today: date, profile: StudentProfile | None
) -> S.ResearchLead | None:
    faculty = opp.faculty
    if faculty is None:
        return None
    match = _match_for(opp, profile.id if profile else None)
    newest = max(faculty.evidence, key=lambda e: (e.year or 0), default=None)
    return S.ResearchLead(
        opportunity_id=opp.id,
        faculty=faculty_ref(faculty),
        lab=lab_ref(opp.lab or (faculty.labs[0] if faculty.labs else None)),
        lead_state=lead_state_for(opp).value,
        fit_score=match.fit_score if match else None,
        fit_confidence=match.confidence if match else None,
        topics=[
            S.TopicRef(slug=t.topic.slug, label=t.topic.label, weight=t.weight, origin=t.origin)
            for t in faculty.topics
            if t.topic is not None
        ][:8],
        overlap=topic_overlap(faculty, profile),
        latest_evidence=evidence_item(newest) if newest else None,
        evidence_count=faculty.evidence_count,
        signals=[signal_item(s) for s in faculty.signals if s.kind == SignalKind.UNDERGRAD_PRESENCE][:3],
        status=opp.status.value,
        deadline=opp.deadline,
        deadline_state=opp.deadline_state.value,
        urgency=urgency_for(opp.deadline, opp.deadline_type, today),
    )


def resume_item(db: Session, resume: Resume) -> E.ResumeItem:
    return E.ResumeItem(
        id=resume.id,
        label=resume.label,
        original_filename=resume.original_filename,
        size_bytes=resume.size_bytes,
        page_count=resume.page_count,
        is_default=resume.is_default,
        parse_status=resume.parse_status,
        parse_error=resume.parse_error,
        detected_skills=taxonomy.skill_labels(resume.detected_skills or []),
        detected_topics=[taxonomy.topic_label(t) for t in (resume.detected_topics or [])],
        highlight_count=len(resume.highlights),
        created_at=resume.created_at,
    )


def profile_out(db: Session, profile: StudentProfile) -> E.StudentProfileOut:
    resume_count = db.scalar(select(func.count(Resume.id))) or 0
    return E.StudentProfileOut(
        id=profile.id,
        user_id=profile.user_id,
        email=profile.user.email if profile.user else "",
        display_name=profile.user.display_name if profile.user else None,
        university=profile.university,
        campus=profile.campus,
        major=profile.major,
        secondary_major=profile.secondary_major,
        degree=profile.degree,
        graduation_year=profile.graduation_year,
        gpa=profile.gpa,
        gpa_is_public=profile.gpa_is_public,
        work_authorization=profile.work_authorization.value,
        work_authorization_note=profile.work_authorization_note,
        hours_per_week_min=profile.hours_per_week_min,
        hours_per_week_max=profile.hours_per_week_max,
        preferred_job_types=list(profile.preferred_job_types or []),
        preferred_locations=list(profile.preferred_locations or []),
        keywords=list(profile.keywords or []),
        availability_note=profile.availability_note,
        preferences=dict(profile.preferences or {}),
        onboarding_completed_at=profile.onboarding_completed_at,
        skills=[
            E.ProfileSkillItem(
                id=ps.id,
                slug=ps.skill.slug,
                label=ps.skill.label,
                category=ps.skill.category,
                origin=ps.origin,
                proficiency=ps.proficiency,
                evidence=ps.evidence,
            )
            for ps in profile.skills
            if ps.skill is not None
        ],
        interests=[
            E.ProfileInterestItem(
                id=i.id,
                label=i.label,
                topic_slug=i.topic.slug if i.topic else None,
                weight=i.weight,
                note=i.note,
            )
            for i in profile.interests
        ],
        coursework=[
            E.CourseworkItem(
                id=c.id,
                code=c.code,
                title=c.title,
                term=c.term,
                grade=c.grade,
                topics=list(c.topics or []),
            )
            for c in profile.coursework
        ],
        experiences=[
            E.ExperienceItem(
                id=x.id,
                organization=x.organization,
                role=x.role,
                kind=x.kind,
                started_on=x.started_on,
                ended_on=x.ended_on,
                summary=x.summary,
                highlights=list(x.highlights or []),
                skills=list(x.skills or []),
                origin=x.origin,
            )
            for x in profile.experiences
        ],
        resume_count=resume_count,
    )


def run_summary(run: SearchRun) -> E.SearchRunSummary:
    return E.SearchRunSummary(
        id=run.id,
        kind=run.kind.value,
        status=run.status.value,
        trigger=run.trigger,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_count=run.created_count,
        updated_count=run.updated_count,
        unchanged_count=run.unchanged_count,
        expired_count=run.expired_count,
        held_count=run.held_count,
        skipped_count=run.skipped_count,
        suppressed_count=run.suppressed_count,
        documents_fetched=run.documents_fetched,
        sources_attempted=list(run.sources_attempted or []),
        error=run.error,
        steps=list(run.steps or []),
    )


def reminder_item(r: Reminder) -> E.ReminderItem:
    return E.ReminderItem(
        id=r.id,
        title=r.title,
        due_on=r.due_on,
        offsets_days=list(r.offsets_days or []),
        provider=r.provider.value,
        status=r.status.value,
        opportunity_id=r.opportunity_id,
        url=r.url,
        documents=list(r.documents or []),
        notes=r.notes,
    )


def certainty_of(value: float, has_source: bool) -> Certainty:
    if value >= 0.85 and has_source:
        return Certainty.VERIFIED
    if value >= 0.6:
        return Certainty.LIKELY
    if value > 0:
        return Certainty.INFERRED
    return Certainty.UNKNOWN


def outreach_citation(item: outreach_service.Citation) -> S.OutreachCitationItem:
    return S.OutreachCitationItem(
        label=item.label,
        detail=item.detail,
        source_url=item.source_url,
        side=item.side,
    )


def outreach_draft(draft: outreach_service.OutreachDraft) -> S.OutreachDraftOut:
    return S.OutreachDraftOut(
        subject=draft.subject,
        body=draft.body,
        word_count=draft.word_count,
        research_citations=[outreach_citation(c) for c in draft.research_citations],
        student_citations=[outreach_citation(c) for c in draft.student_citations],
        refusal=draft.refusal,
        todos=list(draft.todos),
    )
