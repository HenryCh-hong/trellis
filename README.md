# Trellis

A personal opportunity agent for a university student. It finds, evaluates,
organises and helps prepare applications for four things a student actually
needs and that no single tool covers together:

1. **On-campus jobs** — library, IT, dining, campus recreation, residential ed
2. **Part-time jobs**
3. **Undergraduate research openings** — programmes you formally apply to
4. **Labs and professors worth emailing** even when nothing is advertised

The fourth is the point. Most undergraduate research never gets posted, so a
job-board-shaped product cannot see it. Trellis reads what a lab has actually
published in the last 12–24 months, infers where the work is heading *now*, and
tells you whether there is a real opening or whether this is a cold-email lead —
with the evidence attached.

It is currently seeded with a **real, cited Stanford corpus**. There is no
fabricated demo data anywhere in this repository.

| | |
|---|---|
| Faculty profiles | 28, with 187 dated evidence items |
| Labs | 21 linked, 57 sites catalogued |
| Campus & part-time jobs | 38 real postings |
| Undergraduate research programmes | 16 (5 with published deadlines) |
| Research topics | 49, all traceable to harvested text |

## Setup

Requires PostgreSQL 16, Node 20+, and [uv](https://docs.astral.sh/uv/).

```bash
make setup     # venv + npm install + create the database + migrate
make seed      # load the real Stanford corpus from data/harvest/
make dev       # API on :8000, web on :3000
```

Then open http://localhost:3000. On first run you land in onboarding: five
questions, then discovery starts.

No API key is needed. Trellis ships with a deterministic, rule-based LLM
provider and runs end to end without one. Set `ANTHROPIC_API_KEY` in
`apps/api/.env` to switch to Claude for the steps where reading prose genuinely
helps; everything else is ordinary code either way.

## Layout

```
apps/api/          FastAPI + SQLAlchemy 2.0 + PostgreSQL
  app/models/      32 tables
  app/agents/      the eight agents (search, research, extraction, deadline,
                   eligibility, matching, resume, application prep)
  app/services/    scoring, taxonomy, extractors, dedup, applications, runs
  app/sources/     one adapter per source, behind a common interface
  app/llm/         provider abstraction (deterministic | anthropic)
  app/reminders/   ics | apple_shortcuts | none
  app/seed/        loads data/harvest into Postgres, idempotently
apps/web/          Next.js 16 (App Router), React 19, Tailwind v4
apps/extension/    Chrome MV3 extension for Handshake import
data/harvest/      the real harvested corpus + its provenance manifest
docs/              architecture, data sources, privacy, uncertainty, decisions
```

## What is real, and what is not

**Real and live.** These adapters hit real endpoints:

- Stanford CS faculty directory, by research area
- Stanford student-employment pages (thehub, R&DE, campus rec, ResEd)
- Stanford Careers (Oracle HCM JSON API)
- Stanford undergraduate research programmes (CURIS, VPUE, Bio-X …)
- OpenAlex for recent publications
- Any URL you paste

**Real but harvested ahead of time.** The shipped corpus in `data/harvest/` was
collected from public pages on 2026-08-31, each field carrying its source URL
and a confidence. `docs/data-sources.md` lists what could *not* be collected.

**Deliberately not automated.** Handshake. Stanford's own Administrative Guide
10.1.1 routes undergraduate hiring there, so it holds the majority of campus
jobs — but it is behind SSO + Duo, its `robots.txt` is `Disallow: /`, and its
terms forbid third-party bulk collection. Trellis therefore never fetches it.
Those jobs arrive through `apps/extension/`, which reads the page you are
already looking at in your own logged-in tab. See its README for the full list
of things it will not do.

**Not built, on purpose.** Resume rewriting. Trellis reads the resumes you
upload and tells you which one to use and which of your own lines to lead with.
It never edits them and never invents experience. The architecture leaves room
for tailoring later; the MVP does none.

## Principles this codebase actually enforces

- An unsupported value is `null` with confidence 0 and renders as **Unknown**.
  It is never a plausible guess.
- **Required** and **preferred** qualifications are separate columns, separate
  arrays, and separate UI blocks. A "preferred" line can never be shown as required.
- Every score is a component breakdown with weights and human reasons. Open any
  opportunity and you can audit the number.
- Nothing is submitted anywhere without an approval bound to a hash of the exact
  payload you reviewed. Change one answer and the approval is void.
- Work-authorisation, demographic, disability, veteran-status and
  self-identification questions are never auto-filled or drafted. Ever.

## Commands

```bash
make test        # backend suite
make lint        # ruff + eslint
make typecheck   # tsc --noEmit
make reseed      # wipe and reload the corpus
bash scripts/verify.sh   # end-to-end smoke test
```
