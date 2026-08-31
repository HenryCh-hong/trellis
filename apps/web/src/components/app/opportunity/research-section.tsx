"use client";

/**
 * Research context for a lab or professor lead.
 *
 * The evidence timeline is the honest core of this section: "this lab is
 * active in X" is only credible next to the dated papers, projects and news
 * items it was read from, so the years are always shown.
 */

import * as React from "react";
import { CertaintyMark, LeadStateTag } from "@/components/app/indicators";
import { PanelSection } from "@/components/ui/panel";
import { Badge, ExternalLink, Tooltip } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import type {
  LabSignalItem,
  ResearchContext,
  ResearchEvidenceItem,
} from "@/lib/types";

const EVIDENCE_LABEL: Record<ResearchEvidenceItem["kind"], string> = {
  publication: "Paper",
  project: "Project",
  news: "News",
  grant: "Grant",
  course: "Course",
  talk: "Talk",
  student_project: "Student project",
};

const SIGNAL_LABEL: Record<LabSignalItem["kind"], string> = {
  undergrad_presence: "Undergrads",
  recruiting: "Recruiting",
  activity: "Activity",
};

const SIGNAL_ORDER: LabSignalItem["kind"][] = ["undergrad_presence", "recruiting", "activity"];

export function ResearchSection({ research }: { research: ResearchContext }) {
  const { faculty, lab } = research;

  const evidence = [...research.evidence].sort(
    (a, b) => (b.year ?? -1) - (a.year ?? -1) || a.title.localeCompare(b.title),
  );
  const signals = [...research.signals].sort(
    (a, b) => SIGNAL_ORDER.indexOf(a.kind) - SIGNAL_ORDER.indexOf(b.kind),
  );

  return (
    <PanelSection title="Research">
      {/* PI */}
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-sm font-medium text-[var(--text-primary)]">{faculty.name}</span>
            <LeadStateTag state={research.lead_state} />
            {!faculty.is_active && (
              <Tooltip content="No recent evidence of activity was found for this person.">
                <Badge tone="neutral">Quiet</Badge>
              </Tooltip>
            )}
          </div>
          <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">
            {[faculty.title, faculty.department, faculty.university].filter(Boolean).join(" · ")}
          </p>
        </div>
        {faculty.faculty_url && (
          <ExternalLink href={faculty.faculty_url} className="shrink-0 text-2xs">
            Faculty page
          </ExternalLink>
        )}
      </div>

      {/* Lab */}
      {lab && (
        <div className="mt-3 rounded-[var(--radius-md)] border border-[var(--border)] px-3 py-2.5">
          <div className="flex items-start gap-2">
            <span className="min-w-0 flex-1 text-xs font-medium text-[var(--text-primary)]">
              {lab.name}
            </span>
            {lab.url && (
              <ExternalLink href={lab.url} className="shrink-0 text-2xs">
                Lab site
              </ExternalLink>
            )}
          </div>
          {lab.description && (
            <p className="mt-1 text-2xs leading-relaxed text-[var(--text-secondary)]">
              {lab.description}
            </p>
          )}
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
            {lab.people_url && (
              <ExternalLink href={lab.people_url} className="text-2xs">
                People
              </ExternalLink>
            )}
            {lab.news_url && (
              <ExternalLink href={lab.news_url} className="text-2xs">
                News
              </ExternalLink>
            )}
            {lab.join_url && (
              <ExternalLink href={lab.join_url} className="text-2xs">
                Join / openings
              </ExternalLink>
            )}
          </div>
        </div>
      )}

      {/* Current direction */}
      <div className="mt-4">
        <div className="mb-1.5 flex items-center gap-2">
          <h4 className="text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
            Current direction
          </h4>
          <CertaintyMark
            certainty={faculty.current_direction_certainty}
            note={faculty.current_direction_basis}
          />
        </div>
        {faculty.current_direction.length === 0 ? (
          <p className="text-2xs leading-relaxed text-[var(--text-tertiary)]">
            We could not read a current research direction — the pages we found were undated or
            listed only historic interests.
          </p>
        ) : (
          <ul className="flex flex-wrap gap-1.5">
            {faculty.current_direction.map((d) => (
              <li key={d}>
                <Badge tone="accent">{d}</Badge>
              </li>
            ))}
          </ul>
        )}
        {faculty.current_direction_basis && (
          <p className="mt-1.5 text-2xs leading-relaxed text-[var(--text-tertiary)]">
            {faculty.current_direction_basis}
          </p>
        )}
      </div>

      {/* Overlap with the student's interests */}
      {research.overlap.length > 0 && (
        <div className="mt-4">
          <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
            Overlap with your interests
          </h4>
          <ul className="flex flex-col gap-2">
            {research.overlap.map((o) => (
              <li key={o.topic} className="border-l-2 border-[var(--accent-border)] pl-2.5">
                <p className="text-xs font-medium text-[var(--text-primary)]">{o.topic}</p>
                <p className="mt-0.5 text-2xs leading-relaxed text-[var(--text-secondary)]">
                  {o.why}
                </p>
                {o.evidence_title && (
                  <p className="mt-0.5 text-2xs text-[var(--text-tertiary)]">
                    {o.evidence_year !== null && <span className="tnum">{o.evidence_year} · </span>}
                    {o.evidence_url ? (
                      <ExternalLink href={o.evidence_url} className="text-2xs">
                        {o.evidence_title}
                      </ExternalLink>
                    ) : (
                      o.evidence_title
                    )}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Evidence timeline */}
      <div className="mt-4">
        <div className="mb-2 flex items-center gap-2">
          <h4 className="text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
            Evidence
          </h4>
          <span className="text-2xs tnum text-[var(--text-tertiary)]">
            {faculty.evidence_count || evidence.length}
          </span>
          {faculty.last_evidence_year !== null && (
            <span className="text-2xs tnum text-[var(--text-tertiary)]">
              most recent {faculty.last_evidence_year}
            </span>
          )}
        </div>
        {evidence.length === 0 ? (
          <p className="text-2xs leading-relaxed text-[var(--text-tertiary)]">
            No dated work was found for this lab, so there is nothing to back a claim about what it
            is doing right now.
          </p>
        ) : (
          <ul className="flex flex-col">
            {evidence.map((e) => (
              <EvidenceRow key={e.id} item={e} />
            ))}
          </ul>
        )}
      </div>

      {/* Signals */}
      <div className="mt-4">
        <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
          Lab signals
        </h4>
        {signals.length === 0 ? (
          <p className="text-2xs leading-relaxed text-[var(--text-tertiary)]">
            Nothing on the lab&rsquo;s pages said whether undergraduates work here.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {signals.map((s, i) => (
              <li key={`${s.kind}-${i}`} className="flex flex-col gap-0.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-2xs uppercase tracking-[0.04em] text-[var(--text-tertiary)]">
                    {SIGNAL_LABEL[s.kind]}
                  </span>
                  <span className="text-xs text-[var(--text-primary)]">{s.label}</span>
                  <CertaintyMark certainty={s.certainty} note={s.note} />
                  {s.source_url && (
                    <ExternalLink href={s.source_url} className="text-2xs">
                      source
                    </ExternalLink>
                  )}
                </div>
                {s.statement && (
                  <p className="text-2xs italic leading-relaxed text-[var(--text-secondary)]">
                    &ldquo;{s.statement}&rdquo;
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Opening status */}
      <div className="mt-4">
        <div className="mb-1.5 flex items-center gap-2">
          <h4 className="text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
            Opening status
          </h4>
          <LeadStateTag state={research.lead_state} />
        </div>
        {research.opening_statement ? (
          <p className="text-xs italic leading-relaxed text-[var(--text-secondary)]">
            &ldquo;{research.opening_statement}&rdquo;
          </p>
        ) : (
          <p className="text-2xs leading-relaxed text-[var(--text-tertiary)]">
            No advertised opening was found. That is not the same as &ldquo;no opening&rdquo; —
            most undergraduate positions are never posted.
          </p>
        )}
        {research.opening_source_url && (
          <ExternalLink href={research.opening_source_url} className="mt-1 text-2xs">
            Where this came from
          </ExternalLink>
        )}
      </div>

      {/* Contact */}
      <div className="mt-4">
        <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
          Contact
        </h4>
        {faculty.email ? (
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={`mailto:${faculty.email}`}
              className="text-sm text-[var(--accent)] underline-offset-2 hover:underline"
            >
              {faculty.email}
            </a>
            <CertaintyMark certainty={faculty.email_certainty} />
            {faculty.email_source_url && (
              <ExternalLink href={faculty.email_source_url} className="text-2xs">
                source
              </ExternalLink>
            )}
          </div>
        ) : (
          <p className="text-2xs leading-relaxed text-[var(--text-tertiary)]">
            No email address was found on a page we could read. Check the faculty page before
            guessing at an address.
          </p>
        )}
      </div>

      {/* Next step */}
      {research.suggested_next_step && (
        <div className="mt-4 rounded-[var(--radius-md)] border border-[var(--accent-border)] bg-[var(--accent-soft)] px-3 py-2.5">
          <h4 className="text-2xs font-semibold uppercase tracking-[0.05em] text-[var(--color-accent-700)]">
            Suggested next step
          </h4>
          <p className="mt-1 text-xs leading-relaxed text-[var(--text-primary)]">
            {research.suggested_next_step}
          </p>
        </div>
      )}
    </PanelSection>
  );
}

function EvidenceRow({ item }: { item: ResearchEvidenceItem }) {
  return (
    <li className="flex gap-3 border-l border-[var(--border)] pl-3 pb-2.5 last:pb-0">
      <span
        className={cn(
          "w-8 shrink-0 pt-px text-2xs tnum",
          item.year === null ? "text-[var(--text-disabled)]" : "text-[var(--text-tertiary)]",
        )}
      >
        {item.year ?? "—"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-2xs uppercase tracking-[0.04em] text-[var(--text-tertiary)]">
            {EVIDENCE_LABEL[item.kind]}
          </span>
          {item.url ? (
            <ExternalLink href={item.url} className="text-xs">
              {item.title}
            </ExternalLink>
          ) : (
            <span className="text-xs text-[var(--text-primary)]">{item.title}</span>
          )}
        </div>
        {item.venue && (
          <p className="text-2xs text-[var(--text-tertiary)]">{item.venue}</p>
        )}
        {item.summary && (
          <p className="mt-0.5 text-2xs leading-relaxed text-[var(--text-secondary)]">
            {item.summary}
          </p>
        )}
        {item.authors.length > 0 && (
          <p className="mt-0.5 truncate text-2xs text-[var(--text-tertiary)]">
            {item.authors.slice(0, 4).join(", ")}
            {item.authors.length > 4 && ` +${item.authors.length - 4}`}
          </p>
        )}
      </div>
    </li>
  );
}
