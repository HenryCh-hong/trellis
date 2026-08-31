"""Apply the relevance gate to rows already in the database.

Discovery ran before the gate existed, so the table holds crawled navigation
pages filed as opportunities. This re-judges every row on its stored evidence
and reports (or removes) the ones that would never be admitted today.

    python -m scripts.prune_non_opportunities          # report only
    python -m scripts.prune_non_opportunities --apply  # delete them
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.db.session import session_scope
from app.models.opportunity import Opportunity
from app.services.relevance import looks_like_opportunity


def main() -> int:
    apply = "--apply" in sys.argv
    with session_scope() as db:
        rows = list(db.scalars(select(Opportunity)))
        doomed = []
        for opp in rows:
            # Faculty-derived research leads are not crawled pages; they are
            # built from a PI record and are exempt from the page-shape test.
            if opp.faculty_id is not None:
                continue
            data = {
                "title": opp.title,
                "deadline": opp.deadline,
                "pay_text": opp.pay_text,
                "pay_min": opp.pay_min,
                "hours_per_week": opp.hours_per_week,
                "contact_email": opp.contact_email,
                "application_method": opp.application_method,
                "application_url": opp.application_url,
                "requirements": [{"text": r.text} for r in opp.requirements],
            }
            verdict = looks_like_opportunity(data, opp.description or "", require_body=False)
            if not verdict.keep:
                doomed.append((opp, verdict.reason))

        print(f"{len(rows)} opportunities; {len(doomed)} fail the relevance gate\n")
        for opp, reason in doomed:
            print(f"  - {opp.title[:64]:66s} {reason[:60]}")

        if not apply:
            print("\n(report only — pass --apply to delete)")
            return 0

        for opp, _ in doomed:
            db.delete(opp)
        print(f"\ndeleted {len(doomed)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
