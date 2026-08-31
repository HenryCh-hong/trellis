"""Opportunity lifecycle: expiry, and postings that vanish from their source.

Two facts a job board never tells a student, and both are *recorded* here
rather than computed on read:

* a deadline lapsed — ``DeadlineState.EXPIRED``
* the posting is no longer on the page it came from — ``SourceStatus.GONE``

Both write an :class:`OpportunityChange`, because a row that silently changes
colour teaches the student nothing.  Nothing here ever deletes: an expired
opportunity is still the answer to "did I miss that?", and a disappeared one is
still evidence of what the source used to say.

Everything is deterministic date arithmetic and set membership. No model runs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.change import ChangeKind, OpportunityChange
from app.models.enums import DeadlineState, DeadlineType, SourceStatus
from app.models.opportunity import Opportunity, OpportunitySource

#: Statuses that mean the page is genuinely not there any more, as opposed to
#: the many ways a fetch can fail on our side. A timeout, a 500 or a DNS error
#: says nothing about whether the posting still exists; a 404 does.
NOT_FOUND_STATUSES = (404, 410)

MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def format_day(value: date | None) -> str:
    """``Sep 10, 2026`` — the wording used in every change summary."""
    if value is None:
        return "an unknown date"
    return f"{MONTHS[value.month - 1]} {value.day}, {value.year}"


def deadline_state_for(
    deadline: date | None,
    deadline_type: DeadlineType | str,
    today: date,
) -> DeadlineState:
    """The lifecycle state a row *should* be in.

    A stated date always decides: the deadline agent already treats "apply by
    Sep 15" as beating a "rolling basis" phrase elsewhere on the page, so a
    passed date means expired even where the page also called itself rolling.
    """
    kind = deadline_type.value if isinstance(deadline_type, DeadlineType) else str(deadline_type)
    if deadline is not None:
        return DeadlineState.EXPIRED if deadline < today else DeadlineState.HARD
    return DeadlineState.ROLLING if kind == DeadlineType.ROLLING.value else DeadlineState.UNKNOWN


def sync_deadline_state(opp: Opportunity, today: date) -> None:
    """Bring a row's stored state back in line with its dates after a write.

    Writers (extraction, dedup, the deadline agent) record only what the
    posting says; authoring EXPIRED belongs to :func:`sweep_expired` alone,
    because that is the one place that logs the transition.  So a row whose
    date is in the past is left alone here — already-expired stays expired,
    and a not-yet-swept one stays HARD until the sweep marks and logs it.

    Un-expiring, on the other hand, happens immediately: if a posting moves its
    deadline into the future the student can apply again, and the deadline
    change itself is already in the log.
    """
    computed = deadline_state_for(opp.deadline, opp.deadline_type, today)
    if computed == DeadlineState.EXPIRED:
        if opp.deadline_state != DeadlineState.EXPIRED:
            opp.deadline_state = DeadlineState.HARD
        return
    opp.deadline_state = computed


def deadline_change_summary(old: date | None, new: date | None) -> str:
    """One honest sentence about a deadline that moved, appeared or vanished.

    The disappearing case is the one that matters: "Unknown" on its own reads
    like we never knew, when in fact the posting used to say a date and stopped.
    """
    if old is None and new is not None:
        return f"Deadline added: the posting now says {format_day(new)}."
    if new is None and old is not None:
        return f"Deadline removed from the posting — it previously said {format_day(old)}."
    return f"Deadline moved from {format_day(old)} to {format_day(new)}."


def log_change(
    db: Session,
    opp: Opportunity,
    kind: ChangeKind,
    field_name: str | None,
    old: object,
    new: object,
    summary: str,
    now: datetime,
    run_id: uuid.UUID | None,
) -> OpportunityChange:
    change = OpportunityChange(
        opportunity_id=opp.id,
        kind=kind,
        field=field_name,
        old_value=None if old is None else str(old),
        new_value=None if new is None else str(new),
        summary=summary,
        source_url=opp.source_url,
        search_run_id=run_id,
        noticed_at=now,
    )
    db.add(change)
    return change


# --------------------------------------------------------------------------
# Expiry
# --------------------------------------------------------------------------


@dataclass(slots=True)
class SweepReport:
    expired: int = 0
    revived: int = 0
    titles: list[str] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return self.expired + self.revived


def sweep_expired(
    db: Session,
    today: date | None = None,
    *,
    now: datetime | None = None,
    run_id: uuid.UUID | None = None,
) -> SweepReport:
    """Mark every newly-lapsed deadline, and log each transition once.

    Idempotent: a second call on the same day finds nothing to do, because the
    state is stored.  That is the whole reason it is stored.
    """
    now = now or datetime.now(UTC)
    today = today or now.astimezone(UTC).date()
    report = SweepReport()

    # Only rows with a real date can expire; rolling and unknown never do.
    candidates = db.scalars(
        select(Opportunity).where(
            Opportunity.deadline.is_not(None),
            Opportunity.deadline < today,
            Opportunity.deadline_state != DeadlineState.EXPIRED,
        )
    ).all()
    for opp in candidates:
        previous = opp.deadline_state
        opp.deadline_state = DeadlineState.EXPIRED
        log_change(
            db,
            opp,
            ChangeKind.EXPIRED,
            "deadline_state",
            previous.value,
            DeadlineState.EXPIRED.value,
            f"Deadline passed — the posting said {format_day(opp.deadline)}. "
            "Kept here so you can still see it; it is no longer something to apply to.",
            now,
            run_id,
        )
        report.expired += 1
        if len(report.titles) < 10:
            report.titles.append(opp.title)

    # A posting whose deadline moved back into the future is live again. Rare,
    # but it happens when a lab extends a call, and leaving it expired would
    # hide something the student can still apply to.
    revived = db.scalars(
        select(Opportunity).where(
            Opportunity.deadline_state == DeadlineState.EXPIRED,
            (Opportunity.deadline.is_(None)) | (Opportunity.deadline >= today),
        )
    ).all()
    for opp in revived:
        # By construction of the query above this can never come back EXPIRED.
        opp.deadline_state = deadline_state_for(opp.deadline, opp.deadline_type, today)
        log_change(
            db,
            opp,
            ChangeKind.DEADLINE,
            "deadline_state",
            DeadlineState.EXPIRED.value,
            opp.deadline_state.value,
            "No longer expired — the posting now says "
            + (
                f"{format_day(opp.deadline)}."
                if opp.deadline
                else "no fixed deadline."
            ),
            now,
            run_id,
        )
        report.revived += 1

    db.flush()
    return report


# --------------------------------------------------------------------------
# Postings that vanish from their source
# --------------------------------------------------------------------------


@dataclass(slots=True)
class SourceReconciliation:
    marked_gone: int = 0
    marked_back: int = 0
    titles: list[str] = field(default_factory=list)


def reconcile_source(
    db: Session,
    source: OpportunitySource | None,
    *,
    seen_urls: set[str],
    seen_keys: set[str],
    source_succeeded: bool,
    now: datetime | None = None,
    run_id: uuid.UUID | None = None,
) -> SourceReconciliation:
    """Flag this source's opportunities that were not in its results this time.

    ``seen_urls`` must be normalised (:func:`app.services.dedup.normalize_url`)
    and must include the documents the fetcher could *not* read: a timeout or a
    500 is a page we failed on, not a posting that was taken down.  The one
    exception is an explicit not-found (:data:`NOT_FOUND_STATUSES`), which the
    caller leaves out because it is the source saying the page is gone.

    ``source_succeeded`` is the guard that matters, and the caller owes it real
    evidence: the adapter did not raise, it produced at least one posting, and
    the listing was not cut short by our own page budget.  Without that, one
    network outage would mark an entire source's worth of live postings as
    gone — the single most destructive thing this module could do.
    """
    report = SourceReconciliation()
    if source is None or not source_succeeded:
        return report
    # An empty result set from a source that "succeeded" is indistinguishable
    # from a silent failure, so it is never treated as evidence of removal.
    if not seen_urls and not seen_keys:
        return report

    now = now or datetime.now(UTC)
    # Imported here rather than at module scope: dedup depends on this module.
    from app.services.dedup import normalize_url

    rows = db.scalars(select(Opportunity).where(Opportunity.source_id == source.id)).all()
    for opp in rows:
        url = normalize_url(opp.source_url)
        present = (url is not None and url in seen_urls) or (
            opp.external_key is not None and opp.external_key in seen_keys
        )
        if present and opp.source_status == SourceStatus.GONE:
            opp.source_status = SourceStatus.LIVE
            opp.source_status_at = now
            log_change(
                db,
                opp,
                ChangeKind.REAPPEARED,
                "source_status",
                SourceStatus.GONE.value,
                SourceStatus.LIVE.value,
                f"Back on {source.name} — the posting is listed again.",
                now,
                run_id,
            )
            report.marked_back += 1
        elif not present and opp.source_status == SourceStatus.LIVE:
            opp.source_status = SourceStatus.GONE
            opp.source_status_at = now
            log_change(
                db,
                opp,
                ChangeKind.DISAPPEARED,
                "source_status",
                SourceStatus.LIVE.value,
                SourceStatus.GONE.value,
                f"Source no longer available — {source.name} answered, and this posting "
                "was not in its results. Kept for your records.",
                now,
                run_id,
            )
            report.marked_gone += 1
            if len(report.titles) < 10:
                report.titles.append(opp.title)

    db.flush()
    return report
