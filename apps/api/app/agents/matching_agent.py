"""Matching — turns the scoring engine into a persisted, explainable match.

Picks the scoring model from the opportunity type, runs the resume ranking, and
writes one ``opportunity_matches`` row per (opportunity, profile).  Idempotent:
re-running replaces the row rather than accumulating history, because the score
is a current opinion, not an event.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select

from app.agents.base import Agent, AgentContext, AgentOutcome
from app.agents.eligibility_agent import EligibilityAgent, EligibilityRequest
from app.agents.resume_agent import ResumeMatchingAgent, ResumeMatchRequest
from app.llm.base import LLMUnavailable
from app.models.application import ResumeRecommendation
from app.models.enums import OpportunityType
from app.models.opportunity import Opportunity, OpportunityMatch
from app.models.resume import Resume
from app.services.scoring import ScoreResult, score_job, score_research

RESEARCH_TYPES = (OpportunityType.RESEARCH_OPENING, OpportunityType.RESEARCH_OUTREACH)


@dataclass(slots=True)
class MatchRequest:
    profile: object
    opportunity: Opportunity
    resumes: list[Resume] | None = None
    polish: bool = True


@dataclass(slots=True)
class MatchResult:
    score: ScoreResult
    match: OpportunityMatch | None
    recommended_resume_id: uuid.UUID | None


class MatchingAgent(Agent[MatchRequest, MatchResult]):
    name = "matching"
    description = "Scores one opportunity against the student and explains the number."

    def __init__(self) -> None:
        self._resume_agent = ResumeMatchingAgent()
        self._eligibility = EligibilityAgent()

    def run(self, ctx: AgentContext, payload: MatchRequest) -> AgentOutcome[MatchResult]:
        opp = payload.opportunity
        notes: list[str] = []
        warnings: list[str] = []

        elig = self._eligibility.run(ctx, EligibilityRequest(payload.profile, opp)).result

        if opp.type in RESEARCH_TYPES:
            faculty = opp.faculty
            score = score_research(
                payload.profile,
                opp,
                faculty=faculty,
                evidence=list(faculty.evidence) if faculty else [],
                signals=list(faculty.signals) if faculty else [],
                ctx=ctx,
                assessments=elig.assessments,
                eligibility=(elig.state, elig.reasons),
            )
        else:
            score = score_job(
                payload.profile,
                opp,
                ctx=ctx,
                assessments=elig.assessments,
                eligibility=(elig.state, elig.reasons),
            )

        resumes = payload.resumes
        if resumes is None:
            resumes = list(ctx.db.scalars(select(Resume).order_by(Resume.created_at)))

        recommended_id: uuid.UUID | None = None
        rationale: dict = {}
        if resumes:
            outcome = self._resume_agent.run(ctx, ResumeMatchRequest(opp, resumes))
            fit_result = outcome.result
            warnings.extend(outcome.warnings)
            best = fit_result.best
            recommended_id = best.resume_id if best else None
            rationale = fit_result.rationale_payload()
            if not ctx.dry_run and opp.id is not None:
                ctx.db.execute(
                    delete(ResumeRecommendation).where(
                        ResumeRecommendation.opportunity_id == opp.id
                    )
                )
                for row in fit_result.rows:
                    ctx.db.add(row)
        else:
            notes.append("No resumes uploaded yet, so no resume recommendation was made.")

        if payload.polish and ctx.can_reason:
            try:
                self._polish(ctx, score, opp)
            except LLMUnavailable as exc:
                warnings.append(f"Explanation left in its deterministic form ({exc}).")

        match: OpportunityMatch | None = None
        if not ctx.dry_run and opp.id is not None and getattr(payload.profile, "id", None):
            match = self._persist(ctx, payload, opp, score, recommended_id, rationale)

        return AgentOutcome(
            result=MatchResult(score=score, match=match, recommended_resume_id=recommended_id),
            notes=notes,
            warnings=warnings,
        )

    # ------------------------------------------------------------------ #

    def _persist(
        self,
        ctx: AgentContext,
        payload: MatchRequest,
        opp: Opportunity,
        score: ScoreResult,
        recommended_id: uuid.UUID | None,
        rationale: dict,
    ) -> OpportunityMatch:
        profile_id = payload.profile.id
        match = ctx.db.scalars(
            select(OpportunityMatch).where(
                OpportunityMatch.opportunity_id == opp.id,
                OpportunityMatch.profile_id == profile_id,
            )
        ).first()
        if match is None:
            match = OpportunityMatch(opportunity_id=opp.id, profile_id=profile_id)
            ctx.db.add(match)

        match.fit_score = round(score.fit_score, 2)
        match.confidence = round(score.confidence, 4)
        match.model = score.model
        match.breakdown = score.breakdown()
        match.strengths = list(score.strengths)
        match.gaps = list(score.gaps)
        match.explanation = score.explanation
        match.why_interesting = score.why_interesting
        match.recommendation = score.recommendation.value
        match.requirement_matches = score.requirement_rows()
        match.recommended_resume_id = recommended_id
        match.resume_rationale = rationale
        match.computed_at = datetime.now(UTC)
        return match

    def _polish(self, ctx: AgentContext, score: ScoreResult, opp: Opportunity) -> None:
        """The model may only re-word the deterministic explanation.

        It is never allowed to change the score, the strengths or the gaps —
        those are computed, auditable, and shown alongside the prose.
        """
        from pydantic import BaseModel, Field

        class _Explanation(BaseModel):
            explanation: str = Field(max_length=700)

        system = (
            "You rewrite one short explanation of why an opportunity fits a student. "
            "Re-word only the facts given. Never add a skill, course, experience or "
            "claim that is not in the input. Never promote a preferred qualification "
            "to a requirement. Two to four sentences, plain and specific."
        )
        prompt = (
            f"Opportunity: {opp.title}\n"
            f"Fit: {round(score.fit_score)}%\n"
            f"Strengths: {'; '.join(score.strengths) or 'none identified'}\n"
            f"Gaps: {'; '.join(score.gaps) or 'none identified'}\n"
            f"Draft: {score.explanation}"
        )
        result = ctx.llm.complete_json(
            system=system, prompt=prompt, schema=_Explanation, task="match-explanation"
        )
        text = " ".join(result.data.explanation.split())
        if text:
            score.explanation = text
