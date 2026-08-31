"""Load the harvested Stanford corpus into Postgres.

Everything under ``data/harvest`` was collected from real public pages by an
earlier research pass, and every claim in it carries the URL it came from.  This
loader mirrors those files into the database and adds no claim of its own: a
value the harvest does not carry becomes NULL with confidence 0 and certainty
UNKNOWN, never a plausible-looking guess.

The load is idempotent.  Rows are matched on their natural key (``faculty.slug``,
``opportunities.external_key``, ...) and updated in place; child rows that the
harvest no longer mentions are deleted so the database stays a faithful mirror
rather than an append-only pile.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import pkgutil
import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.db.base import utcnow
from app.models.enums import (
    Certainty,
    DeadlineType,
    EligibilityState,
    EvidenceKind,
    ExtractionMethod,
    LeadState,
    OpportunityType,
    RequirementKind,
    SignalKind,
    SourceKind,
)
from app.models.opportunity import (
    ExtractedField,
    Opportunity,
    OpportunitySource,
    OpportunityTopic,
    Requirement,
)
from app.models.ops import DataProvenance
from app.models.research import Faculty, FacultyTopic, Lab, LabSignal, ResearchEvidence
from app.models.user import ResearchTopic, Skill
from app.services import taxonomy

LOADER = "app.seed"
"""Written into every row this module owns so ``--reset`` can find them again."""

# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, limit: int = 120) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_RE.sub("-", ascii_value.lower()).strip("-")
    return slug[:limit].strip("-") or "item"


def clip(value: object, limit: int) -> str | None:
    """Fit a harvested string into a bounded column without silently dropping it.

    Callers keep the untruncated text somewhere unbounded (``raw``, ``notes``,
    ``statement``), so nothing is lost — only the indexable summary is short.
    """
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def text_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_date(value: object) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    parsed = parse_datetime(value)
    return parsed.date() if parsed else None


def certainty_from_confidence(confidence: float, source_text: str | None) -> Certainty:
    """The project-wide confidence -> certainty ladder (docs/uncertainty.md).

    VERIFIED needs quoted source text as well as a high score: a number on its
    own is never enough to let the UI assert something as fact.
    """
    if confidence >= 0.85 and source_text:
        return Certainty.VERIFIED
    if confidence >= 0.6:
        return Certainty.LIKELY
    if confidence > 0:
        return Certainty.INFERRED
    return Certainty.UNKNOWN


_DEADLINE_TYPES = {
    "hard": DeadlineType.HARD,
    "rolling": DeadlineType.ROLLING,
    # A priority date and an until-filled posting both keep accepting
    # applications afterwards, so neither may be shown as a hard cutoff.
    "priority": DeadlineType.ROLLING,
    "until_filled": DeadlineType.ROLLING,
    "unknown": DeadlineType.UNKNOWN,
}

_LEAD_STATES = {
    "OPENING": LeadState.OPENING,
    "OUTREACH": LeadState.OUTREACH,
    "WATCH": LeadState.WATCH,
}

_CERTAINTY_WORDS = {
    "verified": Certainty.VERIFIED,
    "likely": Certainty.LIKELY,
    "inferred": Certainty.INFERRED,
    "unknown": Certainty.UNKNOWN,
}

_EVIDENCE_KINDS = {kind.value: kind for kind in EvidenceKind}
_OPPORTUNITY_TYPES = {kind.value: kind for kind in OpportunityType}

# --- hours -----------------------------------------------------------------

_HOURS_TOKEN = re.compile(
    r"(\d{1,3})\s*(?:[-–—]\s*\d{1,3})?\s*\+?\s*(?:hours?|hrs?)\b(.{0,40})",
    re.IGNORECASE | re.DOTALL,
)
_WEEKLY = re.compile(r"per\s+week|/\s*week|a\s+week|each\s+week|weekly|\bwk\b|\bweeks?\b", re.I)
_NOT_WEEKLY = re.compile(r"\bquarter\b|\bmonth\b|\byear\b|\bterm\b|\bshift|\bsession|\bday\b", re.I)
_FIRST_INT = re.compile(r"(?<![\d.])(\d{1,3})(?![\d.])\s*\+?\s*([A-Za-z%]+)?")
_NOT_HOURS_UNIT = re.compile(
    r"^(weeks?|months?|quarters?|units?|credits?|percent|days?|shifts?|minutes?|%)$", re.I
)


def parse_hours_per_week(value: object) -> int | None:
    """Pull a weekly hour count out of the harvest's free-text hours field.

    The harvest stores hours as either an int or prose like
    ``"10 hours per week (25% appointment)"``.  Prose that measures something
    else — ``"1-3 hour shifts"``, ``"10-20 hours per quarter"``, ``"Full time,
    10 weeks"`` — yields None rather than a wrong number, because the value
    feeds an eligibility check (undergraduates are capped near 15 hrs/week).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value > 0 else None
    if not isinstance(value, str) or not value.strip():
        return None

    match = _HOURS_TOKEN.search(value)
    if match:
        context = match.group(2) or ""
        weekly = _WEEKLY.search(context)
        other = _NOT_WEEKLY.search(context)
        if weekly and (other is None or weekly.start() < other.start()):
            return int(match.group(1))
        # An explicit "hours" figure measured per quarter or per shift is not a
        # weekly commitment; refuse rather than fall through to a looser rule.
        return None

    first = _FIRST_INT.search(value)
    if not first:
        return None
    unit = first.group(2) or ""
    if _NOT_HOURS_UNIT.match(unit):
        return None
    number = int(first.group(1))
    return number if number > 0 else None


# --- pay -------------------------------------------------------------------

_MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)")
_MONEY_RANGE = re.compile(
    r"\$\s*([\d,]+(?:\.\d{1,2})?)\s*(?:/\s*\w+|per\s+\w+)?\s*(?:[-–—]|to)\s*"
    r"\$\s*([\d,]+(?:\.\d{1,2})?)"
)
_HOURLY = re.compile(r"/\s*h(?:ou)?r|per\s+hour|hourly|an\s+hour|a\s+week\s*/\s*hour", re.I)
_STIPEND = re.compile(r"stipend|fellowship|scholarship", re.I)


@dataclass(slots=True)
class ParsedPay:
    text: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    period: str | None = None


def parse_pay(value: object) -> ParsedPay:
    """Read the *first* stated figure and, only for an explicit range, a second.

    Several postings quote a second unrelated number ("$8,500 stipend ... plus a
    $1,500 supplement"); taking min/max over every dollar sign would invent a
    pay band that the page never states.
    """
    text = text_or_none(value)
    if text is None:
        return ParsedPay()

    parsed = ParsedPay(text=text)
    if _HOURLY.search(text):
        parsed.period = "hour"
    elif _STIPEND.search(text):
        parsed.period = "stipend"

    range_match = _MONEY_RANGE.search(text)
    if range_match:
        parsed.minimum = float(range_match.group(1).replace(",", ""))
        parsed.maximum = float(range_match.group(2).replace(",", ""))
        return parsed
    first = _MONEY.search(text)
    if first:
        parsed.minimum = float(first.group(1).replace(",", ""))
    return parsed


def fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EntityCount:
    created: int = 0
    updated: int = 0
    deleted: int = 0

    @property
    def touched(self) -> int:
        return self.created + self.updated


@dataclass(slots=True)
class SkippedItem:
    entity: str
    key: str
    reason: str


@dataclass
class LoadReport:
    root: str = ""
    files: list[str] = field(default_factory=list)
    counts: dict[str, EntityCount] = field(default_factory=dict)
    skipped: list[SkippedItem] = field(default_factory=list)
    known_gaps: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None

    def count(self, entity: str) -> EntityCount:
        return self.counts.setdefault(entity, EntityCount())

    def record(self, entity: str, created: bool) -> None:
        bucket = self.count(entity)
        if created:
            bucket.created += 1
        else:
            bucket.updated += 1

    def deleted(self, entity: str, n: int = 1) -> None:
        self.count(entity).deleted += n

    def skip(self, entity: str, key: str, reason: str) -> None:
        self.skipped.append(SkippedItem(entity=entity, key=key, reason=reason))

    def total(self, entity: str) -> int:
        return self.count(entity).touched

    def render(self) -> str:
        lines = [f"harvest root: {self.root}"]
        if self.finished_at:
            elapsed = (self.finished_at - self.started_at).total_seconds()
            lines.append(f"elapsed:      {elapsed:.2f}s")
        lines.append("")
        lines.append(f"{'entity':<22}{'created':>9}{'updated':>9}{'deleted':>9}")
        lines.append("-" * 49)
        for entity in sorted(self.counts):
            c = self.counts[entity]
            lines.append(f"{entity:<22}{c.created:>9}{c.updated:>9}{c.deleted:>9}")
        lines.append("")
        lines.append(f"files read ({len(self.files)}):")
        lines.extend(f"  {name}" for name in self.files)
        if self.known_gaps:
            lines.append("")
            lines.append(f"known gaps ({len(self.known_gaps)}):")
            lines.extend(f"  - {gap}" for gap in self.known_gaps)
        lines.append("")
        if self.skipped:
            lines.append(f"skipped ({len(self.skipped)}):")
            lines.extend(f"  [{s.entity}] {s.key}: {s.reason}" for s in self.skipped)
        else:
            lines.append("skipped: none")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# harvest files
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class HarvestFile:
    path: Path
    rel: str
    payload: Any
    # Falls back to the file's own mtime: the faculty dossiers carry no
    # ``fetched_at`` of their own, and a written-at time is at least a real
    # property of the harvest rather than an invented timestamp.
    generated_at: datetime


def default_harvest_root() -> Path:
    """Locate ``data/harvest`` by walking up from this file.

    Resolved by search rather than by a fixed depth so that moving the API
    package inside the monorepo cannot silently point the loader at nothing.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "harvest"
        if candidate.is_dir():
            return candidate
    return REPO_ROOT / "data" / "harvest"


def _read(path: Path) -> HarvestFile | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return HarvestFile(path=path, rel=path.name, payload=payload, generated_at=mtime)


def _read_dir(root: Path, name: str, report: LoadReport) -> list[HarvestFile]:
    directory = root / name
    if not directory.is_dir():
        report.skip("file", name, "directory not present in the harvest")
        return []
    files: list[HarvestFile] = []
    for path in sorted(directory.glob("*.json")):
        harvest = _read(path)
        if harvest is None:
            report.skip("file", f"{name}/{path.name}", "unreadable or invalid JSON")
            continue
        harvest.rel = f"{name}/{path.name}"
        files.append(harvest)
        report.files.append(harvest.rel)
    return files


def _read_file(root: Path, rel: str, report: LoadReport) -> HarvestFile | None:
    path = root / rel
    if not path.is_file():
        report.skip("file", rel, "not present in the harvest")
        return None
    harvest = _read(path)
    if harvest is None:
        report.skip("file", rel, "unreadable or invalid JSON")
        return None
    harvest.rel = rel
    report.files.append(rel)
    return harvest


def _item_timestamp(item: dict[str, Any], fallback: datetime) -> datetime:
    return parse_datetime(item.get("fetched_at")) or fallback


# ---------------------------------------------------------------------------
# taxonomy (skills + topics)
# ---------------------------------------------------------------------------


def _taxonomy_callable(name: str) -> Callable[..., Any] | None:
    try:
        taxonomy = importlib.import_module("app.services.taxonomy")
    except Exception:  # pragma: no cover - module is written in parallel
        return None
    fn = getattr(taxonomy, name, None)
    return fn if callable(fn) else None


def _call_taxonomy(db: Session, name: str, labels: Sequence[str]) -> None:
    """Hand the canonical vocabulary to app.services.taxonomy if it is there.

    Its argument order is not ours to pin down, so we try the plausible shapes
    and treat the call as advisory: whatever it does or does not create, the
    caller re-reads the table afterwards and fills any gap itself.
    """
    fn = _taxonomy_callable(name)
    if fn is None or not labels:
        return
    for args in ((db, list(labels)), (list(labels), db), (list(labels),)):
        try:
            fn(*args)
        except TypeError:
            continue
        except Exception:
            # A partially-applied helper must not poison the transaction; we
            # run before any of our own writes, so a rollback is free here.
            db.rollback()
            return
        else:
            db.flush()
            return


def _norm(label: str) -> str:
    return " ".join(label.split()).casefold()


def _ensure_vocabulary(
    db: Session,
    model: type[Skill] | type[ResearchTopic],
    labels: Iterable[str],
    taxonomy_fn: str,
    report: LoadReport,
    entity: str,
) -> dict[str, Skill | ResearchTopic]:
    wanted: dict[str, str] = {}
    for raw_label in labels:
        label = text_or_none(raw_label)
        if label is None:
            continue
        wanted.setdefault(_norm(label), label)
    if not wanted:
        return {}

    _call_taxonomy(db, taxonomy_fn, sorted(wanted.values()))

    existing = list(db.scalars(select(model)))
    index: dict[str, Skill | ResearchTopic] = {}
    for row in existing:
        index[_norm(row.label)] = row
        index.setdefault(row.slug, row)
        for alias in row.aliases:
            index.setdefault(_norm(alias), row)

    resolved: dict[str, Skill | ResearchTopic] = {}
    for key, label in sorted(wanted.items()):
        row = index.get(key) or index.get(slugify(label))
        if row is None:
            row = model(slug=slugify(label), label=clip(label, 160) or label[:160], aliases=[])
            db.add(row)
            db.flush()
            index[key] = row
            index[row.slug] = row
            report.record(entity, created=True)
        elif _norm(row.label) != key and key not in {_norm(a) for a in row.aliases}:
            # Same canonical row, different surface form in the harvest — keep
            # the variant so a later lookup by that wording still resolves.
            row.aliases = [*row.aliases, label]
        resolved[key] = row
    return resolved


def _topic_for(topics: dict[str, Any], label: str) -> ResearchTopic | None:
    row = topics.get(_norm(label))
    return row if isinstance(row, ResearchTopic) else None


def _ontology_entries(harvest: HarvestFile | None) -> list[dict[str, Any]]:
    """Normalise ``recon/topic-ontology.json`` into label/aliases/parent records.

    The file is optional and its shape is the harvest's to choose, so the three
    plausible encodings are all accepted and anything else is ignored rather
    than guessed at.
    """
    if harvest is None:
        return []
    payload = harvest.payload
    entries: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        inner = payload.get("topics")
        if isinstance(inner, list):
            payload = inner
        else:
            for key, value in payload.items():
                if key.startswith("_"):
                    continue
                if isinstance(value, list):
                    entries.append(
                        {"label": key, "aliases": [a for a in value if isinstance(a, str)]}
                    )
                elif isinstance(value, dict):
                    entries.append({**value, "label": value.get("label") or key})
            return [e for e in entries if text_or_none(e.get("label"))]
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, str):
                entries.append({"label": item, "aliases": []})
            elif isinstance(item, dict):
                label = item.get("label") or item.get("name") or item.get("topic")
                if not text_or_none(label):
                    continue
                entries.append(
                    {
                        "label": label,
                        "aliases": [a for a in item.get("aliases") or [] if isinstance(a, str)],
                        "parent": item.get("parent")
                        or item.get("parent_label")
                        or item.get("parent_slug"),
                        "description": item.get("description"),
                    }
                )
    return entries


def _apply_topic_ontology(
    db: Session, topics: dict[str, Any], entries: Sequence[dict[str, Any]]
) -> None:
    for entry in entries:
        topic = _topic_for(topics, str(entry.get("label")))
        if topic is None:
            continue
        aliases = list(topic.aliases)
        known = {_norm(a) for a in aliases} | {_norm(topic.label)}
        for alias in entry.get("aliases") or []:
            if text_or_none(alias) and _norm(alias) not in known:
                aliases.append(alias)
                known.add(_norm(alias))
        topic.aliases = aliases
        topic.description = topic.description or text_or_none(entry.get("description"))
        parent = entry.get("parent")
        if isinstance(parent, str):
            parent_row = _topic_for(topics, parent)
            if parent_row is not None and parent_row.id != topic.id:
                topic.parent_id = parent_row.id
    db.flush()


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SourceIndex:
    """Resolves a posting URL to the source row it was harvested from."""

    by_prefix: list[tuple[str, OpportunitySource]] = field(default_factory=list)
    by_host: dict[str, OpportunitySource] = field(default_factory=dict)

    def add(self, base_url: str | None, source: OpportunitySource) -> None:
        if not base_url:
            return
        self.by_prefix.append((base_url.rstrip("/"), source))
        self.by_prefix.sort(key=lambda pair: len(pair[0]), reverse=True)
        host = urlparse(base_url).netloc.lower()
        if host:
            self.by_host.setdefault(host, source)

    def resolve(self, url: str | None) -> OpportunitySource | None:
        if not url:
            return None
        cleaned = url.rstrip("/")
        for prefix, source in self.by_prefix:
            if cleaned == prefix or cleaned.startswith(prefix + "/"):
                return source
        return self.by_host.get(urlparse(url).netloc.lower())


def _upsert_source(
    db: Session,
    report: LoadReport,
    *,
    slug: str,
    name: str,
    kind: SourceKind,
    base_url: str | None = None,
    adapter: str | None = None,
    requires_auth: bool = False,
    is_public: bool = True,
    enabled: bool = True,
    config: dict[str, Any] | None = None,
    notes: str | None = None,
) -> OpportunitySource:
    source = db.scalar(select(OpportunitySource).where(OpportunitySource.slug == slug))
    created = source is None
    if source is None:
        source = OpportunitySource(slug=slug, name=name, kind=kind)
        db.add(source)
    source.name = clip(name, 240) or slug
    source.kind = kind
    source.base_url = clip(base_url, 1000)
    source.adapter = clip(adapter, 160)
    source.requires_auth = requires_auth
    source.is_public = is_public
    source.enabled = enabled
    source.config = {"loaded_by": LOADER, **(config or {})}
    source.notes = notes
    db.flush()
    report.record("opportunity_sources", created=created)
    return source


def _source_kind_for(entry: dict[str, Any]) -> SourceKind:
    host = urlparse(entry.get("base_url") or "").netloc.lower()
    contains = (entry.get("what_it_contains") or "").lower()
    if "joinhandshake" in host:
        return SourceKind.HANDSHAKE
    if "careersearch" in host:
        return SourceKind.JOB_BOARD
    if entry.get("access") != "public" or "no listings" in contains or "no job listings" in contains:
        return SourceKind.MANUAL
    return SourceKind.CAMPUS_JOBS


def _load_recon_sources(
    db: Session,
    report: LoadReport,
    employment: HarvestFile | None,
    handshake: HarvestFile | None,
    index: SourceIndex,
) -> list[str]:
    """Recon sources become first-class rows so Settings can show coverage."""
    gaps: list[str] = []
    if employment is None or not isinstance(employment.payload, dict):
        return gaps
    entries = employment.payload.get("sources")
    if not isinstance(entries, list):
        return gaps

    handshake_detail = handshake.payload if handshake and isinstance(handshake.payload, dict) else None
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = text_or_none(entry.get("name"))
        if name is None:
            report.skip("opportunity_sources", "<unnamed>", "source entry has no name")
            continue
        slug = slugify(name)
        if slug in seen:
            report.skip("opportunity_sources", name, f"duplicate source slug {slug!r}")
            continue
        seen.add(slug)

        access = text_or_none(entry.get("access")) or "unknown"
        login_required = bool(entry.get("login_required"))
        public = access == "public"
        kind = _source_kind_for(entry)
        config: dict[str, Any] = {
            "harvest_file": employment.rel,
            "access": access,
            "verified_this_run": bool(entry.get("verified_this_run")),
            "what_it_contains": entry.get("what_it_contains"),
            "json_api": entry.get("json_api"),
            "json_area": entry.get("json_area"),
            "paging": entry.get("paging"),
            "public_posting_url_pattern": entry.get("public_posting_url_pattern"),
        }
        if kind is SourceKind.HANDSHAKE and handshake_detail is not None:
            config["integration"] = handshake_detail
            config["integration_file"] = handshake.rel if handshake else None

        source = _upsert_source(
            db,
            report,
            slug=slug,
            name=name,
            kind=kind,
            base_url=text_or_none(entry.get("base_url")),
            requires_auth=login_required,
            is_public=public,
            # Nothing behind a login is harvestable by us, and we never fetch
            # behind a student's credentials — such a source stays disabled.
            enabled=public and not login_required,
            config=config,
            notes=text_or_none(entry.get("fetch_notes")),
        )
        index.add(source.base_url, source)
        if login_required:
            gaps.append(f"{name}: login required, not harvestable ({access})")
        elif access != "public":
            gaps.append(f"{name}: {access}")
    return gaps


def _load_adapter_sources(db: Session, report: LoadReport, index: SourceIndex) -> None:
    """Register every SourceAdapter that exists in app/sources as a source row."""
    try:
        import app.sources as sources_pkg
        from app.sources import base as sources_base
    except Exception:  # pragma: no cover - package always importable in-tree
        return
    adapter_base = getattr(sources_base, "SourceAdapter", None)
    if adapter_base is None:
        return

    search_path = list(getattr(sources_pkg, "__path__", []))
    seen: set[str] = set()
    for module_info in sorted(pkgutil.iter_modules(search_path), key=lambda m: m.name):
        if module_info.name in {"base", "http"}:
            continue
        try:
            module = importlib.import_module(f"app.sources.{module_info.name}")
        except Exception as exc:
            report.skip("opportunity_sources", f"app.sources.{module_info.name}", f"import failed: {exc}")
            continue
        for obj in vars(module).values():
            if not (isinstance(obj, type) and issubclass(obj, adapter_base)):
                continue
            if obj is adapter_base or inspect.isabstract(obj):
                continue
            slug = getattr(obj, "slug", "") or ""
            if not slug or slug in seen or obj.__module__ != module.__name__:
                continue
            seen.add(slug)
            source = _upsert_source(
                db,
                report,
                slug=slug,
                name=getattr(obj, "name", slug),
                kind=getattr(obj, "kind", SourceKind.MANUAL),
                base_url=getattr(obj, "base_url", None),
                adapter=f"{obj.__module__}.{obj.__qualname__}",
                requires_auth=bool(getattr(obj, "requires_auth", False)),
                is_public=bool(getattr(obj, "is_public", True)),
                enabled=not bool(getattr(obj, "requires_auth", False)),
                config={"is_mocked": bool(getattr(obj, "is_mocked", False))},
                notes=text_or_none(getattr(obj, "notes", None)),
            )
            index.add(source.base_url, source)


# ---------------------------------------------------------------------------
# faculty
# ---------------------------------------------------------------------------


def _prune(db: Session, existing: dict[Any, Any], keep: set[Any], report: LoadReport, entity: str) -> None:
    for key, row in existing.items():
        if key not in keep:
            db.delete(row)
            report.deleted(entity)


def _activity_confidence(active: bool, last_year: int | None) -> float:
    """Recency bands, not a model output — the raw counts ride along in ``note``."""
    if not active or last_year is None:
        return 0.0
    current = datetime.now(tz=UTC).year
    if last_year >= current - 1:
        return 0.9
    if last_year >= current - 2:
        return 0.7
    return 0.5


def _lab_link(source_urls: Sequence[str], *segments: str) -> str | None:
    for url in source_urls:
        tail = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1].lower()
        if tail in segments:
            return url
    return None


def _load_faculty_file(
    db: Session,
    report: LoadReport,
    harvest: HarvestFile,
    topics: dict[str, Any],
    faculty_source: OpportunitySource,
) -> None:
    data = harvest.payload
    if not isinstance(data, dict):
        report.skip("faculty", harvest.rel, "expected a JSON object")
        return
    slug = text_or_none(data.get("slug")) or slugify(harvest.path.stem)
    name = text_or_none(data.get("name"))
    if name is None:
        report.skip("faculty", slug, "no name in the harvest record")
        return

    timestamp = _item_timestamp(data, harvest.generated_at)
    row = db.scalar(select(Faculty).where(Faculty.slug == slug))
    created = row is None
    if row is None:
        row = Faculty(slug=slug[:160], name=name, university="")
        row.first_seen_at = timestamp
        db.add(row)

    email = text_or_none(data.get("email"))
    email_source_url = text_or_none(data.get("email_source_url"))
    if email is None:
        email_certainty = Certainty.UNKNOWN
    elif email_source_url:
        email_certainty = Certainty.VERIFIED
    else:
        email_certainty = Certainty.INFERRED

    activity = data.get("lab_activity") if isinstance(data.get("lab_activity"), dict) else {}
    last_year = activity.get("last_evidence_year")
    evidence_count = activity.get("evidence_count")
    directions = [d for d in (data.get("current_direction") or []) if text_or_none(d)]
    source_urls = [u for u in (data.get("source_urls") or []) if text_or_none(u)]

    row.name = clip(name, 240) or name[:240]
    row.title = text_or_none(data.get("title"))
    row.university = clip(data.get("university"), 200) or "Stanford University"
    row.department = clip(data.get("department"), 200)
    row.faculty_url = clip(data.get("faculty_url"), 1000)
    row.email = clip(email, 320)
    row.email_source_url = clip(email_source_url, 1000)
    row.email_certainty = email_certainty
    row.research_areas = [a for a in (data.get("research_areas") or []) if text_or_none(a)]
    row.current_direction = directions
    row.current_direction_basis = text_or_none(data.get("current_direction_basis"))
    # A synthesis over dated evidence is an inference, however well cited.
    row.current_direction_certainty = Certainty.INFERRED if directions else Certainty.UNKNOWN
    row.last_evidence_year = last_year if isinstance(last_year, int) else None
    row.evidence_count = evidence_count if isinstance(evidence_count, int) else 0
    row.is_active = bool(activity.get("active"))
    row.last_checked_at = timestamp
    row.first_seen_at = row.first_seen_at or timestamp
    row.source_urls = source_urls
    row.fetch_notes = text_or_none(data.get("fetch_notes"))
    db.flush()
    report.record("faculty", created=created)

    lab = _sync_lab(db, report, row, data, source_urls, timestamp)
    _sync_evidence(db, report, row, lab, data, timestamp)
    _sync_signals(db, report, row, lab, data)
    _sync_faculty_topics(db, report, row, data, topics)
    _sync_faculty_opportunity(db, report, row, lab, data, harvest, faculty_source, topics, timestamp)


def _sync_lab(
    db: Session,
    report: LoadReport,
    faculty: Faculty,
    data: dict[str, Any],
    source_urls: Sequence[str],
    timestamp: datetime,
) -> Lab | None:
    lab_name = text_or_none(data.get("lab_name"))
    existing = {lab.slug: lab for lab in faculty.labs}
    if lab_name is None:
        _prune(db, existing, set(), report, "labs")
        return None

    slug = slugify(lab_name, 200)
    lab = db.scalar(select(Lab).where(Lab.slug == slug))
    created = lab is None
    if lab is None:
        lab = Lab(slug=slug, name=clip(lab_name, 300) or lab_name[:300], university="")
        db.add(lab)
    lab.pi_id = lab.pi_id or faculty.id
    lab.name = clip(lab_name, 300) or lab_name[:300]
    lab.url = clip(data.get("lab_url"), 1000)
    lab.university = faculty.university
    lab.department = faculty.department
    lab.people_url = clip(_lab_link(source_urls, "people", "team", "members"), 1000)
    lab.news_url = clip(_lab_link(source_urls, "news"), 1000)
    recruiting = data.get("recruiting") if isinstance(data.get("recruiting"), dict) else {}
    lab.join_url = clip(recruiting.get("url"), 1000)
    lab.last_checked_at = timestamp
    db.flush()
    report.record("labs", created=created)
    _prune(db, {s: obj for s, obj in existing.items() if s != slug}, set(), report, "labs")
    return lab


def _sync_evidence(
    db: Session,
    report: LoadReport,
    faculty: Faculty,
    lab: Lab | None,
    data: dict[str, Any],
    timestamp: datetime,
) -> None:
    existing = {(item.title, item.year): item for item in faculty.evidence}
    keep: set[tuple[str, int | None]] = set()
    for entry in data.get("evidence") or []:
        if not isinstance(entry, dict):
            continue
        title = text_or_none(entry.get("title"))
        if title is None:
            report.skip("research_evidence", faculty.slug, "evidence item without a title")
            continue
        kind = _EVIDENCE_KINDS.get(str(entry.get("kind", "")).lower())
        if kind is None:
            report.skip("research_evidence", title, f"unknown evidence kind {entry.get('kind')!r}")
            continue
        year = entry.get("year") if isinstance(entry.get("year"), int) else None
        key = (title, year)
        if key in keep:
            continue
        keep.add(key)
        row = existing.get(key)
        created = row is None
        if row is None:
            row = ResearchEvidence(faculty_id=faculty.id, title=title, year=year, kind=kind)
            db.add(row)
        row.kind = kind
        row.lab_id = lab.id if lab else None
        row.summary = text_or_none(entry.get("summary"))
        row.url = clip(entry.get("url"), 1000)
        row.venue = clip(entry.get("venue"), 300)
        row.source = "harvest"
        row.captured_at = timestamp
        report.record("research_evidence", created=created)
    db.flush()
    _prune(db, existing, keep, report, "research_evidence")


def _sync_signals(
    db: Session, report: LoadReport, faculty: Faculty, lab: Lab | None, data: dict[str, Any]
) -> None:
    existing = {(s.kind, s.statement or s.label): s for s in faculty.signals}
    keep: set[tuple[SignalKind, str]] = set()

    def put(
        kind: SignalKind,
        label: str,
        statement: str | None,
        certainty: Certainty,
        confidence: float,
        source_url: str | None,
        note: str | None,
    ) -> None:
        key = (kind, statement or label)
        if key in keep:
            return
        keep.add(key)
        row = existing.get(key)
        created = row is None
        if row is None:
            row = LabSignal(faculty_id=faculty.id, kind=kind, label=clip(label, 300) or label[:300])
            db.add(row)
        row.label = clip(label, 300) or label[:300]
        row.lab_id = lab.id if lab else None
        # A claim with no URL behind it may never render as verified.
        row.certainty = (
            Certainty.INFERRED
            if certainty is Certainty.VERIFIED and not source_url
            else certainty
        )
        row.statement = statement
        row.source_url = clip(source_url, 1000)
        row.confidence = confidence
        row.note = note
        report.record("lab_signals", created=created)

    for entry in data.get("undergrad_signals") or []:
        if not isinstance(entry, dict):
            continue
        signal = text_or_none(entry.get("signal"))
        if signal is None:
            continue
        status = str(entry.get("status", "")).lower()
        certainty = _CERTAINTY_WORDS.get(status, Certainty.UNKNOWN)
        confidence = {
            Certainty.VERIFIED: 0.95,
            Certainty.LIKELY: 0.7,
            Certainty.INFERRED: 0.4,
            Certainty.UNKNOWN: 0.0,
        }[certainty]
        put(
            SignalKind.UNDERGRAD_PRESENCE,
            signal,
            signal,
            certainty,
            confidence,
            text_or_none(entry.get("evidence_url")),
            text_or_none(entry.get("note")),
        )

    recruiting = data.get("recruiting") if isinstance(data.get("recruiting"), dict) else None
    if recruiting is not None:
        status = str(recruiting.get("status", "unknown")).lower()
        statement = text_or_none(recruiting.get("statement"))
        raw_confidence = recruiting.get("confidence")
        confidence = float(raw_confidence) if isinstance(raw_confidence, int | float) else 0.0
        labels = {
            "open": "Says it is recruiting students",
            "closed": "Says it is not currently recruiting",
            "unverified": "Recruiting language found but not undergraduate-specific",
            "unknown": "No recruiting statement found on the pages fetched",
        }
        put(
            SignalKind.RECRUITING,
            labels.get(status, f"Recruiting status: {status}"),
            statement,
            certainty_from_confidence(confidence, statement),
            confidence,
            text_or_none(recruiting.get("url")),
            f"harvest recruiting.status = {status}",
        )

    activity = data.get("lab_activity") if isinstance(data.get("lab_activity"), dict) else None
    if activity is not None:
        last_year = activity.get("last_evidence_year")
        count = activity.get("evidence_count") if isinstance(activity.get("evidence_count"), int) else 0
        active = bool(activity.get("active"))
        if active and isinstance(last_year, int):
            label = f"Active — {count} dated items collected, most recent {last_year}"
        elif isinstance(last_year, int):
            label = f"{count} dated items collected, most recent {last_year}"
        else:
            label = "No dated evidence collected"
        put(
            SignalKind.ACTIVITY,
            label,
            None,
            # Derived from the evidence list rather than quoted from a page.
            Certainty.INFERRED if active else Certainty.UNKNOWN,
            _activity_confidence(active, last_year if isinstance(last_year, int) else None),
            None,
            json.dumps(activity, sort_keys=True),
        )

    db.flush()
    _prune(db, existing, keep, report, "lab_signals")


def _sync_faculty_topics(
    db: Session, report: LoadReport, faculty: Faculty, data: dict[str, Any], topics: dict[str, Any]
) -> None:
    existing = {(t.topic_id, t.origin): t for t in faculty.topics}
    keep: set[tuple[Any, str]] = set()

    labels = [
        label
        for label in [*(data.get("research_areas") or []), *(data.get("research_topics") or [])]
        if text_or_none(label)
    ]
    evidence_text = " ‖ ".join(
        f"{e.get('title', '')} {e.get('summary', '')}"
        for e in (data.get("evidence") or [])
        if isinstance(e, dict)
    ).casefold()
    evidence_years: dict[str, list[int]] = {}
    for entry in data.get("evidence") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("year"), int):
            continue
        blob = f"{entry.get('title', '')} {entry.get('summary', '')}".casefold()
        for label in labels:
            if len(label) >= 5 and label.casefold() in blob:
                evidence_years.setdefault(_norm(label), []).append(entry["year"])

    for label in labels:
        topic = _topic_for(topics, label)
        if topic is None:
            continue
        for origin in ("directory", "evidence"):
            years = sorted(set(evidence_years.get(_norm(label), [])), reverse=True)
            if origin == "evidence" and not (years and label.casefold() in evidence_text):
                continue
            key = (topic.id, origin)
            if key in keep:
                continue
            keep.add(key)
            row = existing.get(key)
            created = row is None
            if row is None:
                row = FacultyTopic(faculty_id=faculty.id, topic_id=topic.id, origin=origin)
                db.add(row)
            row.evidence_years = years if origin == "evidence" else []
            report.record("faculty_topics", created=created)
    db.flush()
    _prune(db, existing, keep, report, "faculty_topics")


def _sync_faculty_opportunity(
    db: Session,
    report: LoadReport,
    faculty: Faculty,
    lab: Lab | None,
    data: dict[str, Any],
    harvest: HarvestFile,
    source: OpportunitySource,
    topics: dict[str, Any],
    timestamp: datetime,
) -> None:
    """Every lead becomes an Opportunity so research flows through one pipeline."""
    state = _LEAD_STATES.get(str(data.get("opportunity_state", "")).upper())
    if state is None:
        report.skip("opportunities", faculty.slug, f"unknown state {data.get('opportunity_state')!r}")
        return

    recruiting = data.get("recruiting") if isinstance(data.get("recruiting"), dict) else {}
    external_key = f"faculty:{faculty.slug}"
    opportunity, created = _get_opportunity(db, external_key)
    subject = lab.name if lab else faculty.name
    raw_confidence = recruiting.get("confidence")
    confidence = float(raw_confidence) if isinstance(raw_confidence, int | float) else 0.0

    opportunity.title = f"Undergraduate research — {subject}"
    opportunity.type = (
        OpportunityType.RESEARCH_OPENING if state is LeadState.OPENING
        else OpportunityType.RESEARCH_OUTREACH
    )
    opportunity.organization = clip(lab.name if lab else faculty.department, 300)
    opportunity.university = faculty.university
    opportunity.department = faculty.department
    opportunity.faculty_id = faculty.id
    opportunity.lab_id = lab.id if lab else None
    opportunity.source_id = source.id
    opportunity.source_url = clip((lab.url if lab else None) or faculty.faculty_url, 1000)
    opportunity.description = text_or_none(recruiting.get("statement"))
    opportunity.notes = text_or_none(data.get("state_rationale"))
    opportunity.application_url = clip(recruiting.get("url"), 1000)
    opportunity.contact_name = clip(faculty.name, 240)
    # Only an address we watched on a real page; never a guessed first.last@.
    opportunity.contact_email = (
        faculty.email if faculty.email_certainty is Certainty.VERIFIED else None
    )
    opportunity.application_method = "email" if opportunity.contact_email else None
    opportunity.deadline = None
    opportunity.deadline_type = DeadlineType.UNKNOWN
    opportunity.deadline_confidence = 0.0
    opportunity.deadline_certainty = Certainty.UNKNOWN
    opportunity.eligibility = EligibilityState.UNCLEAR
    opportunity.eligibility_reasons = []
    opportunity.skills = []
    opportunity.documents_required = []
    opportunity.extraction_confidence = confidence
    opportunity.first_seen_at = opportunity.first_seen_at or timestamp
    opportunity.last_checked_at = timestamp
    _apply_fingerprint(opportunity, {"harvest_file": harvest.rel, "item": data}, timestamp)
    opportunity.raw = {"harvest_file": harvest.rel, "item": data}
    db.flush()
    report.record("opportunities", created=created)

    link_field = application_url_provenance(
        opportunity.application_url, opportunity.source_url, opportunity.application_method
    )
    if link_field is not None:
        existing_fields = {f.field: f for f in opportunity.fields}
        _put_field(db, report, opportunity, existing_fields, "application_url", **link_field)
        db.flush()

    labels = [*(data.get("research_areas") or []), *(data.get("research_topics") or [])]
    _sync_opportunity_topics(db, report, opportunity, labels, topics)


# ---------------------------------------------------------------------------
# postings (jobs + programs + recon)
# ---------------------------------------------------------------------------


def _get_opportunity(db: Session, external_key: str) -> tuple[Opportunity, bool]:
    row = db.scalar(select(Opportunity).where(Opportunity.external_key == external_key))
    if row is not None:
        return row, False
    row = Opportunity(
        external_key=external_key[:400],
        title="",
        type=OpportunityType.ON_CAMPUS,
    )
    db.add(row)
    return row, True


def _apply_fingerprint(opportunity: Opportunity, payload: object, timestamp: datetime) -> None:
    digest = fingerprint(payload)
    if opportunity.content_fingerprint != digest:
        opportunity.last_changed_at = timestamp
    opportunity.content_fingerprint = digest


def _sync_opportunity_topics(
    db: Session,
    report: LoadReport,
    opportunity: Opportunity,
    labels: Iterable[str],
    topics: dict[str, Any],
) -> None:
    existing = {t.topic_id: t for t in opportunity.topics}
    keep: set[Any] = set()
    for label in labels:
        if not text_or_none(label):
            continue
        topic = _topic_for(topics, label)
        if topic is None or topic.id in keep:
            continue
        keep.add(topic.id)
        row = existing.get(topic.id)
        created = row is None
        if row is None:
            db.add(OpportunityTopic(opportunity_id=opportunity.id, topic_id=topic.id))
        report.record("opportunity_topics", created=created)
    db.flush()
    _prune(db, existing, keep, report, "opportunity_topics")


def _sync_requirements(
    db: Session, report: LoadReport, opportunity: Opportunity, item: dict[str, Any]
) -> None:
    existing = {(r.kind, r.text): r for r in opportunity.requirements}
    keep: set[tuple[RequirementKind, str]] = set()
    confidence = item.get("extraction_confidence")
    confidence = float(confidence) if isinstance(confidence, int | float) else 0.0

    order = 0
    # The harvest keeps the two lists apart and so do we: a "preferred" line
    # promoted to REQUIRED would tell a student they are ineligible when they
    # are not.  The kind is taken from the list the item came from, never from
    # the row's own self-description.
    for field_name, kind in (
        ("requirements", RequirementKind.REQUIRED),
        ("preferred_qualifications", RequirementKind.PREFERRED),
    ):
        for entry in item.get(field_name) or []:
            if isinstance(entry, str):
                entry = {"text": entry}
            if not isinstance(entry, dict):
                continue
            text = text_or_none(entry.get("text"))
            if text is None:
                report.skip("requirements", opportunity.external_key or "?", "requirement with no text")
                continue
            key = (kind, text)
            if key in keep:
                continue
            keep.add(key)
            row = existing.get(key)
            created = row is None
            if row is None:
                row = Requirement(opportunity_id=opportunity.id, text=text, kind=kind)
                db.add(row)
            row.source_text = text_or_none(entry.get("source_text"))
            row.source_url = clip(entry.get("source_url"), 1000)
            row.confidence = confidence
            row.order_index = order
            order += 1
            report.record("requirements", created=created)
    db.flush()
    _prune(db, existing, keep, report, "requirements")


def application_url_provenance(
    application_url: str | None,
    source_url: str | None,
    application_method: str | None,
) -> dict[str, Any] | None:
    """The ``application_url`` provenance row, or ``None`` when there is no link.

    Only a link the harvest recorded *as a distinct destination* earns
    ``VERIFIED``.  When the apply URL is simply the page the posting was read
    on, nobody wrote "apply here": the row is kept, marked INFERRED, and the
    readiness list says "Unverified" rather than claiming we checked.
    """
    if not application_url:
        return None
    distinct = application_url != source_url
    return {
        "value": {"value": application_url, "application_method": application_method},
        "confidence": 1.0 if distinct else 0.4,
        "certainty": Certainty.VERIFIED if distinct else Certainty.INFERRED,
        "method": ExtractionMethod.SOURCE if distinct else ExtractionMethod.HEURISTIC,
        "source_text": (
            application_method
            if distinct
            else "No separate apply link; this is the page the posting was read on."
        ),
        "source_url": source_url,
    }


def _put_field(
    db: Session,
    report: LoadReport,
    opportunity: Opportunity,
    existing: dict[str, ExtractedField],
    name: str,
    *,
    value: dict[str, Any],
    confidence: float,
    certainty: Certainty,
    method: ExtractionMethod,
    source_text: str | None,
    source_url: str | None,
) -> None:
    row = existing.get(name)
    created = row is None
    if row is None:
        row = ExtractedField(opportunity_id=opportunity.id, field=name, method=method)
        db.add(row)
    row.value = value
    row.confidence = confidence
    row.certainty = certainty
    row.method = method
    row.source_text = source_text
    row.source_url = clip(source_url, 1000)
    row.extractor_version = "harvest-1"
    report.record("extracted_fields", created=created)


def _load_posting(
    db: Session,
    report: LoadReport,
    item: dict[str, Any],
    harvest: HarvestFile,
    fallback_source: OpportunitySource,
    index: SourceIndex,
    topics: dict[str, Any],
) -> None:
    external_key = text_or_none(item.get("external_key"))
    if external_key is None:
        report.skip("opportunities", harvest.rel, "posting with no external_key")
        return
    title = text_or_none(item.get("title"))
    if title is None:
        report.skip("opportunities", external_key, "posting with no title")
        return
    kind = _OPPORTUNITY_TYPES.get(str(item.get("type", "")).lower())
    if kind is None:
        report.skip("opportunities", external_key, f"unknown opportunity type {item.get('type')!r}")
        return

    timestamp = _item_timestamp(item, harvest.generated_at)
    source_url = text_or_none(item.get("source_url"))
    source = index.resolve(source_url) or fallback_source

    deadline_obj = item.get("deadline") if isinstance(item.get("deadline"), dict) else {}
    deadline_value = parse_date(deadline_obj.get("value"))
    raw_conf = deadline_obj.get("confidence")
    deadline_conf = float(raw_conf) if isinstance(raw_conf, int | float) else 0.0
    deadline_source_text = text_or_none(deadline_obj.get("source_text"))
    deadline_source_url = text_or_none(deadline_obj.get("source_url")) or source_url
    # Confidence describes a date; with no date there is nothing to be
    # confident about, so the record stays Unknown with confidence 0 and keeps
    # the quoted application-window prose for the student to read.
    stated_certainty = certainty_from_confidence(deadline_conf, deadline_source_text)
    certainty = stated_certainty if deadline_value else Certainty.UNKNOWN

    raw_hours = item.get("hours_per_week")
    hours = parse_hours_per_week(raw_hours)
    hours_note = raw_hours if isinstance(raw_hours, str) else None
    pay = parse_pay(item.get("pay"))
    extraction = item.get("extraction_confidence")
    extraction = float(extraction) if isinstance(extraction, int | float) else 0.0
    eligibility_notes = text_or_none(item.get("eligibility_notes"))
    application_method = text_or_none(item.get("application_method"))

    opportunity, created = _get_opportunity(db, external_key)
    opportunity.title = title
    opportunity.type = kind
    opportunity.organization = clip(item.get("organization"), 300)
    opportunity.university = clip(item.get("university"), 200)
    opportunity.department = clip(item.get("department"), 200)
    opportunity.source_id = source.id
    opportunity.source_url = clip(source_url, 1000)
    opportunity.location = clip(item.get("location"), 300)
    opportunity.pay_text = clip(pay.text, 300)
    opportunity.pay_min = pay.minimum
    opportunity.pay_max = pay.maximum
    opportunity.pay_period = pay.period
    opportunity.hours_per_week = hours
    opportunity.hours_note = clip(hours_note, 300)
    opportunity.deadline = deadline_value
    opportunity.deadline_type = _DEADLINE_TYPES.get(
        str(item.get("deadline_type", "")).lower(), DeadlineType.UNKNOWN
    )
    opportunity.deadline_confidence = deadline_conf if deadline_value else 0.0
    opportunity.deadline_certainty = certainty
    opportunity.deadline_source_text = deadline_source_text
    opportunity.description = text_or_none(item.get("description"))
    opportunity.skills = [s for s in (item.get("skills") or []) if text_or_none(s)]
    opportunity.documents_required = [
        d for d in (item.get("documents_required") or []) if text_or_none(d)
    ]
    # The full sentence lives in ``raw``; the column is a bounded summary.
    opportunity.application_method = clip(application_method, 120)
    opportunity.application_url = clip(item.get("application_url"), 1000)
    opportunity.contact_name = clip(item.get("contact_name"), 240)
    opportunity.contact_email = clip(item.get("contact_email"), 320)
    # Eligibility is per-student: the loader records what the page said and
    # leaves the verdict to the matcher.
    opportunity.eligibility = EligibilityState.UNCLEAR
    opportunity.eligibility_reasons = [eligibility_notes] if eligibility_notes else []
    opportunity.posted_at = parse_date(item.get("posted_at"))
    opportunity.first_seen_at = opportunity.first_seen_at or timestamp
    opportunity.last_checked_at = timestamp
    opportunity.extraction_confidence = extraction
    opportunity.notes = text_or_none(item.get("notes"))
    _apply_fingerprint(opportunity, {"harvest_file": harvest.rel, "item": item}, timestamp)
    opportunity.raw = {"harvest_file": harvest.rel, "item": item}
    db.flush()
    report.record("opportunities", created=created)

    _sync_requirements(db, report, opportunity, item)
    _sync_opportunity_topics(db, report, opportunity, item.get("research_topics") or [], topics)

    existing_fields = {f.field: f for f in opportunity.fields}
    _put_field(
        db,
        report,
        opportunity,
        existing_fields,
        "deadline",
        value={
            "value": deadline_value.isoformat() if deadline_value else None,
            "deadline_type": item.get("deadline_type"),
            "stated_certainty": stated_certainty.value,
        },
        confidence=deadline_conf,
        certainty=certainty,
        method=ExtractionMethod.SOURCE,
        source_text=deadline_source_text,
        source_url=deadline_source_url,
    )
    _put_field(
        db,
        report,
        opportunity,
        existing_fields,
        "pay",
        value={
            "text": pay.text,
            "min": pay.minimum,
            "max": pay.maximum,
            "period": pay.period,
        },
        confidence=extraction if pay.text else 0.0,
        certainty=Certainty.VERIFIED if pay.text and source_url else Certainty.UNKNOWN,
        method=ExtractionMethod.SOURCE,
        source_text=pay.text,
        source_url=source_url,
    )
    link_field = application_url_provenance(
        opportunity.application_url, source_url, application_method
    )
    if link_field is not None:
        _put_field(db, report, opportunity, existing_fields, "application_url", **link_field)
    _put_field(
        db,
        report,
        opportunity,
        existing_fields,
        "hours",
        value={"hours_per_week": hours, "note": hours_note if hours_note else raw_hours},
        confidence=extraction if raw_hours is not None else 0.0,
        certainty=(
            Certainty.VERIFIED if raw_hours is not None and source_url else Certainty.UNKNOWN
        ),
        method=ExtractionMethod.REGEX if hours_note else ExtractionMethod.SOURCE,
        source_text=hours_note,
        source_url=source_url,
    )
    db.flush()


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------


def _put_provenance(
    db: Session,
    report: LoadReport,
    key: str,
    label: str,
    detail: dict[str, Any],
    generated_at: datetime | None,
) -> None:
    row = db.scalar(select(DataProvenance).where(DataProvenance.key == key))
    created = row is None
    if row is None:
        row = DataProvenance(key=key[:120], label=clip(label, 240) or key)
        db.add(row)
    row.label = clip(label, 240) or key
    row.detail = detail
    row.generated_at = generated_at
    report.record("data_provenance", created=created)


def _load_provenance(
    db: Session,
    report: LoadReport,
    root: Path,
    files: dict[str, HarvestFile],
    manifest: HarvestFile | None,
    corpus_generated_at: datetime | None,
) -> None:
    for rel, harvest in sorted(files.items()):
        payload = harvest.payload
        detail: dict[str, Any] = {"file": rel, "loaded_by": LOADER}
        if isinstance(payload, list):
            detail["records"] = len(payload)
            if payload and isinstance(payload[0], dict) and "external_key" in payload[0]:
                detail["external_keys"] = [
                    p.get("external_key") for p in payload if isinstance(p, dict)
                ]
            elif payload and isinstance(payload[0], dict) and "lab_name" in payload[0]:
                detail["labs"] = [p.get("lab_name") for p in payload if isinstance(p, dict)]
                detail["note"] = "Lab inventory recon: catalogued, not yet harvested for evidence."
            elif payload and isinstance(payload[0], dict) and "profile_url" in payload[0]:
                detail["faculty"] = [p.get("name") for p in payload if isinstance(p, dict)]
                detail["note"] = (
                    "Non-CS faculty recon: catalogued from department directories, "
                    "no evidence or recruiting signals collected yet."
                )
        elif isinstance(payload, dict):
            detail["keys"] = sorted(payload)
            if isinstance(payload.get("postings"), list):
                detail["postings"] = len(payload["postings"])
            if isinstance(payload.get("sources"), list):
                detail["sources"] = len(payload["sources"])
            meta = payload.get("_meta")
            if isinstance(meta, dict):
                detail["meta"] = meta
        _put_provenance(
            db,
            report,
            f"harvest:{rel}",
            f"Harvest file — {rel}",
            detail,
            harvest.generated_at,
        )

    if manifest is not None and isinstance(manifest.payload, dict):
        payload = manifest.payload
        _put_provenance(
            db,
            report,
            "harvest:manifest",
            "Harvest manifest",
            {
                "file": manifest.rel,
                "loaded_by": LOADER,
                # The per-item arrays are mirrored by the rows we just wrote;
                # keeping only the summary keeps Settings readable.
                "university": payload.get("university"),
                "counts": payload.get("counts"),
                "known_gaps": payload.get("known_gaps"),
                "files": payload.get("files"),
                "generated_at": payload.get("generated_at"),
            },
            parse_datetime(payload.get("generated_at")) or manifest.generated_at,
        )

    counts = {name: bucket.touched for name, bucket in sorted(report.counts.items())}
    _put_provenance(
        db,
        report,
        "harvest",
        "Stanford harvest corpus",
        {
            "root": str(root),
            "loaded_by": LOADER,
            "files": sorted(files),
            "manifest_present": manifest is not None,
            "counts": counts,
            "known_gaps": report.known_gaps,
            "skipped": [
                {"entity": s.entity, "key": s.key, "reason": s.reason} for s in report.skipped
            ],
        },
        corpus_generated_at,
    )


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


def load_all(db: Session, root: Path | None = None) -> LoadReport:
    """Mirror the harvest at ``root`` into the database. Safe to re-run."""
    root = Path(root) if root is not None else default_harvest_root()
    report = LoadReport(root=str(root))
    if not root.is_dir():
        report.skip("harvest", str(root), "harvest directory not found")
        report.finished_at = utcnow()
        return report

    faculty_files = _read_dir(root, "faculty", report)
    job_files = _read_dir(root, "jobs", report)
    program_files = _read_dir(root, "programs", report)
    employment = _read_file(root, "recon/student-employment-sources.json", report)
    handshake = _read_file(root, "recon/handshake-integration.json", report)
    lab_inventory = _read_file(root, "recon/lab-inventory.json", report)
    non_cs = _read_file(root, "recon/non-cs-faculty.json", report)
    ontology = _read_file(root, "recon/topic-ontology.json", report)
    manifest = _read_file(root, "manifest.json", report)
    if manifest is not None and isinstance(manifest.payload, dict):
        report.known_gaps.extend(
            gap for gap in manifest.payload.get("known_gaps") or [] if isinstance(gap, str)
        )

    recon_postings: list[dict[str, Any]] = []
    if employment is not None and isinstance(employment.payload, dict):
        recon_postings = [p for p in employment.payload.get("postings") or [] if isinstance(p, dict)]

    posting_groups: list[tuple[HarvestFile, list[dict[str, Any]], str]] = []
    for harvest in job_files:
        if isinstance(harvest.payload, list):
            posting_groups.append((harvest, [p for p in harvest.payload if isinstance(p, dict)], "jobs"))
        else:
            report.skip("opportunities", harvest.rel, "expected a JSON array of postings")
    for harvest in program_files:
        if isinstance(harvest.payload, list):
            posting_groups.append(
                (harvest, [p for p in harvest.payload if isinstance(p, dict)], "programs")
            )
        else:
            report.skip("opportunities", harvest.rel, "expected a JSON array of programs")
    if employment is not None and recon_postings:
        posting_groups.append((employment, recon_postings, "jobs"))

    # 1. canonical vocabulary first — everything below resolves against it.
    topic_labels: list[str] = []
    skill_labels: list[str] = []
    for harvest in faculty_files:
        if isinstance(harvest.payload, dict):
            topic_labels.extend(harvest.payload.get("research_areas") or [])
            topic_labels.extend(harvest.payload.get("research_topics") or [])
    for _harvest, items, _group in posting_groups:
        for item in items:
            topic_labels.extend(item.get("research_topics") or [])
            skill_labels.extend(item.get("skills") or [])
    ontology_entries = _ontology_entries(ontology)
    for entry in ontology_entries:
        topic_labels.append(str(entry["label"]))
        if isinstance(entry.get("parent"), str):
            topic_labels.append(entry["parent"])

    # Seed the full canonical vocabulary first; the harvest labels below only
    # add surface forms that the canonical set does not already cover.
    taxonomy.ensure_vocabulary(db)
    _ensure_vocabulary(db, Skill, skill_labels, "ensure_skills", report, "skills")
    topics = _ensure_vocabulary(
        db, ResearchTopic, topic_labels, "ensure_topics", report, "research_topics"
    )
    _apply_topic_ontology(db, topics, ontology_entries)

    # 2. sources: recon rows, registered adapters, and the per-file fallbacks.
    index = SourceIndex()
    report.known_gaps.extend(_load_recon_sources(db, report, employment, handshake, index))
    _load_adapter_sources(db, report, index)

    faculty_source = _upsert_source(
        db,
        report,
        slug="harvest-faculty-pages",
        name="Stanford faculty, lab and profile pages (harvested)",
        kind=SourceKind.FACULTY_DIRECTORY,
        base_url="https://cs.stanford.edu/",
        config={"harvest_dir": "faculty"},
        notes="Per-professor dossiers assembled from department, profile and lab pages.",
    )
    fallback_sources = {
        "jobs": _upsert_source(
            db,
            report,
            slug="harvest-campus-jobs",
            name="Stanford campus job pages (harvested)",
            kind=SourceKind.CAMPUS_JOBS,
            base_url="https://stanford.edu/",
            config={"harvest_dir": "jobs"},
            notes="Public Stanford department and unit pages advertising student roles.",
        ),
        "programs": _upsert_source(
            db,
            report,
            slug="harvest-research-programs",
            name="Stanford undergraduate research programs (harvested)",
            kind=SourceKind.PROGRAM,
            base_url="https://undergradresearch.stanford.edu/",
            config={"harvest_dir": "programs"},
            notes="Formal programmes, fellowships and grants open to undergraduates.",
        ),
    }

    # 3-5. faculty, then the postings and programmes.
    for harvest in faculty_files:
        _load_faculty_file(db, report, harvest, topics, faculty_source)
    for harvest, items, group in posting_groups:
        for item in items:
            _load_posting(db, report, item, harvest, fallback_sources[group], index, topics)

    # 6-7. gaps and provenance.
    report.known_gaps.extend(_corpus_gaps(faculty_files, posting_groups, lab_inventory, non_cs))
    files = {
        h.rel: h
        for h in [
            *faculty_files,
            *job_files,
            *program_files,
            employment,
            handshake,
            lab_inventory,
            non_cs,
            ontology,
        ]
        if h is not None
    }
    corpus_generated_at = max(
        (parse_datetime(item.get("fetched_at")) for _h, items, _g in posting_groups for item in items),
        default=None,
    )
    if corpus_generated_at is None and files:
        corpus_generated_at = max(h.generated_at for h in files.values())
    _load_provenance(db, report, root, files, manifest, corpus_generated_at)

    db.flush()
    report.finished_at = utcnow()
    return report


def _corpus_gaps(
    faculty_files: Sequence[HarvestFile],
    posting_groups: Sequence[tuple[HarvestFile, list[dict[str, Any]], str]],
    lab_inventory: HarvestFile | None,
    non_cs: HarvestFile | None,
) -> list[str]:
    """Say plainly what the corpus does *not* know, for Settings → Data sources."""
    gaps: list[str] = []
    no_email = [
        h.payload.get("slug")
        for h in faculty_files
        if isinstance(h.payload, dict) and not text_or_none(h.payload.get("email"))
    ]
    if no_email:
        gaps.append(
            f"{len(no_email)} of {len(faculty_files)} faculty publish no email address on the "
            f"pages fetched ({', '.join(sorted(str(s) for s in no_email))}) — no address was guessed"
        )
    postings = [item for _h, items, _g in posting_groups for item in items]
    undated = [
        item.get("external_key")
        for item in postings
        if not parse_date((item.get("deadline") or {}).get("value"))
    ]
    if undated:
        gaps.append(f"{len(undated)} of {len(postings)} postings state no dated deadline")
    if lab_inventory is not None and isinstance(lab_inventory.payload, list):
        gaps.append(
            f"{len(lab_inventory.payload)} labs are catalogued in {lab_inventory.rel} but have no "
            "harvested evidence yet"
        )
    if non_cs is not None and isinstance(non_cs.payload, list):
        gaps.append(
            f"{len(non_cs.payload)} non-CS faculty are catalogued in {non_cs.rel} but have no "
            "harvested evidence or recruiting signals yet"
        )
    return gaps


def reset_loaded(db: Session) -> dict[str, int]:
    """Delete everything a previous load created. Dev tool: asks nothing."""
    counts: dict[str, int] = {}
    counts["opportunities"] = db.execute(
        delete(Opportunity).where(Opportunity.raw.has_key("harvest_file"))
    ).rowcount
    counts["faculty"] = db.execute(delete(Faculty)).rowcount
    counts["labs"] = db.execute(delete(Lab)).rowcount
    counts["opportunity_sources"] = db.execute(
        delete(OpportunitySource).where(OpportunitySource.config["loaded_by"].astext == LOADER)
    ).rowcount
    counts["data_provenance"] = db.execute(
        delete(DataProvenance).where(DataProvenance.key.like("harvest%"))
    ).rowcount
    db.flush()
    return counts
