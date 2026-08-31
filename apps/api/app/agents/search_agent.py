"""Opportunity search orchestration.

The pipeline is deliberately linear and observable: strategies -> sources ->
dedup documents -> extract -> classify -> score -> upsert. Each stage records a
step on the run so the UI can show what actually happened rather than a spinner.

One source failing degrades the run to PARTIAL; it never fails the whole thing.
A student with a broken library scraper should still get their lab leads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.agents.base import Agent, AgentContext, AgentOutcome
from app.agents.deadline_agent import DeadlineAgent, DeadlineRequest
from app.agents.extraction_agent import ExtractionRequest, WebExtractionAgent
from app.agents.matching_agent import MatchingAgent, MatchRequest
from app.models.enums import OpportunityType, RunStatus, SearchKind
from app.models.opportunity import OpportunitySource
from app.models.ops import SearchRun
from app.models.resume import Resume
from app.services.dedup import normalize_url, upsert_opportunity
from app.services.relevance import looks_like_opportunity
from app.services.runs import finish_run, record_step
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
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    documents: int = 0
    skipped: int = 0
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

        slugs = payload.source_slugs or self._strategies(profile, run.kind)
        run.sources_attempted = list(slugs)
        record_step(
            run,
            "plan",
            f"Planned {len(slugs)} source(s) from your interests: {', '.join(slugs)}.",
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

            fetched = 0
            errors = 0
            skipped = 0
            skipped_examples: list[str] = []
            for doc in documents:
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

                opp, outcome = upsert_opportunity(
                    ctx.db, extracted.data, source=source_row, run_id=run.id
                )
                ctx.db.flush()
                setattr(result, outcome, getattr(result, outcome) + 1)

                self._deadline.run(
                    ctx,
                    DeadlineRequest(
                        opportunity=opp, text=extracted.text, source_url=doc.url
                    ),
                )
                if profile is not None:
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
            status = "ok" if fetched else ("error" if errors else "empty")
            record_step(run, slug, detail + ".", status, db=ctx.db)
            result.skipped += skipped
            if source_row is not None:
                source_row.last_run_at = run.started_at

        run.documents_fetched = result.documents
        run.created_count = result.created
        run.updated_count = result.updated
        run.unchanged_count = result.unchanged
        run.skipped_count = result.skipped
        run.stats = {"failures": result.failures}
        record_step(
            run,
            "summary",
            f"{result.created} new, {result.updated} updated, {result.unchanged} unchanged"
            + (f", {result.skipped} skipped as not-an-opening." if result.skipped else "."),
        )
        finish_run(
            ctx.db,
            run,
            status=RunStatus.PARTIAL if result.failures and result.documents else None,
        )
        return AgentOutcome(result=result, warnings=[f"{s} failed" for s in result.failures])

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
