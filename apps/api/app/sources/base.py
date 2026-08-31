"""Source adapter abstraction.

Discovery is deliberately not one scraper: each source knows how to enumerate
its own documents and hand back *raw* material.  Normalisation into the
unified opportunity schema happens once, downstream, in the extraction agent —
so adding a source never touches ranking, dedup or the UI.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.enums import OpportunityType, SourceKind


@dataclass(slots=True)
class DiscoveredDocument:
    """One fetched thing that may contain one or more opportunities."""

    url: str
    title: str | None = None
    text: str | None = None
    html: str | None = None
    kind_hint: OpportunityType | None = None
    external_key: str | None = None
    # Fields the adapter could read directly from a structured API and that the
    # extractor should therefore trust over anything it infers from prose.
    structured: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime | None = None
    http_status: int | None = None
    error: str | None = None
    retrieved_by: str = "server"

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text or self.html or self.structured)


@dataclass(slots=True)
class SourceContext:
    """What the search agent knows when it asks a source for documents."""

    university: str
    query: str | None = None
    keywords: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    limit: int = 50


class SourceAdapter(ABC):
    slug: str = "base"
    name: str = "Base source"
    kind: SourceKind = SourceKind.MANUAL
    base_url: str | None = None
    requires_auth: bool = False
    is_public: bool = True
    # True for adapters that cannot fetch on their own and are fed by the
    # browser extension or a user paste. Marked in the UI as such.
    is_mocked: bool = False
    notes: str = ""
    # Shown to the student when this source legitimately returns nothing, so an
    # empty result reads as a fact about the source rather than a failure.
    empty_note: str = ""

    @abstractmethod
    def discover(self, ctx: SourceContext) -> Iterable[DiscoveredDocument]:
        """Yield documents. Must not raise for a single bad page — mark the
        document with ``error`` and continue, so one dead link cannot fail a run."""

    def describe(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "kind": self.kind.value,
            "base_url": self.base_url,
            "requires_auth": self.requires_auth,
            "is_public": self.is_public,
            "is_mocked": self.is_mocked,
            "notes": self.notes,
        }
