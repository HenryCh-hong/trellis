"""Fetch an arbitrary URL the student pasted — and the shared page→document primitive.

``fetch_document`` is the single place in this package that turns a
:class:`FetchResult` into a :class:`DiscoveredDocument`.  Every crawling adapter
goes through it so that the three ways a fetch can succeed at the HTTP level and
still carry nothing usable — a binary body, a robots block, a client-rendered
shell — are reported as an explicit ``error`` rather than silently handed
downstream as mojibake that an extractor would happily "read".
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from app.models.enums import OpportunityType, SourceKind
from app.sources.base import DiscoveredDocument, SourceAdapter, SourceContext
from app.sources.http import get_fetcher

#: Content types whose bytes are meaningful as text. Anything else (PDF, Word,
#: images) is refused rather than decoded — the fetcher hands us ``str``, so a
#: PDF would otherwise become several kilobytes of convincing-looking garbage.
TEXTUAL_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xhtml",
    "application/xml",
    "+xml",
    "application/javascript",
)

#: Markers of a single-page app whose content is assembled in the browser.
SPA_MARKERS = (
    'id="root"',
    "id='root'",
    'id="__next"',
    "you need to enable javascript",
    "please enable javascript",
    "ng-app",
)

#: Below this many characters of body text we stop believing a page rendered.
MIN_SERVER_RENDERED_CHARS = 200

CLIENT_RENDERED_ERROR = (
    "client-rendered page: the server returned an empty app shell, so there is no "
    "text to read. Import it through the browser extension or paste the content."
)


def is_textual(content_type: str | None) -> bool:
    if not content_type:
        # Servers that omit the header are almost always serving HTML.
        return True
    lowered = content_type.lower()
    return any(marker in lowered for marker in TEXTUAL_CONTENT_TYPES)


def looks_client_rendered(html: str | None, text: str | None) -> bool:
    if not html:
        return False
    if text and len(text.strip()) >= MIN_SERVER_RENDERED_CHARS:
        return False
    lowered = html.lower()
    return any(marker in lowered for marker in SPA_MARKERS)


def fetch_document(
    url: str,
    *,
    kind_hint: OpportunityType | None = None,
    external_key: str | None = None,
    structured: dict[str, Any] | None = None,
    title: str | None = None,
) -> DiscoveredDocument:
    """Fetch one URL into a document. Never raises — failure becomes ``error``."""
    result = get_fetcher().fetch(url)
    payload: dict[str, Any] = dict(structured or {})

    if not result.ok:
        return DiscoveredDocument(
            url=url,
            title=title,
            kind_hint=kind_hint,
            external_key=external_key,
            structured=payload,
            fetched_at=result.fetched_at,
            http_status=result.status,
            error=result.error or f"HTTP {result.status}",
        )

    if not is_textual(result.content_type):
        payload["content_type"] = result.content_type
        return DiscoveredDocument(
            url=url,
            title=title,
            kind_hint=kind_hint,
            external_key=external_key,
            structured=payload,
            fetched_at=result.fetched_at,
            http_status=result.status,
            error=f"non-textual content ({result.content_type}) is not parsed server-side",
        )

    if looks_client_rendered(result.html, result.text):
        payload["client_rendered"] = True
        return DiscoveredDocument(
            url=url,
            title=title or result.title,
            html=result.html,
            kind_hint=kind_hint,
            external_key=external_key,
            structured=payload,
            fetched_at=result.fetched_at,
            http_status=result.status,
            error=CLIENT_RENDERED_ERROR,
        )

    if result.content_type:
        payload.setdefault("content_type", result.content_type)

    return DiscoveredDocument(
        url=url,
        title=title or result.title,
        text=result.text,
        html=result.html,
        kind_hint=kind_hint,
        external_key=external_key,
        structured=payload,
        fetched_at=result.fetched_at,
        http_status=result.status,
    )


def parse_url_list(raw: str | None) -> list[str]:
    """Split a pasted blob into http(s) URLs, order-preserving and de-duplicated."""
    if not raw:
        return []
    seen: set[str] = set()
    urls: list[str] = []
    for token in raw.replace(",", " ").split():
        candidate = token.strip().strip("<>\"'")
        if not candidate.lower().startswith(("http://", "https://")):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


class ManualUrlAdapter(SourceAdapter):
    """Whatever the student pastes: one URL in, one document out.

    The escape hatch for everything the built-in adapters do not cover — a
    departmental page, a Google Doc job description, a professor's "we are
    hiring" post.
    """

    slug = "manual_url"
    name = "Pasted URL"
    kind = SourceKind.MANUAL
    base_url = None
    requires_auth = False
    is_public = True
    is_mocked = False
    notes = (
        "Fetches exactly the URLs given in the search context (whitespace- or "
        "comma-separated). Nothing is crawled beyond them."
    )

    def discover(self, ctx: SourceContext) -> Iterable[DiscoveredDocument]:
        urls = parse_url_list(ctx.query)[: max(ctx.limit, 1)]
        return self._documents(urls)

    def _documents(self, urls: list[str]) -> Iterator[DiscoveredDocument]:
        for url in urls:
            yield fetch_document(url, structured={"origin": "pasted_url"})
