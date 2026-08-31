"""Source adapter tests.

Offline by default: every test here parses a saved fixture of a shape we have
actually seen on the wire.  The handful of tests that hit the real endpoints are
gated on ``TRELLIS_NETWORK_TESTS=1`` so the default suite stays fast and works
on a plane.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from app.models.enums import OpportunityType, SourceKind
from app.sources import handshake, lab_site, manual_url, openalex
from app.sources import stanford_careersearch as careers
from app.sources import stanford_cs_faculty as cs_faculty
from app.sources import stanford_programs as programs
from app.sources import stanford_student_jobs as student_jobs
from app.sources.base import SourceContext
from app.sources.registry import SOURCE_ADAPTERS, all_adapters, get_adapter

NETWORK = os.environ.get("TRELLIS_NETWORK_TESTS") == "1"
requires_network = pytest.mark.skipif(
    not NETWORK, reason="set TRELLIS_NETWORK_TESTS=1 to run tests that hit live endpoints"
)


# --------------------------------------------------------------------------
# Fixtures: real response shapes, trimmed.
# --------------------------------------------------------------------------

HCM_SEARCH_RESPONSE: dict[str, Any] = {
    "items": [
        {
            "SearchId": 1,
            "Offset": 0,
            "Limit": 200,
            "SortBy": "POSTING_DATES_DESC",
            "TotalJobsCount": 415,
            "SiteNumber": "CX_1",
            "requisitionList": [
                {
                    "Id": "200888",
                    "Title": "Assistant Director, SPCS Admissions & Enrollment",
                    "PostedDate": "2026-08-29",
                    "PostingEndDate": None,
                    "JobFamily": "Student Services",
                    "PrimaryLocation": "Redwood City, CA, United States",
                    "WorkplaceType": "Hybrid",
                    "WorkplaceTypeCode": "ORA_HYBRID",
                    "ShortDescriptionStr": (
                        "Responsible for administering, managing and implementing "
                        "admission activities and/or programs and services for students."
                    ),
                    "ContractType": None,
                },
                {
                    "Id": "200761",
                    "Title": "Life Science Research Professional 1",
                    "PostedDate": "2026-08-21",
                    "PostingEndDate": None,
                    "JobFamily": "Research",
                    "PrimaryLocation": "Stanford, CA, United States",
                    "WorkplaceType": "On-site",
                    "ShortDescriptionStr": "Perform laboratory research.",
                    "ContractType": "Regular",
                },
            ],
        }
    ],
    "count": 1,
    "hasMore": False,
}

HCM_DETAIL_RESPONSE: dict[str, Any] = {
    "items": [
        {
            "Id": "200888",
            "Title": "Assistant Director, SPCS Admissions & Enrollment",
            "Category": "Student Services",
            "RequisitionType": "Stanford Non Bargaining Unit",
            "JobGrade": "G",
            "ContractType": "Regular",
            "JobFunction": "Admissions",
            "ExternalPostedStartDate": "2026-08-29T00:47:57+00:00",
            "ExternalPostedEndDate": None,
            "ExternalContactName": None,
            "ExternalContactEmail": None,
            "NumberOfOpenings": None,
            "PrimaryLocation": "Redwood City, CA, United States",
            "WorkplaceType": "Hybrid",
            "ShortDescriptionStr": "Responsible for administering admission activities.",
            "ExternalDescriptionStr": "<p>Read and evaluate applications for the program.</p>",
            "ExternalQualificationsStr": (
                "<ul><li>Bachelor's degree and three years of relevant experience.</li>"
                "<li>Preferred: experience with Slate.</li></ul>"
            ),
            "ExternalResponsibilitiesStr": (
                "<p><strong>Core Duties</strong>:</p><ul><li>Advocate to the Admission "
                "Committee.</li></ul>"
            ),
            "requisitionFlexFields": [
                {"Prompt": "Pay Range", "Value": "$79,105.16-$147,662.97", "SequenceNumber": 1},
                {"Prompt": "Pay Frequency", "Value": "Annually", "SequenceNumber": 2},
                {"Prompt": "Fixed Term", "Value": "N", "SequenceNumber": 3},
                {
                    "Prompt": "Stanford Schools and Units",
                    "Value": "Offices of the President and Provost",
                    "SequenceNumber": 4,
                },
                {"Prompt": "Full time or Part time", "Value": "Full Time", "SequenceNumber": 7},
            ],
            "workLocation": [
                {
                    "LocationName": "ACADEMY HALL",
                    "AddressLine1": "415 Broadway St",
                    "TownOrCity": "Redwood City",
                    "Region2": "CA",
                    "PostalCode": "94063",
                    "Country": "US",
                }
            ],
            "secondaryLocations": [],
            "skills": [],
        }
    ],
    "count": 1,
}

CS_FACULTY_HTML = """
<html><body><main>
  <div class="ds-entity--node ds-entity--stanford-person">
    <article class="su-card su-card--minimal">
      <div class="su-card__contents">
        <div class="node stanford-person node-title ds label-hidden">
          <h3><a href="/people/ehsan-adeli" hreflang="en">Ehsan Adeli</a></h3>
        </div>
        <div class="node stanford-person su-person-short-title string label-hidden">
          Assistant Professor of Psychiatry &amp; Behavioral Sciences
        </div>
      </div>
    </article>
  </div>
  <div class="ds-entity--node ds-entity--stanford-person">
    <article class="su-card">
      <div class="su-card__contents">
        <div class="node-title"><h3><a href="/people/chelsea-finn">Chelsea Finn</a></h3></div>
        <div class="su-person-short-title">Assistant Professor of Computer Science</div>
      </div>
    </article>
  </div>
</main></body></html>
"""

HUB_INDEX_HTML = """
<html><body>
  <nav><a href="/jobs">Student Jobs at The Hub</a><a href="/saml/login?destination=/jobs">Web Login</a></nav>
  <main>
    <a href="/student-technical-consultant-job-description">Student Technical Consultant Job Description</a>
    <a href="/tech-desk-consultant-job-description">The Tech Desk Consultant Job Description</a>
    <a href="/about-us">About the Hub</a>
    <a href="https://form.asana.com/?k=abc&amp;d=123">Apply Now!</a>
    <a href="mailto:hub-jobs@stanford.edu">hub-jobs@stanford.edu</a>
  </main>
</body></html>
"""

REC_INDEX_HTML = """
<html><body><main>
  <p>Contact information: <a href="mailto:stanfordaquatics@stanford.edu">stanfordaquatics@stanford.edu</a></p>
  <a href="https://drive.google.com/file/d/1B6Nf9/view?usp=sharing">Lifeguard</a>
  <a href="https://docs.google.com/document/d/1jiGA/edit">Swim Instructor</a>
  <a href="https://www.teamworksapp.com/ext/14771279">Teamworks Application</a>
  <a href="/connect/staff-directory">Staff Directory</a>
  <a href="https://careersearch.stanford.edu/">Stanford University Careers Page</a>
</main></body></html>
"""

LAB_HOME_HTML = """
<html><body>
  <a href="/people">Lab Members</a>
  <a href="/join">Join the lab</a>
  <a href="/news">News</a>
  <a href="/publications">Publications</a>
  <a href="/research">Research</a>
  <a href="/cv.pdf">CV</a>
  <a href="https://twitter.com/somelab">Twitter</a>
  <a href="mailto:pi@stanford.edu">Email the PI</a>
</body></html>
"""

SPA_SHELL_HTML = (
    '<!doctype html><html><head><title>CURIS</title></head><body>'
    "<noscript>You need to enable JavaScript to run this app.</noscript>"
    '<div id="root"></div></body></html>'
)

OPENALEX_WORK: dict[str, Any] = {
    "id": "https://openalex.org/W4394987867",
    "doi": "https://doi.org/10.1016/j.example.2026.109795",
    "title": "Humanoid whole-body loco-manipulation from motion tracking",
    "display_name": "Humanoid whole-body loco-manipulation from motion tracking",
    "publication_year": 2026,
    "publication_date": "2026-04-21",
    "type": "article",
    "primary_location": {
        "landing_page_url": "https://example.org/paper",
        "source": {"display_name": "Conference on Robot Learning"},
    },
    "authorships": [
        {"author": {"display_name": "A. Student"}},
        {"author": {"display_name": "C. Karen Liu"}},
    ],
}


# --------------------------------------------------------------------------
# careersearch — Oracle HCM JSON
# --------------------------------------------------------------------------


def test_parse_search_page_reads_total_and_requisitions() -> None:
    page = careers.parse_search_page(HCM_SEARCH_RESPONSE)
    assert page.total == 415
    assert [r["Id"] for r in page.requisitions] == ["200888", "200761"]


@pytest.mark.parametrize("payload", [None, {}, {"items": []}, {"items": [None]}, "nope"])
def test_parse_search_page_tolerates_garbage(payload: object) -> None:
    page = careers.parse_search_page(payload)
    assert page.total == 0
    assert page.requisitions == []


def test_parse_detail_returns_the_requisition() -> None:
    detail = careers.parse_detail(HCM_DETAIL_RESPONSE)
    assert detail is not None
    assert detail["Id"] == "200888"
    assert careers.parse_detail({"items": []}) is None


def test_flex_fields_are_keyed_by_prompt() -> None:
    detail = careers.parse_detail(HCM_DETAIL_RESPONSE)
    flex = careers.flex_fields(detail)
    assert flex["Pay Range"] == "$79,105.16-$147,662.97"
    assert flex["Full time or Part time"] == "Full Time"
    assert careers.flex_fields(None) == {}


def test_build_document_prefers_api_fields_over_prose() -> None:
    summary = HCM_SEARCH_RESPONSE["items"][0]["requisitionList"][0]
    document = careers.build_document(summary, careers.parse_detail(HCM_DETAIL_RESPONSE))

    assert document.url == (
        "https://careersearch.stanford.edu/hcmUI/CandidateExperience/en/sites/"
        "stanford/job/200888"
    )
    assert document.external_key == "stanford-careersearch-200888"
    assert document.kind_hint is OpportunityType.PART_TIME
    assert document.error is None
    assert document.ok

    structured = document.structured
    assert structured["requisition_id"] == "200888"
    assert structured["pay_range"] == "$79,105.16-$147,662.97"
    assert structured["pay_frequency"] == "Annually"
    assert structured["full_or_part_time"] == "Full Time"
    assert structured["school_or_unit"] == "Offices of the President and Provost"
    assert structured["job_family"] == "Student Services"
    assert structured["category"] == "Student Services"
    assert structured["work_locations"][0]["city"] == "Redwood City"
    assert "Slate" in structured["qualifications_text"]
    assert "Admission Committee" in structured["responsibilities_text"]
    # The recon census is recorded on every document so no downstream code can
    # mistake this board for the student-jobs board.
    assert structured["board_carries_student_hourly_jobs"] is False


def test_build_text_keeps_qualifications_and_responsibilities_apart() -> None:
    summary = HCM_SEARCH_RESPONSE["items"][0]["requisitionList"][0]
    text = careers.build_document(
        summary, careers.parse_detail(HCM_DETAIL_RESPONSE)
    ).text
    assert text is not None
    assert "## Description" in text
    assert "## Responsibilities" in text
    # Oracle publishes one qualifications blob; the heading must say so rather
    # than let a "preferred" line be read as required.
    assert "## Qualifications (as published; the source does not separate" in text
    assert text.index("## Qualifications") < text.index("## Responsibilities")


def test_build_document_without_detail_records_why() -> None:
    summary = HCM_SEARCH_RESPONSE["items"][0]["requisitionList"][1]
    document = careers.build_document(summary, None, error="requisition detail unavailable")
    assert document.error == "requisition detail unavailable"
    assert document.structured["title"] == "Life Science Research Professional 1"
    assert document.structured["pay_range"] is None
    assert document.structured["description_text"] is None


def test_matches_context_filters_on_keywords() -> None:
    summary = HCM_SEARCH_RESPONSE["items"][0]["requisitionList"][1]
    assert careers.matches_context(summary, SourceContext(university="Stanford University"))
    assert careers.matches_context(
        summary, SourceContext(university="Stanford University", keywords=["research"])
    )
    assert not careers.matches_context(
        summary, SourceContext(university="Stanford University", keywords=["dining"])
    )


# --------------------------------------------------------------------------
# handshake — extension payload only
# --------------------------------------------------------------------------


def test_handshake_discovers_nothing() -> None:
    adapter = handshake.HandshakeAdapter()
    assert list(adapter.discover(SourceContext(university="Stanford University"))) == []
    assert adapter.requires_auth is True
    assert adapter.is_mocked is False
    assert adapter.kind is SourceKind.HANDSHAKE


def test_normalize_extension_payload_maps_fields() -> None:
    document = handshake.normalize_extension_payload(
        {
            "job_id": "8000000",
            "url": "https://stanford.joinhandshake.com/stu/jobs/8000000",
            "title": "Residential SOAR Specialist",
            "employer": "Trilogy, Inc.",
            "employer_id": "14571",
            "location": "Chicago, Illinois",
            "work_mode": "On-site",
            "job_type": "On Campus Student Employment",
            "employment_type": "Part-time",
            "pay": "$22.83 /Hr.",
            "posted_at": "2026-08-14",
            "apply_by": "2026-09-30",
            "application_method": "quick apply",
            "documents_required": ["Resume", "  "],
            "description_text": "Support residents in the SOAR program.",
            "description_html": "<p>Support residents in the SOAR program.</p>",
            "captured_at": "2026-08-31T12:00:00Z",
            "extension_version": "0.1.0",
        }
    )

    assert document.retrieved_by == "extension"
    assert document.url == "https://stanford.joinhandshake.com/stu/jobs/8000000"
    assert document.external_key == "handshake-8000000"
    assert document.title == "Residential SOAR Specialist"
    assert document.text == "Support residents in the SOAR program."
    assert document.kind_hint is OpportunityType.ON_CAMPUS
    assert document.fetched_at is not None
    assert document.fetched_at.year == 2026
    assert document.error is None

    structured = document.structured
    assert structured["job_id"] == "8000000"
    assert structured["employer"] == "Trilogy, Inc."
    assert structured["pay_text"] == "$22.83 /Hr."
    assert structured["documents_required"] == ["Resume"]
    # Case-insensitive match onto Handshake's own documented button label.
    assert structured["application_method"] == "Quick Apply"
    assert structured["auto_submit_forbidden"] is True
    assert "application_method_unrecognized" not in structured


def test_normalize_extension_payload_recovers_the_job_id_from_the_url() -> None:
    for url in (
        "https://stanford.joinhandshake.com/jobs/12345",
        "https://stanford.joinhandshake.com/stu/jobs/12345",
        "https://app.joinhandshake.com/emp/jobs/12345",
    ):
        document = handshake.normalize_extension_payload({"url": url, "title": "Role"})
        assert document.structured["job_id"] == "12345"
        assert document.external_key == "handshake-12345"


def test_normalize_extension_payload_drops_unexpected_fields() -> None:
    document = handshake.normalize_extension_payload(
        {
            "job_id": "77",
            "title": "Role",
            "sunet_password": "hunter2",
            "session_cookie": "abc",
        }
    )
    assert document.structured["rejected_fields"] == ["session_cookie", "sunet_password"]
    assert "sunet_password" not in document.structured
    assert "hunter2" not in str(document.structured)


def test_normalize_extension_payload_flags_an_unknown_apply_flow() -> None:
    document = handshake.normalize_extension_payload(
        {"job_id": "77", "application_method": "One-Click Magic Apply"}
    )
    assert document.structured["application_method"] is None
    assert document.structured["application_method_unrecognized"] == "One-Click Magic Apply"


def test_normalize_extension_payload_needs_an_identity() -> None:
    document = handshake.normalize_extension_payload({"title": "Role"})
    assert document.error is not None
    assert not document.ok
    assert handshake.normalize_extension_payload(["not", "a", "dict"]).error is not None


def test_infer_kind_never_guesses() -> None:
    assert handshake.infer_kind({"job_type": "Internship"}) is None
    assert handshake.infer_kind({"employment_type": "Full-time"}) is None
    assert handshake.infer_kind({"employment_type": "Part-time"}) is OpportunityType.PART_TIME


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------


def test_registry_round_trips_every_slug() -> None:
    assert SOURCE_ADAPTERS
    for slug, cls in SOURCE_ADAPTERS.items():
        adapter = get_adapter(slug)
        assert isinstance(adapter, cls)
        assert adapter.slug == slug
        assert adapter.describe()["slug"] == slug
        assert adapter.describe()["kind"] == adapter.kind.value


def test_all_adapters_matches_the_registry() -> None:
    adapters = all_adapters()
    assert {a.slug for a in adapters} == set(SOURCE_ADAPTERS)
    assert len(adapters) == len(SOURCE_ADAPTERS)
    assert all(a.name for a in adapters)


def test_get_adapter_rejects_an_unknown_slug() -> None:
    with pytest.raises(LookupError):
        get_adapter("linkedin")


def test_only_handshake_requires_auth() -> None:
    assert {a.slug for a in all_adapters() if a.requires_auth} == {"handshake"}


# --------------------------------------------------------------------------
# CS faculty directory
# --------------------------------------------------------------------------


def test_parse_area_page_reads_name_title_and_profile_url() -> None:
    records = cs_faculty.parse_area_page(
        CS_FACULTY_HTML,
        area="artificial-intelligence",
        page_url=cs_faculty.area_url("artificial-intelligence"),
    )
    assert [r["name"] for r in records] == ["Ehsan Adeli", "Chelsea Finn"]
    assert records[0]["profile_url"] == "https://www.cs.stanford.edu/people/ehsan-adeli"
    assert records[0]["title"].startswith("Assistant Professor of Psychiatry")
    assert records[1]["area"] == "artificial-intelligence"


def test_parse_area_page_falls_back_to_bare_profile_links() -> None:
    html = '<html><body><a href="/people/jane-doe">Jane Doe</a></body></html>'
    records = cs_faculty.parse_area_page(html, area="robotics", page_url=cs_faculty.area_url("robotics"))
    assert records == [
        {
            "name": "Jane Doe",
            "title": None,
            "profile_url": "https://www.cs.stanford.edu/people/jane-doe",
            "area": "robotics",
        }
    ]


def test_faculty_document_carries_the_directory_facts() -> None:
    record = cs_faculty.parse_area_page(
        CS_FACULTY_HTML,
        area="artificial-intelligence",
        page_url=cs_faculty.area_url("artificial-intelligence"),
    )[1]
    document = cs_faculty.faculty_document(record, ["artificial-intelligence", "robotics"])
    assert document.kind_hint is OpportunityType.RESEARCH_OUTREACH
    assert document.external_key == "stanford-cs-faculty-chelsea-finn"
    assert document.structured["name"] == "Chelsea Finn"
    assert document.structured["profile_url"].endswith("/people/chelsea-finn")
    assert document.structured["areas"] == ["artificial-intelligence", "robotics"]
    assert document.ok


def test_areas_for_topics_maps_interests_onto_directory_slugs() -> None:
    assert cs_faculty.areas_for_topics(["NLP"]) == ["natural-language-processing-and-speech"]
    assert cs_faculty.areas_for_topics(["Machine Learning"]) == [
        "machine-learning",
        "empirical-machine-learning",
    ]
    assert cs_faculty.areas_for_topics(["robotics", "rl"]) == [
        "robotics",
        "reinforcement-learning",
    ]
    # An area slug passes straight through; an unknown topic contributes nothing.
    assert cs_faculty.areas_for_topics(["computer-vision"]) == ["computer-vision"]
    assert cs_faculty.areas_for_topics(["underwater basket weaving"]) == []


def test_every_mapped_area_is_a_real_directory_slug() -> None:
    for areas in cs_faculty.TOPIC_TO_AREAS.values():
        for area in areas:
            assert area in cs_faculty.AREA_SLUGS


# --------------------------------------------------------------------------
# student job pages
# --------------------------------------------------------------------------


def test_detail_links_follows_only_the_configured_hint() -> None:
    page = student_jobs.SOURCE_PAGES[0]
    assert page.detail_hints == ("-job-description",)
    links = student_jobs.detail_links(HUB_INDEX_HTML, page)
    assert [link.url for link in links] == [
        "https://thehub.stanford.edu/student-technical-consultant-job-description",
        "https://thehub.stanford.edu/tech-desk-consultant-job-description",
    ]


def test_detail_links_ignores_other_configured_index_pages() -> None:
    page = student_jobs.SOURCE_PAGES[1]
    html = (
        '<html><body><main><a href="/dining-hospitality/student-engagement">'
        "Explore Opportunities</a>"
        '<a href="/student-employment/housing-worker">Student Housing Worker job</a>'
        "</main></body></html>"
    )
    urls = [link.url for link in student_jobs.detail_links(html, page)]
    assert urls == ["https://rde.stanford.edu/student-employment/housing-worker"]


def test_linked_documents_records_offsite_descriptions_without_fetching() -> None:
    page = student_jobs.SOURCE_PAGES[3]
    documents = student_jobs.linked_documents(REC_INDEX_HTML, page.url)
    by_url = {d["url"]: d["kind"] for d in documents}
    assert by_url["https://drive.google.com/file/d/1B6Nf9/view?usp=sharing"] == "google_drive_file"
    assert by_url["https://docs.google.com/document/d/1jiGA/edit"] == "google_doc"
    assert by_url["https://www.teamworksapp.com/ext/14771279"] == "application_form"
    assert "https://careersearch.stanford.edu/" not in by_url


def test_external_key_is_stable_and_slugged() -> None:
    page = student_jobs.SOURCE_PAGES[0]
    key = student_jobs.external_key_for(
        "https://thehub.stanford.edu/student-technical-consultant-job-description", page
    )
    assert key == "stanford-thehub-student-technical-consultant"
    assert student_jobs.external_key_for(page.url, page) == "stanford-thehub-jobs"


def test_every_configured_student_job_page_is_stanford_and_https() -> None:
    for page in student_jobs.SOURCE_PAGES:
        assert page.url.startswith("https://")
        assert ".stanford.edu" in page.url
        assert page.unit and page.organization


# --------------------------------------------------------------------------
# programs
# --------------------------------------------------------------------------


def test_program_links_follows_grants_and_skips_chrome() -> None:
    page = programs.PROGRAM_PAGES[-1]
    html = """
    <html><body><main>
      <a href="/fund-your-project/explore-student-grants/major">Major Grant</a>
      <a href="/fund-your-project/explore-student-grants/small">Small Grant</a>
      <a href="/node/51">Get Inspired</a>
      <a href="https://www.instagram.com/mystanfordresearch/">Instagram</a>
      <a href="/apply">Preparing your Application</a>
    </main></body></html>
    """
    urls = [link.url for link in programs.program_links(html, page)]
    assert urls == [
        "https://undergradresearch.stanford.edu/fund-your-project/explore-student-grants/major",
        "https://undergradresearch.stanford.edu/fund-your-project/explore-student-grants/small",
    ]


def test_curis_pages_are_flagged_as_client_rendered_in_the_config() -> None:
    curis = [p for p in programs.PROGRAM_PAGES if "curis.stanford.edu" in p.url]
    assert curis
    assert all("client-rendered" in p.note.lower() for p in curis)


def test_program_external_keys_are_distinct() -> None:
    keys = [programs.external_key_for(p.url) for p in programs.PROGRAM_PAGES]
    assert len(keys) == len(set(keys))
    assert "stanford-curis-summer" in keys


# --------------------------------------------------------------------------
# lab site + shared crawl helpers
# --------------------------------------------------------------------------


def test_same_host_links_are_absolute_and_deduped() -> None:
    links = lab_site.same_host_links(LAB_HOME_HTML, "https://tml.stanford.edu/", main_only=False)
    urls = [link.url for link in links]
    assert "https://tml.stanford.edu/join" in urls
    assert "https://twitter.com/somelab" not in urls
    assert len(urls) == len(set(urls))


def test_link_role_classifies_lab_sections() -> None:
    roles = {
        link.url.rsplit("/", 1)[-1]: lab_site.link_role(link)
        for link in lab_site.same_host_links(
            LAB_HOME_HTML, "https://tml.stanford.edu/", main_only=False
        )
    }
    assert roles["join"] == "join"
    assert roles["people"] == "people"
    assert roles["news"] == "news"
    assert roles["publications"] == "publications"


def test_extract_emails_reads_mailto_links() -> None:
    assert lab_site.extract_emails(LAB_HOME_HTML, "https://tml.stanford.edu/") == [
        "pi@stanford.edu"
    ]


def test_document_links_are_recognised() -> None:
    assert lab_site.is_document_link("https://rde.stanford.edu/files/jd.pdf")
    assert not lab_site.is_document_link("https://rde.stanford.edu/student-employment")
    assert lab_site.is_offsite_document("https://docs.google.com/document/d/1/edit")


def test_normalise_url_drops_fragments_and_trailing_slash() -> None:
    assert lab_site.normalise_url("https://x.edu/a/#top") == "https://x.edu/a"
    assert lab_site.normalise_url("https://x.edu/") == "https://x.edu/"


# --------------------------------------------------------------------------
# manual url primitive
# --------------------------------------------------------------------------


def test_client_rendered_shells_are_detected() -> None:
    assert manual_url.looks_client_rendered(SPA_SHELL_HTML, "CURIS")
    assert not manual_url.looks_client_rendered(SPA_SHELL_HTML, "x" * 400)
    assert not manual_url.looks_client_rendered(None, None)


def test_binary_content_types_are_refused() -> None:
    assert manual_url.is_textual("text/html; charset=utf-8")
    assert manual_url.is_textual(None)
    assert not manual_url.is_textual("application/pdf")


def test_parse_url_list_keeps_order_and_drops_junk() -> None:
    assert manual_url.parse_url_list(
        "https://a.edu/x, https://b.edu/y https://a.edu/x not-a-url"
    ) == ["https://a.edu/x", "https://b.edu/y"]
    assert manual_url.parse_url_list(None) == []


# --------------------------------------------------------------------------
# openalex
# --------------------------------------------------------------------------


def test_work_to_dict_is_a_citation() -> None:
    work = openalex.work_to_dict(OPENALEX_WORK)
    assert work["title"] == "Humanoid whole-body loco-manipulation from motion tracking"
    assert work["year"] == 2026
    assert work["venue"] == "Conference on Robot Learning"
    assert work["doi"] == "https://doi.org/10.1016/j.example.2026.109795"
    assert work["url"] == "https://example.org/paper"
    assert work["authors"] == ["A. Student", "C. Karen Liu"]


def test_work_to_dict_survives_missing_location() -> None:
    work = openalex.work_to_dict({"id": "https://openalex.org/W1", "display_name": "Untitled"})
    assert work["venue"] is None
    assert work["url"] == "https://openalex.org/W1"
    assert work["authors"] == []


def test_pick_author_prefers_an_exact_name_then_output() -> None:
    candidates = [
        {"id": "A1", "display_name": "Chelsea Finn", "works_count": 3},
        {"id": "A2", "display_name": "Chelsea Finn", "works_count": 390},
        {"id": "A3", "display_name": "Chelsea B. Finnegan", "works_count": 9000},
    ]
    assert openalex.pick_author("Chelsea Finn", candidates)["id"] == "A2"
    assert openalex.pick_author("Nobody Here", candidates)["id"] == "A3"
    assert openalex.pick_author("Chelsea Finn", []) is None


def test_openalex_urls_escape_names_without_breaking_filter_syntax() -> None:
    url = openalex._build_url(
        openalex.AUTHORS_URL,
        filters=f"display_name.search:C. Karen Liu,{openalex.AFFILIATION_FILTER}:"
        f"{openalex.STANFORD_ROR}",
        select="id",
    )
    assert "display_name.search:C.%20Karen%20Liu" in url
    assert "affiliations.institution.ror:00f54p054" in url
    assert "%25" not in url


# --------------------------------------------------------------------------
# live endpoint checks (opt-in)
# --------------------------------------------------------------------------


@requires_network
def test_live_careersearch_search_endpoint() -> None:
    from app.sources.http import get_fetcher

    url = careers.SEARCH_URL.format(site=careers.SITE_NUMBER, limit=5, offset=0)
    status, payload, error = get_fetcher().get_json(url)
    assert error is None, error
    assert status == 200
    page = careers.parse_search_page(payload)
    assert page.total > 0
    assert page.requisitions


@requires_network
def test_live_cs_faculty_area_page() -> None:
    ctx = SourceContext(university="Stanford University", topics=["robotics"], limit=5)
    documents = list(cs_faculty.StanfordCsFacultyAdapter().discover(ctx))
    assert documents
    assert all(d.structured.get("name") for d in documents if d.ok)


@requires_network
def test_live_openalex_recent_works() -> None:
    works = openalex.recent_works("Chelsea Finn", since_year=2024, limit=3)
    assert works
    assert all(w["title"] for w in works)


@requires_network
def test_live_student_job_index_pages_are_readable() -> None:
    from app.sources.manual_url import fetch_document

    for page in student_jobs.SOURCE_PAGES:
        document = fetch_document(page.url)
        assert document.error is None, f"{page.url}: {document.error}"
        assert document.text


def test_extension_payload_fields_reach_the_opportunity_schema():
    """The extension's most valuable fields — apply-by date, pay, employer —
    must survive normalisation and extraction. They were silently dropped once
    because the adapter and the extractor used different key names."""
    from app.agents.extraction_agent import STRUCTURED_ALIASES
    from app.sources.handshake import normalize_extension_payload

    doc = normalize_extension_payload(
        {
            "url": "https://stanford.joinhandshake.com/jobs/9137742",
            "title": "Undergraduate Research Assistant",
            "employer": "Stanford HAI",
            "pay": "$22.50/hr",
            "apply_by": "2026-09-30",
            "application_method": "handshake",
            "description": "Qualifications: current Stanford undergraduate.",
        }
    )
    assert doc.ok, doc.error

    for canonical, key in (
        ("deadline", "apply_by"),
        ("pay", "pay_text"),
        ("organization", "employer"),
    ):
        assert key in STRUCTURED_ALIASES[canonical], (
            f"{key!r} must be an alias of {canonical!r} or the extractor drops it"
        )
        assert doc.structured.get(key), f"normaliser did not emit {key!r}"
