import { Suspense } from "react";

import { PageHeader } from "@/components/app/page-header";
import { Alert, TableSkeleton } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import type { ApplicationKit } from "@/lib/types";

import { ApplicationsClient } from "./applications-client";

export default function ApplicationsPage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Suspense
        fallback={
          <>
            <PageHeader title="Applications" />
            <TableSkeleton rows={6} />
          </>
        }
      >
        <Content />
      </Suspense>
    </div>
  );
}

async function Content() {
  let kits: ApplicationKit[] = [];
  let failure: ApiError | null = null;
  try {
    kits = await api.applications.list();
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    failure = error;
  }

  if (failure) {
    // 409 means "no profile yet" — an onboarding state, not a failure.
    const onboarding = failure.status === 409;
    return (
      <>
        <PageHeader title="Applications" />
        <div className="p-5">
          <Alert
            tone={onboarding ? "neutral" : "danger"}
            title={onboarding ? "Finish onboarding first" : "Could not load applications"}
          >
            {failure.message}
          </Alert>
        </div>
      </>
    );
  }

  return <ApplicationsClient initial={kits} />;
}
