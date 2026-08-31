"use client";

/**
 * Requirements.
 *
 * Required, preferred and AI-inferred lines are three separate blocks with
 * three different visual treatments on purpose: conflating "preferred" with
 * "required" is the single most damaging mistake this screen could make, and
 * an inferred line must never be mistaken for something the posting said.
 */

import * as React from "react";
import { RequirementMark } from "@/components/app/indicators";
import { PanelSection } from "@/components/ui/panel";
import { Badge, Tooltip } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import type { Requirement } from "@/lib/types";

const MATCH_NOTE: Record<Requirement["match_state"], string> = {
  matched: "Matched by your profile",
  partial: "Partly matched",
  missing: "Not found in your profile",
  unknown: "Not checked against your profile",
};

export function RequirementsSection({
  required,
  preferred,
  inferred,
}: {
  required: Requirement[];
  preferred: Requirement[];
  inferred: Requirement[];
}) {
  const total = required.length + preferred.length + inferred.length;

  return (
    <PanelSection title="Requirements">
      {total === 0 ? (
        <p className="text-xs leading-relaxed text-[var(--text-tertiary)]">
          The source page did not state any qualifications we could read. Open the posting before
          assuming there are none.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          <Block
            heading="Required"
            note="Stated on the source page as a requirement."
            items={required}
            empty="No hard requirements were stated."
            variant="required"
          />

          {preferred.length > 0 && (
            <Block
              heading="Preferred qualifications"
              note="Nice to have. Not required — a missing line here does not disqualify you."
              items={preferred}
              empty=""
              variant="preferred"
              badge={<Badge tone="info">Not required</Badge>}
            />
          )}

          {inferred.length > 0 && (
            <Block
              heading="AI-inferred"
              note="Deduced from the posting's wording, not stated outright. Verify before relying on it."
              items={inferred}
              empty=""
              variant="inferred"
              badge={<Badge tone="warn">Inferred</Badge>}
            />
          )}
        </div>
      )}
    </PanelSection>
  );
}

function Block({
  heading,
  note,
  items,
  empty,
  variant,
  badge,
}: {
  heading: string;
  note: string;
  items: Requirement[];
  empty: string;
  variant: "required" | "preferred" | "inferred";
  badge?: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        variant === "preferred" &&
          "rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-3 py-2.5",
        variant === "inferred" &&
          "rounded-[var(--radius-md)] border border-dashed border-[var(--border)] px-3 py-2.5",
      )}
    >
      <div className="mb-1.5 flex items-center gap-2">
        <h4
          className={cn(
            "text-2xs font-semibold uppercase tracking-[0.05em]",
            variant === "required" ? "text-[var(--text-secondary)]" : "text-[var(--text-tertiary)]",
          )}
        >
          {heading}
        </h4>
        <span className="text-2xs tnum text-[var(--text-tertiary)]">{items.length}</span>
        {badge}
      </div>
      <p className="mb-2 text-2xs leading-relaxed text-[var(--text-tertiary)]">{note}</p>

      {items.length === 0 ? (
        <p className="text-xs text-[var(--text-tertiary)]">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((r) => (
            <RequirementRow key={r.id} requirement={r} variant={variant} />
          ))}
        </ul>
      )}
    </div>
  );
}

function RequirementRow({
  requirement: r,
  variant,
}: {
  requirement: Requirement;
  variant: "required" | "preferred" | "inferred";
}) {
  const evidence = r.source_text
    ? `“${r.source_text}”`
    : "No supporting sentence was captured for this line.";

  return (
    <li className="flex gap-2">
      <span className="mt-0.5">
        <RequirementMark state={r.match_state} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <Tooltip content={evidence}>
            <span
              className={cn(
                "text-xs leading-relaxed",
                variant === "inferred"
                  ? "text-[var(--text-secondary)]"
                  : "text-[var(--text-primary)]",
                r.source_text && "decoration-dotted underline-offset-2 hover:underline",
              )}
            >
              {r.text}
            </span>
          </Tooltip>
          {r.category && (
            <span className="ml-auto shrink-0 pt-0.5 text-2xs text-[var(--text-tertiary)]">
              {r.category}
            </span>
          )}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-2xs text-[var(--text-tertiary)]">
          <span>{r.match_reason || MATCH_NOTE[r.match_state]}</span>
          {variant === "inferred" && (
            <span className="tnum">confidence {Math.round(r.confidence * 100)}%</span>
          )}
        </div>
      </div>
    </li>
  );
}
