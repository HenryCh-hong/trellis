"""Re-run lead classification over every faculty record already in the database.

Adds the ``lead_state`` / ``lead_state_signals`` columns if they are missing
(idempotent), then re-derives the state for each faculty lead and prints the
resulting distribution.  Nothing here fetches the network: it re-reads the
evidence and signals that are already stored, so it is safe to run repeatedly.

    .venv/bin/python -m scripts.reclassify_leads [--dry-run]
"""

from __future__ import annotations

import sys
from collections import Counter

from sqlalchemy import select, text

from app.agents.base import AgentContext
from app.agents.research_agent import ResearchDiscoveryAgent
from app.core.config import get_settings
from app.db.session import engine, session_scope
from app.models import Base
from app.models.enums import LeadState, OpportunityType
from app.models.opportunity import Opportunity
from app.models.research import Faculty

DDL = """
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS lead_state VARCHAR(8);
ALTER TABLE opportunities
    ADD COLUMN IF NOT EXISTS lead_state_signals JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS lead_state_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS ix_opportunities_lead_state ON opportunities (lead_state);
"""

CHECK = """
DO $$ BEGIN
    ALTER TABLE opportunities ADD CONSTRAINT lead_state
        CHECK (lead_state IN ('opening', 'outreach', 'watch', 'unknown'));
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


def main(dry_run: bool = False) -> int:
    migrate()
    settings = get_settings()
    agent = ResearchDiscoveryAgent()
    counts: Counter[str] = Counter()
    rows: list[tuple[str, str, int]] = []

    with session_scope() as db:
        ctx = AgentContext(db=db)
        faculty_rows = list(db.scalars(select(Faculty).order_by(Faculty.name)))
        for faculty in faculty_rows:
            evidence = sorted(faculty.evidence, key=lambda e: (e.year or 0), reverse=True)
            state, signals = agent._classify(faculty, evidence, ctx, settings)
            counts[state.value] += 1
            rows.append((faculty.name, state.value, len(signals)))
            opp = db.scalars(
                select(Opportunity).where(Opportunity.faculty_id == faculty.id)
            ).first()
            if opp is None or dry_run:
                continue
            opp.lead_state = state
            opp.lead_state_signals = [s.as_dict() for s in signals]
            opp.type = (
                OpportunityType.RESEARCH_OPENING
                if state == LeadState.OPENING
                else OpportunityType.RESEARCH_OUTREACH
            )
        if dry_run:
            db.rollback()

    width = max(len(name) for name, _, _ in rows)
    for name, state, n in rows:
        print(f"{name:<{width}}  {state:<8}  {n} signal(s)")
    print("\n--- distribution ---")
    for state in ("opening", "outreach", "watch", "unknown"):
        print(f"{state:<9} {counts.get(state, 0)}")
    print(f"{'total':<9} {sum(counts.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(dry_run="--dry-run" in sys.argv))
