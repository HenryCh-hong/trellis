"""Handshake — a normaliser, not a scraper. This adapter never fetches anything.

Stanford's Handshake (``stanford.joinhandshake.com``) is the official student job
board, and it is entirely behind SUNet SSO (SAML 2.0 to Stanford's Shibboleth
IdP) plus Duo two-step, with Cloudflare bot checks in front of the login.  A
recon pass confirmed this end to end: every student route returns 302 to /login
when logged out, while nonsense paths return 404.  There is no headless path to
this data, and there is no honest way to manufacture one.

So Handshake postings enter Trellis by exactly one route: a browser extension
running in the student's own already-authenticated tab reads the page they are
personally looking at and POSTs it to ``/api/import/handshake``, which calls
:func:`normalize_extension_payload`.

The constraints this module exists to enforce:

* We never store, request, transmit or cache a SUNet password, a Duo code, or
  any Stanford credential. There is no password field anywhere in this product.
* We never bypass, replay, proxy or automate SSO/SAML or two-step, and never
  reuse a session cookie or SAML assertion outside the student's own browser.
* We never solve, suppress or interact with Cloudflare bot checks or CAPTCHAs.
  The extension stays inert on an interstitial.
* We never fetch Handshake while logged out and never crawl it server-side.
  Handshake's robots.txt is ``Disallow: /`` with a narrow allowlist, and their
  Terms of Service explicitly prohibit bulk collection of job descriptions.
  Reading the one page the student is looking at, for that student, is the whole
  permitted surface — enumerating the job graph is not.
* We never auto-submit. Nothing here or downstream may click Apply, Quick Apply,
  Submit Application, or Step 2: External Application. A submission is
  irreversible and is attributed to the student personally; they click it.
* We never use Handshake's EDU API — it is issued to the school, not to students.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from app.models.enums import OpportunityType, SourceKind
from app.sources.base import DiscoveredDocument, SourceAdapter, SourceContext

BASE_URL = "https://stanford.joinhandshake.com/"
JOB_URL_TEMPLATE = "https://stanford.joinhandshake.com/stu/jobs/{job_id}"
_JOB_ID_RE = re.compile(r"/(?:stu/)?(?:jobs|emp/jobs|postings)/(\d+)")

DISCOVERY_NOTE = (
    "Handshake is not discoverable server-side: it is behind Stanford SSO and Duo, "
    "its robots.txt disallows crawling, and its Terms of Service prohibit bulk "
    "collection. Postings arrive only from the browser extension running in the "
    "student's own logged-in tab, via POST /api/import/handshake."
)

#: The three application flows Handshake documents, verbatim. Anything else is
#: reported as unrecognised rather than guessed into one of these.
APPLICATION_METHODS = ("Apply", "Quick Apply", "Apply Externally")

#: Everything the extension is allowed to send. An allowlist, not a passthrough:
#: a compromised or over-eager extension cannot smuggle extra fields into the
#: record, and nothing resembling a credential has a place to land.
ALLOWED_PAYLOAD_FIELDS = frozenset(
    {
        "job_id",
        "url",
        "title",
        "employer",
        "employer_id",
        "location",
        "work_mode",
        "job_type",
        "employment_type",
        "pay",
        "posted_at",
        "apply_by",
        "application_method",
        "external_application_url",
        "documents_required",
        "description",
        "description_text",
        "description_html",
        "page_title",
        "captured_at",
        "extension_version",
    }
)

#: Handshake's documented Job Type vocabulary, mapped only where the mapping is
#: unambiguous. Everything else stays ``None`` for the extractor to decide.
_JOB_TYPE_KINDS: dict[str, OpportunityType] = {
    "on campus student employment": OpportunityType.ON_CAMPUS,
}
_EMPLOYMENT_TYPE_KINDS: dict[str, OpportunityType] = {
    "part-time": OpportunityType.PART_TIME,
    "part time": OpportunityType.PART_TIME,
}


def extract_job_id(payload: dict[str, Any]) -> str | None:
    """The numeric route id — the only stable identity a Handshake posting has."""
    raw = payload.get("job_id")
    if isinstance(raw, (str, int)):
        text = str(raw).strip()
        if text.isdigit():
            return text
    url = payload.get("url")
    if isinstance(url, str):
        match = _JOB_ID_RE.search(url)
        if match:
            return match.group(1)
    return None


def _clean_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _parse_timestamp(value: object) -> datetime | None:
    text = _clean_str(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def infer_kind(payload: dict[str, Any]) -> OpportunityType | None:
    job_type = (_clean_str(payload.get("job_type")) or "").lower()
    if job_type in _JOB_TYPE_KINDS:
        return _JOB_TYPE_KINDS[job_type]
    employment_type = (_clean_str(payload.get("employment_type")) or "").lower()
    return _EMPLOYMENT_TYPE_KINDS.get(employment_type)


def normalize_extension_payload(payload: object) -> DiscoveredDocument:
    """Turn what the extension read off the student's own screen into a document.

    Typed ``object`` on purpose: this is an untrusted boundary, and it never
    raises — a malformed payload comes back as a document carrying ``error``,
    because the import endpoint has to answer the extension either way.
    """
    if not isinstance(payload, dict):
        return DiscoveredDocument(
            url=BASE_URL,
            retrieved_by="extension",
            error="handshake payload must be an object",
        )

    data: dict[str, Any] = {str(key): value for key, value in payload.items()}
    known = {k: v for k, v in data.items() if k in ALLOWED_PAYLOAD_FIELDS}
    rejected = sorted(set(data) - ALLOWED_PAYLOAD_FIELDS)

    job_id = extract_job_id(known)
    url = _clean_str(known.get("url"))
    if job_id is None and url is None:
        return DiscoveredDocument(
            url=BASE_URL,
            retrieved_by="extension",
            structured={"rejected_fields": rejected} if rejected else {},
            error="handshake payload has neither a job id nor a url",
        )

    canonical_url = url or JOB_URL_TEMPLATE.format(job_id=job_id)

    method = _clean_str(known.get("application_method"))
    normalised_method: str | None = None
    unrecognised_method: str | None = None
    if method is not None:
        match = next((m for m in APPLICATION_METHODS if m.lower() == method.lower()), None)
        if match is not None:
            normalised_method = match
        else:
            unrecognised_method = method

    structured: dict[str, Any] = {
        "job_id": job_id,
        "handshake_url": canonical_url,
        "title": _clean_str(known.get("title")),
        "employer": _clean_str(known.get("employer")),
        "employer_id": _clean_str(known.get("employer_id")),
        "location": _clean_str(known.get("location")),
        "work_mode": _clean_str(known.get("work_mode")),
        "job_type": _clean_str(known.get("job_type")),
        "employment_type": _clean_str(known.get("employment_type")),
        # Pay is frequently prose inside the employer's description rather than a
        # labelled field, so it is carried as text and never parsed into a range here.
        "pay_text": _clean_str(known.get("pay")),
        "posted_at": _clean_str(known.get("posted_at")),
        "apply_by": _clean_str(known.get("apply_by")),
        "application_method": normalised_method,
        "external_application_url": _clean_str(known.get("external_application_url")),
        "documents_required": _string_list(known.get("documents_required")),
        "extension_version": _clean_str(known.get("extension_version")),
        "captured_at": _clean_str(known.get("captured_at")),
        "university": "Stanford University",
        "auto_submit_forbidden": True,
    }
    if unrecognised_method is not None:
        structured["application_method_unrecognized"] = unrecognised_method
    if rejected:
        structured["rejected_fields"] = rejected

    title = structured["title"] or _clean_str(known.get("page_title"))
    return DiscoveredDocument(
        url=canonical_url,
        title=title,
        # The extension emits "description"; the longer names are accepted
        # too so an older build keeps working.
        text=_clean_str(known.get("description") or known.get("description_text")),
        html=_clean_str(known.get("description_html")),
        kind_hint=infer_kind(known),
        external_key=f"handshake-{job_id}" if job_id else None,
        structured=structured,
        fetched_at=_parse_timestamp(known.get("captured_at")),
        retrieved_by="extension",
    )


class HandshakeAdapter(SourceAdapter):
    """Registered so Handshake postings have a source row — it discovers nothing."""

    slug = "handshake"
    name = "Handshake (Stanford) — browser extension import"
    kind = SourceKind.HANDSHAKE
    base_url = BASE_URL
    requires_auth = True
    is_public = False
    # Not mocked: the data is real. It simply arrives from the student's browser
    # rather than from our server.
    is_mocked = False
    notes = DISCOVERY_NOTE

    def discover(self, ctx: SourceContext) -> Iterable[DiscoveredDocument]:
        """Always empty. Server-side discovery of Handshake is prohibited — see
        the module docstring and :data:`DISCOVERY_NOTE`."""
        return ()
