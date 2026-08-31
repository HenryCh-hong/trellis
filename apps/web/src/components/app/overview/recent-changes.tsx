import Link from "next/link";

import { Card, EmptyState } from "@/components/ui/primitives";
import type { OpportunityChangeItem } from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";

/**
 * What moved since you last looked.
 *
 * This is the section a job board cannot have: it exists only because
 * discovery records what changed instead of silently overwriting it. A
 * deadline moving is the single most consequential event in this product.
 */
const TONE: Record<string, string> = {
  deadline: "bg-[var(--color-danger-500)]",
  requirement_added: "bg-[var(--color-warn-500)]",
  requirement_removed: "bg-[var(--color-neutral-400)]",
  pay: "bg-[var(--color-info-500)]",
  hours: "bg-[var(--color-info-500)]",
  application_url: "bg-[var(--color-info-500)]",
  disappeared: "bg-[var(--color-danger-500)]",
  discovered: "bg-[var(--accent)]",
};

export function RecentChanges({ changes }: { changes: OpportunityChangeItem[] }) {
  if (changes.length === 0) {
    return (
      <Card>
        <EmptyState
          className="py-8"
          title="No changes recorded yet"
          body="Once discovery has run more than once, anything that moves — a deadline, a new required document, a posting that disappears — shows up here instead of changing silently."
        />
      </Card>
    );
  }

  return (
    <Card className="divide-y divide-[var(--border-subtle)]">
      {changes.map((c) => (
        <Link
          key={c.id}
          href={`/opportunities?id=${c.opportunity_id}`}
          className="flex items-start gap-2.5 px-3 py-2.5 transition-colors hover:bg-[var(--bg-hover)]"
        >
          <span
            className={cn("mt-[7px] size-1.5 shrink-0 rounded-full", TONE[c.kind] ?? "bg-[var(--color-neutral-400)]")}
          />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-medium text-[var(--text-primary)]">
              {c.opportunity_title}
            </span>
            <span className="block text-xs text-[var(--text-secondary)]">{c.summary}</span>
          </span>
          <span className="shrink-0 whitespace-nowrap text-2xs text-[var(--text-tertiary)]">
            {formatDateTime(c.noticed_at)}
          </span>
        </Link>
      ))}
    </Card>
  );
}
