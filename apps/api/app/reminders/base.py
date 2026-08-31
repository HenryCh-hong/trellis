"""Reminder provider abstraction.

The MVP ships two providers that need no account and no cloud round trip:
an ``.ics`` file with alarms, and an Apple Shortcuts payload.  Offsets are
data, never literals, so "7/3/1 days before" can become user-configurable
without touching a provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(slots=True)
class ReminderPayload:
    """Everything a reminder should carry (spec §9)."""

    title: str
    due_on: date | None
    due_at: datetime | None = None
    url: str | None = None
    application_url: str | None = None
    documents: list[str] = field(default_factory=list)
    notes: str | None = None
    offsets_days: list[int] = field(default_factory=list)
    opportunity_id: str | None = None

    def body(self) -> str:
        parts: list[str] = []
        if self.due_on:
            parts.append(f"Deadline: {self.due_on.isoformat()}")
        if self.application_url:
            parts.append(f"Apply: {self.application_url}")
        elif self.url:
            parts.append(f"Details: {self.url}")
        if self.documents:
            parts.append("Required: " + ", ".join(self.documents))
        if self.notes:
            parts.append(self.notes)
        return "\n".join(parts)


@dataclass(slots=True)
class ReminderExport:
    provider: str
    content_type: str
    filename: str | None = None
    body: str | None = None
    payload: dict | None = None
    instructions: str | None = None
    external_id: str | None = None


class ReminderProvider(ABC):
    slug: str = "none"
    label: str = "None"
    description: str = ""
    # True when the export needs the user to complete a step outside the app.
    requires_user_action: bool = True

    @abstractmethod
    def export(self, payload: ReminderPayload) -> ReminderExport: ...
