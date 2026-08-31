import Link from "next/link";
import { DeadlineCell, ScoreMeter } from "@/components/app/indicators";
import { Card, EmptyState } from "@/components/ui/primitives";
import type { ActionItem } from "@/lib/types";
import { ButtonLink, SectionLink } from "./links";
import { orgLine } from "./format";

/**
 * The one block on this page that is allowed to shout. Everything else is a
 * list you may browse; these are the items that will go stale if ignored.
 */

/** "Resume ready · Missing: transcript" — never a generic "incomplete". */
/** Shorten a server-side blocker to something scannable. */
function shortBlocker(text: string): string {
  const t = text.replace(/\.$/, "");
  const questions = /^(\d+) questions?\b/.exec(t);
  if (questions) {
    const n = questions[1];
    return /only you can answer/.test(t)
      ? `${n} sensitive ${n === "1" ? "question" : "questions"}`
      : `${n} unanswered ${n === "1" ? "question" : "questions"}`;
  }
  return t.replace(/^Missing document:\s*/i, "").replace(/^No resume selected/i, "a resume");
}

function blockerLine(item: ActionItem): string | null {
  // Resume readiness only means something once an application exists, and the
  // reason line already sits directly above — so this must add information, not
  // restate it. Terse and capped: a wall of text here is not scannable.
  if (!item.application_id && item.blocking.length === 0) return null;
  const shown = item.blocking.slice(0, 3).map(shortBlocker);
  const extra = item.blocking.length - shown.length;
  const parts: string[] = [];
  if (item.resume_ready) parts.push("Resume ready");
  if (shown.length) {
    parts.push(`Still needed: ${shown.join(", ")}${extra > 0 ? ` +${extra} more` : ""}`);
  }
  return parts.length ? parts.join(" · ") : null;
}

function ctaHref(item: ActionItem): string {
  return item.application_id
    ? `/applications?id=${item.application_id}`
    : `/opportunities?id=${item.opportunity.id}`;
}

export function ActionNeeded({ items }: { items: ActionItem[] }) {
  // Only call it "Action needed" when something is genuinely blocked or in
  // flight. Otherwise these are suggestions, and saying so keeps the label
  // meaningful for when it does matter.
  const blocked = items.some((i) => i.application_id !== null || i.blocking.length > 0);
  const heading = blocked ? "Action needed" : "What to do next";

  return (
    <section className="min-w-0">
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold tracking-[-0.01em] text-[var(--text-primary)]">
            {heading}
          </h2>
          {items.length > 0 && (
            <span className="tnum text-xs text-[var(--text-tertiary)]">{items.length}</span>
          )}
        </div>
        <SectionLink href="/applications">All applications</SectionLink>
      </div>

      <Card className="overflow-hidden shadow-card">
        {items.length === 0 ? (
          <EmptyState
            className="py-10"
            title="Nothing is waiting on you"
            body="Every opportunity you have started has the documents and answers it needs. The best matches below are the next thing worth opening."
            action={<ButtonLink href="/opportunities">Browse opportunities</ButtonLink>}
          />
        ) : (
          <ul className="divide-y divide-[var(--border-subtle)]">
            {items.map((item) => {
              const o = item.opportunity;
              return (
                <li key={o.id} className="px-4 py-3.5 sm:px-5">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-6">
                    <div className="min-w-0 flex-1">
                      <Link
                        href={`/opportunities?id=${o.id}`}
                        className="text-sm font-medium text-[var(--text-primary)] underline-offset-2 hover:text-[var(--accent)] hover:underline"
                      >
                        {o.title}
                      </Link>
                      <div className="mt-0.5 truncate text-xs text-[var(--text-secondary)]">
                        {orgLine(o)}
                      </div>
                      <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                        {item.reason}
                      </p>
                      {blockerLine(item) && (
                        <p className="mt-1 text-2xs text-[var(--text-tertiary)]">
                          {blockerLine(item)}
                        </p>
                      )}
                    </div>

                    <div className="flex shrink-0 items-center gap-4 sm:w-[184px] sm:flex-col sm:items-end sm:gap-2">
                      <ScoreMeter score={o.fit_score} confidence={o.fit_confidence} />
                      <DeadlineCell
                        deadline={o.deadline}
                        type={o.deadline_type}
                        urgency={o.urgency}
                        days={o.days_until_deadline}
                        certainty={o.deadline_certainty}
                      />
                    </div>

                    <ButtonLink
                      href={ctaHref(item)}
                      variant="primary"
                      className="w-full sm:w-auto sm:shrink-0"
                    >
                      {item.cta}
                    </ButtonLink>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </section>
  );
}
