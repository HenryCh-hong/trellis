"""Opportunity search orchestration.

The pipeline is deliberately linear and observable: strategies -> sources ->
dedup documents -> extract -> classify -> score -> upsert. Each stage records a
step on the run so the UI can show what actually happened rather than a spinner.

One source failing degrades the run to PARTIAL; it never fails the whole thing.
A student with a broken library scraper should still get their lab leads.

Quality is enforced in three places, in order, because they answer three
different questions:

1. ``relevance.looks_like_opportunity`` — is this page an opening at all?
2. ``signals.load_suppressions``        — did the student already say no to it?
3. ``confidence.assess_extraction``     — did we read enough of it to recommend?

Every document ends in exactly one bucket of the run ledger, so the numbers the
student sees add up to what the run actually looked at.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from app.agents.base import Agent, AgentContext, AgentOutcome
from app.agents.deadline_agent import DeadlineAgent, DeadlineRequest
from app.agents.extraction_agent import ExtractionRequest, WebExtractionAgent
from app.agents.matching_agent import MatchingAgent, MatchRequest
from app.models.change import ChangeKind
from app.models.enums import ConfidenceState, OpportunityType, RunStatus, SearchKind
from app.models.opportunity import Opportunity, OpportunityMatch, OpportunitySource
from app.models.ops import SearchRun
from app.models.resume import Resume
from app.services.confidence import ConfidenceVerdict, assess_extraction
from app.services.dedup import normalize_url, upsert_opportunity
from app.services.lifecycle import (
    NOT_FOUND_STATUSES,
    log_change,
    reconcile_source,
    sweep_expired,
)
from app.services.relevance import looks_like_opportunity
from app.services.runs import finish_run, record_step
from app.services.signals import load_suppressions
from app.sources.base import SourceContext
from app.sources.registry import get_adapter

# Which adapters serve which intent. Adding a source is a row here plus the
# adapter class; nothing else in the pipeline changes.
# These must match SourceAdapter.slug exactly (see app/sources/registry.py).
JOB_SOURCES = ("stanford_student_jobs", "stanford_careersearch")
RESEARCH_SOURCES = ("stanford_programs",)

# Handled by ResearchDiscoveryAgent, not here. A faculty directory row is a
# person, not a posting: extracting it as an opportunity produced rows titled
# "Professor of Linguistics". The research agent turns the same source into
# properly linked PI leads with evidence.
FACULTY_SOURCES = ("stanford_cs_faculty",)


@dataclass(slots=True)
class SearchRequest:
    profile: Any
    run: SearchRun
    source_slugs: list[str] = field(default_factory=list)
    query: str | None = None
    limit_per_source: int = 40


@dataclass(slots=True)
class SearchOutcome:
    """The run ledger. Every document looked at lands in exactly one bucket."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    expired: int = 0
    #: Postings the source itself no longer lists. Flagged, never deleted.
    disappeared: int = 0
    reappeared: int = 0
    held: int = 0
    skipped: int = 0
    suppressed: int = 0
    #: Held rows that read well this time and are back in the list. A subset of
    #: created/updated/unchanged, reported separately because it is good news.
    promoted: int = 0
    documents: int = 0
    hold_reasons: list[str] = field(default_factory=list)
    promoted_titles: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


class OpportunitySearchAgent(Agent[SearchRequest, SearchOutcome]):
    name = "opportunity-search"
    description = "Runs the configured sources, extracts opportunities, dedups them and scores them."

    def __init__(self) -> None:
        self._extract = WebExtractionAgent()
        self._deadline = DeadlineAgent()
        self._match = MatchingAgent()

    def run(self, ctx: AgentContext, payload: SearchRequest) -> AgentOutcome[SearchOutcome]:
        run = payload.run
        profile = payload.profile
        result = SearchOutcome()
        now = datetime.now(UTC)

        slugs = payload.source_slugs or self._strategies(profile, run.kind)
        run.sources_attempted = list(slugs)
        record_step(
            run,
            "plan",
            f"Planned {len(slugs)} source(s) from your interests: {', '.join(slugs)}.",
            db=ctx.db,
        )

        suppressions = load_suppressions(ctx.db, getattr(profile, "id", None))
        if suppressions:
            record_step(
                run,
                "your-feedback",
                f"Excluding {len(suppressions.opportunity_ids)} result(s) you marked hidden or "
                "not relevant. They will not be offered again unless you unhide them.",
                db=ctx.db,
            )

        resumes = list(ctx.db.scalars(select(Resume).order_by(Resume.created_at)))
        seen_urls: set[str] = set()

        for slug in slugs:
            if slug in FACULTY_SOURCES:
                record_step(
                    run,
                    slug,
                    "Faculty directory is handled by research discovery, not job search.",
                    "skipped",
                    db=ctx.db,
                )
                continue
            try:
                adapter = get_adapter(slug)
            except (KeyError, LookupError):
                result.failures.append(slug)
                record_step(run, slug, f"No adapter registered for {slug}.", "error")
                continue

            source_row = ctx.db.scalars(
                select(OpportunitySource).where(OpportunitySource.slug == slug)
            ).first()

            if adapter.requires_auth:
                record_step(
                    run,
                    slug,
                    f"{adapter.name} needs your login, so it is imported from your browser "
                    "rather than fetched here.",
                    "skipped",
                )
                continue

            source_ctx = SourceContext(
                university=getattr(profile, "university", "") or "",
                query=payload.query,
                keywords=list(getattr(profile, "keywords", []) or []),
                topics=[i.label for i in getattr(profile, "interests", [])],
                limit=payload.limit_per_source,
            )

            try:
                documents = list(adapter.discover(source_ctx))
            except Exception as exc:
                result.failures.append(slug)
                record_step(run, slug, f"{adapter.name} failed: {type(exc).__name__}: {exc}", "error")
                continue

            # Everything this source listed, whether or not we could read it.
            # A page we failed to fetch is a page WE failed on, and must never
            # be mistaken for a posting that was taken down.
            listed_urls: set[str] = set()
            listed_keys: set[str] = set()
            postings_seen = 0

            fetched = 0
            errors = 0
            skipped = 0
            held = 0
            suppressed = 0
            skipped_examples: list[str] = []
            for doc in documents:
                # A 404 is the source telling us the posting is gone, so its URL
                # is deliberately NOT recorded as seen. Every other failure —
                # timeout, 500, DNS — is ours, and the URL counts as present so
                # a bad afternoon on the network cannot bury a live posting.
                listed = normalize_url(doc.url)
                found = doc.http_status not in NOT_FOUND_STATUSES
                if listed and found:
                    listed_urls.add(listed)
                if doc.external_key and found:
                    listed_keys.add(doc.external_key)

                if doc.error or not doc.ok:
                    errors += 1
                    continue
                key = normalize_url(doc.url) or doc.url
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                fetched += 1
                result.documents += 1

                extracted = self._extract.run(
                    ctx, ExtractionRequest(document=doc, source=source_row)
                ).result
                if not extracted.data.get("title"):
                    skipped += 1
                    if len(skipped_examples) < 3:
                        skipped_examples.append(f"{doc.url[:60]} (no title could be read)")
                    continue

                # A crawl finds pages, not openings. Without this gate a run over
                # a department site files "PhD" and "Joint Programs" as things to
                # apply for, which buries the real postings.
                verdict = looks_like_opportunity(extracted.data, extracted.text)
                if not verdict.keep:
                    skipped += 1
                    if len(skipped_examples) < 3:
                        skipped_examples.append(
                            f"{extracted.data['title'][:48]} ({verdict.reason})"
                        )
                    continue

                # Something the student has already dismissed is not a find. It
                # is checked before the upsert so a rediscovered-and-deleted row
                # cannot come back through the "created" path either.
                if suppressions.blocks(
                    url=normalize_url(doc.url), external_key=extracted.data.get("external_key")
                ):
                    suppressed += 1
                    continue

                confidence = assess_extraction(extracted.data, extracted.text)

                opp, outcome = upsert_opportunity(
                    ctx.db, extracted.data, source=source_row, run_id=run.id
                )
                ctx.db.flush()
                postings_seen += 1

                if opp.id in suppressions.opportunity_ids:
                    suppressed += 1
                    continue

                promoted = self._apply_confidence(ctx, opp, confidence, now, run.id)
                if promoted:
                    result.promoted += 1
                    if len(result.promoted_titles) < 5:
                        result.promoted_titles.append(opp.title)

                if confidence.hold:
                    held += 1
                    if len(result.hold_reasons) < 5:
                        result.hold_reasons.append(f"{opp.title[:48]} — {confidence.reason}")
                else:
                    setattr(result, outcome, getattr(result, outcome) + 1)

                self._deadline.run(
                    ctx,
                    DeadlineRequest(
                        opportunity=opp, text=extracted.text, source_url=doc.url
                    ),
                )
                # A held row is never scored: a fit number computed from a page
                # we barely read is a confident-looking guess, which is the one
                # thing this product must not produce.
                if profile is not None and opp.confidence_state == ConfidenceState.OK:
                    self._match.run(
                        ctx,
                        MatchRequest(
                            profile=profile, opportunity=opp, resumes=resumes, polish=False
                        ),
                    )

            host = (adapter.base_url or slug).replace("https://", "").rstrip("/")

            # "Nothing matched" and "the source broke" are different facts and
            # must not share a status. Flagging an empty-but-healthy source as an
            # error trains the student to ignore real errors.
            if not documents:
                record_step(
                    run,
                    slug,
                    f"{adapter.name} returned nothing matching your profile. "
                    f"{adapter.empty_note or 'No postings matched your interests and filters.'}",
                    "empty",
                    db=ctx.db,
                )
                continue

            detail = f"Fetched {fetched} page(s) from {host}"
            if errors:
                detail += f"; {errors} could not be read"
            if skipped:
                detail += f"; skipped {skipped} page(s) that were not openings"
                if skipped_examples:
                    detail += f" (e.g. {skipped_examples[0]})"
            if held:
                detail += f"; held {held} back as too thin to recommend"
            if suppressed:
                detail += f"; left out {suppressed} you had marked not relevant"
            status = "ok" if fetched else ("error" if errors else "empty")
            record_step(run, slug, detail + ".", status, db=ctx.db)
            result.skipped += skipped
            result.held += held
            result.suppressed += suppressed

            # Only now, with the source's own answer in hand, can a posting's
            # absence mean anything, and only under two guards.
            #
            # ``postings_seen``: a source that answered but produced no postings
            # at all is indistinguishable from one that quietly broke.
            #
            # The page budget: several adapters enumerate a catalogue far larger
            # than ``limit_per_source`` and stop when WE tell them to. A posting
            # we never got to is not a posting that was removed, so absence only
            # counts when the source ran out before our budget did.
            complete_listing = len(documents) < payload.limit_per_source
            gone = reconcile_source(
                ctx.db,
                source_row,
                seen_urls=listed_urls,
                seen_keys=listed_keys,
                source_succeeded=postings_seen > 0 and complete_listing,
                now=now,
                run_id=run.id,
            )
            result.disappeared += gone.marked_gone
            result.reappeared += gone.marked_back
            if gone.marked_gone or gone.marked_back:
                note = f"{gone.marked_gone} posting(s) are no longer listed on {adapter.name}"
                if gone.marked_back:
                    note += f"; {gone.marked_back} are listed again"
                record_step(run, slug, note + ". Nothing was deleted.", db=ctx.db)

            if source_row is not None:
                source_row.last_run_at = run.started_at

        # Expiry is a fact about rows we already hold, not about this crawl, so
        # it runs once at the end over everything. Idempotent by design.
        sweep = sweep_expired(ctx.db, ctx.today, now=now, run_id=run.id)
        result.expired = sweep.expired
        if sweep.expired or sweep.revived:
            detail = ""
            if sweep.expired:
                detail = f"{sweep.expired} deadline(s) have now passed"
                if sweep.titles:
                    detail += f" (e.g. {sweep.titles[0][:60]})"
            if sweep.revived:
                detail += (
                    f"{'; ' if detail else ''}{sweep.revived} came back with a new date"
                )
            record_step(run, "deadlines", detail + ". Kept, but no longer recommended.", db=ctx.db)

        if result.held:
            reasons = "; ".join(result.hold_reasons[:3])
            record_step(
                run,
                "confidence",
                f"Held {result.held} extraction(s) back: too little came off the page to put "
                f"in front of you. Kept in full and shown under "
                f"“Low-confidence, not recommended”. {reasons}.",
                db=ctx.db,
            )
        if result.promoted:
            record_step(
                run,
                "promoted",
                f"{result.promoted} previously held row(s) read properly this time and are back "
                f"in the list: {', '.join(t[:48] for t in result.promoted_titles)}.",
                db=ctx.db,
            )

        run.documents_fetched = result.documents
        run.created_count = result.created
        run.updated_count = result.updated
        run.unchanged_count = result.unchanged
        run.expired_count = result.expired
        run.held_count = result.held
        run.skipped_count = result.skipped
        run.suppressed_count = result.suppressed
        run.stats = {
            "failures": result.failures,
            "promoted": result.promoted,
            "hold_reasons": result.hold_reasons,
            # False means the Signals phase has not landed yet — distinct from
            # "the student has rejected nothing", which is what 0 suppressed
            # would otherwise be read as.
            "feedback_table_available": suppressions.available,
            "disappeared": result.disappeared,
            "reappeared": result.reappeared,
        }
        record_step(run, "summary", self._summary(result))
        finish_run(
            ctx.db,
            run,
            status=RunStatus.PARTIAL if result.failures and result.documents else None,
        )
        return AgentOutcome(result=result, warnings=[f"{s} failed" for s in result.failures])

    # ------------------------------------------------------------------ #

    def _summary(self, result: SearchOutcome) -> str:
        """The one line a student reads. Every number in it is a real bucket."""
        parts = [
            f"{result.created} new",
            f"{result.updated} updated",
            f"{result.unchanged} unchanged",
        ]
        if result.expired:
            parts.append(f"{result.expired} expired")
        if result.held:
            parts.append(f"{result.held} held as low-confidence")
        if result.skipped:
            parts.append(f"{result.skipped} skipped as not an opening")
        if result.suppressed:
            parts.append(f"{result.suppressed} left out because you rejected them")
        return ", ".join(parts) + "."

    def _apply_confidence(
        self,
        ctx: AgentContext,
        opp: Opportunity,
        verdict: ConfidenceVerdict,
        now: datetime,
        run_id: uuid.UUID | None,
    ) -> bool:
        """Record the gate's decision on the row. Returns True on a promotion.

        A faculty-linked lead is re-judged as exempt rather than skipped, so a
        row that gains a faculty link is promoted out of the held state instead
        of being stuck there by a decision made before the link existed.
        """
        if opp.faculty_id is not None:
            verdict = ConfidenceVerdict(
                False,
                "it is a research lead, judged on its lead state rather than on extraction",
                verdict.evidence,
            )

        previous = opp.confidence_state
        new_state = ConfidenceState.HELD if verdict.hold else ConfidenceState.OK
        # The reason is only ever shown next to a held row, so it is cleared on
        # the way out rather than left behind to be read as a current caveat.
        opp.confidence_reason = verdict.reason if verdict.hold else None
        if previous == new_state:
            return False

        opp.confidence_state = new_state
        opp.confidence_state_at = now
        if new_state == ConfidenceState.HELD:
            # The score was derived from an extraction we no longer trust, and a
            # match row is a current opinion rather than a record of an event.
            # Leaving it would mean a held row still carrying a confident number.
            if opp.id is not None:
                ctx.db.execute(
                    delete(OpportunityMatch).where(OpportunityMatch.opportunity_id == opp.id)
                )
            log_change(
                ctx.db,
                opp,
                ChangeKind.HELD,
                "confidence_state",
                previous.value,
                new_state.value,
                f"Held back as low-confidence: {verdict.reason}. Nothing was deleted — open "
                "the “Low-confidence, not recommended” filter to read it yourself.",
                now,
                run_id,
            )
            return False

        log_change(
            ctx.db,
            opp,
            ChangeKind.PROMOTED,
            "confidence_state",
            previous.value,
            new_state.value,
            f"Back in your list: this time {verdict.reason}.",
            now,
            run_id,
        )
        return True

    def _strategies(self, profile: Any, kind: SearchKind) -> list[str]:
        """Turn the student's stated preferences into a source list.

        Never includes FACULTY_SOURCES: those belong to the research agent.
        """
        wanted = set(getattr(profile, "preferred_job_types", []) or [])
        if kind == SearchKind.RESEARCH:
            return list(RESEARCH_SOURCES)
        slugs: list[str] = []
        if not wanted or {OpportunityType.ON_CAMPUS.value, OpportunityType.PART_TIME.value} & wanted:
            slugs.extend(JOB_SOURCES)
        if {
            OpportunityType.RESEARCH_OPENING.value,
            OpportunityType.RESEARCH_OUTREACH.value,
        } & wanted:
            slugs.extend(RESEARCH_SOURCES)
        return slugs or list(JOB_SOURCES)

