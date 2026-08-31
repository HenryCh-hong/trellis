"""Add the answer category column and the application-link provenance rows.

Two things the readiness summary needs that predate it:

1. ``application_answers.category`` — the four-way classification.  Rows
   created before it existed carry only the old sensitive/not-sensitive bit,
   so every one is re-run through :func:`classify_question`.  If that promotes
   a question to SENSITIVE *and* software had prefilled it, the value is
   cleared: a work-authorisation answer that arrived from the profile is
   exactly what the rule forbids, and leaving it in place would ship it.

2. ``extracted_fields.application_url`` — the provenance that licences the
   word "Verified" on an application link.  Written from the row itself with
   the same rule the harvest loader uses, so a re-load produces the same
   answer.  An opportunity with no such row reads as "Unverified", never as
   verified-by-default.

    .venv/bin/python -m scripts.migrate_application_readiness          # report
    .venv/bin/python -m scripts.migrate_application_readiness --apply  # write
"""

from __future__ import annotations

import sys
from collections import Counter

from sqlalchemy import select, text

from app.db.session import engine, session_scope
from app.models import Base
from app.models.application import ApplicationAnswer
from app.models.enums import AnswerCategory, AnswerSource
from app.models.opportunity import ExtractedField, Opportunity
from app.seed.load_harvest import application_url_provenance
from app.services.applications import classify_question

DDL = """
ALTER TABLE application_answers
    ADD COLUMN IF NOT EXISTS category VARCHAR(18) NOT NULL DEFAULT 'unknown';
"""

CHECK = """
DO $$ BEGIN
    ALTER TABLE application_answers ADD CONSTRAINT answer_category
        CHECK (category IN ('safe_profile_field', 'safe_generative', 'sensitive', 'unknown'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""


def migrate() -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for statement in DDL.strip().split(";\n"):
            if statement.strip():
                conn.execute(text(statement))
        conn.execute(text(CHECK))


def main(apply: bool) -> int:
    migrate()
    counts: Counter[str] = Counter()
    changed: list[str] = []
    cleared: list[str] = []
    links: Counter[str] = Counter()

    with session_scope() as db:
        for answer in db.scalars(select(ApplicationAnswer).order_by(ApplicationAnswer.order_index)):
            kind = classify_question(answer.question)
            counts[kind.category.value] += 1
            if answer.category is not kind.category:
                changed.append(f"{answer.category.value} -> {kind.category.value}: {answer.question}")
            answer.category = kind.category
            answer.is_sensitive = kind.is_sensitive
            answer.sensitive_category = kind.sensitive_category
            if kind.is_sensitive and answer.source is not AnswerSource.USER:
                # Software put a value in a field only the student may fill.
                cleared.append(answer.question)
                answer.answer = None
                answer.source = AnswerSource.USER
                answer.profile_field = None
                answer.needs_user_input = True
                answer.reuse_approved = False
            elif not kind.may_prefill_from_profile and answer.source is AnswerSource.PROFILE:
                answer.needs_user_input = answer.answer is None

        existing = {
            (row.opportunity_id, row.field)
            for row in db.scalars(
                select(ExtractedField).where(ExtractedField.field == "application_url")
            )
        }
        for opp in db.scalars(select(Opportunity).order_by(Opportunity.title)):
            provenance = application_url_provenance(
                opp.application_url, opp.source_url, opp.application_method
            )
            if provenance is None:
                links["not_found"] += 1
                continue
            links[provenance["certainty"].value] += 1
            if (opp.id, "application_url") in existing:
                continue
            db.add(
                ExtractedField(
                    opportunity_id=opp.id,
                    field="application_url",
                    value=provenance["value"],
                    confidence=provenance["confidence"],
                    certainty=provenance["certainty"],
                    method=provenance["method"],
                    source_text=provenance["source_text"],
                    source_url=provenance["source_url"],
                    extractor_version="readiness-1",
                )
            )
        if not apply:
            db.rollback()

    print(f"{sum(counts.values())} application answers classified")
    for category in AnswerCategory:
        print(f"  {category.value:20s} {counts[category.value]}")
    if changed:
        print("\nreclassified:")
        for line in changed:
            print(f"  - {line[:110]}")
    if cleared:
        print("\ncleared (sensitive, but software had filled it in):")
        for question in cleared:
            print(f"  - {question[:100]}")

    print(f"\n{sum(links.values())} opportunities checked for an application link")
    print(f"  verified   {links['verified']}")
    print(f"  inferred   {links['inferred']}   (renders as 'Unverified')")
    print(f"  not found  {links['not_found']}")
    if not apply:
        print("\n(report only — pass --apply to write it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(apply="--apply" in sys.argv))
