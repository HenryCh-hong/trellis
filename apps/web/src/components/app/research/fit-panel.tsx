/**
 * "Why this matches you", in the three parts the decision actually has.
 *
 * Strong overlap is what the lab's dated work shows; relevant background is
 * what the student already has, quoted from their own profile and resumes; a
 * gap is an absence in that record, never a judgement of the person. The
 * server decides all three — this file only lays them out, so the wording a
 * student reads is the wording the honesty tests pin.
 */

import type * as React from "react";

import { Badge, Card, ExternalLink } from "@/components/ui/primitives";
import type { FitBreakdown } from "@/lib/types";
import { hostOf } from "@/lib/utils";

function GroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
      {children}
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-1.5 text-xs leading-relaxed text-[var(--text-tertiary)]">{children}</p>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-subtle)] p-3">
      {children}
    </div>
  );
}

export function FitPanel({ fit }: { fit: FitBreakdown }) {
  return (
    <div className="space-y-3">
      <div>
        <GroupLabel>Strong overlap</GroupLabel>
        {fit.strong_overlap.length === 0 ? (
          <Note>
            Nothing in this lab&apos;s recent work touches an interest you have named.
          </Note>
        ) : (
          <div className="mt-2 space-y-2.5">
            {fit.strong_overlap.map((o) => (
              <Card key={`${o.kind}-${o.label}`} className="p-3">
                <div className="flex flex-wrap items-baseline gap-2">
                  <Badge tone="accent">{o.label}</Badge>
                  <span className="text-xs leading-relaxed text-[var(--text-secondary)]">
                    {o.evidence}
                  </span>
                </div>
                {o.source_url && (
                  <p className="mt-1.5 text-xs text-[var(--text-tertiary)]">
                    <ExternalLink href={o.source_url}>{hostOf(o.source_url)}</ExternalLink>
                  </p>
                )}
              </Card>
            ))}
          </div>
        )}
      </div>

      <Panel>
        <GroupLabel>Relevant background</GroupLabel>
        {fit.background_note && <Note>{fit.background_note}</Note>}
        {fit.relevant_background.length === 0 ? (
          <>
            <Note>
              Nothing you have entered or uploaded connects to what this lab works on. Only
              your own records are listed here, so this section stays empty rather than
              filling up with things you did not say.
            </Note>
            {fit.resumes_read.length > 0 && (
              <p className="mt-1.5 text-2xs text-[var(--text-tertiary)]">
                Read from {fit.resumes_read.join(", ")}.
              </p>
            )}
          </>
        ) : (
          <ul className="mt-1.5 space-y-1.5">
            {fit.relevant_background.map((b, i) => (
              <li
                key={`${b.kind}-${b.label}-${i}`}
                className="text-xs leading-relaxed text-[var(--text-secondary)]"
              >
                <span className="text-[var(--text-primary)]">{b.label}</span>
                {b.detail && (
                  <span className="text-[var(--text-tertiary)]">
                    {" — "}
                    {/* A quoted line is the student's own text; it is shown as a
                        quotation so it can never be mistaken for our wording. */}
                    {b.verbatim ? <span className="italic">“{b.detail}”</span> : b.detail}
                  </span>
                )}
                {b.resume && (
                  <span className="ml-1.5 inline-flex align-middle">
                    <Badge>{b.resume}</Badge>
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel>
        <GroupLabel>Potential gaps</GroupLabel>
        {fit.potential_gaps.length === 0 ? (
          <Note>
            Nothing this lab&apos;s recent work is about is missing from your record.
          </Note>
        ) : (
          <ul className="mt-1.5 space-y-2">
            {fit.potential_gaps.map((g, i) => (
              <li key={`${g.label}-${i}`}>
                <div className="flex flex-wrap items-baseline gap-1.5">
                  <span className="text-xs text-[var(--text-primary)]">{g.label}</span>
                  {/* Only a stated hard requirement is ever marked as a gate. */}
                  {g.blocking && <Badge tone="warn">Stated requirement</Badge>}
                </div>
                <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-tertiary)]">
                  {g.note}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
