"""Apple Reminders, for real.

Trellis runs on the student's own machine, so the backend can talk to the
Reminders app directly through AppleScript. That makes this a genuine
integration rather than a page of setup instructions: pressing the button puts
an item in Reminders, with a due date and an alert, and the student sees it on
their phone a moment later through iCloud.

Two honest limits, both surfaced in the UI rather than papered over:

* This only works when the API is running on the same Mac as the Reminders app.
  A hosted deployment cannot do it, and :func:`availability` says so instead of
  failing at the point of use.
* macOS gates Reminders behind a TCC permission prompt. The first call raises a
  a permission error until the student clicks Allow. That is a real manual step
  and is reported as one.

Reminders attaches one alert to a reminder, not several. Rather than silently
dropping the 7/3/1 schedule, one reminder is created per offset, each labelled
with its lead time, which is also what a student actually wants: three nudges.
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.reminders.base import ReminderExport, ReminderPayload, ReminderProvider

LIST_NAME = "Trellis"
ALERT_HOUR = 9
OSASCRIPT_TIMEOUT = 20


class AppleRemindersUnavailable(RuntimeError):
    """Reminders cannot be reached, with a reason fit to show a person."""


@dataclass(slots=True)
class Availability:
    available: bool
    reason: str
    needs_permission: bool = False


def _escape(value: str) -> str:
    """Quote a Python string for AppleScript.

    AppleScript has no escape for a literal newline inside a quoted string, so
    those become concatenated `return` constants. Getting this wrong turns a
    posting title with an apostrophe into a syntax error at the worst moment.
    """
    parts = value.replace("\\", "\\\\").replace('"', '\\"').split("\n")
    # `linefeed`, not `return`: Reminders renders CR-joined text as one run-on
    # line, which turned a tidy note into an unreadable wall.
    return " & linefeed & ".join(f'"{p}"' for p in parts)


def _date_expression(name: str, when: datetime) -> str:
    """Build an AppleScript date by setting its components.

    Parsing a formatted string depends on the user's region settings, and an
    arithmetic construction silently collapsed the alert onto the due date in
    testing. Setting year/month/day/time explicitly is the only form that is
    both locale-independent and verifiably correct.
    """
    return (
        f"set {name} to current date\n"
        f"set year of {name} to {when.year}\n"
        f"set month of {name} to {when.month}\n"
        f"set day of {name} to {when.day}\n"
        f"set time of {name} to ({when.hour} * hours) + ({when.minute} * minutes)\n"
    )


def _run(script: str) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=OSASCRIPT_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AppleRemindersUnavailable("osascript is not available on this machine.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AppleRemindersUnavailable(
            "The Reminders app did not respond. It may be showing a permission prompt."
        ) from exc

    if result.returncode != 0:
        message = (result.stderr or "").strip()
        if "not authorized" in message.lower() or "-1743" in message:
            raise AppleRemindersUnavailable(
                "macOS has not granted Trellis access to Reminders yet. "
                "Approve the prompt, or enable it under System Settings → Privacy & Security → Reminders."
            )
        raise AppleRemindersUnavailable(message or "Reminders returned an unknown error.")
    return result.stdout.strip()


def availability() -> Availability:
    """Can we actually write to Reminders right now?"""
    if platform.system() != "Darwin":
        return Availability(False, "Apple Reminders needs macOS; this API is not running on a Mac.")
    try:
        _run('tell application "Reminders" to return name of default list')
    except AppleRemindersUnavailable as exc:
        return Availability(False, str(exc), needs_permission="access" in str(exc).lower())
    return Availability(True, "Connected to the Reminders app on this Mac.")


def _reminder_script(title: str, body: str, alert_at: datetime) -> str:
    """Set ONLY the alert date.

    Reminders overwrites `remind me date` with `due date` whenever both are
    supplied, which silently collapsed every lead-time alert onto the deadline
    itself — the exact failure a reminder exists to prevent. So the alert is the
    only date set, and the deadline is carried in the title and the note.

    Two other traps, both learned the hard way: date components must be set
    OUTSIDE the tell block (inside it they are dispatched to Reminders, which
    does not implement them, and osascript hangs), and the new reminder's id
    must not be read back (it forces an iCloud round trip and hangs likewise).
    """
    return f"""
{_date_expression("alertDate", alert_at)}
tell application "Reminders"
  set targetList to missing value
  repeat with l in lists
    if name of l is "{LIST_NAME}" then set targetList to l
  end repeat
  if targetList is missing value then
    set targetList to make new list with properties {{name:"{LIST_NAME}"}}
  end if
  make new reminder at end of targetList with properties {{name:{_escape(title)}, body:{_escape(body)}, remind me date:alertDate}}
end tell
return "ok"
"""


class AppleRemindersProvider(ReminderProvider):
    slug = "apple_reminders"
    label = "Apple Reminders"
    description = (
        "Creates the reminders directly in the Reminders app on this Mac, one per alert. "
        "They sync to your iPhone through iCloud."
    )
    # False once macOS has granted permission: after that it is one click.
    requires_user_action = False

    def export(self, payload: ReminderPayload) -> ReminderExport:
        state = availability()
        if not state.available:
            raise AppleRemindersUnavailable(state.reason)

        if payload.due_on is None:
            raise AppleRemindersUnavailable(
                "This opportunity has no known deadline, so there is nothing to be reminded about."
            )

        offsets = sorted({int(o) for o in payload.offsets_days if o >= 0}, reverse=True) or [0]

        created: list[dict[str, str]] = []
        skipped: list[str] = []
        today = date.today()

        for offset in offsets:
            alert_on = payload.due_on - timedelta(days=offset)
            if alert_on < today:
                # An alert in the past would fire immediately and teach the
                # student to ignore Trellis notifications.
                skipped.append(f"{offset} days before ({alert_on.isoformat()}) is already past")
                continue
            # The deadline itself goes in the title, because the reminder can only
            # carry one date and that date has to be the alert.
            when = "today" if offset == 0 else f"in {offset} day{'s' if offset != 1 else ''}"
            title = f"{payload.title} — due {when} ({payload.due_on.isoformat()})"
            alert_at = datetime.combine(alert_on, time(hour=ALERT_HOUR))
            _run(_reminder_script(title, payload.body(), alert_at))
            created.append({"title": title, "alert_on": alert_on.isoformat()})

        if not created:
            raise AppleRemindersUnavailable(
                "Every alert for this deadline would already be in the past: "
                + "; ".join(skipped)
            )

        note = f"Added {len(created)} reminder(s) to your “{LIST_NAME}” list."
        if skipped:
            note += " Skipped " + "; ".join(skipped) + "."

        return ReminderExport(
            provider=self.slug,
            content_type="application/json",
            payload={"created": created, "skipped": skipped, "list": LIST_NAME},
            instructions=note,
            external_id=None,
        )
