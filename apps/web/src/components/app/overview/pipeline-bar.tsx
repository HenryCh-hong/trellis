import Link from "next/link";
import { Card } from "@/components/ui/primitives";
import type { OpportunityStatus, PipelineStage } from "@/lib/types";

/**
 * One bar, one hue. Segments darken as an application moves forward, so the
 * shape of the bar reads as progress rather than as a chart of eight
 * unrelated categories. Offer is the only stage that changes colour.
 */
const SEGMENT: Record<OpportunityStatus, string> = {
  new: "var(--color-neutral-300)",
  saved: "var(--color-neutral-400)",
  preparing: "var(--color-accent-200)",
  ready_to_apply: "var(--color-accent-300)",
  applying: "var(--color-accent-400)",
  submitted: "var(--color-accent-600)",
  interview: "var(--color-accent-800)",
  offer: "var(--color-success-500)",
  rejected: "var(--color-neutral-200)",
  archived: "var(--color-neutral-200)",
};

export function PipelineBar({ stages }: { stages: PipelineStage[] }) {
  const filled = stages.filter((s) => s.count > 0);
  const total = filled.reduce((n, s) => n + s.count, 0);

  return (
    <Card className="px-4 py-3.5">
      {total === 0 ? (
        <p className="text-xs leading-relaxed text-[var(--text-tertiary)]">
          No applications in flight. Preparing one from an opportunity puts it in this
          pipeline and starts tracking what it still needs.
        </p>
      ) : (
        <div className="flex h-2 w-full gap-px overflow-hidden rounded-full bg-[var(--bg-sunken)]">
          {filled.map((s) => (
            <Link
              key={s.status}
              href={`/applications?status=${s.status}`}
              title={`${s.label}: ${s.count}`}
              style={{ flexGrow: s.count, background: SEGMENT[s.status] }}
              className="block min-w-[5px] basis-0 transition-opacity duration-150 hover:opacity-75"
            >
              <span className="sr-only">{`${s.label}: ${s.count}`}</span>
            </Link>
          ))}
        </div>
      )}

      <div className="mt-3.5 flex flex-wrap items-center gap-x-5 gap-y-2">
        {stages.map((s) => (
          <Link
            key={s.status}
            href={`/applications?status=${s.status}`}
            className="group inline-flex items-center gap-1.5"
          >
            <span
              className="size-1.5 shrink-0 rounded-full"
              style={{ background: s.count > 0 ? SEGMENT[s.status] : "var(--border)" }}
            />
            <span
              className={
                s.count > 0
                  ? "text-xs text-[var(--text-secondary)] group-hover:text-[var(--text-primary)]"
                  : "text-xs text-[var(--text-tertiary)]"
              }
            >
              {s.label}
            </span>
            <span
              className={
                s.count > 0
                  ? "tnum text-xs font-medium text-[var(--text-primary)]"
                  : "tnum text-xs text-[var(--text-tertiary)]"
              }
            >
              {s.count}
            </span>
          </Link>
        ))}
      </div>
    </Card>
  );
}
