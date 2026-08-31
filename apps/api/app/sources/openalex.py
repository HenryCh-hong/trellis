"""OpenAlex — what a professor is actually working on *now*.

A faculty bio is a description of the last decade.  A list of their last two
years of papers is a description of this year, and that is the difference
between a cold email that lands and one that reads as generic.  So this adapter
resolves a name to an OpenAlex author scoped to Stanford, then pulls their most
recent works, newest first.

Everything returned here is a citation with a URL: title, year, venue, DOI,
co-authors.  Nothing is summarised or interpreted at this layer.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date
from typing import Any
from urllib.parse import quote, urlencode

from app.core.config import get_settings
from app.models.enums import SourceKind
from app.sources.base import DiscoveredDocument, SourceAdapter, SourceContext
from app.sources.http import get_fetcher

API_BASE = "https://api.openalex.org"
AUTHORS_URL = f"{API_BASE}/authors"
WORKS_URL = f"{API_BASE}/works"

#: Stanford University's ROR identifier.
STANFORD_ROR = "00f54p054"

#: ``affiliations.institution.ror`` matches any affiliation OpenAlex has ever
#: recorded for the author. ``last_known_institutions.ror`` was tried first and
#: returns zero results even for current Stanford faculty, so it is not used.
AFFILIATION_FILTER = "affiliations.institution.ror"

AUTHOR_SELECT = "id,display_name,display_name_alternatives,orcid,works_count,cited_by_count,last_known_institutions"
WORK_SELECT = (
    "id,doi,title,display_name,publication_year,publication_date,type,primary_location,authorships"
)

DEFAULT_WORK_LIMIT = 10
MAX_AUTHOR_CANDIDATES = 25
MAX_LISTED_AUTHORS = 25


def _polite_params() -> dict[str, str]:
    """OpenAlex asks for a contact address; sending one gets the faster pool."""
    email = get_settings().fetch_contact_email
    return {"mailto": email} if email else {}


def _build_url(base: str, *, filters: str, **params: str) -> str:
    # ``filter`` uses bare ':' and ',' as its own syntax, so those two characters
    # are left alone while everything else (spaces in a name, most of all) is
    # percent-escaped. Values must therefore arrive here *unescaped*.
    query = {"filter": filters, **params, **_polite_params()}
    return f"{base}?{urlencode(query, safe=':,', quote_via=quote)}"


def _normalise_name(name: str) -> str:
    return " ".join("".join(ch for ch in name.lower() if ch.isalnum() or ch.isspace()).split())


def _results(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


def author_candidates(name: str, *, ror: str = STANFORD_ROR) -> list[dict[str, Any]]:
    """Every Stanford-affiliated OpenAlex author matching ``name``."""
    cleaned = name.strip()
    if not cleaned:
        return []
    url = _build_url(
        AUTHORS_URL,
        filters=f"display_name.search:{cleaned},{AFFILIATION_FILTER}:{ror}",
        select=AUTHOR_SELECT,
    )
    url = f"{url}&per-page={MAX_AUTHOR_CANDIDATES}"
    _, payload, error = get_fetcher().get_json(url)
    if error is not None:
        return []
    return _results(payload)


def pick_author(name: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Exact name match wins; otherwise the most prolific candidate.

    OpenAlex splits some people across duplicate author records, so an
    unqualified "first result" pick routinely lands on a one-paper stub.
    """
    if not candidates:
        return None
    target = _normalise_name(name)
    exact = [c for c in candidates if _normalise_name(str(c.get("display_name") or "")) == target]
    pool = exact or candidates
    return max(pool, key=lambda c: int(c.get("works_count") or 0))


def find_author(name: str, *, ror: str = STANFORD_ROR) -> dict[str, Any] | None:
    return pick_author(name, author_candidates(name, ror=ror))


def work_to_dict(work: dict[str, Any]) -> dict[str, Any]:
    """One OpenAlex work as a citation — every field taken verbatim."""
    location = work.get("primary_location")
    location = location if isinstance(location, dict) else {}
    source = location.get("source")
    source = source if isinstance(source, dict) else {}

    authors: list[str] = []
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if isinstance(author, dict) and author.get("display_name"):
            authors.append(str(author["display_name"]))
        if len(authors) >= MAX_LISTED_AUTHORS:
            break

    doi = work.get("doi")
    url = location.get("landing_page_url") or doi or work.get("id")
    return {
        "openalex_id": work.get("id"),
        "title": work.get("title") or work.get("display_name"),
        "year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "venue": source.get("display_name"),
        "doi": doi,
        "url": url,
        "authors": authors,
        "type": work.get("type"),
    }


def recent_works(
    author_name: str,
    since_year: int | None = None,
    limit: int = DEFAULT_WORK_LIMIT,
) -> list[dict[str, Any]]:
    """The author's most recent works, newest first.

    Returns ``[]`` — never a guess — when the author cannot be resolved.
    """
    author = find_author(author_name)
    if author is None or not author.get("id"):
        return []
    return works_for_author(str(author["id"]), since_year=since_year, limit=limit)


def works_for_author(
    author_id: str,
    *,
    since_year: int | None = None,
    limit: int = DEFAULT_WORK_LIMIT,
) -> list[dict[str, Any]]:
    settings = get_settings()
    if since_year is None:
        months = max(settings.recency_window_months, 1)
        since_year = date.today().year - max(months // 12, 1)
    per_page = max(min(limit, 200), 1)
    short_id = author_id.rsplit("/", 1)[-1]
    url = _build_url(
        WORKS_URL,
        filters=f"author.id:{short_id},from_publication_date:{since_year}-01-01",
        select=WORK_SELECT,
    )
    url = f"{url}&sort=publication_date:desc&per-page={per_page}"
    _, payload, error = get_fetcher().get_json(url)
    if error is not None:
        return []
    return [work_to_dict(work) for work in _results(payload)][:limit]


class OpenAlexAdapter(SourceAdapter):
    slug = "openalex"
    name = "OpenAlex scholarly index"
    kind = SourceKind.SCHOLARLY
    base_url = API_BASE
    requires_auth = False
    is_public = True
    is_mocked = False
    notes = (
        "Resolves a faculty name to a Stanford-affiliated OpenAlex author "
        f"(ROR {STANFORD_ROR}) and returns their recent works newest-first, as "
        "citations with DOIs. This is what makes 'current research direction' "
        "evidence rather than a bio keyword. Author name goes in the search "
        "context's query."
    )

    def discover(self, ctx: SourceContext) -> Iterable[DiscoveredDocument]:
        return self._documents(ctx)

    def _documents(self, ctx: SourceContext) -> Iterator[DiscoveredDocument]:
        name = (ctx.query or "").strip()
        if not name:
            return

        author = find_author(name)
        if author is None:
            yield DiscoveredDocument(
                url=f"{AUTHORS_URL}?filter=display_name.search:{quote(name)}",
                title=name,
                structured={"query": name, "matched": False},
                error=f"no Stanford-affiliated OpenAlex author matched {name!r}",
            )
            return

        author_ref = {
            "author_openalex_id": author.get("id"),
            "author_display_name": author.get("display_name"),
            "author_orcid": author.get("orcid"),
            "author_works_count": author.get("works_count"),
            "query": name,
        }
        works = works_for_author(str(author.get("id") or ""), limit=max(ctx.limit, 1))
        for work in works:
            title = work["title"] or "Untitled work"
            body_lines = [title]
            if work["venue"]:
                body_lines.append(str(work["venue"]))
            if work["publication_date"]:
                body_lines.append(str(work["publication_date"]))
            if work["authors"]:
                body_lines.append(", ".join(work["authors"]))
            yield DiscoveredDocument(
                url=str(work["url"] or work["openalex_id"] or API_BASE),
                title=title,
                text="\n".join(body_lines),
                external_key=str(work["openalex_id"]) if work["openalex_id"] else None,
                structured={**work, **author_ref},
            )
