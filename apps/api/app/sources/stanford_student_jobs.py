"""The Stanford student-job pages that are genuinely public and genuinely scrapable.

Stanford has no single student-jobs API.  What it has is a handful of unit-run
pages — Student Affairs' Hub, R&DE, Recreation & Wellness, Residential Education —
each of which publishes real, current student roles in plain HTML.  A recon pass
verified every URL below returns HTTP 200 with server-rendered content.

Two shapes show up, and both are handled:

* an *index* page that links out to one job-description page per role
  (thehub.stanford.edu), and
* a *flat* page whose roles are sections on the page itself, with the full job
  description living in an off-site Google Doc or PDF (Recreation, R&DE, ResEd).

For the second shape the index page is the posting — so it is yielded as a
document, and the off-site descriptions are recorded in ``linked_documents``
rather than fetched.  We do not guess at their contents.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.models.enums import OpportunityType, SourceKind
from app.sources.base import DiscoveredDocument, SourceAdapter, SourceContext
from app.sources.lab_site import (
    PageLink,
    extract_emails,
    extract_links,
    is_document_link,
    is_offsite_document,
    normalise_url,
    same_host_links,
)
from app.sources.manual_url import fetch_document

MAX_DETAIL_PAGES_PER_SOURCE = 25
CRAWL_DEPTH = 1

#: A link is a candidate job description if its path or its anchor text says so.
JOB_LINK_RE = re.compile(
    r"(job|employment|intern|position|hiring|opportunit|apply|application|"
    r"work-for|work-with|openings?)",
    re.IGNORECASE,
)

#: Paths that match the keyword test but are never a posting.
JOB_LINK_EXCLUDE_RE = re.compile(
    r"(/search|/login|/saml|/user/|/node/\d+$|privacy|accessibility|non-discrimination)",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class StudentJobPage:
    url: str
    unit: str
    organization: str
    #: href substrings that mark a definite job-description page on this site.
    #: When set, only these are followed — no keyword guessing.
    detail_hints: tuple[str, ...] = ()
    note: str = ""


SOURCE_PAGES: tuple[StudentJobPage, ...] = (
    StudentJobPage(
        url="https://thehub.stanford.edu/jobs",
        unit="The Hub @ Lathrop",
        organization="Learning Technologies & Spaces, Stanford Student Affairs",
        detail_hints=("-job-description",),
        note=(
            "Index of student technology roles; each links to its own job-description "
            "page carrying pay, minimum weekly hours, terms and qualifications."
        ),
    ),
    StudentJobPage(
        url="https://rde.stanford.edu/student-employment",
        unit="Residential & Dining Enterprises",
        organization="Stanford Residential & Dining Enterprises (R&DE)",
        note=(
            "Standing student roles (Student Connect Team, Student Housing Worker, "
            "Student Dining Worker). Evergreen rather than dated requisitions, so the "
            "page itself is the posting."
        ),
    ),
    StudentJobPage(
        url="https://rde.stanford.edu/dining-hospitality/student-engagement",
        unit="Stanford Dining, Hospitality & Auxiliaries",
        organization="Stanford Residential & Dining Enterprises (R&DE)",
        note="Dining student hiring plus individually posted intern roles (PDF JDs).",
    ),
    StudentJobPage(
        url="https://rec.stanford.edu/connect/employment-opportunities",
        unit="Stanford Recreation & Wellness",
        organization="Stanford Recreation & Wellness",
        note=(
            "Part-time recreation roles grouped by unit, each with a contact email. "
            "Per-role job descriptions live in Google Drive/Docs and are recorded, "
            "not fetched — so per-role pay and requirements stay unknown here."
        ),
    ),
    StudentJobPage(
        url="https://resed.stanford.edu/houses/get-involved/student-internships",
        unit="Residential Education",
        organization="Stanford Residential Education (ResEd)",
        note="Paid student intern roles for the academic year; applications via Google Forms.",
    ),
)

_INDEX_URLS = frozenset(normalise_url(page.url) for page in SOURCE_PAGES)


def _host_label(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host.split(".", 1)[0] or "stanford"


def external_key_for(url: str, page: StudentJobPage) -> str:
    """Stable per-posting identity: unit host plus the page's own slug."""
    path = urlparse(url).path.strip("/")
    slug = path.rsplit("/", 1)[-1] if path else "index"
    slug = re.sub(r"-job-description$", "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-") or "index"
    return f"stanford-{_host_label(page.url)}-{slug}"


def classify_linked_document(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "docs.google.com" in host:
        return "google_doc"
    if "drive.google.com" in host:
        return "google_drive_file"
    if "forms.gle" in host or "form.asana.com" in host or "/forms/" in url:
        return "application_form"
    if "teamworksapp.com" in host:
        return "application_form"
    if is_document_link(url):
        return urlparse(url).path.rsplit(".", 1)[-1].lower()
    return "external"


def linked_documents(html: str, base_url: str) -> list[dict[str, str]]:
    """Off-site job descriptions and application forms, recorded but never fetched."""
    out: list[dict[str, str]] = []
    for link in extract_links(html, base_url, main_only=True):
        if not (is_document_link(link.url) or is_offsite_document(link.url)):
            continue
        out.append(
            {"url": link.url, "label": link.text, "kind": classify_linked_document(link.url)}
        )
    return out


def detail_links(html: str, page: StudentJobPage) -> list[PageLink]:
    """Same-host job-description pages linked from an index page."""
    index_url = normalise_url(page.url)
    candidates: list[PageLink] = []
    for link in same_host_links(html, page.url, main_only=True):
        if link.url == index_url or link.url in _INDEX_URLS:
            continue
        if is_document_link(link.url):
            continue
        if page.detail_hints:
            if any(hint.lower() in link.url.lower() for hint in page.detail_hints):
                candidates.append(link)
            continue
        haystack = f"{urlparse(link.url).path} {link.text}"
        if JOB_LINK_EXCLUDE_RE.search(link.url):
            continue
        if JOB_LINK_RE.search(haystack):
            candidates.append(link)
    return candidates[:MAX_DETAIL_PAGES_PER_SOURCE]


@dataclass(slots=True)
class _PageResult:
    document: DiscoveredDocument
    followed: list[PageLink] = field(default_factory=list)


def _index_document(page: StudentJobPage) -> _PageResult:
    structured: dict[str, Any] = {
        "page_role": "index",
        "unit": page.unit,
        "organization": page.organization,
        "university": "Stanford University",
        "source_note": page.note,
    }
    document = fetch_document(
        page.url,
        kind_hint=OpportunityType.ON_CAMPUS,
        external_key=external_key_for(page.url, page),
        structured=structured,
    )
    if not document.ok or not document.html:
        return _PageResult(document=document)

    followed = detail_links(document.html, page)
    document.structured["contact_emails"] = extract_emails(document.html, page.url)
    document.structured["linked_documents"] = linked_documents(document.html, page.url)
    document.structured["detail_urls"] = [link.url for link in followed]
    return _PageResult(document=document, followed=followed)


def _detail_document(link: PageLink, page: StudentJobPage) -> DiscoveredDocument:
    structured: dict[str, Any] = {
        "page_role": "posting",
        "unit": page.unit,
        "organization": page.organization,
        "university": "Stanford University",
        "index_url": page.url,
        "link_text": link.text,
    }
    document = fetch_document(
        link.url,
        kind_hint=OpportunityType.ON_CAMPUS,
        external_key=external_key_for(link.url, page),
        structured=structured,
        title=link.text or None,
    )
    if document.ok and document.html:
        document.structured["contact_emails"] = extract_emails(document.html, link.url)
        document.structured["linked_documents"] = linked_documents(document.html, link.url)
    return document


class StanfordStudentJobsAdapter(SourceAdapter):
    slug = "stanford_student_jobs"
    name = "Stanford student job pages"
    kind = SourceKind.CAMPUS_JOBS
    base_url = "https://thehub.stanford.edu/jobs"
    requires_auth = False
    is_public = True
    is_mocked = False
    notes = (
        "Crawls the public unit-run student-job pages verified to serve real "
        "postings: The Hub @ Lathrop, R&DE student employment and dining student "
        f"engagement, Recreation & Wellness, and ResEd internships. Depth {CRAWL_DEPTH}, "
        f"at most {MAX_DETAIL_PAGES_PER_SOURCE} job-description pages per source. "
        "Off-site descriptions (Google Docs, PDFs) and application forms are recorded "
        "as linked documents, not fetched."
    )

    def discover(self, ctx: SourceContext) -> Iterable[DiscoveredDocument]:
        return self._documents(ctx)

    def _documents(self, ctx: SourceContext) -> Iterator[DiscoveredDocument]:
        budget = max(ctx.limit, 1)
        emitted = 0
        seen: set[str] = set()

        for page in SOURCE_PAGES:
            if emitted >= budget:
                return
            result = _index_document(page)
            seen.add(normalise_url(page.url))
            yield result.document
            emitted += 1

            for link in result.followed:
                if emitted >= budget:
                    return
                if link.url in seen:
                    continue
                seen.add(link.url)
                yield _detail_document(link, page)
                emitted += 1
