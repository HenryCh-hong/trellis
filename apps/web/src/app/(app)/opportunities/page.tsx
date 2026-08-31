import { Suspense } from "react";
import type { Metadata } from "next";
import { OpportunitiesClient } from "./opportunities-client";
import { PageHeader } from "@/components/app/page-header";
import { Alert, TableSkeleton } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type {
  OpportunityFacets,
  OpportunityListItem,
  OpportunityListResponse,
} from "@/lib/types";

export const metadata: Metadata = { title: "Opportunities · Trellis" };

const EMPTY_FACETS: OpportunityFacets = {
  types: [],
  statuses: [],
  sources: [],
  topics: [],
  departments: [],
  confidence: [],
};

/**
 * The whole working set is fetched once and filtered in the browser: a
 * student tracks tens to low hundreds of opportunities, not millions, and
 * instant filtering is worth far more here than server-side pagination.
 */
const PAGE_SIZE = 500;

export default async function OpportunitiesPage() {
  let data: OpportunityListResponse | null = null;
  let error: string | null = null;

  let savedFocus: "interests" | "all" = "interests";
  let heldItems: OpportunityListItem[] = [];

  try {
    // Two requests rather than one `confidence=all`, because the API's default
    // is what the product recommends and the held rows are a deliberate,
    // separate ask. They are loaded up front so the toggle is instant, but the
    // client never mixes them into a single view.
    const [list, held, profile] = await Promise.all([
      // `include_hidden` so the client can state how many rows you put away
      // and bring them back without a round trip. The API's own default still
      // omits them — hidden means hidden for anything that just asks for a list.
      api.opportunities.list({ limit: PAGE_SIZE, offset: 0, include_hidden: true }),
      api.opportunities
        .list({ limit: PAGE_SIZE, offset: 0, confidence: "held", include_hidden: true })
        .catch(() => null),
      api.profile.get().catch(() => null),
    ]);
    data = list;
    heldItems = held?.items ?? [];
    // Server-held, so the view follows the student to another browser or
    // machine rather than living in one tab's localStorage.
    const stored = profile?.preferences?.opportunityFocus;
    if (stored === "all" || stored === "interests") savedFocus = stored;
  } catch (err) {
    error =
      err instanceof ApiError
        ? err.message
        : "The opportunities request failed for an unknown reason.";
  }

  if (!data) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <PageHeader title="Opportunities" />
        <div className="p-5">
          <Alert tone="danger" title="Could not load opportunities">
            {error} Start the API with{" "}
            <code className="font-mono text-2xs">uvicorn app.main:app --reload</code> in{" "}
            <code className="font-mono text-2xs">apps/api</code>, then reload this page.
          </Alert>
        </div>
      </div>
    );
  }

  return (
    <Suspense fallback={<ListSkeleton />}>
      <OpportunitiesClient
        initialItems={[...data.items, ...heldItems]}
        facets={data.facets ?? EMPTY_FACETS}
        total={data.total}
        savedFocus={savedFocus}
      />
    </Suspense>
  );
}

function ListSkeleton() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader title="Opportunities" description="Loading…" />
      <div className="min-h-0 flex-1 overflow-hidden">
        <TableSkeleton rows={12} />
      </div>
    </div>
  );
}
