# Architecture

## Request path

```
Next.js server component ──► FastAPI ──► service/agent ──► SQLAlchemy ──► Postgres
        (typed client)          │
                                └─► task queue ──► search / research agent ──► sources
```

The frontend never talks to the database and never re-implements a rule. Every
judgement — eligibility, fit, urgency, what is blocking an application — is
computed server-side and serialised once, in `app/api/serializers.py`, so two
screens can never disagree about the same fact.

## Why eight small agents instead of one loop

A single autonomous agent would be easier to write and much harder to trust.
Splitting it means each unit has a typed input, a typed output, and a test.

| Agent | Does | Uses an LLM? |
|---|---|---|
| `OpportunitySearchAgent` | strategies → sources → dedup → extract → score → upsert | no |
| `ResearchDiscoveryAgent` | interests → faculty → lab → recent work → current direction → classify | no |
| `WebExtractionAgent` | page → structured opportunity + provenance | only for fields left empty |
| `DeadlineAgent` | date + the sentence that supports it | no |
| `EligibilityAgent` | per-requirement match, required vs preferred | no |
| `MatchingAgent` | the explainable score, persisted | only to re-word the explanation |
| `ResumeMatchingAgent` | rank the student's uploads, quote their own lines | only to polish a rationale |
| `ApplicationPrepAgent` | questions, prefill, submission plan, approval | only to draft open essay answers |

The rule: **deterministic code for deterministic work.** Dates, scores, dedup,
eligibility and status transitions are ordinary Python. The model is used only
where reading unstructured prose actually helps, and never has authority over a
number. Where it does contribute, its output is a validated Pydantic model
obtained through a forced tool call — never parsed out of free text.

The whole product runs with `DeterministicProvider`, which has no network and no
model. It answers what it can from rules and returns *unknown* for the rest. It
never fabricates to fill a gap.

## The four provider abstractions

Each is a small ABC with one job, so swapping an implementation is a settings
change rather than a refactor.

- `app/llm/base.py` — `LLMProvider.complete_json(schema=…)`. Ships
  `deterministic` (default) and `anthropic`.
- `app/sources/base.py` — `SourceAdapter.discover(ctx) -> Iterable[DiscoveredDocument]`.
  **Adding a source is a new class plus a registry entry. Nothing else changes** —
  not extraction, not dedup, not ranking, not the UI.
- `app/tasks/base.py` — `TaskQueue`. Ships an in-process thread pool; four
  methods, so Celery/RQ is a drop-in later.
- `app/reminders/base.py` — `ReminderProvider`. Ships `ics`, `apple_shortcuts`, `none`.

## Evidence, not assertions

`Evidenced[T]` carries `{value, confidence, method, source_text, source_url}` and
maps confidence onto the four words the UI is allowed to say. Thresholds live in
one place (`Evidenced.certainty`) so "Verified" means the same thing everywhere.
See `docs/uncertainty.md`.

Fields whose correctness could change a student's decision also get an
`extracted_fields` row, which is what the detail panel's Source section renders.

## Dedup and refresh

`app/services/dedup.py` resolves identity in precedence order — `(source, external_key)`,
then `external_key`, then normalised URL, then a fuzzy `(title, organization)`
match. Fuzzy is last because two lab postings can easily share a title.

`first_seen_at` is set once and never moves. `last_checked_at` moves every run.
`last_changed_at` and the content fingerprint move only when a *material* field
changes — title, deadline, pay, hours, application URL, requirements — so a
reworded blurb does not show up as "updated".

## The two scoring models

Both return the same `ScoreResult`, so the UI renders one shape. Weights sum to
1.0 and are read here directly from `app/services/scoring.py`.

### Jobs

| Component | Weight | Label |
|---|---|---|
| `qualification_match` | 0.28 | Stated qualifications |
| `skills_match` | 0.18 | Skills |
| `interest_alignment` | 0.16 | Interest alignment |
| `hours_fit` | 0.10 | Weekly hours |
| `location_fit` | 0.08 | Location |
| `deadline_urgency` | 0.08 | Deadline |
| `compensation` | 0.06 | Pay |
| `eligibility` | 0.06 | Eligibility |

Preferred qualifications can only *add*. An unmet preferred line never lowers a
score below what the required lines alone would produce.

When pay is unknown, `compensation` is not scored as zero — its weight is
redistributed across the others and the component reports "not scored". Scoring
an unknown as a zero would quietly punish every posting that omits pay.

### Research

| Component | Weight | Label |
|---|---|---|
| `topic_similarity` | 0.24 | Topic overlap |
| `recent_work_alignment` | 0.20 | Recent work (last 1–2 years) |
| `skills_overlap` | 0.14 | Skills |
| `undergrad_friendliness` | 0.12 | Undergraduate involvement |
| `coursework_overlap` | 0.08 | Coursework |
| `lab_activity` | 0.08 | Lab activity |
| `opening_vs_outreach` | 0.08 | Opening vs. cold outreach |
| `campus_fit` | 0.06 | Campus |

`recent_work_alignment` is the differentiator and the part that took the most
care to get right.

Each evidence item is weighted by recency (≤12 months 1.0, 13–24 months 0.6,
25–36 months 0.25, older 0.05) *before* it competes, so a perfect match from 2019
carries 0.05 and cannot carry the component. A stale biography keyword cannot
produce a high score on its own.

The aggregation is `0.65 × best_recent_hit + 0.35 × breadth`, not a mean over
every item. An early version averaged, and it was wrong: a productive lab with 4
direct hits among 20 papers scored 0.2, because the 16 unrelated papers dragged
it down. Nobody expects every paper from a lab to be about your topic — the
question is whether its *recent* work lands there.

`undergrad_friendliness` is scaled by the certainty of the signal: verified 1.0,
likely 0.7, inferred 0.4, unknown 0.0. Guessed evidence earns proportionally
less credit.

## Lead classification

`OPENING` requires a quoted, currently-open, **undergraduate-relevant** statement
with a source URL. A page that only invites prospective PhD applicants is not an
undergraduate opening. Everything else is `OUTREACH` when the lab has recent
evidence, or `WATCH` when it does not.

Most labs are correctly `OUTREACH`. That is the honest answer and the useful one:
"no advertised opening" is not "no opportunity".

## Pipeline status

One status column drives sorting and filtering. `applications` owns every
transition past `SAVED` and writes through to `opportunities.status`. The write
is one-way, so the two cannot diverge, and `ALLOWED_TRANSITIONS` rejects moves
the pipeline does not permit (there is no `submitted → preparing`).
