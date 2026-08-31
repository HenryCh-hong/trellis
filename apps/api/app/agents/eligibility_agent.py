"""Eligibility — deterministic, and deliberately cautious.

An unmet REQUIRED qualification pushes toward ineligible; an unmet PREFERRED
one never does.  A requirement we could not interpret is ``unknown``, not
``missing`` — the difference matters, because "we couldn't tell" and "you don't
have it" lead a student to very different decisions.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.base import Agent, AgentContext, AgentOutcome
from app.models.enums import EligibilityState
from app.models.opportunity import Opportunity
from app.services.scoring import (
    ProfileView,
    RequirementAssessment,
    assess_requirements,
    derive_eligibility,
)


@dataclass(slots=True)
class EligibilityRequest:
    profile: object
    opportunity: Opportunity


@dataclass(slots=True)
class EligibilityResult:
    state: EligibilityState
    reasons: list[str]
    assessments: list[RequirementAssessment]

    @property
    def blocking(self) -> list[RequirementAssessment]:
        return [a for a in self.assessments if a.blocking]


class EligibilityAgent(Agent[EligibilityRequest, EligibilityResult]):
    name = "eligibility"
    description = "Checks the student against each stated qualification, keeping required and preferred distinct."

    def run(self, ctx: AgentContext, payload: EligibilityRequest) -> AgentOutcome[EligibilityResult]:
        view = ProfileView.of(payload.profile)
        assessments = assess_requirements(view, payload.opportunity)
        state, reasons = derive_eligibility(assessments, view, payload.opportunity)

        notes: list[str] = []
        unknown = sum(1 for a in assessments if a.state.value == "unknown")
        if unknown:
            notes.append(f"{unknown} qualification(s) could not be judged from the posting text.")

        result = EligibilityResult(state=state, reasons=reasons, assessments=assessments)
        if not ctx.dry_run:
            payload.opportunity.eligibility = state
            payload.opportunity.eligibility_reasons = reasons
        return AgentOutcome(result=result, notes=notes)
