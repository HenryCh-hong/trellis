import Link from "next/link";
import * as React from "react";
import { DeadlineCell, ScoreMeter, TypeTag } from "@/components/app/indicators";
import { Card } from "@/components/ui/primitives";
import type { OpportunityListItem } from "@/lib/types";
import { orgLine } from "./format";

/**
 * The compact list shape used by both Due soon and Best matches. Same columns,
 * same row height, so the eye can move between the two without re-learning
 * the layout; only the third column changes.
 */

const COLS = "grid-cols-[minmax(0,1fr)_116px_168px_76px]";

export function OpportunityTable({
  items,
  variant,
  empty,
}: {
  items: OpportunityListItem[];
  variant: "deadline" | "match";
  empty: React.ReactNode;
}) {
  const thirdHeading = variant === "deadline" ? "Deadline" : "Top topic";

  return (
    <Card className="overflow-hidden">
      {items.length === 0 ? (
        empty
      ) : (
        <div className="overflow-x-auto scrollbar-thin">
          <div className="min-w-[600px]">
            <div
              className={`grid ${COLS} h-8 items-center gap-3 border-b border-[var(--border)] bg-[var(--bg-subtle)] px-4 text-2xs uppercase tracking-[0.04em] text-[var(--text-tertiary)]`}
            >
              <span>Opportunity</span>
              <span>Type</span>
              <span>{thirdHeading}</span>
              <span className="text-right">Score</span>
            </div>
            <ul className="divide-y divide-[var(--border-subtle)]">
              {items.map((o) => (
                <li key={o.id}>
                  <Link
                    href={`/opportunities?id=${o.id}`}
                    className={`grid ${COLS} h-11 items-center gap-3 px-4 transition-colors duration-100 hover:bg-[var(--bg-hover)]`}
                  >
                    <span className="flex min-w-0 items-baseline gap-2">
                      <span
                        className="truncate text-xs font-medium text-[var(--text-primary)]"
                        title={o.title}
                      >
                        {o.title}
                      </span>
                      <span className="hidden truncate text-2xs text-[var(--text-tertiary)] sm:inline">
                        {orgLine(o)}
                      </span>
                    </span>

                    <span className="min-w-0">
                      <TypeTag type={o.type} />
                    </span>

                    <span className="min-w-0">
                      {variant === "deadline" ? (
                        <DeadlineCell
                          deadline={o.deadline}
                          type={o.deadline_type}
                          urgency={o.urgency}
                          days={o.days_until_deadline}
                          certainty={o.deadline_certainty}
                          compact
                        />
                      ) : (
                        <TopTopic topics={o.topics} />
                      )}
                    </span>

                    <span className="flex justify-end">
                      <ScoreMeter score={o.fit_score} confidence={o.fit_confidence} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </Card>
  );
}

function TopTopic({ topics }: { topics: OpportunityListItem["topics"] }) {
  if (!topics.length) {
    return <span className="text-xs text-[var(--text-tertiary)]">No topics read</span>;
  }
  const [first, ...rest] = topics;
  return (
    <span
      className="flex min-w-0 items-baseline gap-1.5"
      title={topics.map((t) => t.label).join(", ")}
    >
      <span className="truncate text-xs text-[var(--text-secondary)]">{first.label}</span>
      {rest.length > 0 && (
        <span className="tnum shrink-0 text-2xs text-[var(--text-tertiary)]">
          +{rest.length}
        </span>
      )}
    </span>
  );
}
