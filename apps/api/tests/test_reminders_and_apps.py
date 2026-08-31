"""Guards on the two subsystems where a bug is a real-world harm:
reminder exports (a missed deadline) and the approval gate (an unwanted submit).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.agents.application_agent import payload_hash
from app.models.enums import OpportunityStatus
from app.reminders.base import ReminderPayload
from app.reminders.ics import parse_description
from app.reminders.registry import all_providers, get_provider
from app.services.applications import ALLOWED_TRANSITIONS, sensitivity_of


def _payload(**kw) -> ReminderPayload:
    base = dict(
        title="AI Lab Undergraduate RA; deadline, sharp",
        due_on=date(2026, 9, 15),
        application_url="https://example.org/apply",
        documents=["Resume", "Transcript"],
        notes="Line one\nLine two",
        offsets_days=[7, 3, 1],
        opportunity_id="abc",
    )
    base.update(kw)
    return ReminderPayload(**base)


def test_ics_emits_one_alarm_per_offset():
    body = get_provider("ics").export(_payload()).body
    assert body.count("BEGIN:VALARM") == 3
    for offset in (7, 3, 1):
        assert f"TRIGGER:-P{offset}D" in body


def test_ics_offsets_are_data_not_literals():
    body = get_provider("ics").export(_payload(offsets_days=[14, 2])).body
    assert body.count("BEGIN:VALARM") == 2
    assert "TRIGGER:-P14D" in body
    assert "TRIGGER:-P7D" not in body


def test_ics_escaping_survives_a_round_trip():
    """Commas, semicolons and newlines must come back intact, or the student
    reads a mangled deadline note."""
    body = get_provider("ics").export(_payload()).body
    description = parse_description(body)
    assert "Line one\nLine two" in description
    assert "Resume, Transcript" in description
    assert "https://example.org/apply" in description


def test_ics_folds_long_lines_at_75_octets():
    body = get_provider("ics").export(_payload(title="A" * 300)).body
    for line in body.split("\r\n"):
        assert len(line.encode()) <= 75


def test_ics_folding_survives_multibyte_titles():
    """Real titles contain em-dashes. Folding on a byte count can land inside a
    multi-byte character; the export must not corrupt or crash on it."""
    title = "Undergraduate research \u2014 Stanford Social and Language Technologies (SALT) Lab \u2014 apply"
    export = get_provider("ics").export(_payload(title=title))
    body = export.body
    for line in body.split("\r\n"):
        assert len(line.encode()) <= 75
    # Unfolding must give the original text back intact.
    unfolded = body.replace("\r\n ", "")
    assert title.replace(",", "\\,") in unfolded


@pytest.mark.parametrize("title", ["\u4e2d\u6587\u5b9e\u9a8c\u5ba4 " * 20, "caf\u00e9 " * 30, "\U0001f600" * 40])
def test_ics_folding_handles_every_utf8_width(title):
    body = get_provider("ics").export(_payload(title=title)).body
    for line in body.split("\r\n"):
        assert len(line.encode()) <= 75
    assert body.replace("\r\n ", "")


def test_every_provider_declares_itself():
    slugs = {p.slug for p in all_providers()}
    assert slugs == {"ics", "apple_shortcuts", "none"}
    for provider in all_providers():
        assert provider.label and provider.description


def test_apple_shortcuts_payload_carries_the_offsets():
    export = get_provider("apple_shortcuts").export(_payload())
    reminder = export.payload["reminders"][0]
    assert reminder["alert_offsets_days"] == [7, 3, 1]
    assert reminder["due_on"] == "2026-09-15"
    assert export.instructions


# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "question",
    [
        "Are you authorized to work in the United States?",
        "Will you now or in the future require sponsorship?",
        "Please self-identify your race and ethnicity",
        "Do you identify as a protected veteran?",
        "Do you have a disability?",
        "What is your date of birth?",
    ],
)
def test_sensitive_questions_are_detected(question):
    is_sensitive, category = sensitivity_of(question)
    assert is_sensitive, f"{question!r} must be treated as sensitive"
    assert category


@pytest.mark.parametrize(
    "question",
    [
        "What is your major?",
        "Why are you interested in this lab?",
        "Describe your experience with Python",
        "How many hours per week are you available?",
    ],
)
def test_ordinary_questions_are_not_flagged_sensitive(question):
    assert sensitivity_of(question) == (False, None)


def test_submitted_cannot_return_to_preparing():
    assert OpportunityStatus.PREPARING not in ALLOWED_TRANSITIONS[OpportunityStatus.SUBMITTED]


def test_payload_hash_changes_when_a_value_changes():
    plan = {
        "target_url": "https://example.org",
        "method": "email",
        "fields": [{"key": "a", "label": "A", "value": "1", "source": "profile", "will_submit": True}],
        "attachments": [],
        "withheld": [{"label": "Work authorisation", "reason": "never auto-filled"}],
    }
    before = payload_hash(plan)
    plan["fields"][0]["value"] = "2"
    assert payload_hash(plan) != before, "an edited answer must invalidate a prior approval"


def test_payload_hash_is_stable_for_the_same_plan():
    plan = {"target_url": "u", "method": "m", "fields": [], "attachments": [], "withheld": []}
    assert payload_hash(plan) == payload_hash(dict(plan))
