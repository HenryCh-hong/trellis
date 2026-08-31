import { ExternalLink } from "@/components/ui/primitives";
import type { ResearchEvidenceItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { EVIDENCE_KIND_LABEL, RECENCY_WINDOW_YEARS, isRecent } from "./format";

/** groupByYear's key for evidence with no date of its own. */
const UNDATED = "Year unknown";

/**
 * The receipts.
 *
 * Every claim this page makes about what a lab is doing now traces back to one
 * of these rows, so they are shown in full and in order rather than summarised.
 * Work outside the recency window is kept — it is the lab's history — but dimmed
 * beneath a divider so it can never be mistaken for current activity.
 */
export function EvidenceTimeline({
  evidence,
  thisYear,
}: {
  evidence: ResearchEvidenceItem[];
  thisYear: number;
}) {
  if (evidence.length === 0) {
    return (
      <p className="text-sm text-[var(--text-secondary)]">
        No publications, projects or news could be read for this lab. Without
        evidence we cannot say what it is working on now.
      </p>
    );
  }

  const sorted = [...evidence].sort((a, b) => (b.year ?? -1) - (a.year ?? -1));
  const recent = groupByYear(sorted.filter((e) => isRecent(e.year, thisYear)));
  const older = groupByYear(sorted.filter((e) => !isRecent(e.year, thisYear)));

  return (
    <div>
      {recent.map(([year, items]) => (
        <YearGroup key={year} year={year} items={items} />
      ))}

      {older.length > 0 && (
        <div className="my-5 flex items-center gap-3">
          <span className="text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
            Older work
          </span>
          <span className="h-px flex-1 bg-[var(--border-subtle)]" />
          <span className="text-2xs text-[var(--text-tertiary)]">
            before {thisYear - RECENCY_WINDOW_YEARS}
            {older.some(([year]) => year === UNDATED) && ", or undated"}
          </span>
        </div>
      )}

      {older.map(([year, items]) => (
        <YearGroup key={year} year={year} items={items} dimmed />
      ))}
    </div>
  );
}

function YearGroup({
  year,
  items,
  dimmed,
}: {
  year: string;
  items: ResearchEvidenceItem[];
  dimmed?: boolean;
}) {
  return (
    <div className={cn("grid grid-cols-[3.25rem_1fr] gap-x-3", dimmed && "opacity-60")}>
      <div>
        <span className="sticky top-2 block py-1 tnum text-xs font-medium text-[var(--text-tertiary)]">
          {year}
        </span>
      </div>
      <ul className="space-y-4 border-l border-[var(--border-subtle)] py-1 pl-5">
        {items.map((item) => (
          <li key={item.id} className="relative">
            <span className="absolute -left-[1.4375rem] top-[0.45rem] size-1.5 rounded-full bg-[var(--border-strong)] ring-2 ring-[var(--bg)]" />
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
                {EVIDENCE_KIND_LABEL[item.kind]}
              </span>
              {item.venue && (
                <span className="text-2xs text-[var(--text-tertiary)]">{item.venue}</span>
              )}
            </div>
            <h3 className="mt-0.5 text-sm font-medium leading-snug text-[var(--text-primary)]">
              {item.url ? (
                <ExternalLink href={item.url} className="text-[var(--text-primary)]">
                  {item.title}
                </ExternalLink>
              ) : (
                item.title
              )}
            </h3>
            {item.authors.length > 0 && (
              <p className="mt-0.5 truncate text-2xs text-[var(--text-tertiary)]">
                {item.authors.slice(0, 4).join(", ")}
                {item.authors.length > 4 && ` +${item.authors.length - 4} more`}
              </p>
            )}
            {item.summary && (
              <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
                {item.summary}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Newest year first; anything undated collects at the end under "Year unknown". */
function groupByYear(items: ResearchEvidenceItem[]): [string, ResearchEvidenceItem[]][] {
  const groups = new Map<string, ResearchEvidenceItem[]>();
  for (const item of items) {
    const key = item.year === null ? "Year unknown" : String(item.year);
    const bucket = groups.get(key);
    if (bucket) bucket.push(item);
    else groups.set(key, [item]);
  }
  return [...groups.entries()];
}
