import { CertaintyMark } from "@/components/app/indicators";
import { ExternalLink } from "@/components/ui/primitives";
import type { DirectionClaim } from "@/lib/types";

/**
 * Directions you can open to see what they rest on.
 *
 * A flat list of phrases asks the reader to take our word for it. Each row here
 * expands to the dated items that support it and the words the two texts share,
 * so "is this lab really doing that now?" is answerable in one click rather
 * than by cross-referencing the timeline by hand.
 *
 * Native `<details>` on purpose: this stays a server component, and the
 * disclosure works before any JavaScript loads.
 */
export function DirectionList({ directions }: { directions: DirectionClaim[] }) {
  return (
    <ul className="space-y-1.5">
      {directions.map((d) => (
        <li key={d.direction}>
          <details className="group rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-subtle)]">
            <summary className="flex cursor-pointer list-none items-start gap-2 p-3">
              <span className="mt-[7px] size-1 shrink-0 rounded-full bg-[var(--accent)]" />
              <span className="min-w-0 flex-1 text-sm leading-relaxed">{d.direction}</span>
              <span className="mt-0.5 flex shrink-0 items-center gap-2">
                <CertaintyMark
                  certainty={d.certainty}
                  note={`Backed by ${d.evidence.length} recent item(s). Open to read them.`}
                />
                <span className="text-2xs text-[var(--text-tertiary)] tnum">
                  {d.evidence.length}
                </span>
                <span className="text-2xs text-[var(--text-tertiary)] group-open:hidden">
                  Show
                </span>
                <span className="hidden text-2xs text-[var(--text-tertiary)] group-open:inline">
                  Hide
                </span>
              </span>
            </summary>
            <ul className="space-y-2 border-t border-[var(--border-subtle)] px-3 py-2.5">
              {d.evidence.map((e) => (
                <li key={e.id} className="text-xs leading-relaxed">
                  <p className="text-[var(--text-secondary)]">
                    <span className="tnum text-[var(--text-tertiary)]">{e.year ?? "—"}</span>{" "}
                    <span className="text-[var(--text-tertiary)]">· {e.kind} ·</span>{" "}
                    {e.url ? <ExternalLink href={e.url}>{e.title}</ExternalLink> : e.title}
                  </p>
                  {/* Derived from the overlapping words, not written about them. */}
                  <p className="mt-0.5 text-[var(--text-tertiary)]">{e.why}</p>
                </li>
              ))}
            </ul>
          </details>
        </li>
      ))}
    </ul>
  );
}
