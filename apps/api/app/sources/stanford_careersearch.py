"""careersearch.stanford.edu — Oracle HCM Candidate Experience REST API.

This is a real, unauthenticated JSON API (no cookie, no Referer, no key): the
search finder returns the requisition list plus a total, and a second finder
returns one requisition's full record.  Because the fields arrive already
structured, they go into ``DiscoveredDocument.structured`` and the extractor is
expected to trust them over anything it infers from the prose body.

Honest scope note, and it matters: a prior recon pass censused all 415 open
requisitions by job family and found **no student-hourly or student-assistant
postings**.  "Student Services" here is a staff job family (Student Services
Officer / Specialist), not student employment.  This source is therefore useful
for part-time *staff* and academic roles a student might still be eligible for —
it is not the campus student-jobs board.  For those, see
``stanford_student_jobs`` and the Handshake browser extension.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.models.enums import OpportunityType, SourceKind
from app.sources.base import DiscoveredDocument, SourceAdapter, SourceContext
from app.sources.http import PoliteFetcher, get_fetcher, html_to_text

BASE_URL = "https://careersearch.stanford.edu/"
SITE_NUMBER = "CX_1"

SEARCH_URL = (
    "https://careersearch.stanford.edu/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    "?onlyData=true&expand=requisitionList"
    "&finder=findReqs;siteNumber={site},limit={limit},offset={offset},sortBy=POSTING_DATES_DESC"
)
DETAIL_URL = (
    "https://careersearch.stanford.edu/hcmRestApi/resources/latest/"
    "recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
    "&finder=ById;Id=%22{req_id}%22,siteNumber={site}"
)
#: The slug form that shows up in search engines 404s; only this one resolves.
POSTING_URL = (
    "https://careersearch.stanford.edu/hcmUI/CandidateExperience/en/sites/stanford/job/{req_id}"
)

#: Largest page size the finder accepts.
PAGE_SIZE = 200
#: Detail calls are one HTTP request each, so they are bounded by the caller's limit.
MAX_DETAIL_FETCHES = 200


@dataclass(slots=True)
class SearchPage:
    total: int
    requisitions: list[dict[str, Any]] = field(default_factory=list)


def parse_search_page(payload: object) -> SearchPage:
    """Pull the total and the requisition list out of one search response."""
    if not isinstance(payload, dict):
        return SearchPage(total=0)
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return SearchPage(total=0)
    head = items[0]
    if not isinstance(head, dict):
        return SearchPage(total=0)
    raw_total = head.get("TotalJobsCount")
    total = int(raw_total) if isinstance(raw_total, (int, float)) else 0
    requisitions = [r for r in head.get("requisitionList") or [] if isinstance(r, dict)]
    return SearchPage(total=total, requisitions=requisitions)


def parse_detail(payload: object) -> dict[str, Any] | None:
    """The single requisition record from a ``findReqs;ById`` response."""
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return None
    head = items[0]
    return head if isinstance(head, dict) else None


def flex_fields(detail: dict[str, Any] | None) -> dict[str, str]:
    """``requisitionFlexFields`` as ``{prompt: value}`` — this is where pay lives."""
    if not detail:
        return {}
    out: dict[str, str] = {}
    for entry in detail.get("requisitionFlexFields") or []:
        if not isinstance(entry, dict):
            continue
        prompt = entry.get("Prompt")
        value = entry.get("Value")
        if isinstance(prompt, str) and isinstance(value, str) and value.strip():
            out[prompt.strip()] = value.strip()
    return out


def _text_from_html(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    _, text = html_to_text(value)
    return text or None


def _work_locations(detail: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not detail:
        return []
    out: list[dict[str, Any]] = []
    for entry in detail.get("workLocation") or []:
        if not isinstance(entry, dict):
            continue
        out.append(
            {
                "name": entry.get("LocationName"),
                "address": entry.get("AddressLine1"),
                "city": entry.get("TownOrCity"),
                "region": entry.get("Region2"),
                "postal_code": entry.get("PostalCode"),
                "country": entry.get("Country"),
            }
        )
    return out


def build_structured(summary: dict[str, Any], detail: dict[str, Any] | None) -> dict[str, Any]:
    """Everything the API stated outright, keyed the way the extractor expects."""
    flex = flex_fields(detail)
    detail = detail or {}
    req_id = str(summary.get("Id") or detail.get("Id") or "")
    return {
        "requisition_id": req_id,
        "title": summary.get("Title") or detail.get("Title"),
        "apply_url": POSTING_URL.format(req_id=req_id) if req_id else None,
        "posted_date": summary.get("PostedDate") or detail.get("ExternalPostedStartDate"),
        "posting_end_date": summary.get("PostingEndDate") or detail.get("ExternalPostedEndDate"),
        "primary_location": summary.get("PrimaryLocation") or detail.get("PrimaryLocation"),
        "workplace_type": summary.get("WorkplaceType") or detail.get("WorkplaceType"),
        "job_family": summary.get("JobFamily"),
        "category": detail.get("Category"),
        "job_function": detail.get("JobFunction"),
        "job_grade": detail.get("JobGrade"),
        "requisition_type": detail.get("RequisitionType"),
        "contract_type": summary.get("ContractType") or detail.get("ContractType"),
        "number_of_openings": detail.get("NumberOfOpenings"),
        "contact_name": detail.get("ExternalContactName"),
        "contact_email": detail.get("ExternalContactEmail"),
        "short_description": summary.get("ShortDescriptionStr") or detail.get("ShortDescriptionStr"),
        "pay_range": flex.get("Pay Range"),
        "pay_frequency": flex.get("Pay Frequency"),
        "full_or_part_time": flex.get("Full time or Part time"),
        "fixed_term": flex.get("Fixed Term"),
        "school_or_unit": flex.get("Stanford Schools and Units"),
        "work_locations": _work_locations(detail),
        "description_text": _text_from_html(detail.get("ExternalDescriptionStr")),
        "qualifications_text": _text_from_html(detail.get("ExternalQualificationsStr")),
        "responsibilities_text": _text_from_html(detail.get("ExternalResponsibilitiesStr")),
        # Stated for the reader of this record: Oracle publishes one prose blob
        # per section, so required and preferred lines arrive interleaved and
        # must be separated downstream — never assumed.
        "qualifications_are_unsplit": True,
        "board_carries_student_hourly_jobs": False,
    }


def build_text(structured: dict[str, Any]) -> str:
    """A readable body with the API's own section boundaries preserved."""
    lines: list[str] = []
    if structured.get("title"):
        lines.append(str(structured["title"]))
    header_fields = (
        ("Requisition", "requisition_id"),
        ("Posted", "posted_date"),
        ("Closes", "posting_end_date"),
        ("Location", "primary_location"),
        ("Workplace type", "workplace_type"),
        ("Job family", "job_family"),
        ("Category", "category"),
        ("School or unit", "school_or_unit"),
        ("Schedule", "full_or_part_time"),
        ("Pay range", "pay_range"),
        ("Pay frequency", "pay_frequency"),
        ("Contract type", "contract_type"),
        ("Contact", "contact_email"),
    )
    for label, key in header_fields:
        value = structured.get(key)
        if value:
            lines.append(f"{label}: {value}")

    if structured.get("short_description"):
        lines.append("")
        lines.append("## Summary")
        lines.append(str(structured["short_description"]))
    if structured.get("description_text"):
        lines.append("")
        lines.append("## Description")
        lines.append(str(structured["description_text"]))
    if structured.get("qualifications_text"):
        lines.append("")
        lines.append(
            "## Qualifications (as published; the source does not separate "
            "required from preferred)"
        )
        lines.append(str(structured["qualifications_text"]))
    if structured.get("responsibilities_text"):
        lines.append("")
        lines.append("## Responsibilities")
        lines.append(str(structured["responsibilities_text"]))
    return "\n".join(lines).strip()


def build_document(
    summary: dict[str, Any],
    detail: dict[str, Any] | None,
    *,
    error: str | None = None,
    fetched_at: datetime | None = None,
) -> DiscoveredDocument:
    structured = build_structured(summary, detail)
    req_id = structured["requisition_id"]
    return DiscoveredDocument(
        url=structured["apply_url"] or BASE_URL,
        title=structured["title"],
        text=build_text(structured) or None,
        kind_hint=OpportunityType.PART_TIME,
        external_key=f"stanford-careersearch-{req_id}" if req_id else None,
        structured=structured,
        fetched_at=fetched_at or datetime.now(UTC),
        http_status=200 if error is None else None,
        error=error,
    )


def matches_context(summary: dict[str, Any], ctx: SourceContext) -> bool:
    """Client-side keyword filter.

    Deliberately not the API's ``keyword=`` finder: that returns relevance-ranked
    results, which silently reorders and truncates, and the recon pass showed it
    surfacing unrelated staff roles for student-sounding terms.
    """
    terms = [t.strip().lower() for t in [*ctx.keywords, ctx.query or ""] if t and t.strip()]
    if not terms:
        return True
    haystack = " ".join(
        str(summary.get(key) or "")
        for key in ("Title", "ShortDescriptionStr", "JobFamily", "PrimaryLocation")
    ).lower()
    return any(term in haystack for term in terms)


class StanfordCareerSearchAdapter(SourceAdapter):
    slug = "stanford_careersearch"
    name = "Stanford Careers (careersearch.stanford.edu)"
    kind = SourceKind.JOB_BOARD
    base_url = BASE_URL
    requires_auth = False
    is_public = True
    is_mocked = False
    empty_note = (
        "This board carries university staff and academic requisitions, not student-hourly "
        "roles — a census of all open requisitions found none. Campus student jobs come from "
        "the department pages and from Handshake."
    )
    notes = (
        "Public Oracle HCM Candidate Experience JSON API (siteNumber CX_1). Carries "
        "university staff and academic requisitions — a census of all 415 open "
        "requisitions found NO student-hourly or student-assistant postings, and "
        "'Student Services' is a staff job family, not student employment. Use it for "
        "part-time staff roles; campus student jobs come from stanford_student_jobs "
        "and Handshake."
    )

    def discover(self, ctx: SourceContext) -> Iterable[DiscoveredDocument]:
        return self._documents(ctx)

    def _documents(self, ctx: SourceContext) -> Iterator[DiscoveredDocument]:
        fetcher = get_fetcher()
        wanted = max(ctx.limit, 1)
        seen: set[str] = set()
        offset = 0
        total: int | None = None
        emitted = 0

        while emitted < wanted:
            url = SEARCH_URL.format(site=SITE_NUMBER, limit=PAGE_SIZE, offset=offset)
            status, payload, error = fetcher.get_json(url)
            if error is not None:
                yield DiscoveredDocument(
                    url=url,
                    title="Stanford Careers requisition search",
                    kind_hint=OpportunityType.PART_TIME,
                    http_status=status,
                    error=error,
                )
                return

            page = parse_search_page(payload)
            if total is None:
                total = page.total
            if not page.requisitions:
                return

            for summary in page.requisitions:
                req_id = str(summary.get("Id") or "").strip()
                if not req_id or req_id in seen:
                    continue
                seen.add(req_id)
                if not matches_context(summary, ctx):
                    continue
                yield self._with_detail(fetcher, summary, req_id)
                emitted += 1
                if emitted >= wanted or emitted >= MAX_DETAIL_FETCHES:
                    return

            offset += PAGE_SIZE
            if total is not None and offset >= total:
                return

    def _with_detail(
        self, fetcher: PoliteFetcher, summary: dict[str, Any], req_id: str
    ) -> DiscoveredDocument:
        detail_url = DETAIL_URL.format(req_id=req_id, site=SITE_NUMBER)
        _, payload, error = fetcher.get_json(detail_url)
        if error is not None:
            # The list row alone is still a real posting; note what is missing
            # rather than dropping it or inventing the description.
            return build_document(
                summary,
                None,
                error=f"requisition detail unavailable ({error}); list fields only",
            )
        return build_document(summary, parse_detail(payload))
