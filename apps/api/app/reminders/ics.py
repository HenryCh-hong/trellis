"""iCalendar export.

Chosen as the default because it needs no account, no cloud round trip and no
permission: the student downloads a file and their calendar app owns it from
there. One VALARM per configured offset (spec §9), and the offsets come from
the reminder row, never from a literal here.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from app.reminders.base import ReminderExport, ReminderPayload, ReminderProvider

MAX_LINE = 75


def escape(value: str) -> str:
    """RFC 5545 §3.3.11 text escaping."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Fold at 75 octets, continuing with a leading space (RFC 5545 §3.1).

    The octet limit is on bytes, not characters, so a naive split lands inside a
    multi-byte character and produces an undecodable chunk. Real opportunity
    titles contain em-dashes, so this is not a theoretical case: back up until
    the split point is at a character boundary.
    """
    raw = line.encode("utf-8")
    if len(raw) <= MAX_LINE:
        return line
    chunks: list[bytes] = []
    start = 0
    limit = MAX_LINE
    while start < len(raw):
        end = min(start + limit, len(raw))
        # A continuation byte (0b10xxxxxx) at `end` means `end` is mid-character.
        while end > start + 1 and end < len(raw) and (raw[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(raw[start:end])
        start = end
        limit = MAX_LINE - 1
    return "\r\n ".join(c.decode("utf-8") for c in chunks)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


class IcsReminderProvider(ReminderProvider):
    slug = "ics"
    label = "Calendar file (.ics)"
    description = (
        "Downloads a calendar file with an alert for each offset. Works with Apple Calendar, "
        "Google Calendar and Outlook. Nothing leaves your machine."
    )
    requires_user_action = True

    def export(self, payload: ReminderPayload) -> ReminderExport:
        due = payload.due_at or (
            datetime.combine(payload.due_on, datetime.min.time()).replace(
                hour=9, tzinfo=UTC
            )
            if payload.due_on
            else None
        )
        uid_seed = f"{payload.opportunity_id or payload.title}-{payload.due_on}"
        uid = f"{hashlib.sha256(uid_seed.encode()).hexdigest()[:24]}@trellis.local"
        now = datetime.now(UTC)

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Trellis//Opportunity Agent//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_stamp(now)}",
            f"SUMMARY:{escape(payload.title)}",
        ]

        if due is not None:
            lines += [f"DTSTART:{_stamp(due)}", f"DTEND:{_stamp(due + timedelta(hours=1))}"]
        elif payload.due_on:
            day = payload.due_on.strftime("%Y%m%d")
            lines += [f"DTSTART;VALUE=DATE:{day}", f"DTEND;VALUE=DATE:{day}"]

        body = payload.body()
        if body:
            lines.append(f"DESCRIPTION:{escape(body)}")
        if payload.application_url or payload.url:
            lines.append(f"URL:{escape(payload.application_url or payload.url or '')}")

        for offset in payload.offsets_days:
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"TRIGGER:-P{int(offset)}D",
                f"DESCRIPTION:{escape(f'{payload.title} — due in {int(offset)} day(s)')}",
                "END:VALARM",
            ]

        lines += ["END:VEVENT", "END:VCALENDAR"]
        content = "\r\n".join(fold(line) for line in lines) + "\r\n"

        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in payload.title)[:60]
        return ReminderExport(
            provider=self.slug,
            content_type="text/calendar; charset=utf-8",
            filename=f"{safe or 'reminder'}.ics",
            body=content,
            external_id=uid,
            instructions="Open the downloaded file to add it to your calendar.",
        )


def parse_description(ics: str) -> str:
    """Unfold and unescape the DESCRIPTION — used by the tests to round-trip."""
    unfolded = ics.replace("\r\n ", "")
    for line in unfolded.splitlines():
        if line.startswith("DESCRIPTION:"):
            value = line[len("DESCRIPTION:") :]
            return (
                value.replace("\\n", "\n")
                .replace("\\,", ",")
                .replace("\\;", ";")
                .replace("\\\\", "\\")
            )
    return ""
