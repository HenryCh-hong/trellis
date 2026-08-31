"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CertaintyMark, LeadStateTag, ScoreMeter } from "@/components/app/indicators";
import type { ResearchLead } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  EVIDENCE_KIND_LABEL,
  labHeading,
  labSubheading,
  primarySignal,
} from "./format";

/**
 * The dense alternative to the card grid. Same facts, one row each — for
 * scanning thirty labs by year of last activity rather than reading them.
 */
export function LeadTable({ leads }: { leads: ResearchLead[] }) {
  const router = useRouter();

  return (
    <table className="w-full min-w-[900px] border-collapse text-left">
      <thead className="sticky top-0 z-10 bg-[var(--bg)]">
        <tr className="border-b border-[var(--border)]">
          <Th className="w-[104px]">Lead</Th>
          <Th>Lab &amp; PI</Th>
          <Th className="w-[168px]">Department</Th>
          <Th className="w-[300px]">Latest evidence</Th>
          <Th className="w-[170px]">Undergraduates</Th>
          <Th className="w-[92px] text-right">Match</Th>
        </tr>
      </thead>
      <tbody>
        {leads.map((lead) => {
          const href = `/research/${lead.faculty.id}`;
          const signal = primarySignal(lead.signals);
          const latest = lead.latest_evidence;
          return (
            <tr
              key={lead.opportunity_id}
              onClick={() => router.push(href)}
              className="h-11 cursor-pointer border-b border-[var(--border-subtle)] transition-colors duration-100 hover:bg-[var(--bg-hover)]"
            >
              <Td>
                <LeadStateTag state={lead.lead_state} />
              </Td>
              <Td>
                <Link
                  href={href}
                  onClick={(e) => e.stopPropagation()}
                  className="block max-w-[300px] truncate text-xs font-medium text-[var(--text-primary)]"
                >
                  {labHeading(lead)}
                </Link>
                <span className="block max-w-[300px] truncate text-2xs text-[var(--text-tertiary)]">
                  {labSubheading(lead)}
                </span>
              </Td>
              <Td className="text-xs text-[var(--text-secondary)]">
                <span className="block truncate">
                  {lead.faculty.department ?? "Not stated"}
                </span>
              </Td>
              <Td>
                {latest ? (
                  <span className="flex min-w-0 items-baseline gap-1.5">
                    <span className="tnum shrink-0 text-2xs text-[var(--text-tertiary)]">
                      {latest.year ?? "—"}
                    </span>
                    <span className="truncate text-xs text-[var(--text-secondary)]">
                      {latest.title}
                    </span>
                  </span>
                ) : (
                  <span className="text-xs text-[var(--text-tertiary)]">
                    Nothing recent found
                  </span>
                )}
                <span className="block text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
                  {latest ? EVIDENCE_KIND_LABEL[latest.kind] : "No evidence"}
                </span>
              </Td>
              <Td>
                <span className="flex min-w-0 items-center gap-1.5">
                  <CertaintyMark
                    certainty={signal?.certainty ?? "unknown"}
                    showLabel={false}
                    note={
                      signal
                        ? undefined
                        : "No page we could read mentions undergraduates in this lab."
                    }
                  />
                  <span className="truncate text-xs text-[var(--text-secondary)]">
                    {signal?.label ?? "Unknown"}
                  </span>
                </span>
              </Td>
              <Td className="text-right">
                <span className="inline-flex justify-end">
                  <ScoreMeter score={lead.fit_score} confidence={lead.fit_confidence} />
                </span>
              </Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Th({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <th
      scope="col"
      className={cn(
        "px-3 py-2 text-2xs font-medium uppercase tracking-[0.05em] text-[var(--text-tertiary)]",
        className,
      )}
    >
      {children}
    </th>
  );
}

function Td({ className, children }: { className?: string; children: React.ReactNode }) {
  return <td className={cn("min-w-0 px-3 align-middle", className)}>{children}</td>;
}
