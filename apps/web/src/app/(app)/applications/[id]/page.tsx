import { notFound } from "next/navigation";
import { Suspense } from "react";

import { PageHeader } from "@/components/app/page-header";
import { Alert, Skeleton } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import type { ApplicationKit, ResumeItem } from "@/lib/types";

import { KitClient } from "./kit-client";

export default async function ApplicationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
      <Suspense fallback={<KitSkeleton />}>
        <Content id={id} />
      </Suspense>
    </div>
  );
}

function KitSkeleton() {
  return (
    <div className="p-5">
      <Skeleton className="h-5 w-[320px]" />
      <div className="mt-6 grid gap-5 lg:grid-cols-[2fr_1fr]">
        <div className="space-y-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
        <Skeleton className="h-56 w-full" />
      </div>
    </div>
  );
}

async function Content({ id }: { id: string }) {
  // Fetch inside the try, render outside: JSX built in a try block is not
  // rendered there, so render errors would slip past the catch anyway.
  let kit: ApplicationKit | null = null;
  let resumes: ResumeItem[] = [];
  let failure: string | null = null;

  try {
    [kit, resumes] = await Promise.all([
      api.applications.get(id),
      api.resumes.list().catch(() => []),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (!(error instanceof ApiError)) throw error;
    failure = error.message;
  }

  if (failure || !kit) {
    return (
      <>
        <PageHeader title="Application" />
        <div className="p-5">
          <Alert tone="danger" title="Could not load this application">
            {failure ?? "The application could not be read."}
          </Alert>
        </div>
      </>
    );
  }

  return <KitClient initial={kit} resumes={resumes} />;
}
