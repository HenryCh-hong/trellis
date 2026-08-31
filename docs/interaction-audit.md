# Interaction audit

Every interactive control on every screen, checked for the one failure mode that
matters: **a control that looks like it works and does nothing.**

`apps/web/interaction-audit.mjs` walks all 11 screens, reads each control's React
props, and flags anything with no handler, no `href`, and no form submission —
plus broken internal links, unexplained disabled states, and missing accessible
names.

Latest run: **322 controls, 0 inert, 0 broken links.**

```bash
cd apps/web && node interaction-audit.mjs
```

| Screen | Controls |
|---|---|
| Overview | 47 |
| Opportunities | 17 |
| Opportunity panel | 31 |
| Research | 66 |
| Lab profile | 36 |
| Applications | 12 |
| Application kit | 14 |
| Resumes | 12 |
| Profile | 42 |
| Settings | 33 |
| Onboarding | 2 |

---

## Problems found and fixed

### 1. Every Overview link into an opportunity was a no-op

`selectedId` was `useState(null)` and never read from the URL, so
`/opportunities?id=<id>` — which is exactly what the Overview's *Due soon*,
*Best matches* and *Recent discoveries* rows link to — landed on the list with
nothing open. Deep links, refresh-with-panel-open and back/forward were all
broken.

Selection now seeds from `?id=` and is mirrored back into the URL alongside the
filters.

### 2. "Add reminder" was a dead end

It created a `reminders` row and stopped. `icsUrl` and `shortcut` existed in the
API client but **no component called them**, so a reminder could be created and
never used for anything. Replaced with a real flow: choose offsets → create →
download `.ics` → optional Apple Shortcut setup with the payload and recipe.

### 3. `.ics` export returned HTTP 500 on real data

RFC-5545 line folding is on *octets*. The multi-byte backtrack checked
`raw[end-1]` instead of `raw[end]`, so a fold landing inside a character produced
an undecodable chunk. The existing test used `"A" * 300` — pure ASCII — so it
passed while every real title containing an em-dash crashed the endpoint. Fixed,
with tests covering em-dash, CJK, accented and emoji titles.

### 4. Settings' reminder-offset input saved nothing

It had `useState` and no persistence — a control that appeared configurable and
was not. Now persists to `localStorage` and seeds the reminder dialog, with the
relationship stated in the UI ("Seeds new reminders. Each reminder keeps its own
offsets once created.").

### 5. Tag inputs lost their affordance once populated

`placeholder={values.length ? "" : placeholder}` left the field visually empty
with no hint that it still accepted input. Now shows "Add another interest…" and
carries an `aria-label`.

### 6. Two controls had no accessible name

The "remember this answer" checkbox on the application kit and the
work-authorisation `Select` on the profile were announced unnamed. `Checkbox`
now derives a name from its label, and both call sites pass an explicit one.

---

### 7. Handshake import dropped the fields that mattered most

Two independent key mismatches between the extension normaliser and the
extractor. The normaliser emitted `apply_by` / `pay_text` / `employer`; the
extractor looked for `deadline` / `pay` / `organization`, so an imported job
arrived with no deadline, no pay and no employer. Separately the normaliser read
`description_text` while the extension and the API schema both send
`description`, so no requirements were ever extracted. A third bug surfaced
behind those: structured dates arrive as JSON **strings** and were passed
untouched to the scorer, which raised `TypeError: unsupported operand type(s)
for -: 'str' and 'datetime.date'` a long way from the cause.

Fixed with an explicit alias table, an accepted `description` field, and
coercion at the boundary. Three regression tests pin all of it.

### 8. Archiving an application was a dead end

`MOVE_TARGETS.archived = []` in both application views, so an archived
application could never be recovered — even though the backend already allowed
the transition. Archiving is now reversible and resumes in Preparing.

### 9. Live discovery filed navigation pages as opportunities

A crawl over `cs.stanford.edu` and `undergradresearch.stanford.edu` created
"PhD", "Master's", "Bachelor's", "Joint Programs" and 16 rows whose title was a
professor's academic title ("Professor of Linguistics") as things to apply for.
Added an evidence-based relevance gate, routed the faculty directory to the
research pipeline where it belongs, and pruned the 23 junk rows already stored.

### 10. A healthy source reported itself as an error

`careersearch.stanford.edu` returns no student-hourly roles — a documented fact
about that board, not a failure. The run marked it `[error]`, which trains you to
ignore real errors. `empty` is now a distinct status carrying the reason.

### 11. Running research discovery downgraded its own data

The agent overwrote rich harvested direction phrases ("Auditing what AI agents
actually do to human work") with generic canonical topic labels ("Large Language
Models"). Re-running discovery made the product worse. It now only fills an empty
direction, never trades a specific one for a generic one.

### 12. Raw slugs leaking into the UI

Nine topics rendered as `computational-education`, `ai-and-society`. Relabelled,
with `clean_label()` in the taxonomy so a slug can never become a label again.

### 13. A stale approval kept claiming it was current

The application kit showed "Approved Aug 31" next to "No resume selected". The
server correctly refuses the stale hash, but the banner did not say so. It now
warns that the application changed since approval.

### 14. The default ranking buried every good match

"Recommended" sorted by deadline urgency *before* fit. Research leads carry an
unknown deadline while campus jobs are rolling, so every rolling job outranked
every lab: a 38-point Swim Instructor sat above a 79-point AI lab, and the top
15 contained no research at all. Urgency now only leads when a deadline is
genuinely close, overdue sinks to the bottom, and fit decides the rest.

### 15. Too much on screen at once

The Opportunities filter bar carried eight always-visible selects and wrapped to
two rows; the Overview ran to eight stacked sections with two ranked lists of
the same data. Secondary filters now collapse behind a `Filters` button that
shows how many are active, and the Overview is six sections with "Best matches"
and "Recent discoveries" removed as duplicates of "What to do next".

## Deliberately disabled controls

Three remain flagged by the script as "disabled without a tooltip". Each is
self-evident from its immediate context and was left alone:

- **Back** on onboarding step 1 — there is nowhere back to go.
- **Add** on the coursework form — the title field next to it is empty.
- **Delete everything** in Settings — the input beside it reads *"Type DELETE to
  confirm"*.

The opportunity panel's **Add reminder** is disabled only when the posting has no
deadline, and carries a tooltip explaining exactly that.

---

## What the audit does not cover

- The Handshake extension's popup, which needs a live logged-in page.
- Hover-only affordances and drag interactions.
- Whether a handler does the *right* thing — that is `audit.mjs`'s job, which
  asserts against Postgres after every mutation.
