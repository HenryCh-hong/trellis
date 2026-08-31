import Link from "next/link";
import { LeadStateTag, ScoreMeter } from "@/components/app/indicators";
import type { ResearchLead } from "@/lib/types";
import { leadHeading, leadSubline } from "./format";

/**
 * Deliberately not a table. A lab is judged on what it has been doing lately,
 * which needs a sentence of evidence — that does not survive a 40px row.
 */
export function ResearchLeadCards({ leads }: { leads: ResearchLead[] }) {
  return (
    <div className="grid min-w-0 gap-3 sm:grid-cols-2">
      {leads.map((lead) => (
        <Link
          key={lead.opportunity_id}
          href={`/research?faculty=${lead.faculty.id}`}
          className="group flex min-w-0 flex-col rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg)] p-3.5 transition-colors duration-150 hover:border-[var(--border-strong)] hover:bg-[var(--bg-subtle)]"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-[var(--text-primary)]">
                {leadHeading(lead)}
              </div>
              <div className="mt-0.5 truncate text-xs text-[var(--text-secondary)]">
                {leadSubline(lead)}
              </div>
            </div>
            <LeadStateTag state={lead.lead_state} />
          </div>

          <div className="mt-3 border-t border-[var(--border-subtle)] pt-2.5">
            {lead.latest_evidence ? (
              <p className="line-clamp-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                <span className="tnum text-[var(--text-tertiary)]">
                  {lead.latest_evidence.year ?? "Year unknown"}
                </span>
                <span className="text-[var(--text-tertiary)]"> · </span>
                {lead.latest_evidence.title}
              </p>
            ) : (
              <p className="text-xs leading-relaxed text-[var(--text-tertiary)]">
                No recent publication or project was found on this lab&rsquo;s own pages.
              </p>
            )}
          </div>

          <div className="mt-2.5 flex items-center justify-between gap-3">
            <ScoreMeter score={lead.fit_score} confidence={lead.fit_confidence} />
            <span className="tnum shrink-0 text-2xs text-[var(--text-tertiary)]">
              {lead.evidence_count} evidence item{lead.evidence_count === 1 ? "" : "s"}
            </span>
          </div>
        </Link>
      ))}
    </div>
  );
}
