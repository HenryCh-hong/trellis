"""Stanford CS faculty directory, sliced by research area.

``cs.stanford.edu/people-cs/faculty-research/<area>`` is a real, server-rendered
page listing every CS faculty member working in one area, with their short title.
That is exactly the right entry point for outreach: it answers "who at Stanford
works on the thing I care about" without any inference at all.

This adapter deliberately stops there.  It yields one document per person with
the directory's own facts — name, title, profile URL, area — and leaves the
expensive, evidence-hungry work (lab site, recent papers, whether they take
undergraduates) to ``lab_site`` and ``openalex``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.models.enums import OpportunityType, SourceKind
from app.sources.base import DiscoveredDocument, SourceAdapter, SourceContext
from app.sources.manual_url import fetch_document

#: The canonical host. ``cs.stanford.edu`` 301s here, and ``/people/<slug>``
#: only resolves on ``www`` — so build absolute URLs against this one.
BASE_URL = "https://www.cs.stanford.edu/"
AREA_URL = "https://www.cs.stanford.edu/people-cs/faculty-research/{area}"

#: Area slugs verified to return HTTP 200.
AREA_SLUGS: tuple[str, ...] = (
    "artificial-intelligence",
    "machine-learning",
    "natural-language-processing-and-speech",
    "computer-vision",
    "human-computer-interaction-hci",
    "human-centered-and-creative-ai",
    "robotics",
    "reinforcement-learning",
    "computational-education",
    "empirical-machine-learning",
)

#: How a student's interest topics map onto those area pages. Aliases are
#: normalised (lowercased, punctuation to hyphens) before lookup, so
#: "Natural Language Processing", "nlp" and "natural-language-processing" all land.
TOPIC_TO_AREAS: dict[str, tuple[str, ...]] = {
    "ai": ("artificial-intelligence",),
    "artificial-intelligence": ("artificial-intelligence",),
    "machine-learning": ("machine-learning", "empirical-machine-learning"),
    "ml": ("machine-learning", "empirical-machine-learning"),
    "deep-learning": ("machine-learning",),
    "statistical-learning": ("machine-learning",),
    "nlp": ("natural-language-processing-and-speech",),
    "natural-language-processing": ("natural-language-processing-and-speech",),
    "natural-language-processing-and-speech": ("natural-language-processing-and-speech",),
    "computational-linguistics": ("natural-language-processing-and-speech",),
    "speech": ("natural-language-processing-and-speech",),
    "language-models": ("natural-language-processing-and-speech", "empirical-machine-learning"),
    "large-language-models": (
        "natural-language-processing-and-speech",
        "empirical-machine-learning",
    ),
    "llm": ("natural-language-processing-and-speech", "empirical-machine-learning"),
    "llms": ("natural-language-processing-and-speech", "empirical-machine-learning"),
    "computer-vision": ("computer-vision",),
    "cv": ("computer-vision",),
    "vision": ("computer-vision",),
    "multimodal": ("computer-vision", "natural-language-processing-and-speech"),
    "graphics": ("computer-vision",),
    "hci": ("human-computer-interaction-hci",),
    "human-computer-interaction": ("human-computer-interaction-hci",),
    "human-computer-interaction-hci": ("human-computer-interaction-hci",),
    "user-interfaces": ("human-computer-interaction-hci",),
    "design": ("human-computer-interaction-hci",),
    "human-centered-ai": ("human-centered-and-creative-ai",),
    "human-centered-and-creative-ai": ("human-centered-and-creative-ai",),
    "creative-ai": ("human-centered-and-creative-ai",),
    "generative-ai": ("human-centered-and-creative-ai", "machine-learning"),
    "ai-ethics": ("human-centered-and-creative-ai",),
    "responsible-ai": ("human-centered-and-creative-ai",),
    "ai-safety": ("human-centered-and-creative-ai", "empirical-machine-learning"),
    "alignment": ("human-centered-and-creative-ai", "empirical-machine-learning"),
    "robotics": ("robotics",),
    "robot-learning": ("robotics", "reinforcement-learning"),
    "manipulation": ("robotics",),
    "autonomous-vehicles": ("robotics",),
    "control": ("robotics",),
    "reinforcement-learning": ("reinforcement-learning",),
    "rl": ("reinforcement-learning",),
    "decision-making": ("reinforcement-learning",),
    "sequential-decision-making": ("reinforcement-learning",),
    "computational-education": ("computational-education",),
    "cs-education": ("computational-education",),
    "education": ("computational-education",),
    "learning-sciences": ("computational-education",),
    "edtech": ("computational-education",),
    "empirical-machine-learning": ("empirical-machine-learning",),
    "foundation-models": ("empirical-machine-learning", "machine-learning"),
    "evaluation": ("empirical-machine-learning",),
    "benchmarks": ("empirical-machine-learning",),
}

#: Cards on the directory page; the class names are Stanford's Drupal design system.
_CARD_SELECTOR = "div.ds-entity--stanford-person"
_NAME_SELECTOR = ".node-title a"
_TITLE_SELECTOR = ".su-person-short-title"


def normalise_topic(topic: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in topic)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")


def areas_for_topics(topics: Iterable[str]) -> list[str]:
    """Area slugs to crawl for a set of interest topics, in directory order."""
    wanted: set[str] = set()
    for topic in topics:
        key = normalise_topic(topic)
        if not key:
            continue
        if key in AREA_SLUGS:
            wanted.add(key)
        wanted.update(TOPIC_TO_AREAS.get(key, ()))
    return [area for area in AREA_SLUGS if area in wanted]


def area_url(area: str) -> str:
    return AREA_URL.format(area=area)


def profile_slug(profile_url: str) -> str:
    path = urlparse(profile_url).path.strip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def parse_area_page(html: str, *, area: str, page_url: str) -> list[dict[str, Any]]:
    """One record per faculty card. Only what the directory literally states."""
    tree = HTMLParser(html)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for card in tree.css(_CARD_SELECTOR):
        anchor = card.css_first(_NAME_SELECTOR) or card.css_first("a[href*='/people/']")
        if anchor is None:
            continue
        href = (anchor.attributes.get("href") or "").strip()
        name = anchor.text(strip=True)
        if not href or not name:
            continue
        profile_url = urljoin(page_url, href)
        if profile_url in seen:
            continue
        seen.add(profile_url)
        title_node = card.css_first(_TITLE_SELECTOR)
        records.append(
            {
                "name": name,
                "title": title_node.text(strip=True) if title_node else None,
                "profile_url": profile_url,
                "area": area,
            }
        )

    if records:
        return records

    # The design-system card class is the stable hook, but never assume markup:
    # fall back to bare profile links so a template change degrades to fewer
    # fields rather than to zero faculty.
    for anchor in tree.css("a[href*='/people/']"):
        href = (anchor.attributes.get("href") or "").strip()
        name = anchor.text(strip=True)
        if not href or not name:
            continue
        profile_url = urljoin(page_url, href)
        if profile_url in seen:
            continue
        seen.add(profile_url)
        records.append(
            {"name": name, "title": None, "profile_url": profile_url, "area": area}
        )
    return records


def faculty_document(record: dict[str, Any], areas: list[str]) -> DiscoveredDocument:
    slug = profile_slug(record["profile_url"])
    structured: dict[str, Any] = {
        "name": record["name"],
        "title": record["title"],
        "profile_url": record["profile_url"],
        "area": record["area"],
        "areas": areas,
        "department": "Computer Science",
        "university": "Stanford University",
        "directory_url": area_url(record["area"]),
    }
    body = record["name"] if not record["title"] else f"{record['name']}\n{record['title']}"
    return DiscoveredDocument(
        url=record["profile_url"],
        title=record["name"],
        text=body,
        kind_hint=OpportunityType.RESEARCH_OUTREACH,
        external_key=f"stanford-cs-faculty-{slug}" if slug else None,
        structured=structured,
    )


class StanfordCsFacultyAdapter(SourceAdapter):
    slug = "stanford_cs_faculty"
    name = "Stanford CS faculty directory"
    kind = SourceKind.FACULTY_DIRECTORY
    base_url = BASE_URL
    requires_auth = False
    is_public = True
    is_mocked = False
    notes = (
        "Reads cs.stanford.edu/people-cs/faculty-research/<area> for the areas that "
        "match the student's interests. Yields one document per faculty member with "
        "the directory's own name, short title, profile URL and area — no inference. "
        "With no matching interests it reads every area page."
    )

    def discover(self, ctx: SourceContext) -> Iterable[DiscoveredDocument]:
        return self._documents(ctx)

    def _documents(self, ctx: SourceContext) -> Iterator[DiscoveredDocument]:
        areas = areas_for_topics([*ctx.topics, *ctx.keywords]) or list(AREA_SLUGS)
        budget = max(ctx.limit, 1)

        # profile_url -> (record, areas it appeared in)
        found: dict[str, tuple[dict[str, Any], list[str]]] = {}
        order: list[str] = []

        for area in areas:
            url = area_url(area)
            document = fetch_document(url, structured={"area": area, "page_role": "directory"})
            if not document.ok or not document.html:
                yield document
                continue
            for record in parse_area_page(document.html, area=area, page_url=url):
                key = record["profile_url"]
                if key in found:
                    seen_areas = found[key][1]
                    if area not in seen_areas:
                        seen_areas.append(area)
                    continue
                found[key] = (record, [area])
                order.append(key)

        for key in order[:budget]:
            record, record_areas = found[key]
            yield faculty_document(record, record_areas)
