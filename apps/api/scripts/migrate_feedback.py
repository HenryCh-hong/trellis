"""Create ``opportunity_feedback`` on a running database.

Idempotent, and safe against a database that already has it: every statement is
``IF NOT EXISTS`` or a drop-then-add of a named constraint.  There is nothing to
backfill — an absent row means "you have said nothing", which is exactly what
every existing opportunity should mean.

    .venv/bin/python -m scripts.migrate_feedback
"""

from __future__ import annotations

from sqlalchemy import text

from app.db.session import engine
from app.models import Base
from app.models.enums import FeedbackReason, FeedbackSignal

STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS opportunity_feedback (
        id UUID PRIMARY KEY,
        opportunity_id UUID NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
        profile_id UUID NOT NULL REFERENCES student_profiles(id) ON DELETE CASCADE,
        signal VARCHAR NOT NULL,
        reason VARCHAR,
        note TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_feedback_opportunity_profile
        ON opportunity_feedback (opportunity_id, profile_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_opportunity_feedback_opportunity_id
        ON opportunity_feedback (opportunity_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_opportunity_feedback_profile_id
        ON opportunity_feedback (profile_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_opportunity_feedback_signal
        ON opportunity_feedback (signal)
    """,
)


def _values(enum_cls: type) -> str:
    return ", ".join(f"'{m.value}'" for m in enum_cls)


CONSTRAINTS = (
    ("feedback_signal", f"signal IN ({_values(FeedbackSignal)})"),
    ("feedback_reason", f"reason IS NULL OR reason IN ({_values(FeedbackReason)})"),
    # The rule the whole feature rests on: a reason is a fact about one
    # "not relevant", and it may not be attached to anything else.
    ("ck_opportunity_feedback_reason_only_for_not_relevant",
     "reason IS NULL OR signal = 'not_relevant'"),
)


def main() -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for statement in STATEMENTS:
            conn.execute(text(statement))
        for name, check in CONSTRAINTS:
            conn.execute(
                text(
                    f"ALTER TABLE opportunity_feedback DROP CONSTRAINT IF EXISTS {name}; "
                    f"ALTER TABLE opportunity_feedback ADD CONSTRAINT {name} CHECK ({check})"
                )
            )
        rows = conn.execute(text("SELECT count(*) FROM opportunity_feedback")).scalar_one()
    print(f"opportunity_feedback present; {rows} signal(s) recorded")


if __name__ == "__main__":
    main()
