"""Is this extraction solid enough to recommend?

``relevance.looks_like_opportunity`` answers "is this page an opening at all?".
This answers the next question: "did we actually read enough of it to be worth
the student's attention?"  A page can be a genuine posting and still extract to
almost nothing — the text is behind a script, the body is a one-line teaser, the
qualifications live in a PDF.  Putting that row in the list costs the student a
click and returns a blank card.

Deleting it is worse, though: the URL, the title and the fact that we saw it are
real information, and the page may well read cleanly next week.  So a thin
extraction is *held*, not dropped: kept in full, excluded from the default list,
the Overview and match scoring, reachable behind an explicit filter that says
plainly what it is, and promoted back automatically the moment a later run reads
it properly.

Everything here is deterministic. Nothing calls a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Why 0.60, and why confidence alone can never hold a row.
#
# Measured against the live database (91 opportunities) on 2026-09-01:
#
#     confidence  <0.60   0.60-0.79   >=0.80
#     rows           31          14        46
#
# The 31 rows under 0.60 are NOT junk.  Eighteen are faculty-linked research
# leads (0.00-0.55) and thirteen are the Recreation & Wellness campus jobs at
# exactly 0.55 — Lifeguard, Swim Instructor, Climbing Wall Staff.  Every one of
# them came from the verified harvest and every one is a real thing to apply
# for.  A threshold on ``extraction_confidence`` alone would hold 34% of the
# corpus and all of it wrongly, which is the strongest possible argument that
# the number is not by itself a quality signal.
#
# What it actually measures (see WebExtractionAgent._confidence) is how many
# *fields* were filled: base 0.35, +0.15 for a title, +0.10 for an organisation,
# +0.15 for requirements, +0.10 for an application URL, +0.15 x deadline
# confidence.  A page with a title and nothing else scores 0.50.  So:
#
#   * 0.60 sits above that 0.50 floor — a page that filled nothing but its title
#     is under it, a page that also found an organisation and a deadline is over.
#   * 0.60 sits below the lowest row any live source has ever produced
#     (stanford_programs 0.65, stanford_student_jobs 0.70,
#     stanford_careersearch 0.85).  It cannot reach into today's real results.
#
# And because the number is a field count rather than a quality judgement, it is
# only ever the *second* half of the test.  A row is held only when it also has
# no actionable evidence at all — nothing to apply to, no deadline, no pay, no
# hours, no stated qualification.  Checked against the live database, that
# combination holds 0 of 91 rows.  It is a gate on what comes next, not a purge
# of what is already there.
# ---------------------------------------------------------------------------
HOLD_BELOW_CONFIDENCE = 0.60

#: Below this, a description is a teaser rather than a posting. Only ever used
#: to *report* thinness — never on its own to hold a row, because CURIS and the
#: R&DE dining posts are both genuinely short.
THIN_DESCRIPTION_CHARS = 200


@dataclass(slots=True)
class ConfidenceVerdict:
    """``hold`` plus the sentence the student will actually read."""

    hold: bool
    reason: str
    evidence: list[str]

    @property
    def state(self) -> str:
        return "held" if self.hold else "ok"


def _join(parts: list[str]) -> str:
    """``a, b and c`` — the reason is read by a student, not parsed."""
    if len(parts) <= 1:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _actionable_evidence(data: dict[str, Any]) -> list[str]:
    """The things a student could act on, named the way they would name them.

    Deliberately excludes "the page uses the word apply" — the relevance gate
    accepts that as proof a page is a posting, but it is not proof that we read
    anything from it, which is the question here.
    """
    found: list[str] = []

    requirements = data.get("requirements") or []
    if requirements:
        found.append(
            f"{len(requirements)} stated qualification{'s' if len(requirements) != 1 else ''}"
        )
    if data.get("deadline"):
        found.append("a deadline")
    if data.get("pay_text") or data.get("pay_min") is not None:
        found.append("stated pay")
    if data.get("hours_per_week"):
        found.append("stated hours")

    method = (data.get("application_method") or "").strip().lower()
    if method and method not in ("unknown", "external"):
        found.append("a way to apply")
    elif data.get("application_url"):
        found.append("an application link")
    elif data.get("contact_email"):
        found.append("a contact address")

    return found


def assess_extraction(
    data: dict[str, Any],
    text: str | None = None,
    *,
    faculty_linked: bool = False,
) -> ConfidenceVerdict:
    """Decide whether an extracted opportunity is fit to recommend.

    ``faculty_linked`` rows are exempt outright.  A research lead is built from
    a PI record, its evidence and its lab pages — there is no posting to
    extract, so ``extraction_confidence`` is measuring the wrong thing entirely
    (every faculty lead in the database scores between 0.00 and 0.90 while being
    equally real).  Their quality lives in ``lead_state``, which has its own
    four-way honest classification.
    """
    confidence = float(data.get("extraction_confidence") or 0.0)
    evidence = _actionable_evidence(data)
    body = (data.get("description") or text or "").strip()

    if faculty_linked:
        return ConfidenceVerdict(
            False, "it is a research lead, judged on its lead state rather than on extraction", []
        )

    if evidence:
        return ConfidenceVerdict(False, f"the page states {_join(evidence)}", evidence)

    if confidence >= HOLD_BELOW_CONFIDENCE:
        # Nothing actionable, but enough of the page came through that a human
        # reading it would probably find something. Not our call to bury it.
        return ConfidenceVerdict(
            False,
            f"nothing actionable was stated, but the page itself read cleanly ({confidence:.2f})",
            evidence,
        )

    missing = "no deadline, pay, hours, qualifications or way to apply"
    if len(body) < THIN_DESCRIPTION_CHARS:
        detail = f"only {len(body)} characters of text came off the page, and {missing}"
    else:
        detail = f"{missing} could be read from the page"
    return ConfidenceVerdict(True, detail, evidence)


def assess_row(opportunity: Any, *, requirements: list[Any] | None = None) -> ConfidenceVerdict:
    """The same judgement over a row already in the database.

    Used by the backfill script and by promotion, where the page text is long
    gone and only the stored fields remain.
    """
    reqs = requirements if requirements is not None else list(opportunity.requirements or [])
    data = {
        "extraction_confidence": opportunity.extraction_confidence,
        "requirements": [{"text": r.text} for r in reqs],
        "deadline": opportunity.deadline,
        "pay_text": opportunity.pay_text,
        "pay_min": opportunity.pay_min,
        "hours_per_week": opportunity.hours_per_week,
        "application_method": opportunity.application_method,
        "application_url": opportunity.application_url,
        "contact_email": opportunity.contact_email,
        "description": opportunity.description,
    }
    return assess_extraction(data, faculty_linked=opportunity.faculty_id is not None)
