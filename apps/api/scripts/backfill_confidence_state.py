"""Add the confidence gate's columns and judge every row already in the table.

Discovery ran before the gate existed, so every opportunity currently sits at
the default ``ok``.  This applies :func:`app.services.confidence.assess_row` to
each of them and reports — or writes — what the gate would say.

Report first, always.  The threshold was chosen against this exact corpus and
the expected answer is *zero held*: everything in the database today came from
the verified Stanford harvest or from a live source that extracts cleanly.  If
this script wants to hold real rows, the threshold is wrong, not the data.

    .venv/bin/python -m scripts.backfill_confidence_state          # report only
    .venv/bin/python -m scripts.backfill_confidence_state --apply  # write it
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.db.session import engine, session_scope
from app.models import Base
from app.models.enums import ConfidenceState
from app.models.opportunity import Opportunity
from app.models.ops import SearchRun
from app.services.confidence import assess_row

DDL = """
ALTER TABLE opportunities
    ADD COLUMN IF NOT EXISTS confidence_state VARCHAR(4) NOT NULL DEFAULT 'ok';
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS confidence_reason TEXT;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS confidence_state_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS ix_opportunities_confidence_state
    ON opportunities (confidence_state);
ALTER TABLE search_runs ADD COLUMN IF NOT EXISTS expired_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE search_runs ADD COLUMN IF NOT EXISTS held_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE search_runs ADD COLUMN IF NOT EXISTS suppressed_count INTEGER NOT NULL DEFAULT 0;
"""

CHECK = """
DO $$ BEGIN
    ALTER TABLE opportunities ADD CONSTRAINT confidence_state
        CHECK (confidence_state IN ('ok', 'held'));
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
    now = datetime.now(UTC)
    counts: Counter[str] = Counter()
    held: list[tuple[str, str]] = []
    promoted: list[str] = []

    with session_scope() as db:
        for opp in db.scalars(select(Opportunity).order_by(Opportunity.title)):
            verdict = assess_row(opp)
            counts[verdict.state] += 1
            state = ConfidenceState.HELD if verdict.hold else ConfidenceState.OK
            if verdict.hold:
                held.append((opp.title, verdict.reason))
            elif opp.confidence_state == ConfidenceState.HELD:
                promoted.append(opp.title)
            if not apply or opp.confidence_state == state:
                continue
            opp.confidence_state = state
            opp.confidence_reason = verdict.reason if verdict.hold else None
            opp.confidence_state_at = now

        run_count = db.scalar(select(SearchRun.id).limit(1))
        if not apply:
            db.rollback()

    total = sum(counts.values())
    print(f"{total} opportunities judged by the confidence gate\n")
    print(f"  ok    {counts['ok']}")
    print(f"  held  {counts['held']}")
    if held:
        print("\nwould be held:")
        for title, reason in held:
            print(f"  - {title[:60]:62s} {reason[:70]}")
    if promoted:
        print(f"\nwould be promoted back: {len(promoted)}")
        for title in promoted:
            print(f"  - {title[:60]}")
    if run_count is None:
        print("\n(no search runs recorded yet)")
    if not apply:
        print("\n(report only — pass --apply to write it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(apply="--apply" in sys.argv))
