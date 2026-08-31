"""Application preparation and the assisted-apply safety gate.

The hard rule this module enforces: a sensitive question is never answered,
drafted, or prefilled by software. Not from the profile, not by the model, not
"helpfully" left as a suggestion. The student answers it, every time, unless
they have explicitly chosen to reuse a previous answer.

The permission comes from the stored ``AnswerCategory`` and nowhere else.
Only ``SAFE_PROFILE_FIELD`` is prefilled and only ``SAFE_GENERATIVE`` is
drafted, so a question we did not recognise (``UNKNOWN``) is left for the
student rather than answered on a hunch.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.base import Agent, AgentContext, AgentOutcome
from app.llm.base import LLMUnavailable
from app.models.application import Application, ApplicationAnswer, ApplicationEvent
from app.models.enums import AnswerCategory, AnswerSource, DocumentStatus
from app.models.resume import Resume
from app.services.applications import (
    blocking_reasons,
    classify_question,
    known_profile_fields,
    planned_questions,
    profile_field_value,
)


class _Draft(BaseModel):
    draft: str = Field(max_length=1200)


@dataclass(slots=True)
class PrepRequest:
    application: Application
    profile: Any
    draft_free_text: bool = True


@dataclass(slots=True)
class PrepResult:
    application: Application
    created_answers: int
    drafted: int
    blocking: list[str]


class ApplicationPrepAgent(Agent[PrepRequest, PrepResult]):
    name = "application-prep"
    description = "Builds the question list for an application and prefills only what is safe to prefill."

    def run(self, ctx: AgentContext, payload: PrepRequest) -> AgentOutcome[PrepResult]:
        app = payload.application
        profile = payload.profile
        opp = app.opportunity
        warnings: list[str] = []

        existing = {a.question.strip().lower() for a in app.answers}
        questions = planned_questions(opp)

        created = 0
        drafted = 0
        for index, question in enumerate(questions):
            if question.strip().lower() in existing:
                continue
            kind = classify_question(question)
            answer = ApplicationAnswer(
                application_id=app.id,
                question=question,
                order_index=index,
                category=kind.category,
                is_sensitive=kind.is_sensitive,
                sensitive_category=kind.sensitive_category,
            )
            # Only a SAFE_PROFILE_FIELD is ever filled in by software. SENSITIVE
            # is off limits by law and by policy; UNKNOWN is off limits because
            # we do not know what is being asked, and a guess at an unread
            # question is exactly the kind of fabrication rule 1 forbids.
            value = (
                profile_field_value(profile, kind.profile_field)
                if kind.may_prefill_from_profile and kind.profile_field
                else None
            )
            if value:
                answer.answer = value
                answer.source = AnswerSource.PROFILE
                answer.profile_field = kind.profile_field
                answer.field_key = kind.profile_field
                answer.needs_user_input = False
            else:
                answer.answer = None
                answer.source = AnswerSource.USER
                answer.needs_user_input = True
                answer.reuse_approved = False
            ctx.db.add(answer)
            created += 1

        ctx.db.flush()

        if payload.draft_free_text and ctx.can_reason:
            try:
                drafted = self._draft_free_text(ctx, app, profile)
            except LLMUnavailable as exc:
                warnings.append(f"Free-text drafts skipped ({exc}).")
        elif payload.draft_free_text:
            warnings.append(
                "Running without a model, so open questions were left blank rather than "
                "filled with a template."
            )

        return AgentOutcome(
            result=PrepResult(
                application=app,
                created_answers=created,
                drafted=drafted,
                blocking=blocking_reasons(app, ctx.today),
            ),
            warnings=warnings,
        )

    # ------------------------------------------------------------------ #

    def _draft_free_text(self, ctx: AgentContext, app: Application, profile: Any) -> int:
        """Draft only open-ended, non-sensitive questions, from the student's own material."""
        opp = app.opportunity
        resume = ctx.db.get(Resume, app.resume_id) if app.resume_id else None
        highlights = [h.text for h in (resume.highlights if resume else [])][:12]
        interests = [i.label for i in getattr(profile, "interests", [])]
        skills = [s.skill.label for s in getattr(profile, "skills", []) if s.skill]

        direction = []
        if opp is not None and opp.faculty is not None:
            direction = list(opp.faculty.current_direction or [])

        system = (
            "You draft a short answer for a student's job or research application. "
            "You may use ONLY the facts supplied: their resume lines, listed skills, "
            "listed interests, and the opportunity description. Never claim a skill, "
            "course, project, publication or experience that is not in the input. "
            "Never state a GPA, work authorisation, or any demographic fact. "
            "Write 3-5 sentences in the student's plain first-person voice. "
            "This is a draft the student will edit."
        )

        count = 0
        for answer in app.answers:
            # Only an open, essay-shaped question is drafted. A SENSITIVE one is
            # never drafted, and an UNKNOWN one is not either: we cannot write an
            # answer to a question we have not understood.
            if answer.category is not AnswerCategory.SAFE_GENERATIVE:
                continue
            if answer.answer or not answer.needs_user_input:
                continue
            prompt = json.dumps(
                {
                    "question": answer.question,
                    "opportunity": {
                        "title": opp.title if opp else None,
                        "organization": opp.organization if opp else None,
                        "description": (opp.description or "")[:2500] if opp else None,
                        "lab_current_direction": direction,
                    },
                    "student_resume_lines": highlights,
                    "student_skills": skills[:25],
                    "student_interests": interests[:15],
                },
                ensure_ascii=False,
            )
            result = ctx.llm.complete_json(
                system=system, prompt=prompt, schema=_Draft, task="application-draft"
            )
            text = result.data.draft.strip()
            if text:
                answer.answer = text
                answer.source = AnswerSource.LLM_DRAFT
                # Still needs the student: a draft is not an answer.
                answer.needs_user_input = True
                count += 1
        return count


# --------------------------------------------------------------------------- #
# Submission plan + approval
# --------------------------------------------------------------------------- #


def build_submission_plan(app: Application, profile: Any, today=None) -> dict[str, Any]:
    """Exactly what would be submitted, and what deliberately would not be."""
    opp = app.opportunity
    fields: list[dict[str, Any]] = []
    withheld: list[dict[str, str]] = []
    # An answer that was filled from a profile field IS that profile field. Listing
    # both would show the reviewer the same value twice and overstate what is
    # actually being sent, so answers win and the profile row is skipped.
    answered_profile_keys = {
        a.profile_field for a in app.answers if a.profile_field and a.answer
    }

    for row in known_profile_fields(profile):
        if row["value"] and row["key"] not in answered_profile_keys:
            fields.append(
                {
                    "key": row["key"],
                    "label": row["label"],
                    "value": row["value"],
                    "source": "profile",
                    "is_sensitive": False,
                    "will_submit": True,
                    "note": None,
                }
            )

    for answer in sorted(app.answers, key=lambda a: a.order_index):
        if answer.is_sensitive:
            if answer.answer and answer.reuse_approved:
                fields.append(
                    {
                        "key": answer.field_key or f"answer_{answer.order_index}",
                        "label": answer.question,
                        "value": answer.answer,
                        "source": "user",
                        "is_sensitive": True,
                        "will_submit": True,
                        "note": "You entered this and chose to reuse it.",
                    }
                )
            else:
                withheld.append(
                    {
                        "label": answer.question,
                        "reason": (
                            "Trellis never answers work-authorisation, demographic, disability, "
                            "veteran-status or self-identification questions for you. "
                            "You will fill this in on the site."
                        ),
                    }
                )
            continue
        if answer.answer:
            fields.append(
                {
                    "key": answer.field_key or f"answer_{answer.order_index}",
                    "label": answer.question,
                    "value": answer.answer,
                    "source": "llm_draft" if answer.source == AnswerSource.LLM_DRAFT else (
                        "profile" if answer.source == AnswerSource.PROFILE else "user"
                    ),
                    "is_sensitive": False,
                    "will_submit": True,
                    "note": (
                        "This is a draft — review it before it goes out."
                        if answer.source == AnswerSource.LLM_DRAFT
                        else None
                    ),
                }
            )
        else:
            withheld.append({"label": answer.question, "reason": "You have not answered this yet."})

    attachments = [
        {
            "kind": doc.kind.value,
            "filename": doc.filename or (doc.label if doc.status == DocumentStatus.READY else ""),
            "label": doc.label,
        }
        for doc in app.documents
        if doc.status == DocumentStatus.READY
    ]

    manual_steps = [
        "Trellis opens the application page in your browser — it does not submit anything.",
        "Paste or confirm each field above on the site.",
        "Answer anything listed under Withheld yourself.",
        "Press submit on the site when you are satisfied.",
        "Come back and mark this application as submitted.",
    ]
    requires_user_at = [w["label"] for w in withheld]
    if opp is not None and (opp.application_method or "").lower() == "handshake":
        requires_user_at.insert(0, "Handshake sign-in (SSO and two-step) — you do this yourself.")

    plan: dict[str, Any] = {
        "application_id": str(app.id),
        "target_url": (opp.application_url or opp.source_url) if opp else None,
        "method": opp.application_method if opp else None,
        "fields": fields,
        "attachments": attachments,
        "withheld": withheld,
        "manual_steps": manual_steps,
        "requires_user_at": requires_user_at,
        "blocking": blocking_reasons(app, today),
    }
    plan["payload_hash"] = payload_hash(plan)
    plan["approved"] = (
        app.approved_at is not None and app.approved_payload_hash == plan["payload_hash"]
    )
    return plan


def payload_hash(plan: dict[str, Any]) -> str:
    """Hash of what the student is being shown.

    Excludes the volatile keys so re-rendering the same plan is stable, and
    includes everything that would actually be sent, so any change to a value
    invalidates a prior approval.
    """
    material = {
        "target_url": plan.get("target_url"),
        "method": plan.get("method"),
        "fields": [
            {k: f.get(k) for k in ("key", "label", "value", "source", "will_submit")}
            for f in plan.get("fields", [])
        ],
        "attachments": plan.get("attachments", []),
        "withheld": [w.get("label") for w in plan.get("withheld", [])],
    }
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


class ApprovalError(ValueError):
    """The plan changed since the student reviewed it."""


def approve(db, app: Application, profile: Any, submitted_hash: str, today=None) -> Application:
    plan = build_submission_plan(app, profile, today)
    if plan["payload_hash"] != submitted_hash:
        raise ApprovalError(
            "This application changed since you reviewed it. Re-open the review so you can "
            "see what would be submitted now."
        )
    app.approved_at = datetime.now(UTC)
    app.approved_payload_hash = submitted_hash
    db.add(
        ApplicationEvent(
            application_id=app.id,
            kind="approved",
            actor="user",
            note="Student reviewed and approved the submission payload.",
            payload={"payload_hash": submitted_hash, "field_count": len(plan["fields"])},
        )
    )
    return app


def latest_application(db, opportunity_id) -> Application | None:
    return db.scalars(
        select(Application)
        .where(Application.opportunity_id == opportunity_id)
        .order_by(Application.created_at.desc())
    ).first()
