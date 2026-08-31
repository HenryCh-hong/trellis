"""Apple Reminders, via a Shortcut the student installs once.

We do not claim to write into Apple Reminders directly: there is no sanctioned
way for a local web app to do that without the student granting an automation
some access. Instead we emit exactly the payload an Apple Shortcut consumes,
plus the recipe for building it. The student stays in control of the grant.
"""

from __future__ import annotations

from app.reminders.base import ReminderExport, ReminderPayload, ReminderProvider

SHORTCUT_RECIPE = [
    "In Shortcuts, create a new shortcut named “Add Trellis Reminder”.",
    "Add “Get Contents of URL” pointed at your Trellis reminder endpoint (the popup shows the URL).",
    "Add “Get Dictionary from Input”, then “Repeat with Each” over the `reminders` key.",
    "Inside the loop add “Add New Reminder”: Title = `title`, Notes = `notes`, "
    "Due Date = `due_on`, List = your choice.",
    "For each value in `alert_offsets_days`, add an alert that many days before the due date.",
    "Run the shortcut whenever you want to sync; nothing is sent anywhere else.",
]


class AppleShortcutsReminderProvider(ReminderProvider):
    slug = "apple_shortcuts"
    label = "Apple Reminders (via Shortcuts)"
    description = (
        "Produces a payload an Apple Shortcut can turn into Reminders with alerts. "
        "One-time setup; Trellis never touches your Reminders directly."
    )
    requires_user_action = True

    def export(self, payload: ReminderPayload) -> ReminderExport:
        data = {
            "version": 1,
            "reminders": [
                {
                    "title": payload.title,
                    "notes": payload.body(),
                    "due_on": payload.due_on.isoformat() if payload.due_on else None,
                    "url": payload.application_url or payload.url,
                    "documents": list(payload.documents),
                    "alert_offsets_days": list(payload.offsets_days),
                }
            ],
        }
        return ReminderExport(
            provider=self.slug,
            content_type="application/json",
            payload=data,
            instructions=(
                "Install the “Add Trellis Reminder” shortcut once, then run it to add this "
                "reminder with its alerts."
            ),
        )

    @property
    def recipe(self) -> list[str]:
        return list(SHORTCUT_RECIPE)


class NoopReminderProvider(ReminderProvider):
    slug = "none"
    label = "Track in Trellis only"
    description = "Keeps the deadline on the dashboard without exporting it anywhere."
    requires_user_action = False

    def export(self, payload: ReminderPayload) -> ReminderExport:
        return ReminderExport(
            provider=self.slug,
            content_type="application/json",
            payload={"tracked": True, "title": payload.title},
            instructions="This deadline is tracked on your Trellis dashboard.",
        )
