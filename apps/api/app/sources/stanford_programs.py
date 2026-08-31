"""Formal undergraduate research programs at Stanford.

These are the structured, deadline-bearing routes into research — CURIS, PURE,
CS independent study, and the VPUE grant and fellowship family — as opposed to
the unstructured route of emailing a professor.  They matter because they are
the ones with an actual application to prepare for.

One honest limitation is encoded here rather than papered over: ``curis.stanford.edu``
is a client-rendered React app.  Its HTML shell contains no program text at all,
so those documents come back flagged ``client_rendered`` with an explicit error
instead of an empty body that would read like "this program has no requirements".
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.models.enums import OpportunityType, SourceKind
from app.sources.base import DiscoveredDocument, SourceAdapter, SourceContext
from app.sources.lab_site import (
    PageLink,
    extract_emails,
    is_document_link,
    normalise_url,
    same_host_links,
)
from app.sources.manual_url import fetch_document

MAX_FOLLOWED_PER_SEED = 8
MAX_PAGES_TOTAL = 24

PROGRAM_LINK_RE = re.compile(
    r"(grant|fellow|scholar|research|intern|program|opportunit|curis|pure|reu|summer|stipend)",
    re.IGNORECASE,
)
PROGRAM_LINK_EXCLUDE_RE = re.compile(
    r"(/login|/saml|/user/|/search|/node/\d+$|privacy|accessibility|"
    r"non-discrimination|instagram|twitter|facebook|linkedin)",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class ProgramPage:
    url: str
    label: str
    organization: str
    follow: bool = False
    note: str = ""


PROGRAM_PAGES: tuple[ProgramPage, ...] = (
    ProgramPage(
        url="https://curis.stanford.edu/",
        label="CURIS — CS undergraduate research internships",
        organization="Stanford Computer Science Department (CURIS)",
        note="Client-rendered React app; the shell carries no program text server-side.",
    ),
    ProgramPage(
        url="https://curis.stanford.edu/summer/",
        label="CURIS Summer Internship Program",
        organization="Stanford Computer Science Department (CURIS)",
        note="Client-rendered React app; the shell carries no program text server-side.",
    ),
    ProgramPage(
        url="https://curis.stanford.edu/pure_student/",
        label="PURE — Paid Undergraduate Research Experience",
        organization="Stanford Computer Science Department (CURIS)",
        note="Client-rendered React app; the shell carries no program text server-side.",
    ),
    ProgramPage(
        url="https://curis.stanford.edu/year_round_cs_projects/",
        label="CURIS year-round CS research projects",
        organization="Stanford Computer Science Department (CURIS)",
        note="Client-rendered React app; the shell carries no program text server-side.",
    ),
    ProgramPage(
        url="https://curis.stanford.edu/curis_fellowships",
        label="CURIS fellowships",
        organization="Stanford Computer Science Department (CURIS)",
        note="Client-rendered React app; the shell carries no program text server-side.",
    ),
    ProgramPage(
        url="https://www.cs.stanford.edu/bachelors/research-opportunities",
        label="CS undergraduate research opportunities",
        organization="Stanford Computer Science Department",
        follow=True,
    ),
    ProgramPage(
        url="https://www.cs.stanford.edu/research/independent-study-research",
        label="CS independent study and research (CS 191/195/199)",
        organization="Stanford Computer Science Department",
    ),
    ProgramPage(
        url="https://undergradresearch.stanford.edu/",
        label="Undergraduate Research and Independent Projects (VPUE)",
        organization="Stanford Vice Provost for Undergraduate Education",
        follow=True,
    ),
    ProgramPage(
        url="https://undergradresearch.stanford.edu/fund-your-project/explore-student-grants",
        label="VPUE undergraduate research student grants",
        organization="Stanford Vice Provost for Undergraduate Education",
        follow=True,
    ),
)

_SEED_URLS = frozenset(normalise_url(page.url) for page in PROGRAM_PAGES)


def program_links(html: str, page: ProgramPage) -> list[PageLink]:
    """Same-host program pages worth following from a hub page."""
    out: list[PageLink] = []
    for link in same_host_links(html, page.url, main_only=True):
        if link.url in _SEED_URLS or is_document_link(link.url):
            continue
        if PROGRAM_LINK_EXCLUDE_RE.search(link.url):
            continue
        haystack = f"{urlparse(link.url).path} {link.text}"
        if PROGRAM_LINK_RE.search(haystack):
            out.append(link)
    return out[:MAX_FOLLOWED_PER_SEED]


def external_key_for(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.").split(".", 1)[0]
    slug = re.sub(r"[^a-z0-9]+", "-", parsed.path.lower()).strip("-") or "index"
    return f"stanford-{host}-{slug}"


def _document(
    url: str,
    page: ProgramPage,
    *,
    link_text: str | None = None,
    hub_url: str | None = None,
) -> DiscoveredDocument:
    structured: dict[str, Any] = {
        "page_role": "program",
        "program_label": link_text or page.label,
        "organization": page.organization,
        "university": "Stanford University",
    }
    if hub_url:
        structured["hub_url"] = hub_url
    if page.note and hub_url is None:
        structured["source_note"] = page.note
    document = fetch_document(
        url,
        kind_hint=OpportunityType.RESEARCH_OPENING,
        external_key=external_key_for(url),
        structured=structured,
        title=link_text or None,
    )
    if document.ok and document.html:
        document.structured["contact_emails"] = extract_emails(document.html, url)
    return document


class StanfordProgramsAdapter(SourceAdapter):
    slug = "stanford_programs"
    name = "Stanford undergraduate research programs"
    kind = SourceKind.PROGRAM
    base_url = "https://undergradresearch.stanford.edu/"
    requires_auth = False
    is_public = True
    is_mocked = False
    notes = (
        "CURIS/PURE, CS independent study, and the VPUE grant and fellowship pages. "
        f"Follows at most {MAX_FOLLOWED_PER_SEED} same-host program links per hub page "
        f"and {MAX_PAGES_TOTAL} pages in total. curis.stanford.edu is a client-rendered "
        "app, so its pages are returned flagged as unreadable server-side rather than "
        "as empty programs."
    )

    def discover(self, ctx: SourceContext) -> Iterable[DiscoveredDocument]:
        return self._documents(ctx)

    def _documents(self, ctx: SourceContext) -> Iterator[DiscoveredDocument]:
        budget = min(max(ctx.limit, 1), MAX_PAGES_TOTAL)
        emitted = 0
        seen: set[str] = set()

        for page in PROGRAM_PAGES:
            if emitted >= budget:
                return
            key = normalise_url(page.url)
            if key in seen:
                continue
            seen.add(key)
            document = _document(page.url, page)
            yield document
            emitted += 1

            if not page.follow or not document.ok or not document.html:
                continue
            for link in program_links(document.html, page):
                if emitted >= budget:
                    return
                if link.url in seen:
                    continue
                seen.add(link.url)
                yield _document(link.url, page, link_text=link.text, hub_url=page.url)
                emitted += 1
