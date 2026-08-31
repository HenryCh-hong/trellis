import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { CertaintyMark, LeadStateTag, ScoreMeter } from "@/components/app/indicators";
import { EvidenceTimeline } from "@/components/app/research/evidence-timeline";
import { ExpandableText } from "@/components/app/research/expandable-text";
import { matchingBackground } from "@/components/app/research/format";
import { LabProfileSkeleton } from "@/components/app/research/skeletons";
import { OutreachPanel } from "@/components/app/research/outreach-panel";
import {
  Alert,
  Badge,
  Card,
  EmptyState,
  ExternalLink,
  SectionHeader,
} from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import type { ResearchContext, ResearchLead, StudentProfile } from "@/lib/types";
import { hostOf } from "@/lib/utils";

export default async function LabProfilePage({
  params,
}: {
  params: Promise<{ facultyId: string }>;
}) {
  const { facultyId } = await params;
  return (
    <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
      <Suspense fallback={<LabProfileSkeleton />}>
        <LabProfile facultyId={facultyId} />
      </Suspense>
    </div>
  );
}

async function LabProfile({ facultyId }: { facultyId: string }) {
  let context: ResearchContext;
  let profile: StudentProfile | null = null;
  let lead: ResearchLead | null = null;

  try {
    const [ctx, prof, leads] = await Promise.all([
      api.research.faculty(facultyId),
      api.profile.get().catch(() => null),
      api.research.leads({ limit: 300 }).catch(() => null),
    ]);
    context = ctx;
    profile = prof;
    lead = leads?.items.find((l) => l.faculty.id === facultyId) ?? null;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (!(error instanceof ApiError)) throw error;
    return (
      <div className="p-5">
        <Alert tone="danger" title="Could not load this lab">
          {error.message}
        </Alert>
      </div>
    );
  }

  const { faculty, lab } = context;
  const thisYear = new Date().getFullYear();
  const background = matchingBackground(
    profile,
    context.topics.map((t) => t.slug),
  );

  return (
    <article className="mx-auto max-w-[860px] px-5 py-6">
      <Link
        href="/research"
        className="text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
      >
        ← All research
      </Link>

      <header className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-[-0.02em]">
            {lab?.name ?? faculty.name}
          </h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            {[faculty.name, faculty.title, faculty.department]
              .filter(Boolean)
              .filter((v, i, a) => a.indexOf(v) === i)
              .join(" · ")}
          </p>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <LeadStateTag state={context.lead_state} />
            {lab?.url && (
              <ExternalLink href={lab.url} className="text-xs">
                {hostOf(lab.url)}
              </ExternalLink>
            )}
            {faculty.faculty_url && (
              <ExternalLink href={faculty.faculty_url} className="text-xs">
                Faculty page
              </ExternalLink>
            )}
          </div>
        </div>
        {lead?.fit_score != null && (
          <div className="shrink-0 text-right">
            <div className="mb-1 text-2xs uppercase tracking-[0.04em] text-[var(--text-tertiary)]">
              Match
            </div>
            <ScoreMeter score={lead.fit_score} confidence={lead.fit_confidence} size="lg" />
          </div>
        )}
      </header>

      {/* Current direction — inferred from recent work only, and said so. */}
      <section className="mt-7">
        <SectionHeader title="Current research direction" />
        {faculty.current_direction.length === 0 ? (
          <Alert tone="neutral">
            No recent work could be read for this lab, so we will not guess at its current
            direction. An older biography is not evidence of what it is doing now.
          </Alert>
        ) : (
          <>
            <ul className="space-y-1.5">
              {faculty.current_direction.map((d) => (
                <li key={d} className="flex gap-2 text-sm leading-relaxed">
                  <span className="mt-[7px] size-1 shrink-0 rounded-full bg-[var(--accent)]" />
                  <span>{d}</span>
                </li>
              ))}
            </ul>
            <div className="mt-3 flex items-start gap-2">
              <CertaintyMark certainty={faculty.current_direction_certainty} />
              {faculty.current_direction_basis && (
                <ExpandableText
                  text={faculty.current_direction_basis}
                  className="text-xs leading-relaxed text-[var(--text-tertiary)]"
                />
              )}
            </div>
          </>
        )}
      </section>

      <section className="mt-8">
        <SectionHeader
          title="Evidence"
          count={context.evidence.length}
          description="Everything above traces back to these. Nothing else was used."
        />
        <EvidenceTimeline evidence={context.evidence} thisYear={thisYear} />
      </section>

      {context.overlap.length > 0 && (
        <section className="mt-8">
          <SectionHeader title="Why this matches you" />
          <div className="space-y-2.5">
            {context.overlap.map((o) => (
              <Card key={`${o.topic}-${o.evidence_title}`} className="p-3">
                <div className="flex flex-wrap items-baseline gap-2">
                  <Badge tone="accent">{o.topic}</Badge>
                  <span className="text-xs text-[var(--text-secondary)]">{o.why}</span>
                </div>
                {o.evidence_title && (
                  <p className="mt-1.5 text-xs text-[var(--text-tertiary)]">
                    {o.evidence_year ? `${o.evidence_year} · ` : ""}
                    {o.evidence_url ? (
                      <ExternalLink href={o.evidence_url}>{o.evidence_title}</ExternalLink>
                    ) : (
                      o.evidence_title
                    )}
                  </p>
                )}
              </Card>
            ))}
          </div>
          {background.length > 0 && (
            <div className="mt-3 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-subtle)] p-3">
              <div className="text-2xs uppercase tracking-[0.05em] text-[var(--text-tertiary)]">
                From your profile
              </div>
              <ul className="mt-1.5 space-y-1">
                {background.map((b) => (
                  <li key={b.label} className="text-xs text-[var(--text-secondary)]">
                    <span className="text-[var(--text-primary)]">{b.label}</span>
                    {b.detail && <span className="text-[var(--text-tertiary)]"> — {b.detail}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      <section className="mt-8">
        <SectionHeader
          title="Undergraduate signals"
          description="Absence of evidence is shown as unknown, not hidden."
        />
        {context.signals.length === 0 ? (
          <p className="text-sm text-[var(--text-tertiary)]">
            No undergraduate signal could be read from this lab&apos;s pages.
          </p>
        ) : (
          <ul className="space-y-2.5">
            {context.signals.map((s, i) => (
              <li key={`${s.kind}-${i}`} className="flex gap-3">
                <span className="pt-0.5">
                  <CertaintyMark certainty={s.certainty} showLabel={false} note={s.note} />
                </span>
                <div className="min-w-0">
                  <div className="text-sm">{s.label}</div>
                  {/* Some harvested signals carry a statement identical to the
                      label; quoting it back adds noise, not evidence. */}
                  {s.statement && s.statement.trim() !== s.label.trim() && (
                    <ExpandableText
                      text={`“${s.statement}”`}
                      className="mt-0.5 text-xs italic leading-relaxed text-[var(--text-tertiary)]"
                    />
                  )}
                  <div className="mt-1 flex items-center gap-2">
                    <CertaintyMark certainty={s.certainty} />
                    {s.source_url && (
                      <ExternalLink href={s.source_url} className="text-2xs">
                        source
                      </ExternalLink>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-8">
        <SectionHeader title="Opening status" />
        {context.opening_statement ? (
          <Alert tone="accent" title="A stated opening was found">
            <p className="italic">“{context.opening_statement}”</p>
            {context.opening_source_url && (
              <p className="mt-1.5">
                <ExternalLink href={context.opening_source_url} className="text-2xs">
                  {hostOf(context.opening_source_url)}
                </ExternalLink>
              </p>
            )}
          </Alert>
        ) : (
          <Alert tone="neutral">
            No advertised undergraduate opening was found on any page we could read. That is not
            the same as “no opportunity” — most undergraduate research starts with an email.
          </Alert>
        )}
      </section>

      <section className="mt-8">
        <SectionHeader title="Contact & next step" />
        <Card className="p-4">
          {faculty.email ? (
            <div className="flex flex-wrap items-center gap-2">
              <a
                href={`mailto:${faculty.email}`}
                className="font-mono text-sm text-[var(--accent)] hover:underline"
              >
                {faculty.email}
              </a>
              <CertaintyMark certainty={faculty.email_certainty} />
              {faculty.email_source_url && (
                <ExternalLink href={faculty.email_source_url} className="text-2xs">
                  where we read it
                </ExternalLink>
              )}
            </div>
          ) : (
            <p className="text-sm text-[var(--text-secondary)]">
              No email address appears on the pages we could read, so we have not guessed one. Use
              the lab&apos;s own contact page.
            </p>
          )}
          {context.suggested_next_step && (
            <p className="mt-3 text-sm leading-relaxed text-[var(--text-secondary)]">
              {context.suggested_next_step}
            </p>
          )}
          <div className="mt-4">
            <OutreachPanel context={context} background={background} />
          </div>
        </Card>
      </section>

      <section className="mt-8 mb-10">
        <SectionHeader title="Sources" description="Every page this profile was built from." />
        {faculty.source_urls.length === 0 ? (
          <EmptyState
            className="py-6"
            title="No source list recorded"
            body="This record predates source tracking, or its pages could not be reached."
          />
        ) : (
          <ul className="space-y-1">
            {faculty.source_urls.map((u) => (
              <li key={u} className="truncate text-xs">
                <ExternalLink href={u}>{u}</ExternalLink>
              </li>
            ))}
          </ul>
        )}
      </section>
    </article>
  );
}
