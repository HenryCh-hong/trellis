"""What the student has already said no to.

Discovery must never hand back something that was explicitly dismissed. Finding
it again is not new information — the student already spent the attention once,
and re-offering it is the single fastest way to make a recommender feel like it
is not listening.

The feedback table itself belongs to the Signals phase and may not exist yet, so
every query here is written against ``information_schema`` first and degrades to
"nothing is suppressed" rather than failing a discovery run.  The moment the
table lands, this starts working with no edit: it looks for any table whose name
mentions signals or feedback, that carries an ``opportunity_id``, and that
records a kind among the ones that mean "do not show me this".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

#: The verdicts that mean "stop offering me this". Anything else in a signals
#: table (saved, interested, applied) is left alone.
NEGATIVE_KINDS = ("hidden", "not_relevant", "dismissed", "rejected", "not_interested")

#: Column names a feedback row might use for the verdict, most likely first.
_KIND_COLUMNS = ("kind", "signal", "signal_kind", "action", "verdict", "value", "type")

#: If one of these exists it marks a withdrawn signal, which must not suppress.
_CLEARED_COLUMNS = ("cleared_at", "undone_at", "removed_at", "deleted_at", "reverted_at")

_TABLE_SQL = """
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name LIKE ANY (ARRAY['%signal%', '%feedback%'])
"""


@dataclass(slots=True)
class Suppressions:
    """Everything discovery needs to avoid re-offering a rejected result."""

    opportunity_ids: set[uuid.UUID] = field(default_factory=set)
    #: Normalised source URLs, so a row that was deleted and then rediscovered
    #: from the same page is still not resurfaced.
    urls: set[str] = field(default_factory=set)
    external_keys: set[str] = field(default_factory=set)
    #: True only when a feedback table was actually found and read.
    available: bool = False

    def __bool__(self) -> bool:
        return bool(self.opportunity_ids or self.urls or self.external_keys)

    def blocks(self, *, url: str | None, external_key: str | None) -> bool:
        if external_key and external_key in self.external_keys:
            return True
        return bool(url and url in self.urls)


def _feedback_tables(db: Session) -> list[tuple[str, dict[str, None]]]:
    """Tables that could hold per-opportunity feedback, with their columns."""
    columns: dict[str, dict[str, None]] = {}
    for table_name, column_name in db.execute(text(_TABLE_SQL)):
        columns.setdefault(table_name, {})[column_name] = None
    return [
        (name, cols)
        for name, cols in sorted(columns.items())
        if "opportunity_id" in cols and any(c in cols for c in _KIND_COLUMNS)
    ]


def rejected_opportunity_ids(
    db: Session, profile_id: uuid.UUID | None = None
) -> tuple[set[uuid.UUID], bool]:
    """Opportunity ids the student has hidden or marked not relevant.

    Returns ``(ids, table_found)``.  ``table_found`` is False when the Signals
    phase has not landed yet, which is why the caller can tell "nothing was
    rejected" apart from "there is nowhere to record a rejection".
    """
    found = False
    ids: set[uuid.UUID] = set()

    for table_name, cols in _feedback_tables(db):
        kind_col = next(c for c in _KIND_COLUMNS if c in cols)
        where = [f"lower({kind_col}::text) = ANY(:kinds)"]
        params: dict[str, Any] = {"kinds": list(NEGATIVE_KINDS)}

        cleared = next((c for c in _CLEARED_COLUMNS if c in cols), None)
        if cleared:
            where.append(f"{cleared} IS NULL")
        if profile_id is not None and "profile_id" in cols:
            # A NULL owner still counts. Trellis is a single-student product, so
            # an unattributed rejection is this student's rejection; dropping it
            # would re-offer something they had already dismissed, which is the
            # exact failure this module exists to prevent.
            where.append("(profile_id = :profile_id OR profile_id IS NULL)")
            params["profile_id"] = profile_id

        # Identifiers come from information_schema, never from user input, so
        # the interpolation here cannot carry anything a caller controls.
        sql = (
            f"SELECT DISTINCT opportunity_id FROM {table_name} "  # noqa: S608
            f"WHERE opportunity_id IS NOT NULL AND {' AND '.join(where)}"
        )
        found = True
        for (row_id,) in db.execute(text(sql), params):
            if row_id is not None:
                ids.add(row_id)

    return ids, found


def load_suppressions(db: Session, profile_id: uuid.UUID | None = None) -> Suppressions:
    """Build the full suppression set for one discovery run.

    Resolved once per run rather than per document: the set is small, and a
    per-document lookup would put an introspection query in the inner loop.
    """
    from app.models.opportunity import Opportunity
    from app.services.dedup import normalize_url

    ids, found = rejected_opportunity_ids(db, profile_id)
    result = Suppressions(opportunity_ids=ids, available=found)
    if not ids:
        return result

    from sqlalchemy import select

    rows = db.execute(
        select(Opportunity.source_url, Opportunity.external_key).where(Opportunity.id.in_(ids))
    ).all()
    for source_url, external_key in rows:
        normalized = normalize_url(source_url)
        if normalized:
            result.urls.add(normalized)
        if external_key:
            result.external_keys.add(external_key)
    return result
