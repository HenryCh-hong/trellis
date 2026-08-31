"""Task queue abstraction.

The MVP runs jobs in a bounded thread pool in the API process — enough for one
student's searches, and the entire surface is four methods, so swapping in
Celery/RQ later is a single class.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class TaskHandle:
    id: str
    name: str
    status: str = "queued"
    submitted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "submitted_at": self.submitted_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
        }


class TaskQueue(ABC):
    @abstractmethod
    def enqueue(self, name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> TaskHandle: ...

    @abstractmethod
    def get(self, task_id: str) -> TaskHandle | None: ...

    @abstractmethod
    def list(self, limit: int = 50) -> list[TaskHandle]: ...

    @abstractmethod
    def shutdown(self) -> None: ...


def new_task_id() -> str:
    return uuid.uuid4().hex[:12]
