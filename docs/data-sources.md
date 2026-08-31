# Data sources

Every source is a `SourceAdapter` in `apps/api/app/sources/`. Adding one is a new
class plus a registry entry; extraction, dedup, ranking and the UI do not change.

## Live adapters

| Adapter | Endpoint | Public? | Yields |
|---|---|---|---|
| `stanford-cs-faculty` | `cs.stanford.edu/people-cs/faculty-research/<area>` | yes | faculty per research area — the interest → department → faculty step |
| `stanford-student-jobs` | `thehub.stanford.edu/jobs`, `rde.stanford.edu/student-employment`, `rec.stanford.edu/connect/employment-opportunities`, `resed.stanford.edu/…/student-internships` | yes | the genuinely scrapable campus postings |
| `stanford-careersearch` | `careersearch.stanford.edu/hcmRestApi/…` (Oracle HCM JSON) | yes | staff/academic requisitions |
| `stanford-programs` | `curis.stanford.edu`, `undergradresearch.stanford.edu`, `cs.stanford.edu/bachelors/research-opportunities` | yes | formal undergraduate research programmes |
| `lab-site` | any lab URL | yes | home + news/people/join/publications, bounded to 6 pages |
| `openalex` | `api.openalex.org` (ROR `00f54p054`) | yes | recent publications — what makes "current direction" real |
| `manual-url` | anything you paste | — | one document |
| `handshake` | — | **no** | yields nothing by design; see below |

Server-side fetching is polite by construction: real UA and contact address,
`robots.txt` honoured, per-host rate limiting, response size capped, no cookies.

## Handshake

`stanford-careersearch` carries **no student-hourly jobs**. The harvest verified
this by pulling all 415 open requisitions and censusing `JobFamily` — "Student
Services" turns out to be a staff family, not student employment.

Stanford's Administrative Guide 10.1.1 sends departments to Handshake to post
undergraduate work, and Financial Aid tells students to apply there. So Handshake
holds the majority of campus jobs — and:

- it is behind Stanford SSO (SAML) plus Duo two-step,
- its `robots.txt` is `Disallow: /` on both hosts,
- its Terms explicitly forbid third-party bulk collection of job descriptions,
- its EDU API is issued to the institution, not to students or third-party apps.

Trellis therefore never fetches Handshake. The adapter exists so the source is
visible and honestly labelled in Settings, and `normalize_extension_payload()`
converts what `apps/extension/` reads from the student's own logged-in tab.
**Whatever this app shows for campus jobs is a floor, not a census.**

## Sources checked that yielded nothing

Recorded because a negative result is also provenance:

- Stanford Libraries — no public student-jobs page (9 candidate URLs 404'd)
- Stanford UIT — no public student-job listing
- Cardinal at Work — an HR benefits portal, zero listings
- `financialaid.stanford.edu` — policy only; its own footer is dated 2022-08-31
- `studentjobs.stanford.edu` — does not resolve
- R&DE Strategic Communications — behind SUNet SSO

## Known gaps in the shipped corpus

Collected 2026-08-31. Surfaced in-app under **Settings → Where this data came
from**, in full.

- HANDSHAKE (the biggest gap): Stanford's own Administrative Guide 10.1.1 directs departments hiring undergraduate part-time workers to post on Handshake, so the majority of Stanford student jobs live at https://stanford.joinhandshake.com/ behind SUNet SSO plus Duo two-step. Verified 2026-08-31: /stu/postings redirects to /login. ZERO Handshake postings were harvested. No Stanford credentials were u…
- The Handshake integration recon (recon/handshake-integration.json) is a plan, not data. Its own file lists 11 unverified assumptions - the logged-in DOM was never observed, the search URL parameter grammar is unknown, and it is not confirmed that the student-facing job page even renders a posted date or an apply-by date. It sampled exactly one live posting for structure. Nothing in it should be re…
- 9 of the 16 research programs have NO published next-cycle deadline as of 2026-08-31 and carry deadline.value = null with confidence 0.0: CURIS Summer Internship, PURE, CURIS Fellowships (page says the program 'is not available for Summer 2026'), Bio-X USRP, Tech Ethics & Policy Summer Fellowships, HAI Student Research Opportunities, SESUR, Stanford Summer Fellows Program, and Data Science for Soc…
- Stanford Data Science for Social Good has not been updated since the 2025 cycle - it is unclear whether the program will run again at all. It is recorded with extraction_confidence 0.65 and no deadline rather than being dropped or guessed at.
- 2 more programs (CURIS year-round CS projects, CS 191/195/199 independent study) are genuinely rolling with no dated deadline by design. Only 5 of 16 programs - all VPUE/UAR grants - carry a real, currently-published next-cycle date.
- CURIS individual project listings sit behind Stanford SUNet login and were NOT read; the CURIS project API returned HTTP 401. So the harvest knows the CURIS programs exist but not which specific projects or professors are recruiting through them this cycle.
- 2 of 28 faculty have NO reachable lab or personal site at all. Mehran Sahami: cs.stanford.edu/people/sahami/ returns HTTP 200 but is a 1997-era meta-refresh stub pointing at robotics.stanford.edu/~sahami/bio.html, which itself 404s. Eric Roberts: he is emeritus, has no group, and every group/people/join/CURIS path 404s. Both records carry has_lab_url false and their opportunity assessment rests on…
- 10 more faculty had part of their lab site unreachable, so absence of a recruiting statement is weaker evidence than it looks for them: geometry.stanford.edu /member/guibas/ and /papers/ returned HTTP 403 (Guibas); cs.stanford.edu/~fedkiw/ and physbam.stanford.edu/~fedkiw/ both redirect to a GitHub Pages 404 (Fedkiw); piechlab.stanford.edu /join /contact /news /research all 404 (Piech); autonomous…
- VERIFICATION IS UNEVEN. Exactly 8 of the 28 faculty records (chelsea-finn, dorsa-sadigh, emma-brunskill, jiajun-wu, marco-pavone, mykel-kochenderfer, serena-yeung-levy, tengyu-ma) went through a second, independent ADVERSARIAL re-verification pass in which every load-bearing claim was re-fetched live. The other 20 carry single-pass extraction confidence only. The 'verified' flag in the faculty arr…
- That adversarial pass changed answers, which is the reason to distrust the un-re-verified 20: it downgraded chelsea-finn and mykel-kochenderfer from OPENING to OUTREACH, nulled a faculty email that did not actually appear on its recorded source page (emma-brunskill), and downgraded several individual signals from 'verified' to 'likely' or 'inferred'. Of the 12 records still marked OPENING, only 6 …
- All 28 CS-directory links supplied to the harvest returned HTTP 404 on cs.stanford.edu. faculty_url was rebuilt case by case, usually from profiles.stanford.edu. Any downstream tool should treat cs.stanford.edu/people/<slug> as an unreliable identifier.
- 4 recruiting/application forms are live-routed but sign-in gated, so the harvest can confirm the link is not dead but CANNOT confirm the form is still accepting responses: Chelsea Finn (goo.gl shortlink to a Google Form behind Google sign-in), Dorsa Sadigh, Jeannette Bohg (forms.gle to a JS-rendered proxy interstitial), and Mykel Kochenderfer (Google sign-in/storage interstitial). A student should…
- Faculty coverage is CS-centric and partial. The harvest holds 28 full faculty records, while recon/non-cs-faculty.json separately identified 25 AI-adjacent faculty outside CS, 20 of whom have NO record here at all (including Potts, Gweon, Gerstenberg, Wetzstein, Boyd, Pilanci, Van Roy, Udell, Johari, Demszky, Lee, Pea, Thille, Subramonyam, Hinds, Valentine, Karunakaran, Eichstaedt, Shain, Hawkins)…
- Absence of an OPENING is not evidence of no opportunity. 15 records are OUTREACH and 1 is WATCH, meaning no posted, currently-open, undergraduate-relevant position was found on any page fetched - not that the professor will not take a student.
- One posting is duplicated across files under two different keys: Stanford Careers requisition 200761 (Weekend Library Specialist) appears both as jobs/campus-academic-roles.json#stanford-libraries-weekend-library-specialist-200761 and as recon/student-employment-sources.json#postings/stanford-careersearch-200761. counts.campus_jobs (38) de-duplicates it; the raw files hold 39 records.
- counts.evidence_items (187) counts only the dated evidence items attached to faculty records (136 publications, 24 course listings, 11 news items, 9 projects, 4 talks, 3 grants). It does NOT include the per-field source_text quotations carried by the 15 campus-job and 16 program records, nor the 145 undergraduate signals on faculty records. 123 of the 187 items are dated 2026 and 56 are dated 2025…
- Of the 145 undergraduate-recruiting signals attached to faculty records, 107 are marked 'verified' (backed by a literal quote from a fetched page), 20 'unknown', 13 'likely' and 5 'inferred'. The non-verified 38 are judgement calls, and several of them were downgraded from 'verified' precisely because a claim of ABSENCE cannot be backed by a quote.
- faculty[].latest_evidence_year is each record's own curated lab_activity.last_evidence_year. For eric-roberts this reads 2024 even though the record contains one 2026 item, because that 2026 item is a current Willamette directory listing rather than research output - the record explicitly judges the lab inactive.
- Several plausible sources were checked and yielded nothing, which is itself provenance: careersearch.stanford.edu carries 415 open requisitions but no student-hourly postings; Stanford Libraries has no public student-employment page (9 candidate URLs all 404); UIT has no public student-job listing; Cardinal at Work has none; financialaid.stanford.edu is policy-only and its own footer is dated Augu…
- The ResEd RA/ETA residential-leadership cycle described on resed.stanford.edu had already closed on 2026-08-31 (applications closed January 19), so no postings were emitted from it. The Stanford Recreation per-role job descriptions live on Google Drive/Docs and were NOT fetched, so the 14 recreation postings carry only the page-level $17-$25/hour range and no per-role pay or requirements.
- Freshness: every fetch in this harvest was made on 2026-08-31. Postings, forms and deadlines change without notice; nothing here has been re-checked since. This manifest describes the harvest tree as it stood at generated_at; files added after that time are not reflected.
- recon/topic-ontology.json is a DERIVED artifact - 49 topic slugs rolled up from the research_topics already present on the faculty records, with a seen_in count each. It is not a fetched source and adds no new evidence; it inherits every gap of the records it summarises.
- Two files in this tree carry no external provenance of their own and are listed under files for completeness rather than as sources: recon/topic-ontology.json (derived, above) and this manifest itself.

The machine-readable version is `data/harvest/manifest.json`.
