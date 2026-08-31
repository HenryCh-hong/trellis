"""Generic bounded crawler for a single lab / research-group website.

A lab site is the only place where the things that actually decide a cold email
live: whether undergraduates are on the people page, whether the join page says
"not taking students", what the group shipped in the last year.  So this adapter
fetches the home page plus a handful of *named* sections and hands them back
whole — interpretation belongs to the research agent, not here.

This module also owns the link-extraction helpers the other crawling adapters in
this package share, because a bounded page-graph walk is exactly what they all do.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse

from selectolax.parser import HTMLParser

from app.models.enums import OpportunityType, SourceKind
from app.sources.base import DiscoveredDocument, SourceAdapter, SourceContext
from app.sources.manual_url import fetch_document

#: Section name -> substrings that identify it in a URL path or link text.
#: Order matters: the first role a link matches is the one it is filed under.
SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "join": (
        "join",
        "opening",
        "position",
        "hiring",
        "recruit",
        "prospective",
        "opportunit",
        "work-with",
        "apply",
        "jobs",
    ),
    "people": ("people", "member", "team", "group", "students", "lab-members", "who-we-are"),
    "news": ("news", "update", "blog", "announcement"),
    "publications": ("publication", "papers", "pubs", "preprint"),
    "research": ("research", "projects", "project", "work"),
}

MAX_LAB_PAGES = 6

#: File extensions we will not fetch server-side (the fetcher returns text, so a
#: PDF would decode into noise). They are still reported as linked documents.
DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".csv")

#: Hosts that serve a real job description but only to a browser (JS/consent
#: walls, or an application form). Recorded, never fetched.
OFFSITE_DOCUMENT_HOSTS = (
    "drive.google.com",
    "docs.google.com",
    "forms.gle",
    "form.asana.com",
    "teamworksapp.com",
    "app.smartsheet.com",
    "airtable.com",
)


@dataclass(slots=True, frozen=True)
class PageLink:
    url: str
    text: str

    @property
    def host(self) -> str:
        return urlparse(self.url).netloc.lower()


def normalise_url(url: str) -> str:
    """Drop the fragment and any trailing slash so two spellings dedupe to one."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def extract_links(html: str, base_url: str, *, main_only: bool = True) -> list[PageLink]:
    """Absolute, de-duplicated http(s) links, preferring the main content region.

    ``main_only`` keeps site-wide navigation out of the crawl frontier, which is
    what stops a five-page walk from turning into a whole-site mirror.
    """
    tree = HTMLParser(html)
    root = None
    if main_only:
        root = tree.css_first("main") or tree.css_first("article")
    root = root or tree.body
    if root is None:
        return []

    seen: set[str] = set()
    links: list[PageLink] = []
    for node in root.css("a"):
        href = (node.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = normalise_url(urljoin(base_url, href))
        if not absolute.lower().startswith(("http://", "https://")):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(PageLink(url=absolute, text=node.text(strip=True)))
    return links


def same_host_links(html: str, base_url: str, *, main_only: bool = True) -> list[PageLink]:
    host = urlparse(base_url).netloc.lower()
    bare = host.removeprefix("www.")
    return [
        link
        for link in extract_links(html, base_url, main_only=main_only)
        if link.host == host or link.host.removeprefix("www.") == bare
    ]


def extract_emails(html: str, base_url: str) -> list[str]:
    """Contact addresses published on the page, in document order."""
    tree = HTMLParser(html)
    root = tree.css_first("main") or tree.body
    if root is None:
        return []
    seen: set[str] = set()
    emails: list[str] = []
    for node in root.css("a"):
        href = (node.attributes.get("href") or "").strip()
        if not href.lower().startswith("mailto:"):
            continue
        address = href[7:].split("?", 1)[0].strip().lower()
        if address and address not in seen:
            seen.add(address)
            emails.append(address)
    return emails


def is_document_link(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(DOCUMENT_EXTENSIONS)


def is_offsite_document(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == known or host.endswith("." + known) for known in OFFSITE_DOCUMENT_HOSTS)


def link_role(link: PageLink) -> str | None:
    """Which lab-site section a link points at, if any."""
    haystack = f"{urlparse(link.url).path.lower()} {link.text.lower()}"
    for role, keywords in SECTION_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return role
    return None


def crawl_lab(url: str, *, max_pages: int = MAX_LAB_PAGES) -> list[DiscoveredDocument]:
    """Home page plus up to ``max_pages - 1`` linked sections on the same host.

    One section per role first, so a site with twelve publication pages cannot
    crowd out the join page — which is the one that actually matters.
    """
    home = fetch_document(
        url,
        kind_hint=OpportunityType.RESEARCH_OUTREACH,
        structured={"lab_url": url, "page_role": "home"},
    )
    documents = [home]
    if not home.ok or not home.html:
        return documents

    by_role: dict[str, PageLink] = {}
    extras: list[PageLink] = []
    home_url = normalise_url(url)
    for link in same_host_links(home.html, url, main_only=False):
        if link.url == home_url or is_document_link(link.url):
            continue
        role = link_role(link)
        if role is None:
            continue
        if role not in by_role:
            by_role[role] = link
        else:
            extras.append(link)

    ordered = [(role, by_role[role]) for role in SECTION_KEYWORDS if role in by_role]
    ordered.extend((link_role(link) or "other", link) for link in extras)

    for role, link in ordered[: max(max_pages - 1, 0)]:
        documents.append(
            fetch_document(
                link.url,
                kind_hint=OpportunityType.RESEARCH_OUTREACH,
                structured={"lab_url": url, "page_role": role, "link_text": link.text},
            )
        )
    return documents


class LabSiteAdapter(SourceAdapter):
    """Crawl one lab website, given its URL in ``SourceContext.query``."""

    slug = "lab_site"
    name = "Lab website"
    kind = SourceKind.LAB_SITE
    base_url = None
    requires_auth = False
    is_public = True
    is_mocked = False
    notes = (
        "Given a lab URL, fetches the home page plus up to five linked same-host "
        "sections (join / people / news / publications / research). Hard cap of "
        f"{MAX_LAB_PAGES} pages per lab; PDFs and off-site forms are recorded, not fetched."
    )

    def __init__(self, url: str | None = None) -> None:
        self.url = url

    def discover(self, ctx: SourceContext) -> Iterable[DiscoveredDocument]:
        target = self.url or (ctx.query or "").strip()
        return self._documents(target)

    def _documents(self, target: str) -> Iterator[DiscoveredDocument]:
        if not target.lower().startswith(("http://", "https://")):
            return
        yield from crawl_lab(target)
