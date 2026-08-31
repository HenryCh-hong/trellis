# Reality check

What actually works, verified by running it — not by reading the code.

Method: `apps/web/audit.mjs` drives the real UI in a real Chromium against the
real API and asserts against Postgres after a full page reload;
`apps/web/interaction-audit.mjs` enumerates every interactive control on every
screen and reports any that are wired to nothing. Both are committed and
re-runnable.

Last run: 2026-09-01. **30/30** audit checks pass. **1060** interactive
controls checked, **0** inert, **0** disabled without a stated reason. **234**
backend tests pass. `tsc`, `eslint --max-warnings 0` and `ruff` all clean.

```bash
cd apps/web && node audit.mjs              # 30 checks, incl. the daily-loop rules
cd apps/web && node interaction-audit.mjs  # every button on every screen
cd apps/api && python -m pytest -q         # 234 tests
```

---

## WORKING END-TO-END

Verified by driving the browser and then reading Postgres.

| Capability | Evidence from the run |
|---|---|
| Edit profile (university, major, campus, degree, grad year, GPA) | Field edited → DB updated → survives full reload |
| Add / remove research interests | Row written to `profile_research_interests`, visible after reload, removal deletes it |
| Add skills | `profile_skills` 23 → 24; free text normalised onto the canonical skill |
| GPA visibility switch | `gpa_is_public` flips in DB; gates whether GPA enters an application payload |
| Upload a real PDF resume | 1 page, 980 chars parsed, file written to `storage/resumes/`, 5 verbatim lines extracted |
| Resume persists and reopens | Detail panel shows detected skills/topics and the quoted lines after reload |
| Delete a resume | Row **and** the file on disk both removed |
| Resume recommendation | Top recommendation is a real uploaded row, never a placeholder |
| Opportunity table | 91 rows, all from Postgres; a known row renders |
| Interests-first default | 36 of 91 shown by default; every row states why it is there; one click widens to all 91 |
| Un-archive an application | Archiving is reversible; resuming lands in Preparing |
| Deadline sorting | Upcoming → rolling → unknown → **overdue last**; unknown never sorts as "far away" |
| Save an opportunity | Panel control → `status='saved'` in Postgres |
| Deep link to an opportunity | `/opportunities?id=…` opens the panel; selection round-trips through the URL |
| Application status changes | `interview → archived` persisted, and written through to `opportunities.status` |
| Application kit | Real profile fields prefilled; sensitive questions blank and marked |
| Submission plan + approval | Hash-bound; a stale hash is refused with **409** |
| Add reminder | Choose offsets → row created → `.ics` download offered |
| `.ics` export | Valid iCalendar, 3 `VALARM`s, real Stanford URL, real required documents |
| Research leads | 28 leads, **every one** backed by stored evidence |
| Evidence URLs | 5/5 randomly sampled evidence URLs returned HTTP 200 |
| Lab profile | Current direction + certainty word + evidence timeline all render |
| Outreach framing | An outreach lead never shows "Apply now" |
| Live job discovery | 27–49 real pages fetched per run from thehub / undergradresearch / cs.stanford.edu |
| Dedup on re-run | Opportunity count stable at 91 across a repeat run — zero duplicates |
| Live research discovery | 28 faculty re-assessed, 0 duplicates, classifier produces 10 openings / 18 outreach |
| Change tracking | Deadline, pay, hours, application-link and requirement changes recorded to `opportunity_changes` and surfaced on Overview |
| Honesty invariants | No deadline at zero confidence; no email without a source page; unknown renders as "Unknown" |

---

## WORKING WITH LIMITATIONS

**Stanford Careers (`careersearch.stanford.edu`)** — the adapter works and
returns real requisitions, but a census of all open requisitions found **no
student-hourly roles**; it is a staff/academic board. A run now reports this as
`empty` with the reason, not as an error.

**Recreation & Wellness postings (13 roles)** — real roles, but their individual
job descriptions live on Google Drive and were not fetched. They carry only the
page-level `$17–$25/hour` range and no per-role requirements. Stored at
extraction confidence 0.55 and shown as such.

**Research "current direction"** — an inference from recent evidence, labelled
**Inferred** with the basis listed. It is not the lab's own words.

**Apple Reminders** — now a real integration, verified end to end on this Mac.
Trellis runs locally, so the backend drives the Reminders app through
AppleScript. `POST /api/reminders/{id}/apple` created three real reminders in a
"Trellis" list for a real Stanford deadline (Bing Nursery School RA, 9 Oct 2026)
with alerts on 2, 6 and 8 Oct, read back from the Reminders app to confirm.

Three bugs were found only by inspecting the result rather than trusting the
success return, each of which silently broke it:

1. Setting date components inside `tell application "Reminders"` dispatches them
   to Reminders, which does not implement them — `osascript` hung until killed.
2. Reading `id of` the new reminder forces an iCloud round trip and hangs the
   same way.
3. **Reminders overwrites `remind me date` with `due date` when both are set**,
   which collapsed every lead-time alert onto the deadline itself — precisely
   the thing a reminder exists to prevent. Only the alert date is set now, and
   the deadline is carried in the title and note.

Limits, both surfaced in the UI: it needs the API running on the same Mac
(a hosted deployment cannot do it), and macOS gates Reminders behind a
permission prompt on first use.

---

## REQUIRES MANUAL STEP

**Handshake import** — split honestly into two halves:

- *Trellis side — verified.* `POST /api/import/handshake` was driven with a
  payload shaped like the extension's output: it created the opportunity, parsed
  pay `$22.50/hr`, stored the apply-by date as **verified**, split requirements
  into 2 required / 2 preferred, recorded a change entry, and a re-import
  **updated rather than duplicated**. Two real bugs were found and fixed doing
  this (see `docs/interaction-audit.md`). The synthetic record was then deleted —
  it is not real Handshake data and does not sit in the UI.
- *Extraction against real Handshake markup — verified.* Handshake's own
  `robots.txt` explicitly allows `/jobs/*/share_preview`, so the extractor was
  run against three real public job pages (8000000, 9000000, 7500000). It read
  **title, employer, location, description and job id** correctly from all
  three. `job_type`, `pay`, `posted_at`, `apply_by` and `application_method`
  came back `null` — honest, because the logged-out preview genuinely does not
  render them. Notably job 8000000 carries "$22.83 /Hr." as prose inside the
  description and `pay` stayed `null`, which is the behaviour the tests pin: a
  rate the page never labelled is not asserted as the pay.
  The pages were not committed as fixtures — Handshake's terms name job
  descriptions specifically in their anti-bulk-collection clause.
- *Logged-in path — `MANUAL VERIFICATION REQUIRED`.* The extension has **not**
  been run against a live logged-in Handshake page; that needs SUNet plus Duo.
  The fields only visible when signed in are therefore unverified. A markup
  change now surfaces as an explicit error in the popup, and a partial
  extraction names which fields came back empty, rather than a button that
  appears to do nothing.

**Applying to anything** — by design. Trellis opens the application page and
stops. Handshake Quick Apply, external ATS, SSO, CAPTCHA and Duo are never
automated.

**Apple Shortcut installation** — one-time, done by you in the Shortcuts app.

---

## Daily loop — added 2026-09-01

Verified against the real corpus (28 faculty, 187 evidence rows, 91
opportunities), not fixtures.

- **Four lead states, and the discipline not to inflate them.** Every lead is
  `opening` / `outreach` / `watch` / `unknown` with stored signals, each
  carrying a source URL — asserted for all 28 by `audit.mjs`. 7 openings, all
  backed by a quoted statement naming undergraduates; four of those quotes were
  re-fetched from the live pages on 2026-09-01 and found verbatim. The rule
  that mattered: Shuran Song's lab reads *"POSTDOC ONLY — not an undergraduate
  opening"* and stays `outreach`, and Eric Roberts (retired from Stanford in
  2017) is `watch` with that reason shown, not an outreach lead invented to
  give the screen a button.
- **Per-direction evidence and "why now?".** Directions expand to the dated work
  they rest on. "Why now?" appears only with a real signal behind it and says
  what it is ("3 of their 2025–2026 items are on Robotics"); otherwise it says
  no timing signal was found.
- **Fit, from the student's own material.** Strong overlap / relevant
  background / potential gaps, with resume lines quoted verbatim and the file
  named. Gaps are stated plainly ("No Robotics in your profile or resumes").
- **Outreach drafts, composed not generated.** 100–160 words assembled only
  from a dated publication of that lab and the student's own profile and resume
  text, with both sides listed underneath. Tests forbid the failure that
  matters: the draft may never claim the student read, enjoyed or admired
  anything, may never name a skill they do not have, and a course listing may
  never be called a paper. With no recent work that connects, or nothing real
  on file about the student, it refuses and says which — rather than sending a
  template to a named professor. Nothing is ever sent.
- **Deadline lifecycle.** `expired` is a stored state written only by the sweep,
  logged once to the change log, hidden by default with the count always shown
  ("87 of 91 shown · 4 expired hidden") and one click to restore. An expired
  deadline refuses a reminder and the tooltip says why.
- **Feedback that nudges, not filters.** Hiding one row costs it 20 points of
  sort position; siblings sharing its reason stay — asserted by `audit.mjs`.
- **Intent-aware search.** "nlp" surfaces labs whose titles never contain it;
  "part-time" restricts to jobs; "barista" honestly returns nothing.

---

## NOT IMPLEMENTED

- ⌘K command palette. Not built rather than built as a demo.
- Scheduled/background discovery. Runs are manual only.
- Multi-university. Architecture supports it; only Stanford is loaded.
- Resume tailoring or rewriting. Deliberately out of scope.
- Email sending of any kind.

---

## BROKEN

Nothing known. Everything found broken during this pass was fixed — see
`docs/interaction-audit.md` for the list.

---

## UNKNOWN / UNVERIFIED

- **Handshake logged-in DOM.** The extension's selectors are heuristic
  (JSON-LD → knockout props → `<title>` → label matching) because no stable
  logged-in selector is publicly verifiable. Real behaviour is unverified.
- **Long-term source stability.** Adapters were verified on 2026-08-31. Stanford
  pages change without notice.
- **20 of 28 faculty records** carry single-pass extraction confidence; 8 went
  through adversarial re-verification. Recorded in `data/harvest/manifest.json`
  and surfaced in Settings.
- **Deadline coverage.** Only 31 of 91 opportunities have a dated deadline (4 of
  them now expired). The rest are genuinely rolling or unstated, not missing
  data.
- **The `unknown` lead state has no live example.** The code path is tested, but
  all 28 faculty have dated evidence inside the window and a readable contact
  route, so nothing in the real corpus renders as `unknown`. Correct for this
  data; unexercised in the UI.
- **Apple Reminders on another Mac.** Verified on this machine only. The first
  call on a new machine hits the macOS permission prompt, which is a real
  manual step.
