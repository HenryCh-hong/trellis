# Uncertainty

The product's most important promise is that it does not present a guess as a
fact. This is how that is enforced rather than merely intended.

## The four words

Every uncertain value maps onto exactly four words, computed in one place
(`Evidenced.certainty` in `app/llm/base.py`) so they mean the same thing on
every screen:

| Word | When | Rendered as |
|---|---|---|
| **Verified** | read literally from the source, or entered by the student — or confidence ≥ 0.85 **and** a supporting quote exists | green dot |
| **Likely** | confidence ≥ 0.6 | blue dot |
| **Inferred** | confidence > 0 | amber dot |
| **Unknown** | no value at all | grey dot |

Note the conjunction: high confidence alone is not enough for *Verified*. A
value without `source_text` cannot reach it, however sure the extractor was.

## Rules the code holds

**A missing value is `null`, never a plausible default.** An unstated deadline is
`None` at confidence 0 with `deadline_type = unknown`. It renders as "Unknown",
never as a date. The extractor is explicitly forbidden from carrying last cycle's
date forward — 9 of the 16 shipped research programmes have no published
next-cycle deadline, and every one of them says so.

**Unknown is not "far away".** The deadline sort places real upcoming dates
first, then rolling, then unknown, then overdue. Sorting unknown by a sentinel
date would silently rank it as distant-and-safe.

**Absence of evidence is displayed, not hidden.** A lab with no undergraduate
signal shows *Unknown*, because "we could not find out" and "they don't take
undergraduates" are different facts that lead to different decisions.

**Certainty scales credit.** In research scoring, an undergraduate signal
contributes at 1.0 / 0.7 / 0.4 / 0.0 for verified / likely / inferred / unknown.
A guess earns proportionally less.

**Confidence lowers when inputs are thin.** Few requirements extracted, unknown
deadline, unknown pay, or a sparse profile each reduce the match confidence, and
the score meter renders lower confidence as a softer bar. A 90 you should trust
and a 90 built from three fields do not look identical.

**Unscored ≠ zero.** A component with nothing to judge reports "not scored" and
its weight is redistributed. Scoring it zero would punish a posting for what it
merely failed to mention.

## What this looked like in practice

The shipped corpus was adversarially re-verified, and the checks changed answers.
Three examples, all in `data/harvest/`:

- **A de-obfuscated email is not a transcription.** Three faculty emails were
  removed because the page prints `cbfinn at cs dot stanford dot edu`, not the
  literal address. The reconstruction was almost certainly correct — and still
  not something we may store as *Verified*.
- **A quote can be real and still not an opening.** One lab's "we are actively
  looking" text existed verbatim, but the page's content digest was unchanged
  across Wayback captures from 2024, 2025 and 2025, its newest news item was from
  2023, and its intake form returned HTTP 401. Downgraded `OPENING → OUTREACH`.
- **An unreachable form cannot be verified.** Four recruiting forms are live-routed
  but sign-in gated, so the harvest can confirm the link is not dead and cannot
  confirm it still accepts responses. Recorded as exactly that.

The full list of what could not be established is in `docs/data-sources.md` and
is surfaced in the app under **Settings → Where this data came from**. The gaps
are shown to the student, not tidied away.
