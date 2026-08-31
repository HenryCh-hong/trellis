/**
 * The feedback vocabulary, and the one place the client is allowed to act on it.
 *
 * Mirrors `apps/api/app/services/feedback.py`. The two constants below must
 * stay equal to `NOT_RELEVANT_PENALTY` and `INTERESTED_BOOST` there: the list
 * sorts in the browser, the API sorts on the server, and a student who reloads
 * the page must not watch the order change underneath them.
 *
 * Everything here is scoped to a single opportunity. There is deliberately no
 * function that takes a topic, a department or a source — a reason is recorded
 * against one posting and never generalised into a rule about a whole area.
 */

import type { FeedbackReason, FeedbackSignal, OpportunityListItem } from "./types";

/** Sort-only, in fit points. The score itself is never edited. */
export const NOT_RELEVANT_PENALTY = 20;
export const INTERESTED_BOOST = 10;

export const SIGNAL_LABEL: Record<FeedbackSignal, string> = {
  interested: "Interested",
  not_relevant: "Not relevant",
  already_applied: "Already applied",
  hidden: "Hidden",
};

/** One sentence saying exactly what the signal did. Shown wherever it is set. */
export const SIGNAL_EFFECT: Record<FeedbackSignal, string> = {
  interested: "Nudged up your list and shown on the Overview.",
  not_relevant: "Ranked lower — only this one. Still listed, still searchable.",
  already_applied:
    "Kept out of what Trellis suggests you do next. No application was created.",
  hidden: "Out of the default list and the Overview. Nothing was deleted.",
};

export const REASON_LABEL: Record<FeedbackReason, string> = {
  wrong_topic: "Wrong topic",
  wrong_job_type: "Wrong kind of job",
  too_far: "Too far away",
  not_qualified: "I'm not qualified",
  not_interested: "Just not interested",
};

export const REASONS: FeedbackReason[] = [
  "wrong_topic",
  "wrong_job_type",
  "too_far",
  "not_qualified",
  "not_interested",
];

export function signalOf(item: OpportunityListItem): FeedbackSignal | null {
  return item.feedback?.signal ?? null;
}

export function isHidden(item: OpportunityListItem): boolean {
  return item.feedback?.signal === "hidden";
}

/**
 * Fit points added to this row's position in the *recommended* sort — and
 * nowhere else. Bounded on purpose: a 90-point posting you dismissed still
 * ranks above a 60-point one you said nothing about, so one dismissal demotes
 * a row without burying everything that resembles it.
 */
export function sortAdjustment(item: OpportunityListItem): number {
  const signal = signalOf(item);
  if (signal === "not_relevant") return -NOT_RELEVANT_PENALTY;
  if (signal === "interested") return INTERESTED_BOOST;
  return 0;
}

/** True when the row should stop being offered as something to go and do. */
export function isParked(item: OpportunityListItem): boolean {
  const signal = signalOf(item);
  return signal === "already_applied" || signal === "hidden";
}
