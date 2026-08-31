"""Add the deadline-lifecycle and source-status columns to a running database.

Idempotent, and safe to run against a database that already has them: every
statement is ``IF NOT EXISTS``.  The backfill deliberately does NOT write
``expired`` — it seeds the live state and lets ``sweep_expired`` make the
transition, so every lapsed deadline gets a change-log entry the student can
actually see instead of appearing to have always been expired.

    .venv/bin/python -m scripts.migrate_lifecycle
"""

from __future__ import annotations

from sqlalchemy import text

from app.db.session import engine
from app.models import Base

STATEMENTS = (
    """
    ALTER TABLE opportunities
        ADD COLUMN IF NOT EXISTS deadline_state VARCHAR NOT NULL DEFAULT 'unknown'
    """,
    """
    ALTER TABLE opportunities
        ADD COLUMN IF NOT EXISTS source_status VARCHAR NOT NULL DEFAULT 'live'
    """,
    """
    ALTER TABLE opportunities
        ADD COLUMN IF NOT EXISTS source_status_at TIMESTAMPTZ
    """,
    "CREATE INDEX IF NOT EXISTS ix_opportunities_deadline_state ON opportunities (deadline_state)",
    "CREATE INDEX IF NOT EXISTS ix_opportunities_source_status ON opportunities (source_status)",
)

CHECKS = (
    ("deadline_state", ("hard", "rolling", "unknown", "expired")),
    ("source_status", ("live", "gone")),
)

# Seeds the state every row would have had if the column had always existed.
# 'expired' is left to the sweep on purpose (see the module docstring).
BACKFILL = """
    UPDATE opportunities
       SET deadline_state = CASE
             WHEN deadline IS NOT NULL THEN 'hard'
             WHEN deadline_type = 'rolling' THEN 'rolling'
             ELSE 'unknown'
           END
     WHERE deadline_state = 'unknown'
"""


def main() -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for statement in STATEMENTS:
            conn.execute(text(statement))
        for column, values in CHECKS:
            allowed = ", ".join(f"'{v}'" for v in values)
            conn.execute(
                text(
                    f"ALTER TABLE opportunities DROP CONSTRAINT IF EXISTS {column}; "
                    f"ALTER TABLE opportunities ADD CONSTRAINT {column} "
                    f"CHECK ({column} IN ({allowed}))"
                )
            )
        seeded = conn.execute(text(BACKFILL)).rowcount
    print(f"lifecycle columns present; {seeded} row(s) seeded with a live deadline state")


if __name__ == "__main__":
    main()
