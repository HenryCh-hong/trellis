"""Collapse duplicate source rows onto their registered adapter.

The harvest loader created a source row per page it read, named from the page
title. Several of those are the same source an adapter already owns, so Settings
listed both — "Stanford Careers (careersearch.stanford.edu)" next to
"Stanford Careers (careersearch.stanford.edu) - Oracle HCM Candidate
Experience". The adapter row is canonical because it is the one a future run
writes to.

    python -m scripts.merge_duplicate_sources          # report
    python -m scripts.merge_duplicate_sources --apply
"""

from __future__ import annotations

import sys

from sqlalchemy import select, update

from app.db.session import session_scope
from app.models.opportunity import Opportunity, OpportunitySource
from app.sources.registry import SOURCE_ADAPTERS

# harvest slug -> canonical adapter slug
MERGES: dict[str, str] = {
    "stanford-careers-careersearch-stanford-edu-oracle-hcm-candidate-experience": "stanford_careersearch",
    "harvest-research-programs": "stanford_programs",
    "handshake-stanford-career-education-the-official-student-job-board": "handshake",
    "the-hub-lathrop-learning-technologies-spaces-student-affairs-student-jobs": "stanford_student_jobs",
    "harvest-faculty-pages": "stanford_cs_faculty",
}


def main() -> int:
    apply = "--apply" in sys.argv
    with session_scope() as db:
        by_slug = {s.slug: s for s in db.scalars(select(OpportunitySource))}
        moved = 0
        for dup_slug, canon_slug in MERGES.items():
            dup, canon = by_slug.get(dup_slug), by_slug.get(canon_slug)
            if dup is None or canon is None:
                continue
            n = db.scalar(
                select(Opportunity.id).where(Opportunity.source_id == dup.id).limit(1)
            )
            count = len(list(db.scalars(select(Opportunity.id).where(Opportunity.source_id == dup.id))))
            print(f"  {dup_slug}\n    -> {canon_slug}  ({count} opportunities to re-point)")
            if apply:
                # Keep the harvest row's honest note if the adapter has none.
                if dup.notes and not canon.notes:
                    canon.notes = dup.notes
                db.execute(
                    update(Opportunity)
                    .where(Opportunity.source_id == dup.id)
                    .values(source_id=canon.id)
                )
                db.delete(dup)
                moved += count
            void = n
            del void

        # Rows that feed nothing are NOT deleted. Several of them are honest
        # negative provenance — "Stanford Libraries: no public student-jobs page
        # found", "Cardinal at Work: zero listings" — and that is exactly the
        # kind of thing the product should keep showing. They are grouped in the
        # Settings UI instead of being removed from the record.
        quiet = []
        for source in db.scalars(select(OpportunitySource)):
            if source.slug in SOURCE_ADAPTERS:
                continue
            attached = db.scalar(
                select(Opportunity.id).where(Opportunity.source_id == source.id).limit(1)
            )
            if attached is None:
                quiet.append(source.slug)
        print(f"\n  {len(quiet)} source rows currently feed nothing (kept as provenance):")
        for slug in quiet:
            print(f"    - {slug}")

        if not apply:
            print("\n(report only — pass --apply)")
            return 0
        print(f"\nmerged {moved} opportunities onto their adapter rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
