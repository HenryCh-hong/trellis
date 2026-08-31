"""Agent contracts.

Composition over one big autonomous loop (spec §20).  Each agent is a small,
separately testable unit with a typed input and a typed output.  Deterministic
work (scoring, date arithmetic, dedup, eligibility rules) is plain Python;
the LLM is used only where reading unstructured prose actually helps.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.llm.base import LLMProvider
from app.llm.factory import get_llm
from app.models.enums import RunStatus


@dataclass(slots=True)
class AgentContext:
    """Everything an agent may touch. Passing this explicitly keeps agents
    testable and stops them reaching for globals."""

    db: Session
    llm: LLMProvider = field(default_factory=get_llm)
    today: date = field(default_factory=lambda: datetime.now(UTC).date())
    search_run_id: Any = None
    profile_id: Any = None
    dry_run: bool = False

    @property
    def can_reason(self) -> bool:
        return self.llm.is_reasoning_capable


@dataclass(slots=True)
class AgentOutcome[O]:
    result: O
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Agent[I, O](ABC):
    """One capability. Name is recorded on every AgentRun row."""

    name: str = "agent"
    description: str = ""

    @abstractmethod
    def run(self, ctx: AgentContext, payload: I) -> AgentOutcome[O]: ...

    @contextmanager
    def _record(self, ctx: AgentContext, subject_type: str | None = None, subject_id: Any = None):
        """Log the invocation without ever capturing user form answers."""
        from app.models.ops import AgentRun

        started = time.perf_counter()
        run = AgentRun(
            agent=self.name,
            search_run_id=ctx.search_run_id,
            subject_type=subject_type,
            subject_id=subject_id,
            provider=ctx.llm.name,
            status=RunStatus.RUNNING,
        )
        try:
            yield run
            run.status = RunStatus.SUCCEEDED
        except Exception as exc:
            run.status = RunStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"[:2000]
            raise
        finally:
            run.latency_ms = int((time.perf_counter() - started) * 1000)
            if not ctx.dry_run:
                ctx.db.add(run)
