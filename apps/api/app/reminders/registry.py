from __future__ import annotations

from app.reminders.apple_reminders import AppleRemindersProvider
from app.reminders.apple_shortcuts import AppleShortcutsReminderProvider, NoopReminderProvider
from app.reminders.base import ReminderProvider
from app.reminders.ics import IcsReminderProvider

_PROVIDERS: dict[str, ReminderProvider] = {
    p.slug: p
    for p in (
        AppleRemindersProvider(),
        IcsReminderProvider(),
        AppleShortcutsReminderProvider(),
        NoopReminderProvider(),
    )
}


def get_provider(slug: str) -> ReminderProvider:
    provider = _PROVIDERS.get(slug)
    if provider is None:
        raise KeyError(f"unknown reminder provider {slug!r}")
    return provider


def all_providers() -> list[ReminderProvider]:
    return list(_PROVIDERS.values())
