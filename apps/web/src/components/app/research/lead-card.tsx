import Link from "next/link";
import { Badge } from "@/components/ui/primitives";
import {
  CertaintyMark,
  DeadlineCell,
  LeadStateTag,
  ScoreMeter,
  statusLabel,
} from "@/components/app/indicators";
import type { ResearchEvidenceItem, ResearchLead } from "@/lib/types";
import {
  EVIDENCE_KIND_LABEL,
  labHeading,
  labSubheading,
  primarySignal,
} from "./format";

/**
 * A lead is an intelligence profile, not a posting: what the lab is doing now,
 * what it published last, and why any of it concerns this student. The freshness
 * line is the reason the card exists, so it gets the most legible treatment
 * after the name.
 */
export function LeadCard({ lead }: { lead: ResearchLead }) {
  const direction = lead.faculty.current_direction.slice(0, 3);
  const why = lead.overlap[0];

  return (
    <Link
      href={`/research/${lead.faculty.id}`}
      className="group flex min-h-[200px] flex-col rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg)] p-3.5 transition-colors duration-150 hover:border-[var(--border-strong)]"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-1.5">
          <LeadStateTag state={lead.lead_state} />
          {lead.status !== "new" && (
            <Badge tone="neutral">{statusLabel(lead.status)}</Badge>
          )}
        </div>
        <ScoreMeter score={lead.fit_score} confidence={lead.fit_confidence} />
      </div>

      <div className="mt-2.5 min-w-0">
        <h3 className="truncate text-md font-semibold tracking-[-0.01em] text-[var(--text-primary)]">
          {labHeading(lead)}
        </h3>
        <p className="mt-0.5 truncate text-xs text-[var(--text-tertiary)]">
          {labSubheading(lead)}
        </p>
      </div>

      {direction.length > 0 && (
        <div className="mt-2.5 flex max-h-[42px] flex-wrap gap-1 overflow-hidden">
          {direction.map((phrase) => (
            <span
              key={phrase}
              title={phrase}
              className="max-w-[15rem] truncate rounded-[var(--radius-xs)] bg-[var(--bg-sunken)] px-1.5 py-0.5 text-2xs text-[var(--text-secondary)]"
            >
              {phrase}
            </span>
          ))}
        </div>
      )}

      <div className="mt-3">
        <LatestEvidenceLine item={lead.latest_evidence} />
      </div>

      <p className="mt-2.5 line-clamp-1 text-xs text-[var(--text-secondary)]">
        {why
          ? why.why
          : "No overlap with your stated interests yet."}
      </p>

      <div className="mt-auto flex items-center justify-between gap-3 border-t border-[var(--border-subtle)] pt-2.5">
        <SignalSummary lead={lead} />
        <div className="flex shrink-0 items-center gap-2.5">
          {lead.deadline && (
            <DeadlineCell
              deadline={lead.deadline}
              type="unknown"
              urgency={lead.urgency}
              days={null}
              compact
            />
          )}
          <span className="tnum text-2xs text-[var(--text-tertiary)]">
            {lead.evidence_count === 1
              ? "1 evidence item"
              : `${lead.evidence_count} evidence items`}
          </span>
        </div>
      </div>
    </Link>
  );
}

/** The freshness signal: the newest thing anyone can point to about this lab. */
export function LatestEvidenceLine({ item }: { item: ResearchEvidenceItem | null }) {
  if (!item) {
    return (
      <p className="text-xs text-[var(--text-tertiary)]">
        No recent work found on the pages we could read.
      </p>
    );
  }
  return (
    <div className="min-w-0">
      <span className="text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
        {EVIDENCE_KIND_LABEL[item.kind]}
      </span>
      <p className="mt-0.5 line-clamp-2 text-xs leading-snug text-[var(--text-primary)]">
        {item.year !== null && (
          <>
            <span className="tnum text-[var(--text-tertiary)]">{item.year}</span>
            <span className="text-[var(--text-tertiary)]"> · </span>
          </>
        )}
        {item.title}
      </p>
    </div>
  );
}

/**
 * Undergraduate involvement, or the visible absence of it. A lab with nothing
 * on record says so here — silence is the finding, not a blank space.
 */
export function SignalSummary({ lead }: { lead: ResearchLead }) {
  const signal = primarySignal(lead.signals);
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <CertaintyMark
        certainty={signal?.certainty ?? "unknown"}
        note={signal ? undefined : "No page we could read mentions undergraduates in this lab."}
        showLabel={false}
      />
      <span
        title={signal?.label}
        className="truncate text-2xs text-[var(--text-secondary)]"
      >
        {signal?.label ?? "Undergraduate involvement unknown"}
      </span>
    </span>
  );
}
