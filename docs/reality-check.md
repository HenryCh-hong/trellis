# Reality check

What actually works, verified by running it — not by reading the code.

Method: `apps/web/audit.mjs` drives the real UI in a real Chromium against the
real API and asserts against Postgres after a full page reload;
`apps/web/interaction-audit.mjs` enumerates every interactive control on every
screen and reports any that are wired to nothing. Both are committed and
re-runnable.

Last run: 2026-08-31. **25/25** audit checks pass, twice consecutively (the
suite restores everything it touches, so it is repeatable and never leaves test
data in the real profile). **322** interactive controls checked, **0** inert,
**0** broken links. `tsc`, `eslint --max-warnings 0` and `ruff` all clean.

```bash
cd apps/web && node audit.mjs              # 24 checks
cd apps/web && node interaction-audit.mjs  # every button on every screen
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

**Apple Reminders** — Trellis produces the Shortcut payload and the setup recipe;
it cannot write into Apple Reminders directly, and the UI says so. The `.ics`
path needs no setup and is the default.

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
- *Handshake side — `MANUAL VERIFICATION REQUIRED`.* The extension has **not**
  been run against a live logged-in Handshake page, because that needs a real
  SUNet login plus Duo. Its extraction logic is unit-tested against
  hand-authored fixtures (7/7). No fake import was created to paper over this.

**Applying to anything** — by design. Trellis opens the application page and
stops. Handshake Quick Apply, external ATS, SSO, CAPTCHA and Duo are never
automated.

**Apple Shortcut installation** — one-time, done by you in the Shortcuts app.

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
- **Deadline coverage.** Only 11 of 91 opportunities have a dated deadline. The
  rest are genuinely rolling or unstated, not missing data.
