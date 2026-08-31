import { Suspense } from "react";
import { redirect } from "next/navigation";

import { PageHeader } from "@/components/app/page-header";
import { ActionNeeded } from "@/components/app/overview/action-needed";
import {
  byDeadline,
  firstName,
} from "@/components/app/overview/format";
import { LastRunLine } from "@/components/app/overview/last-run";
import { ButtonLink, SectionLink } from "@/components/app/overview/links";
import { OpportunityTable } from "@/components/app/overview/opportunity-table";
import { PipelineBar } from "@/components/app/overview/pipeline-bar";
import { RecentChanges } from "@/components/app/overview/recent-changes";
import { ResearchLeadCards } from "@/components/app/overview/research-leads";
import { RetryButton } from "@/components/app/overview/retry-button";
import { RunDiscoveryButton } from "@/components/app/overview/run-discovery-button";
import { OverviewBody } from "@/components/app/overview/shell";
import { OverviewSkeleton } from "@/components/app/overview/skeleton";
import { StatStrip } from "@/components/app/overview/stat-strip";
import { Alert, Card, EmptyState, SectionHeader } from "@/components/ui/primitives";
import { API_BASE, ApiError, api } from "@/lib/api";
import type { Overview } from "@/lib/types";

/**
 * Overview — "what should I do next?", answerable without scrolling.
 *
 * Ordered by how much a stale answer costs the student: blocked applications
 * first, then deadlines, then things worth reading when there is time.
 */
export default function OverviewPage() {
  return (
    <div className="min-w-0 flex-1 overflow-y-auto scrollbar-thin">
      <Suspense fallback={<OverviewSkeleton />}>
        <OverviewContent />
      </Suspense>
    </div>
  );
}

async function OverviewContent() {
  let overview: Overview | null = null;
  let failure: ApiError | null = null;

  let changes: Awaited<ReturnType<typeof api.opportunities.changes>> = [];
  try {
    const [ov, ch] = await Promise.all([
      api.overview(),
      api.opportunities.changes(8).catch(() => []),
    ]);
    overview = ov;
    changes = ch;
  } catch (error) {
    // redirect() throws, so it must never happen inside this block.
    if (!(error instanceof ApiError)) throw error;
    failure = error;
  }

  if (overview?.needs_onboarding) redirect("/onboarding");

  if (!overview) {
    return (
      <ApiUnreachable status={failure?.status ?? 0} message={failure?.message ?? ""} />
    );
  }

  const name = firstName(overview.profile_name);
  const actions = overview.action_needed.slice(0, 5);
  const dueSoon = [...overview.due_soon].sort(byDeadline).slice(0, 6);
  const leads = overview.research_leads.slice(0, 6);
  const interested = overview.interested;
  // Lab leads only — this is the figure /research shows.
  const leadCount = overview.counts.lab_leads;

  return (
    <>
      <PageHeader
        title="Overview"
        description={name ? `${name} · ${overview.university}` : overview.university}
        actions={<RunDiscoveryButton />}
      />

      <OverviewBody>
        <ActionNeeded items={actions} />

        <StatStrip overview={overview} />

        <section className="min-w-0">
          <SectionHeader
            title="Due soon"
            count={dueSoon.length || undefined}
            action={<SectionLink href="/opportunities">All opportunities</SectionLink>}
          />
          <OpportunityTable
            items={dueSoon}
            variant="deadline"
            empty={
              <EmptyState
                className="py-10"
                title="No dated deadlines ahead"
                body="Nothing you are tracking states a closing date. Rolling and undated postings are still listed under Opportunities, sorted by fit."
                action={<ButtonLink href="/opportunities">Open the list</ButtonLink>}
              />
            }
          />
        </section>

        {/* Only rendered when you have actually marked something. An empty
            "Interested" panel would be the page inventing a habit you do not
            have yet. */}
        {interested.length > 0 && (
          <section className="min-w-0">
            <SectionHeader
              title="You marked interested"
              count={interested.length}
              description="Your own shortlist. Nothing here was chosen for you, and clearing the mark on a row takes it straight back out."
              action={<SectionLink href="/opportunities">All opportunities</SectionLink>}
            />
            <OpportunityTable
              items={interested}
              variant="match"
              empty={null}
            />
          </section>
        )}

        <section className="min-w-0">
          <SectionHeader
            title="Research leads"
            count={leadCount || undefined}
            description="Labs worth an email, whether or not they advertise an opening."
            action={<SectionLink href="/research">All leads</SectionLink>}
          />
          {leads.length === 0 ? (
            <Card>
              <EmptyState
                className="py-10"
                title="No labs surfaced yet"
                body="Research discovery reads department directories and lab pages, then keeps the groups whose recent work overlaps what you have said you care about."
                action={<ButtonLink href="/research">Open research</ButtonLink>}
              />
            </Card>
          ) : (
            <ResearchLeadCards leads={leads} />
          )}
        </section>

        <section className="min-w-0">
          <SectionHeader
            title="What changed"
            count={changes.length || undefined}
            description="Discovery records what moved instead of overwriting it silently."
          />
          <RecentChanges changes={changes} />
        </section>

        <section className="min-w-0">
          <SectionHeader
            title="Application pipeline"
            action={<SectionLink href="/applications">All applications</SectionLink>}
          />
          <PipelineBar stages={overview.pipeline} />
        </section>

        <LastRunLine run={overview.last_run} />
      </OverviewBody>
    </>
  );
}

/** The backend is down or unhappy. Say which, and say how to fix it. */
function ApiUnreachable({ status, message }: { status: number; message: string }) {
  const offline = status === 0;

  return (
    <>
      <PageHeader title="Overview" actions={<RetryButton />} />
      <OverviewBody>
        <Alert
          tone={offline ? "warn" : "danger"}
          title={offline ? "The Trellis API is not answering" : `The API returned an error (${status})`}
        >
          {offline ? (
            <div className="space-y-2">
              <p>
                Nothing responded at <span className="font-mono">{API_BASE}</span>, so this
                page has no data to show. Your saved opportunities and applications are
                untouched — they live in Postgres, not in this tab.
              </p>
              <p>Start the backend from the repo root, then retry:</p>
              <code className="block w-fit max-w-full overflow-x-auto rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg)] px-2 py-1 font-mono text-2xs text-[var(--text-secondary)]">
                make api
              </code>
              <p className="text-[var(--text-tertiary)]">
                Equivalent to: cd apps/api &amp;&amp; .venv/bin/uvicorn app.main:app --reload
                --port 8000
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              <p>{message || "The request failed without a message."}</p>
              <p>
                The API is running but could not build your overview. Its log will name the
                failing step; retry once it is restarted.
              </p>
            </div>
          )}
        </Alert>
      </OverviewBody>
    </>
  );
}
