# Decisions

Each of these departs from the obvious option. The alternative and the reason
are recorded so a reviewer can disagree with the reasoning rather than guess at it.

## Research leads are opportunities, not a separate entity

**Alternative:** a `research_leads` table parallel to `opportunities`.

A lab lead needs saving, deadlines, an application kit, a status, reminders and
a pipeline — the same machinery as a dining job. A parallel table would have
duplicated all of it and forced a UNION on every dashboard query. Leads are
`opportunities` with `type = research_opening | research_outreach` and a
`faculty_id`; the extra intelligence hangs off that FK. The spec's own type enum
already anticipated this.

## `publications` folded into `research_evidence`

**Alternative:** the separate `publications` table the spec lists.

§22 asks for a single "2–5 pieces of recent evidence" timeline mixing papers,
projects, news and grants. Split across tables, that timeline is a UNION on every
read. Publications live in `research_evidence` with `kind='publication'` and
publication-specific nullable columns (`venue`, `doi`, `authors`).

## VARCHAR + CHECK instead of native Postgres enums

Native enums make adding a value an `ALTER TYPE` migration with locking
behaviour. This taxonomy is still moving. `SAEnum(..., native_enum=False)` gives
the same Python-level safety and turns adding a value into a cheap constraint change.

## One pipeline status, written through one way

**Alternative:** independent `opportunities.status` and `applications.status`.

Two sources of truth for the same user-visible fact reliably diverge. The list
view needs one sortable column, so `opportunities.status` is it, and
`applications` is the only writer past `SAVED`. `ALLOWED_TRANSITIONS` rejects
moves the pipeline does not permit.

## Hand-written primitives instead of the shadcn CLI

The brief asked for shadcn "heavily customised so it does not look like a default
shadcn starter". Generating defaults and then overriding them tends to leave the
starter's shape visible in the DOM and the spacing. The ~20 primitives here were
written directly against the token set, which was less work than de-shadcn-ing
and left no default look to escape.

## Deterministic LLM provider as the default

**Alternative:** require `ANTHROPIC_API_KEY`.

A student cloning this should get a working product, and more importantly the
offline path forces the honest architecture: if the app must work without a
model, the model cannot be load-bearing for scores, dates or eligibility. The
deterministic provider returns *unknown* rather than filling gaps. Adding a key
improves prose; it does not change a number.

## Browser extension instead of scraping Handshake

**Alternative:** log in on the student's behalf, or use the EDU API.

Handshake is `Disallow: /`, forbids third-party bulk collection in its terms,
and issues its EDU API to institutions rather than students. Storing a SUNet
password or automating Duo would be indefensible regardless of convenience. The
extension reads the page the student is already looking at, on their click, in
their own session — the one defensible line. Cost: campus-job coverage is a
floor, not a census, and the app says so.

## `recent_work_alignment` rewards the best recent hits, not the mean

The first implementation averaged alignment over every evidence item. A lab with
4 direct hits among 20 papers scored 0.2, because 16 unrelated papers dragged it
down — and the reason string said "4 of 7 items overlap your interests" next to a
score of 0.07, which is the kind of contradiction that destroys trust in a number.

Now: `0.65 × best_recent_hit + 0.35 × breadth`. Recency weighting still happens
per item *before* they compete, so an old paper cannot carry the component.

Relatedly, per-item alignment asks "is this artefact on one of the student's
topics?" rather than "how much of the student's interests does it cover?".
Dividing a single paper by the student's whole interest portfolio capped a
perfect topical hit at `1/len(interests)`.

## Related-topic adjacency instead of exact slug matching

Two vocabularies meet: the canonical ontology (`llm-agents`, `hci`) and
Stanford's own department area names (`artificial-intelligence`,
`human-centered-and-creative-ai`). Exact matching made the UI announce "no
overlap with your stated interests" for labs that plainly overlapped.

`_RELATED_PAIRS` in `app/services/taxonomy.py` is a small hand-checked adjacency
list, one hop only. Not embeddings: a wrong edge here becomes a wrong claim on a
lab card, so it needs to be auditable. Transitive closure would connect nearly
everything to everything.

## Single-letter skills need more than a word boundary

`R&DE` (Stanford Residential & Dining Enterprises) matched the R language,
because `&` is a word boundary. That put a skill the student does not have onto
their profile — precisely the fabrication this product forbids. Single-character
skill names are now rejected when glued to a neighbouring token by `&+#/-_.`.
A miss is recoverable; a fabricated skill is not.

## Inferred requirements are not persisted as requirements

For a faculty-derived lead there is no posted requirement list, so the resume
matcher derives an "ask" from the lab's current direction. Those derived items
are used for matching but are **not** written to the `requirements` table, because
storing them would assert that the posting stated something it never did.

## Assisted apply stops at the handoff

**Alternative:** drive the form with Playwright after approval.

The approval gate is meaningful only if the thing approved is the thing that
happens. Auto-filling a live form invites partial failures the student cannot
see, and Handshake's Quick Apply is one irreversible click from submitting with
the wrong resume. Trellis shows the payload, records the approval against its
hash, opens the page, and stops. The student presses submit.

## The Overview "due soon" fallback

Nothing was due within 30 days, so the panel was empty while five real deadlines
sat just outside the window. It now falls back to the next five upcoming — each
row still rendering its true date and urgency, so a December deadline never looks
imminent. Showing an empty panel would have been accurate and useless.
