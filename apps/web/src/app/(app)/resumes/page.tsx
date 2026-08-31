import { PageHeader } from "@/components/app/page-header";
import { Alert } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import type { ResumeItem } from "@/lib/types";

import { ResumesClient } from "./resumes-client";

export default async function ResumesPage() {
  // Fetch inside the try, render outside it: JSX returned from a try block is
  // constructed, not rendered, so render-time errors would escape the catch.
  let resumes: ResumeItem[] = [];
  let failure: string | null = null;
  try {
    resumes = await api.resumes.list();
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    failure = error.message;
  }

  if (failure) {
    return (
      <>
        <PageHeader title="Resumes" />
        <div className="p-5">
          <Alert tone="danger" title="Could not load resumes">
            {failure}
          </Alert>
        </div>
      </>
    );
  }

  return <ResumesClient initial={resumes} />;
}
