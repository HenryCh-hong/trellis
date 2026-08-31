import { Suspense } from "react";

import { PageHeader } from "@/components/app/page-header";
import { BrowseSkeleton } from "@/components/app/research/skeletons";
import { Alert } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import type { ResearchFacets, ResearchLead, StudentProfile } from "@/lib/types";

import { ResearchClient } from "./research-client";

/**
 * Research browse.
 *
 * Deliberately not the jobs table: a lead is an argument about a lab's current
 * direction, and the evidence for that argument has to be on the card.
 */
export default function ResearchPage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Suspense fallback={<ResearchLoading />}>
        <ResearchContent />
      </Suspense>
    </div>
  );
}

function ResearchLoading() {
  return (
    <>
      <PageHeader title="Research" description="Labs, professors and recent work" />
      <BrowseSkeleton />
    </>
  );
}

async function ResearchContent() {
  let leads: ResearchLead[] = [];
  let facets: ResearchFacets = { departments: [], topics: [], states: [] };
  let profile: StudentProfile | null = null;
  let failure: string | null = null;

  try {
    const [research, prof] = await Promise.all([
      api.research.leads({ limit: 300 }),
      api.profile.get().catch(() => null),
    ]);
    leads = research.items;
    facets = research.facets;
    profile = prof;
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    failure = error.message;
  }

  if (failure) {
    return (
      <>
        <PageHeader title="Research" />
        <div className="p-5">
          <Alert tone="danger" title="Could not load research leads">
            {failure}
          </Alert>
        </div>
      </>
    );
  }

  return <ResearchClient leads={leads} facets={facets} profile={profile} />;
}
