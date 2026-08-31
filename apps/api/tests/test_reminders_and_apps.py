"""Guards on the two subsystems where a bug is a real-world harm:
reminder exports (a missed deadline) and the approval gate (an unwanted submit).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.agents.application_agent import payload_hash
from app.models.enums import AnswerCategory, OpportunityStatus
from app.reminders.base import ReminderPayload
from app.reminders.ics import parse_description
from app.reminders.registry import all_providers, get_provider
from app.services.applications import (
    ALLOWED_TRANSITIONS,
    classify_question,
    planned_questions,
    sensitivity_of,
)


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
    assert slugs == {"apple_reminders", "ics", "apple_shortcuts", "none"}
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


# --------------------------------------------------------------------------- #
# The four-way classification. The category is what decides whether software is
# allowed to touch an answer at all, so each of the four is pinned here.


@pytest.mark.parametrize(
    "question",
    [
        "Full name",
        "What is your email address?",
        "What is your major?",
        "Expected graduation year",
        "Which university do you attend?",
        "How many hours per week are you available?",
    ],
)
def test_profile_questions_are_safe_profile_fields(question):
    result = classify_question(question)
    assert result.category is AnswerCategory.SAFE_PROFILE_FIELD
    assert result.profile_field
    assert result.may_prefill_from_profile
    assert not result.may_draft


@pytest.mark.parametrize(
    "question",
    [
        "Why are you interested in this role?",
        "Describe relevant experience for this position.",
        "Tell us about a project you are proud of",
        "Which of this lab's projects interests you most, and why?",
    ],
)
def test_open_questions_are_safe_generative(question):
    result = classify_question(question)
    assert result.category is AnswerCategory.SAFE_GENERATIVE
    assert result.may_draft
    assert not result.may_prefill_from_profile
    assert result.needs_review, "a draft is never an answer; the student still reviews it"


@pytest.mark.parametrize(
    "question",
    [
        # A visa question is sensitive even though it reads like a plain fact.
        "What is your current visa status?",
        "Will you require visa sponsorship now or in the future?",
        "Are you a U.S. citizen or permanent resident?",
        # Legal attestations: signing something is never done on the student's behalf.
        "I certify that the information provided is true and complete.",
        "I attest under penalty of perjury that the above is accurate.",
        "Type your full name below as your electronic signature.",
        "Do you agree to a criminal background check?",
    ],
)
def test_visa_and_legal_attestation_questions_are_sensitive(question):
    result = classify_question(question)
    assert result.category is AnswerCategory.SENSITIVE
    assert result.sensitive_category
    assert not result.may_prefill_from_profile, "never prefilled, even from the profile"
    assert not result.may_draft, "never drafted"
    assert result.needs_review


@pytest.mark.parametrize(
    "question",
    [
        "When could you start, and for how many quarters?",
        "Please upload a photo of your student ID card.",
        "What shift patterns can you cover?",
    ],
)
def test_unrecognised_questions_default_to_needing_review(question):
    """UNKNOWN is the cautious end of the scale, not a shrug.

    A question Trellis has not understood is never prefilled and never
    drafted: the student answers it.
    """
    result = classify_question(question)
    assert result.category is AnswerCategory.UNKNOWN
    assert result.needs_review
    assert not result.may_prefill_from_profile
    assert not result.may_draft


def test_a_sensitive_question_beats_a_matching_profile_field():
    """"What is your work authorization?" is not answered from the profile
    just because the profile happens to hold a work-authorization value."""
    result = classify_question("What is your work authorization status?")
    assert result.category is AnswerCategory.SENSITIVE
    assert result.profile_field is None


@pytest.mark.parametrize(
    "question",
    [
        "What programming languages do you know?",
        "Describe how you would manage a heavy course load",
        "Which page of your portfolio should we read first?",
    ],
)
def test_substrings_do_not_trigger_a_sensitive_rule(question):
    """"age" lives inside "language", "manage" and "page".

    Matching on substrings sent ordinary technical questions to the
    "only you can answer" pile, which trains a student to ignore it.
    """
    assert classify_question(question).category is not AnswerCategory.SENSITIVE


def test_every_planned_question_is_classified():
    for question in planned_questions(None):
        assert classify_question(question).category in set(AnswerCategory)


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


# --------------------------------------------------------------------------- #
# Apple Reminders — the AppleScript generation, not the app itself.
# Creating real reminders is exercised manually; these pin the three mistakes
# that each silently broke it in testing.


def test_applescript_escaping_handles_quotes_and_newlines():
    from app.reminders.apple_reminders import _escape

    assert _escape('a "quoted" title') == '"a \\"quoted\\" title"'
    # Newlines become linefeed constants, never a raw break inside a literal.
    assert _escape("one\ntwo") == '"one" & linefeed & "two"'
    assert "\n" not in _escape("one\ntwo")


def test_reminder_script_sets_dates_outside_the_tell_block():
    """Inside `tell application "Reminders"` these are dispatched to Reminders,
    which does not implement them, and osascript hangs until killed."""
    from datetime import datetime

    from app.reminders.apple_reminders import _reminder_script

    script = _reminder_script("Title", "Body", datetime(2026, 9, 25, 9, 0))
    before_tell = script.split('tell application "Reminders"')[0]
    assert "set year of alertDate" in before_tell
    assert "set day of alertDate" in before_tell


def test_reminder_script_sets_only_the_alert_date():
    """Reminders overwrites `remind me date` with `due date` when both are given,
    which collapsed every lead-time alert onto the deadline itself."""
    from datetime import datetime

    from app.reminders.apple_reminders import _reminder_script

    script = _reminder_script("Title", "Body", datetime(2026, 9, 25, 9, 0))
    assert "remind me date:alertDate" in script
    assert "due date:" not in script
    # Reading the new reminder's id forces an iCloud round trip and hangs too.
    assert "id of newReminder" not in script


def test_apple_reminders_refuses_alerts_that_are_already_past():
    from datetime import date, timedelta

    from app.reminders.apple_reminders import AppleRemindersProvider, AppleRemindersUnavailable

    payload = _payload(due_on=date.today() - timedelta(days=30), offsets_days=[7, 3, 1])
    with pytest.raises(AppleRemindersUnavailable, match="already be in the past"):
        AppleRemindersProvider().export(payload)


def test_apple_reminders_needs_a_deadline():
    from app.reminders.apple_reminders import AppleRemindersProvider, AppleRemindersUnavailable

    with pytest.raises(AppleRemindersUnavailable, match="no known deadline"):
        AppleRemindersProvider().export(_payload(due_on=None))
