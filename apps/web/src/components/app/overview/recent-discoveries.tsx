import Link from "next/link";
import { Card, Dot } from "@/components/ui/primitives";
import type { OpportunityListItem } from "@/lib/types";
import { sinceLabel, sourceLabel } from "./format";

/** What the last few runs turned up, newest first. */
export function RecentDiscoveries({ items }: { items: OpportunityListItem[] }) {
  return (
    <Card className="overflow-hidden">
      <ul className="divide-y divide-[var(--border-subtle)]">
        {items.map((o) => (
          <li key={o.id}>
            <Link
              href={`/opportunities?id=${o.id}`}
              className="flex h-11 items-center gap-3 px-4 transition-colors duration-100 hover:bg-[var(--bg-hover)]"
            >
              <Dot className={o.is_new ? "bg-[var(--accent)]" : "bg-[var(--border-strong)]"} />
              <span
                className="min-w-0 flex-1 truncate text-xs text-[var(--text-primary)]"
                title={o.title}
              >
                {o.title}
              </span>
              <span className="hidden max-w-[190px] shrink-0 truncate text-2xs text-[var(--text-tertiary)] sm:block">
                {sourceLabel(o)}
              </span>
              <span className="tnum w-[76px] shrink-0 text-right text-2xs text-[var(--text-tertiary)]">
                {sinceLabel(o.first_seen_at)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}
