"use client";

/**
 * Domain indicators.
 *
 * These encode the product's honesty rules in one place: a certainty word, a
 * deadline urgency, a score. If a value is uncertain it must *look* uncertain
 * everywhere, so no screen is allowed to render these inline by hand.
 */

import * as React from "react";
import { Badge, Dot, Tooltip } from "@/components/ui/primitives";
import { cn, formatDate, relativeDays } from "@/lib/utils";
import type {
  Certainty,
  DeadlineState,
  DeadlineType,
  EligibilityState,
  LeadState,
  OpportunityStatus,
  OpportunityType,
  Recommendation,
  RequirementMatchState,
  SourceStatus,
  Urgency,
} from "@/lib/types";

/* ------------------------------------------------------------- Certainty */

const CERTAINTY: Record<
  Certainty,
  { label: string; dot: string; text: string; help: string }
> = {
  verified: {
    label: "Verified",
    dot: "bg-[var(--color-success-500)]",
    text: "text-[var(--color-success-700)]",
    help: "Read directly from the source page.",
  },
  likely: {
    label: "Likely",
    dot: "bg-[var(--color-info-500)]",
    text: "text-[var(--color-info-700)]",
    help: "Strongly supported by the source, but not stated outright.",
  },
  inferred: {
    label: "Inferred",
    dot: "bg-[var(--color-warn-500)]",
    text: "text-[var(--color-warn-700)]",
    help: "Deduced from indirect signals. Worth checking yourself.",
  },
  unknown: {
    label: "Unknown",
    dot: "bg-[var(--color-neutral-400)]",
    text: "text-[var(--text-tertiary)]",
    help: "Not stated anywhere we could read.",
  },
};

export function CertaintyMark({
  certainty,
  note,
  showLabel = true,
  className,
}: {
  certainty: Certainty;
  note?: string | null;
  showLabel?: boolean;
  className?: string;
}) {
  const c = CERTAINTY[certainty] ?? CERTAINTY.unknown;
  return (
    <Tooltip content={note || c.help}>
      <span className={cn("inline-flex items-center gap-1.5", className)}>
        <Dot className={c.dot} />
        {showLabel && (
          <span className={cn("text-2xs font-medium", c.text)}>{c.label}</span>
        )}
      </span>
    </Tooltip>
  );
}

/** A labelled fact with its certainty underneath — the §23 pattern. */
export function EvidencedValue({
  label,
  value,
  certainty,
  note,
  href,
}: {
  label: string;
  value: React.ReactNode;
  certainty: Certainty;
  note?: string | null;
  href?: string | null;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-2xs uppercase tracking-[0.04em] text-[var(--text-tertiary)]">
        {label}
      </span>
      <span className="text-sm text-[var(--text-primary)]">{value}</span>
      <span className="flex items-center gap-1.5">
        <CertaintyMark certainty={certainty} note={note} />
        {href && (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-2xs text-[var(--text-tertiary)] hover:text-[var(--accent)] hover:underline underline-offset-2"
          >
            source
          </a>
        )}
      </span>
    </div>
  );
}

/* -------------------------------------------------------------- Deadline */

const URGENCY: Record<Urgency, { tone: string; dot: string }> = {
  overdue: {
    tone: "text-[var(--color-danger-700)]",
    dot: "bg-[var(--color-danger-500)]",
  },
  urgent: {
    tone: "text-[var(--color-danger-600)]",
    dot: "bg-[var(--color-danger-500)]",
  },
  soon: { tone: "text-[var(--color-warn-700)]", dot: "bg-[var(--color-warn-500)]" },
  later: { tone: "text-[var(--text-primary)]", dot: "bg-[var(--color-neutral-400)]" },
  rolling: { tone: "text-[var(--text-secondary)]", dot: "bg-[var(--color-info-500)]" },
  unknown: { tone: "text-[var(--text-tertiary)]", dot: "bg-[var(--color-neutral-300)]" },
};

export function DeadlineCell({
  deadline,
  type,
  state,
  urgency,
  days,
  certainty,
  compact,
}: {
  deadline: string | null;
  type: DeadlineType;
  /** The recorded lifecycle. Only "expired" changes what is rendered. */
  state?: DeadlineState;
  urgency: Urgency;
  days: number | null;
  certainty?: Certainty;
  compact?: boolean;
}) {
  const u = URGENCY[urgency] ?? URGENCY.unknown;

  // Expired is a closed door, and it must not look like an emergency. An
  // overdue-but-live row is still red and still says how late it is, because
  // it is the thing to hurry at; an expired one is struck through and grey,
  // because hurrying will not help. The date is still legible either way —
  // "did I miss it, and by how much?" is the question this cell answers.
  if (state === "expired") {
    return (
      <Tooltip
        content={
          deadline
            ? `Expired. The posting said ${formatDate(deadline, { year: true })}; that date has passed. Kept so you can still see it.`
            : "Expired. Kept so you can still see it."
        }
      >
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
          <Dot className="bg-[var(--color-neutral-400)]" />
          <span className="text-xs tnum text-[var(--text-tertiary)] line-through decoration-[var(--text-tertiary)]/60">
            {deadline ? formatDate(deadline) : "—"}
          </span>
          <span className="text-2xs font-medium uppercase tracking-[0.04em] text-[var(--text-tertiary)]">
            Expired
          </span>
        </span>
      </Tooltip>
    );
  }

  if (type === "rolling" && !deadline) {
    return (
      <span className="inline-flex items-center gap-1.5">
        <Dot className={URGENCY.rolling.dot} />
        <span className="text-xs text-[var(--text-secondary)]">Rolling</span>
      </span>
    );
  }
  if (!deadline) {
    return (
      <Tooltip content="No deadline was stated on the source page.">
        <span className="inline-flex items-center gap-1.5">
          <Dot className={URGENCY.unknown.dot} />
          <span className="text-xs text-[var(--text-tertiary)]">Unknown</span>
        </span>
      </Tooltip>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <Dot className={u.dot} />
      <span className={cn("text-xs tnum font-medium", u.tone)}>{formatDate(deadline)}</span>
      {!compact && days !== null && Math.abs(days) <= 30 && (
        <span className="text-2xs text-[var(--text-tertiary)]">{relativeDays(days)}</span>
      )}
      {certainty && certainty !== "verified" && (
        <CertaintyMark certainty={certainty} showLabel={false} />
      )}
    </span>
  );
}

/**
 * The posting is not on its source any more.
 *
 * Deliberately not a deletion and deliberately not silent: the row stays, and
 * this says why the link may 404. It is only ever rendered from a recorded
 * `source_status`, which the backend writes only when the source itself
 * answered — never when a fetch failed.
 */
export function SourceStatusBadge({
  status,
  checkedAt,
  compact,
}: {
  status: SourceStatus;
  checkedAt?: string | null;
  /** Narrow spelling for a table row. Same fact, same tooltip, less width. */
  compact?: boolean;
}) {
  if (status !== "gone") return null;
  return (
    <Tooltip
      content={
        checkedAt
          ? `Source no longer available. It was checked on ${formatDate(checkedAt)} and this posting was not in its results. The record is kept; the link may no longer work.`
          : "Source no longer available. The source was checked and this posting was not in its results. The record is kept; the link may no longer work."
      }
    >
      <Badge tone="warn" className={compact ? "h-[16px] text-[10px]" : undefined}>
        {compact ? "Not listed" : "Source no longer available"}
      </Badge>
    </Tooltip>
  );
}

/* ----------------------------------------------------------------- Score */

export function ScoreMeter({
  score,
  confidence,
  size = "sm",
}: {
  score: number | null;
  confidence?: number | null;
  size?: "sm" | "lg";
}) {
  if (score === null || score === undefined) {
    return <span className="text-xs text-[var(--text-tertiary)]">—</span>;
  }
  const v = Math.max(0, Math.min(100, Math.round(score)));
  // Confidence is expressed as opacity on the bar, never as a second number:
  // a low-confidence 90 should look softer than a high-confidence 90.
  const alpha = confidence === null || confidence === undefined ? 1 : 0.4 + confidence * 0.6;

  if (size === "lg") {
    return (
      <div className="flex items-center gap-3">
        <span className="text-2xl font-semibold tnum tracking-[-0.02em] text-[var(--text-primary)]">
          {v}
          <span className="text-sm font-normal text-[var(--text-tertiary)]">%</span>
        </span>
        <div className="h-1.5 w-24 rounded-full bg-[var(--bg-sunken)] overflow-hidden">
          <div
            className="h-full rounded-full bg-[var(--accent)] transition-[width] duration-500 ease-[var(--ease-out-quart)]"
            style={{ width: `${v}%`, opacity: alpha }}
          />
        </div>
      </div>
    );
  }

  return (
    <span className="inline-flex items-center gap-2">
      <span className="w-7 text-right text-xs font-medium tnum text-[var(--text-primary)]">
        {v}
      </span>
      <span className="h-1 w-8 rounded-full bg-[var(--bg-sunken)] overflow-hidden">
        <span
          className="block h-full rounded-full bg-[var(--accent)]"
          style={{ width: `${v}%`, opacity: alpha }}
        />
      </span>
    </span>
  );
}

/* ------------------------------------------------------------------ Tags */

const TYPE_LABEL: Record<OpportunityType, string> = {
  on_campus: "On-campus",
  part_time: "Part-time",
  research_opening: "Research opening",
  research_outreach: "Outreach",
};

export function TypeTag({ type }: { type: OpportunityType }) {
  const tone =
    type === "research_opening" ? "accent" : type === "research_outreach" ? "info" : "neutral";
  return <Badge tone={tone}>{TYPE_LABEL[type]}</Badge>;
}

const STATUS_LABEL: Record<OpportunityStatus, string> = {
  new: "New",
  saved: "Saved",
  preparing: "Preparing",
  ready_to_apply: "Ready",
  applying: "Applying",
  submitted: "Submitted",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  archived: "Archived",
};

const STATUS_DOT: Record<OpportunityStatus, string> = {
  new: "bg-[var(--accent)]",
  saved: "bg-[var(--color-neutral-400)]",
  preparing: "bg-[var(--color-warn-500)]",
  ready_to_apply: "bg-[var(--color-info-500)]",
  applying: "bg-[var(--color-info-500)]",
  submitted: "bg-[var(--color-success-500)]",
  interview: "bg-[var(--color-success-500)]",
  offer: "bg-[var(--color-success-500)]",
  rejected: "bg-[var(--color-neutral-400)]",
  archived: "bg-[var(--color-neutral-300)]",
};

export function StatusPill({ status }: { status: OpportunityStatus }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <Dot className={STATUS_DOT[status]} />
      <span className="text-xs text-[var(--text-secondary)]">{STATUS_LABEL[status]}</span>
    </span>
  );
}

export const statusLabel = (s: OpportunityStatus) => STATUS_LABEL[s];

const LEAD: Record<LeadState, { label: string; tone: "accent" | "info" | "neutral"; help: string }> = {
  opening: {
    label: "Opening",
    tone: "accent",
    help: "A stated, currently-open position we could read on the lab's own page.",
  },
  outreach: {
    label: "Outreach",
    tone: "info",
    help: "No advertised opening, but the lab is active and worth a cold email.",
  },
  watch: {
    label: "Watch",
    tone: "neutral",
    help: "Recent work is there, but nothing we could read says an undergraduate can join right now.",
  },
  unknown: {
    label: "Unknown",
    tone: "neutral",
    help: "Not enough could be read to say. Deliberately not upgraded to give you something to click.",
  },
};

/** The one place a lead state is spelled for a human. */
export const LEAD_STATE_LABEL: Record<LeadState, string> = {
  opening: LEAD.opening.label,
  outreach: LEAD.outreach.label,
  watch: LEAD.watch.label,
  unknown: LEAD.unknown.label,
};

export function LeadStateTag({ state }: { state: LeadState }) {
  const l = LEAD[state];
  return (
    <Tooltip content={l.help}>
      <Badge tone={l.tone}>{l.label}</Badge>
    </Tooltip>
  );
}

const ELIGIBILITY: Record<
  EligibilityState,
  { label: string; tone: "success" | "info" | "warn" | "danger" }
> = {
  eligible: { label: "Eligible", tone: "success" },
  likely_eligible: { label: "Likely eligible", tone: "info" },
  unclear: { label: "Unclear", tone: "warn" },
  ineligible: { label: "Not eligible", tone: "danger" },
};

export function EligibilityTag({
  state,
  reasons,
}: {
  state: EligibilityState;
  reasons?: string[];
}) {
  const e = ELIGIBILITY[state];
  return (
    <Tooltip content={reasons?.length ? reasons.join(" · ") : undefined}>
      <Badge tone={e.tone}>{e.label}</Badge>
    </Tooltip>
  );
}

/* ---------------------------------------------------- Requirement marks */

export function RequirementMark({ state }: { state: RequirementMatchState }) {
  if (state === "matched") {
    return (
      <svg className="size-3.5 shrink-0 text-[var(--color-success-600)]" viewBox="0 0 14 14" fill="none" aria-label="matched">
        <path d="M3 7.4l2.8 2.8L11 4.6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (state === "partial") {
    return (
      <svg className="size-3.5 shrink-0 text-[var(--color-warn-600)]" viewBox="0 0 14 14" fill="none" aria-label="partial">
        <path d="M7 3.2 11.5 10.8h-9L7 3.2Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      </svg>
    );
  }
  if (state === "missing") {
    return (
      <svg className="size-3.5 shrink-0 text-[var(--color-danger-500)]" viewBox="0 0 14 14" fill="none" aria-label="missing">
        <path d="M4 4l6 6M10 4l-6 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg className="size-3.5 shrink-0 text-[var(--color-neutral-400)]" viewBox="0 0 14 14" fill="none" aria-label="unknown">
      <circle cx="7" cy="7" r="3.2" stroke="currentColor" strokeWidth="1.4" strokeDasharray="2 2" />
    </svg>
  );
}

const RECOMMENDATION: Record<
  Recommendation,
  { label: string; tone: "success" | "accent" | "neutral" | "info" }
> = {
  strong_apply: { label: "Strong match — apply", tone: "success" },
  apply: { label: "Apply", tone: "accent" },
  reach_out: { label: "Worth reaching out", tone: "info" },
  consider: { label: "Consider", tone: "neutral" },
  skip: { label: "Probably skip", tone: "neutral" },
};

export function RecommendationTag({ value }: { value: Recommendation | null }) {
  if (!value) return null;
  const r = RECOMMENDATION[value];
  if (!r) return null;
  return <Badge tone={r.tone}>{r.label}</Badge>;
}
