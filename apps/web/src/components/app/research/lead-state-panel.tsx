import { CertaintyMark } from "@/components/app/indicators";
import { ExternalLink } from "@/components/ui/primitives";
import type { LeadStateSignal, WhyNow } from "@/lib/types";

/** Signals that argue against acting, shown in the same list rather than hidden. */
const CAUTIONARY = new Set(["no_longer_reachable", "recruiting_closed", "recruiting_narrowed"]);

export function LeadStateSignals({ signals }: { signals: LeadStateSignal[] }) {
  if (signals.length === 0) {
    return (
      <p className="text-sm text-[var(--text-tertiary)]">
        Nothing on the pages we could read argues either way, which is why the state is what it
        is.
      </p>
    );
  }
  return (
    <ul className="space-y-2.5">
      {signals.map((s) => (
        <li key={`${s.key}-${s.source_url ?? ""}`} className="flex gap-3">
          <span className="pt-0.5">
            <CertaintyMark certainty={s.certainty} showLabel={false} />
          </span>
          <div className="min-w-0">
            <div
              className={
                CAUTIONARY.has(s.key)
                  ? "text-sm text-[var(--text-secondary)]"
                  : "text-sm text-[var(--text-primary)]"
              }
            >
              {CAUTIONARY.has(s.key) && <span aria-hidden>⚠ </span>}
              {s.label}
            </div>
            {s.detail && (
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-tertiary)]">
                {s.detail}
              </p>
            )}
            <div className="mt-1 flex items-center gap-2">
              <CertaintyMark certainty={s.certainty} />
              {s.source_url ? (
                <ExternalLink href={s.source_url} className="text-2xs">
                  source
                </ExternalLink>
              ) : (
                <span className="text-2xs text-[var(--text-tertiary)]">no source recorded</span>
              )}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * The timing signal, or the honest absence of one.
 *
 * There is no "act soon" copy for the null case on purpose: inventing urgency
 * is exactly the failure this field exists to prevent.
 */
export function WhyNowPanel({ whyNow }: { whyNow: WhyNow | null }) {
  if (whyNow === null) {
    return (
      <p className="text-sm text-[var(--text-tertiary)]">
        No specific timing signal found. There is no reason to think this month is better than
        next.
      </p>
    );
  }
  return (
    <div className="flex items-start gap-2">
      <span className="pt-1">
        <CertaintyMark certainty={whyNow.certainty} showLabel={false} />
      </span>
      <div className="min-w-0">
        <p className="text-sm leading-relaxed">{whyNow.statement}</p>
        <div className="mt-1 flex items-center gap-2">
          <CertaintyMark certainty={whyNow.certainty} />
          {whyNow.evidence_ids.length > 0 && (
            <span className="text-2xs text-[var(--text-tertiary)]">
              from {whyNow.evidence_ids.length} item(s) in the timeline below
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
